"""Intégration Vélos Montpellier : comptages des éco-compteurs de la Métropole."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MontpellierApiClient, MontpellierApiError
from .const import CONF_COUNTERS
from .coordinator import VelosMontpellierConfigEntry, VelosMontpellierCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


def selected_counters(entry: VelosMontpellierConfigEntry) -> list[str]:
    """URN des compteurs suivis (les options priment sur la configuration initiale)."""
    return entry.options.get(CONF_COUNTERS, entry.data[CONF_COUNTERS])


async def async_setup_entry(
    hass: HomeAssistant, entry: VelosMontpellierConfigEntry
) -> bool:
    """Configure l'intégration à partir d'une entrée."""
    client = MontpellierApiClient(async_get_clientsession(hass))
    try:
        all_counters = await client.async_get_counters()
    except MontpellierApiError as err:
        raise ConfigEntryNotReady(f"Portail API injoignable : {err}") from err

    wanted = set(selected_counters(entry))
    counters = [c for c in all_counters if c.urn in wanted]

    coordinator = VelosMontpellierCoordinator(hass, entry, client, counters)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: VelosMontpellierConfigEntry
) -> bool:
    """Décharge une entrée."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(
    hass: HomeAssistant, entry: VelosMontpellierConfigEntry
) -> None:
    """Recharge l'entrée après modification des options."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: VelosMontpellierConfigEntry,
    device: dr.DeviceEntry,
) -> bool:
    """Autorise la suppression manuelle d'un compteur qui n'est plus suivi."""
    return not any(urn in selected_counters(entry) for _, urn in device.identifiers)
