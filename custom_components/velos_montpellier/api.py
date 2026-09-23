"""Client pour le portail API NGSI-LD de Montpellier Méditerranée Métropole.

Ce module ne dépend que d'aiohttp afin de pouvoir être testé hors de Home Assistant.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

import aiohttp

from .const import API_HOSTS, DATA_TZ, ENTITY_TYPE, FETCH_CHUNK, URN_PREFIX

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

    async def async_get_hourly(
        self, urns: Iterable[str], start: datetime, end: datetime
    ) -> dict[str, dict[datetime, int]]:
        """Comptages horaires {urn: {début d'heure UTC: nombre}} sur [start, end[.

        La période est découpée en tranches pour limiter la taille des réponses.
        """
        urns = list(urns)
        result: dict[str, dict[datetime, int]] = {urn: {} for urn in urns}
        if not urns:
            return result
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + FETCH_CHUNK, end)
            entities = await self._get(
                "/ngsi-ld/v1/temporal/entities",
                {
                    "type": ENTITY_TYPE,
                    "id": ",".join(urns),
                    "timerel": "between",
                    "timeAt": format_time_at(chunk_start),
                    "endTimeAt": format_time_at(chunk_end),
                    "format": "temporalValues",
                    "limit": _PAGE_SIZE,
                },
            )
            for entity in entities:
                chunk_hours: dict[datetime, int] = {}
                for value, observed_at in (entity.get("intensity") or {}).get(
                    "values"
                ) or []:
                    # La source ignore les changements d'heure (24 valeurs par
                    # jour, y compris un "02:00" inexistant fin mars) : on range
                    # par heure UTC et on additionne les collisions.
                    ts = parse_observed_at(observed_at).astimezone(UTC)
                    chunk_hours[ts] = chunk_hours.get(ts, 0) + int(value)
                # Une heure en bordure de deux tranches est simplement écrasée.
                result.setdefault(entity["id"], {}).update(chunk_hours)
            chunk_start = chunk_end
        return result
