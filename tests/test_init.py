"""Tests de la mise en place : capteurs et statistiques externes."""

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.velos_montpellier.const import (
    CONF_BACKFILL_DAYS,
    CONF_COUNTERS,
    DOMAIN,
)

from .conftest import NOW

BERRACASA = "urn:ngsi-ld:EcoCounter:X2H19070220"
TANNEURS = "urn:ngsi-ld:EcoCounter:XTH19101158"


def _state(hass: HomeAssistant, unique_id: str):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id, unique_id
    return hass.states.get(entity_id)


async def _last_sum(hass: HomeAssistant, stat_id: str) -> float:
    stats = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, stat_id, True, {"sum"}
    )
    return stats[stat_id][0]["sum"]


@pytest.mark.freeze_time(NOW)
async def test_setup(hass: HomeAssistant, mock_api) -> None:
    """Les capteurs reflètent les données publiées et l'historique est importé."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTERS: [BERRACASA, TANNEURS]},
        options={CONF_BACKFILL_DAYS: 0},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Berracasa : journée du 22/09 complète, identique au fichier journalier officiel.
    day = _state(hass, "X2H19070220_last_complete_day")
    assert day.state == "1761"
    assert day.attributes["date"] == "2026-09-22"
    assert day.attributes["statistic_id"] == "velos_montpellier:x2h19070220"

    hour = _state(hass, "X2H19070220_last_hour")
    assert hour.state == "39"
    assert hour.attributes["observed_at"] == "2026-09-22T23:00:00+02:00"
    assert (
        _state(hass, "X2H19070220_last_observed").state == "2026-09-22T21:00:00+00:00"
    )

    # Tanneurs n'a publié que jusqu'au 22/09 à 04h : dernier jour complet = 21/09.
    assert (
        _state(hass, "XTH19101158_last_complete_day").attributes["date"] == "2026-09-21"
    )

    await async_wait_recording_done(hass)
    total = await _last_sum(hass, "velos_montpellier:x2h19070220")
    assert total == 1317 + 1589 + 1761  # 20, 21 et 22 septembre

    # Une nouvelle mise à jour ne doit pas compter deux fois les mêmes heures.
    await entry.runtime_data.async_refresh()
    await async_wait_recording_done(hass)
    assert await _last_sum(hass, "velos_montpellier:x2h19070220") == total
