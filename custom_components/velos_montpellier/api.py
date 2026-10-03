"""Accès aux données des éco-compteurs de Montpellier Méditerranée Métropole.

- Portail API NGSI-LD : liste des compteurs et date de leur dernière mesure.
- Fichiers open data : totaux journaliers, plus complets que les comptages horaires
  de l'API (qui perd des envois entiers, environ un jour sur trois).

Ce module ne dépend que d'aiohttp afin de pouvoir être testé hors de Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
import re
from typing import Any

import aiohttp

from .const import API_HOSTS, DATA_TZ, ENTITY_TYPE, OPEN_DATA_URL, URN_PREFIX

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=30)
_PAGE_SIZE = 100


class MontpellierApiError(Exception):
    """Erreur de communication avec le portail API."""


@dataclass(frozen=True, slots=True)
class Counter:
    """Description d'un éco-compteur."""

    urn: str
    name: str | None
    latitude: float | None
    longitude: float | None
    lane_id: int | None
    vehicle_type: str | None
    replaces: str | None  # urn de l'ancien compteur (relation `oldVersion`)

    @property
    def serial(self) -> str:
        """Numéro de série du compteur (partie finale de l'URN)."""
        return self.urn.removeprefix(URN_PREFIX)

    @property
    def display_name(self) -> str:
        """Nom affichable, même quand l'API ne fournit pas de `name`."""
        return self.name or f"Compteur {self.serial}"


def parse_observed_at(value: str) -> datetime:
    """Convertit un horodatage de l'API en datetime aware (Europe/Paris).

    L'API renvoie par ex. "2026-09-22T08:00:00Z" pour l'heure 08h-09h *locale* :
    on ignore donc le "Z" et on interprète la valeur en heure de Paris.
    """
    naive = datetime.fromisoformat(value.removesuffix("Z")).replace(tzinfo=None)
    return naive.replace(tzinfo=DATA_TZ)


# Les fichiers open data sont des objets JSON mis bout à bout, parfois collés, tronqués
# ou à `"intensity":null` : on extrait directement le total et le jour de chaque objet.
_DAILY_RE = re.compile(
    r'"intensity":(\d+),"laneId":-?\d+,"dateObserved":"(\d{4}-\d{2}-\d{2})T'
)


def parse_daily(text: str) -> dict[date, int]:
    """Totaux journaliers {jour local: passages} d'un fichier open data.

    Un même jour apparaît parfois deux fois : la seconde valeur est un
    enregistrement parasite (identique d'un compteur à l'autre), on garde la première.
    """
    days: dict[date, int] = {}
    for value, day in _DAILY_RE.findall(text):
        days.setdefault(date.fromisoformat(day), int(value))
    return days


def format_time_at(value: datetime) -> str:
    """Formate une date pour les paramètres `timeAt` / `endTimeAt` (même convention)."""
    return value.astimezone(DATA_TZ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _prop(entity: dict[str, Any], key: str) -> Any:
    attr = entity.get(key)
    if isinstance(attr, dict):
        return attr.get("value", attr.get("object"))
    return None


def _parse_counter(entity: dict[str, Any]) -> Counter:
    coords = (_prop(entity, "location") or {}).get("coordinates") or [None, None]
    return Counter(
        urn=entity["id"],
        name=_prop(entity, "name"),
        longitude=coords[0],
        latitude=coords[1],
        lane_id=_prop(entity, "laneId"),
        vehicle_type=_prop(entity, "vehicleType"),
        replaces=_prop(entity, "oldVersion"),
    )


class MontpellierApiClient:
    """Accès aux éco-compteurs via les endpoints NGSI-LD."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._host = API_HOSTS[0]

    async def _get(self, path: str, params: dict[str, str | int]) -> Any:
        """GET JSON avec bascule sur l'hôte de secours en cas d'échec."""
        hosts = [self._host, *(h for h in API_HOSTS if h != self._host)]
        last_err: Exception | None = None
        for host in hosts:
            try:
                async with self._session.get(
                    f"{host}{path}", params=params, timeout=_TIMEOUT
                ) as resp:
                    if resp.status >= 500:
                        raise MontpellierApiError(f"{host} a répondu {resp.status}")
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, MontpellierApiError) as err:
                _LOGGER.debug("Échec de la requête %s%s : %s", host, path, err)
                last_err = err
                continue
            self._host = host
            return data
        raise MontpellierApiError(str(last_err)) from last_err

    async def async_get_counters(self) -> list[Counter]:
        """Liste tous les éco-compteurs déclarés (actifs ou non)."""
        counters: list[Counter] = []
        offset = 0
        while True:
            page = await self._get(
                "/ngsi-ld/v1/entities",
                {"type": ENTITY_TYPE, "limit": _PAGE_SIZE, "offset": offset},
            )
            counters.extend(_parse_counter(e) for e in page)
            if len(page) < _PAGE_SIZE:
                return counters
            offset += _PAGE_SIZE

    async def async_get_last_observations(self, since: datetime) -> dict[str, datetime]:
        """Date de la dernière mesure de chaque compteur ayant publié depuis `since`."""
        entities = await self._get(
            "/ngsi-ld/v1/temporal/entities",
            {
                "type": ENTITY_TYPE,
                "timerel": "after",
                "timeAt": format_time_at(since),
                "lastN": 1,
                "format": "temporalValues",
                "limit": _PAGE_SIZE,
            },
        )
        result: dict[str, datetime] = {}
        for entity in entities:
            values = (entity.get("intensity") or {}).get("values") or []
            if values:
                result[entity["id"]] = max(parse_observed_at(t) for _, t in values)
        return result

    async def async_get_daily(
        self, serial: str, *, archive: bool = False
    ) -> dict[date, int]:
        """Totaux journaliers d'un compteur : derniers jours, ou tout l'historique.

        Un fichier absent (404) ou en cours de réécriture (vide) ne donne aucun jour.
        """
        url = OPEN_DATA_URL.format(serial=serial, suffix="_archive" if archive else "")
        try:
            async with self._session.get(url, timeout=_TIMEOUT) as resp:
                if resp.status == 404:
                    _LOGGER.debug("Pas de fichier open data pour %s", serial)
                    return {}
                resp.raise_for_status()
                text = await resp.text(errors="replace")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise MontpellierApiError(f"Open data {serial} : {err}") from err
        return parse_daily(text)
