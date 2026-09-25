"""Coordinateur de mise à jour des éco-compteurs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
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
    FETCH_WINDOW,
    UPDATE_INTERVAL,
)
from .statistics import async_update_statistics

_LOGGER = logging.getLogger(__name__)

type VelosMontpellierConfigEntry = ConfigEntry[VelosMontpellierCoordinator]


@dataclass(slots=True)
class CounterData:
    """Données calculées pour un compteur."""

    counter: Counter
    # Comptages horaires récents, indexés par début d'heure (UTC).
    hourly: dict[datetime, int] = field(default_factory=dict)

    @property
    def last_observed(self) -> datetime | None:
        """Début de la dernière heure publiée."""
        return max(self.hourly, default=None)

    @property
    def last_hour_count(self) -> int | None:
        """Nombre de passages pendant la dernière heure publiée."""
        last = self.last_observed
        return None if last is None else self.hourly[last]

    @property
    def last_complete_day(self) -> tuple[date, int] | None:
        """(jour, total) du dernier jour local dont toutes les heures sont publiées.

        La source perd parfois un envoi journalier entier : un jour peut n'avoir
        que ses dernières heures (ex. 22h-23h), sans être complet pour autant.
        """
        per_day: dict[date, int] = {}
        hours: dict[date, set[int]] = {}
        for ts, value in self.hourly.items():
            local = ts.astimezone(DATA_TZ)
            per_day[local.date()] = per_day.get(local.date(), 0) + value
            hours.setdefault(local.date(), set()).add(local.hour)
        complete = [day for day, seen in hours.items() if _day_hours(day) <= seen]
        if not complete:
            return None
        day = max(complete)
        return day, per_day[day]


def _day_hours(day: date) -> set[int]:
    """Heures locales existant ce jour-là (sans 02h le jour du passage à l'été)."""
    start = datetime.combine(day, time(), DATA_TZ).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time(), DATA_TZ).astimezone(UTC)
    return {
        (start + timedelta(hours=i)).astimezone(DATA_TZ).hour
        for i in range(int((end - start) / timedelta(hours=1)))
    }


class VelosMontpellierCoordinator(DataUpdateCoordinator[dict[str, CounterData]]):
    """Récupère périodiquement les comptages horaires des compteurs suivis."""

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

    async def _async_update_data(self) -> dict[str, CounterData]:
        now = dt_util.now(DATA_TZ)
        # Début de journée locale, pour que le dernier jour complet soit entier.
        start = (now - FETCH_WINDOW).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now + timedelta(hours=1)
        try:
            hourly = await self.client.async_get_hourly(self.counters, start, end)
        except MontpellierApiError as err:
            raise UpdateFailed(f"Erreur du portail API : {err}") from err

        data = {
            urn: CounterData(counter, hourly.get(urn, {}))
            for urn, counter in self.counters.items()
        }

        backfill_days = self.config_entry.options.get(
            CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS
        )
        try:
            await async_update_statistics(
                self.hass,
                self.client,
                data,
                window_start=start,
                backfill_days=backfill_days,
            )
        except MontpellierApiError as err:
            # Les capteurs restent valides même si l'import d'historique échoue.
            _LOGGER.warning("Import des statistiques reporté : %s", err)

        return data
