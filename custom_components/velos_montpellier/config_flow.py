"""Config flow : sélection des éco-compteurs à suivre."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance
import voluptuous as vol

from .api import Counter, MontpellierApiClient, MontpellierApiError
from .const import (
    ACTIVE_THRESHOLD,
    CONF_BACKFILL_DAYS,
    CONF_COUNTERS,
    DEFAULT_BACKFILL_DAYS,
    DOMAIN,
    MAX_BACKFILL_DAYS,
)
from .coordinator import VelosMontpellierConfigEntry


async def _async_counter_options(
    hass: HomeAssistant, keep: list[str] | None = None
) -> list[SelectOptionDict]:
    """Compteurs actifs (plus ceux de `keep`), triés par distance au domicile."""
    client = MontpellierApiClient(async_get_clientsession(hass))
    counters = await client.async_get_counters()
    active = await client.async_get_last_observations(dt_util.now() - ACTIVE_THRESHOLD)
    keep = keep or []

    def dist_km(counter: Counter) -> float | None:
        if counter.latitude is None or counter.longitude is None:
            return None
        meters = distance(
            hass.config.latitude,
            hass.config.longitude,
            counter.latitude,
            counter.longitude,
        )
        return None if meters is None else meters / 1000

    shown = [c for c in counters if c.urn in active or c.urn in keep]
    shown.sort(key=lambda c: (dist_km(c) is None, dist_km(c) or 0, c.display_name))

    options = []
    for counter in shown:
        label = counter.display_name
        if (km := dist_km(counter)) is not None:
            label += f" — {km:.1f} km"
        if counter.urn not in active:
            label += " (inactif)"
        options.append(SelectOptionDict(value=counter.urn, label=label))
    return options


def _schema(
    options: list[SelectOptionDict], counters: list[str], backfill_days: int
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_COUNTERS, default=counters): SelectSelector(
                SelectSelectorConfig(
                    options=options, multiple=True, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required(CONF_BACKFILL_DAYS, default=backfill_days): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=MAX_BACKFILL_DAYS,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="jours",
                )
            ),
        }
    )


class VelosMontpellierConfigFlow(ConfigFlow, domain=DOMAIN):
    """Flux de configuration initiale."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_COUNTERS]:
                errors[CONF_COUNTERS] = "no_counter"
            else:
                return self.async_create_entry(
                    title="Vélos Montpellier",
                    data={CONF_COUNTERS: user_input[CONF_COUNTERS]},
                    options={CONF_BACKFILL_DAYS: int(user_input[CONF_BACKFILL_DAYS])},
                )

        try:
            options = await _async_counter_options(self.hass)
        except MontpellierApiError:
            return self.async_abort(reason="cannot_connect")

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(options, [], DEFAULT_BACKFILL_DAYS),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: VelosMontpellierConfigEntry,
    ) -> OptionsFlow:
        return VelosMontpellierOptionsFlow()


class VelosMontpellierOptionsFlow(OptionsFlow):
    """Modification de la liste des compteurs suivis."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self.config_entry.options.get(
            CONF_COUNTERS, self.config_entry.data[CONF_COUNTERS]
        )
        if user_input is not None:
            if not user_input[CONF_COUNTERS]:
                errors[CONF_COUNTERS] = "no_counter"
            else:
                return self.async_create_entry(
                    data={
                        CONF_COUNTERS: user_input[CONF_COUNTERS],
                        CONF_BACKFILL_DAYS: int(user_input[CONF_BACKFILL_DAYS]),
                    }
                )

        try:
            options = await _async_counter_options(self.hass, keep=current)
        except MontpellierApiError:
            return self.async_abort(reason="cannot_connect")

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                options,
                current,
                self.config_entry.options.get(
                    CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS
                ),
            ),
            errors=errors,
        )
