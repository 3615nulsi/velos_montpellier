"""Coordinateur de mise à jour des éco-compteurs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Counter, MontpellierApiClient, MontpellierApiError
from .const import (
    CONF_BACKFILL_DAYS,
    DATA_TZ,
    DEFAULT_BACKFILL_DAYS,
    DOMAIN,
    RECENT_DAYS,
    UPDATE_INTERVAL,
)
from .statistics import async_update_statistics

_LOGGER = logging.getLogger(__name__)

type VelosMontpellierConfigEntry = ConfigEntry[VelosMontpellierCoordinator]


@dataclass(slots=True)
class CounterData:
    """Données calculées pour un compteur."""

    counter: Counter
    # Totaux journaliers récents, indexés par jour local.
    daily: dict[date, int] = field(default_factory=dict)

    @property
    def last_day(self) -> tuple[date, int] | None:
        """(jour, total) du dernier jour publié."""
        if not self.daily:
            return None
        day = max(self.daily)
        return day, self.daily[day]


class VelosMontpellierCoordinator(DataUpdateCoordinator[dict[str, CounterData]]):
    """Récupère périodiquement les totaux journaliers des compteurs suivis."""

    config_entry: VelosMontpellierConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: VelosMontpellierConfigEntry,
        client: MontpellierApiClient,
        counters: list[Counter],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.counters = {c.urn: c for c in counters}
        # Compteurs dont l'historique a été réimporté depuis le chargement.
        self._synced: set[str] = set()

    async def _async_update_data(self) -> dict[str, CounterData]:
        previous = self.data or {}
        backfill_days = self.config_entry.options.get(
            CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS
        )
        oldest = dt_util.now(DATA_TZ).date() - timedelta(days=RECENT_DAYS)

        data: dict[str, CounterData] = {}
        errors: list[str] = []
        for urn, counter in self.counters.items():
            known = previous[urn].daily if urn in previous else {}
            try:
                days = await self.client.async_get_daily(counter.serial)
            except MontpellierApiError as err:
                errors.append(str(err))
                days = {}
            # Première valeur publiée conservée (cf. parse_daily).
            item = CounterData(counter, {**days, **known})
            try:
                history = await async_update_statistics(
                    self.hass,
                    self.client,
                    item,
                    full_sync=urn not in self._synced,
                    backfill_days=backfill_days,
                )
            except MontpellierApiError as err:
                # Les capteurs restent valides même si l'import d'historique échoue.
                _LOGGER.warning("Import des statistiques reporté : %s", err)
            else:
                self._synced.add(urn)
                item.daily = {**history, **item.daily}
            item.daily = {d: v for d, v in item.daily.items() if d >= oldest}
            data[urn] = item

        if errors and len(errors) == len(self.counters) and not previous:
            raise UpdateFailed(f"Fichiers open data injoignables : {errors[0]}")
        for err in errors:
            _LOGGER.debug("Mise à jour incomplète : %s", err)
        return data
