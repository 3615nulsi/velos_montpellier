"""Import des comptages horaires dans les statistiques long terme de Home Assistant.

Les données arrivent avec 8 à 30 h de retard : l'historique d'état d'un capteur les
daterait au moment de leur réception. On les insère donc comme statistiques
externes (`velos_montpellier:<numéro de série>`), avec leur véritable horodatage.
Elles sont exploitables avec la carte « Graphique de statistiques ».
"""

from __future__ import annotations

from datetime import datetime, timedelta
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


async def _async_last_stat(
    hass: HomeAssistant, stat_id: str
) -> tuple[datetime, float] | None:
    """(début, somme cumulée) de la dernière heure déjà importée."""
    last = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, stat_id, True, {"sum"}
    )
    if not last.get(stat_id):
        return None
    row = last[stat_id][0]
    return dt_util.utc_from_timestamp(row["start"]), row["sum"] or 0.0


async def async_update_statistics(
    hass: HomeAssistant,
    client: MontpellierApiClient,
    data: dict[str, CounterData],
    *,
    window_start: datetime,
    backfill_days: int,
) -> None:
    """Ajoute aux statistiques les heures publiées depuis le dernier import."""
    last_stats = {
        urn: await _async_last_stat(hass, statistic_id(item.counter))
        for urn, item in data.items()
    }

    # Premier import (ou fenêtre récente dépassée) : on rattrape l'historique.
    backfill_start = (dt_util.now(DATA_TZ) - timedelta(days=backfill_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    to_backfill = [
        urn
        for urn, last in last_stats.items()
        if last is None or last[0] < window_start
    ]
    history: dict[str, dict[datetime, int]] = {}
    if to_backfill:
        # Inutile de relire ce qui est déjà importé (ex. après une coupure de HA).
        fetch_start = max(
            backfill_start,
            min(
                last_stats[urn][0] + timedelta(hours=1)  # type: ignore[index]
                if last_stats[urn]
                else backfill_start
                for urn in to_backfill
            ),
        )
        if fetch_start < window_start:
            _LOGGER.debug("Rattrapage de l'historique pour %s", to_backfill)
            history = await client.async_get_hourly(
                to_backfill, fetch_start, window_start
            )

    for urn, item in data.items():
        hours = {**history.get(urn, {}), **item.hourly}
        last = last_stats[urn]
        last_start, total = last if last else (None, 0.0)

        stats: list[StatisticData] = []
        for start in sorted(hours):
            if last_start is not None and start <= last_start:
                continue
            total += hours[start]
            stats.append(StatisticData(start=start, state=hours[start], sum=total))
        if not stats:
            continue

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=item.counter.display_name,
            source=DOMAIN,
            statistic_id=statistic_id(item.counter),
            unit_class=None,
            unit_of_measurement=UNIT,
        )
        _LOGGER.debug("Import de %d heures pour %s", len(stats), urn)
        async_add_external_statistics(hass, metadata, stats)
