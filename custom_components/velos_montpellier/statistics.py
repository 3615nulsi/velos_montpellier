"""Import des totaux journaliers dans les statistiques long terme de Home Assistant.

Chaque jour est publié le lendemain soir : l'historique d'état d'un capteur le
daterait au moment de sa réception. On l'insère donc comme statistique externe
(`velos_montpellier:<numéro de série>`), datée de minuit (heure de Paris) du jour
compté. Elle est exploitable avec la carte « Graphique de statistiques ».
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import Counter, MontpellierApiClient
from .const import DATA_TZ, DOMAIN

if TYPE_CHECKING:
    from .coordinator import CounterData

_LOGGER = logging.getLogger(__name__)

UNIT = "passages"


def statistic_id(counter: Counter) -> str:
    """Identifiant de la statistique externe d'un compteur."""
    return f"{DOMAIN}:{counter.serial.lower()}"


def _start(day: date) -> datetime:
    """Début de la journée locale."""
    return datetime.combine(day, time(), DATA_TZ)


async def _async_last_stat(
    hass: HomeAssistant, stat_id: str
) -> tuple[date, float] | None:
    """(jour, somme cumulée) du dernier jour déjà importé."""
    last = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, stat_id, True, {"sum"}
    )
    if not last.get(stat_id):
        return None
    row = last[stat_id][0]
    start = dt_util.utc_from_timestamp(row["start"]).astimezone(DATA_TZ)
    return start.date(), row["sum"] or 0.0


def _rows(days: dict[date, int], total: float) -> list[StatisticData]:
    rows: list[StatisticData] = []
    for day in sorted(days):
        total += days[day]
        rows.append(StatisticData(start=_start(day), state=days[day], sum=total))
    return rows


async def async_update_statistics(
    hass: HomeAssistant,
    client: MontpellierApiClient,
    item: CounterData,
    *,
    full_sync: bool,
    backfill_days: int,
) -> dict[date, int]:
    """Ajoute aux statistiques les jours publiés depuis le dernier import.

    Avec `full_sync` (au chargement), ou s'il manque des jours, l'historique est
    relu dans l'archive et réimporté entièrement. Retourne les jours de l'archive.
    """
    counter = item.counter
    stat_id = statistic_id(counter)
    last = await _async_last_stat(hass, stat_id)
    last_day = last[0] if last else None
    new_days = {d: v for d, v in item.daily.items() if last_day is None or d > last_day}
    gap = (
        last_day is not None
        and bool(new_days)
        and min(new_days) > last_day + timedelta(days=1)
    )

    history: dict[date, int] = {}
    if full_sync or gap:
        history = await client.async_get_daily(counter.serial, archive=True)
        # Une archive en cours de réécriture est tronquée : on ne remplace pas un
        # historique déjà importé par une version qui s'arrête bien avant lui. La
        # marge couvre les anciennes statistiques horaires (v0.1), en avance d'un
        # jour ou deux ; un jour manquant sera de toute façon rattrapé (`gap`).
        if history and (
            last_day is None or max(history) >= last_day - timedelta(days=2)
        ):
            today = dt_util.now(DATA_TZ).date()
            days = {**item.daily, **history}
            start = min(today - timedelta(days=backfill_days), max(days))
            days = {d: v for d, v in days.items() if d >= start}
            _LOGGER.debug("Réimport de %d jours pour %s", len(days), stat_id)
            # Remise à zéro : supprime aussi d'éventuelles lignes d'une ancienne
            # version (comptages horaires) ou antérieures à la durée choisie.
            get_instance(hass).async_clear_statistics([stat_id])
            _async_add(hass, counter, _rows(days, 0.0))
            return history
        _LOGGER.debug(
            "Archive de %s incomplète, import des seuls derniers jours", stat_id
        )

    if new_days:
        _async_add(hass, counter, _rows(new_days, last[1] if last else 0.0))
    return history


def _async_add(
    hass: HomeAssistant, counter: Counter, rows: list[StatisticData]
) -> None:
    if not rows:
        return
    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=counter.display_name,
        source=DOMAIN,
        statistic_id=statistic_id(counter),
        unit_class=None,
        unit_of_measurement=UNIT,
    )
    async_add_external_statistics(hass, metadata, rows)
