"""Tests de la mise en place : capteurs et statistiques externes."""

from datetime import datetime

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_last_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.velos_montpellier.const import (
    CONF_BACKFILL_DAYS,
    CONF_COUNTERS,
    DATA_TZ,
    DOMAIN,
    OPEN_DATA_URL,
)

from .conftest import NOW, mock_open_data, mock_portal

BERRACASA = "urn:ngsi-ld:EcoCounter:X2H19070220"
TANNEURS = "urn:ngsi-ld:EcoCounter:XTH19101158"
STAT_BERRACASA = "velos_montpellier:x2h19070220"
STAT_TANNEURS = "velos_montpellier:xth19101158"


def _state(hass: HomeAssistant, unique_id: str):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id, unique_id
    return hass.states.get(entity_id)


async def _last_stat(hass: HomeAssistant, stat_id: str) -> tuple[datetime, float]:
    await async_wait_recording_done(hass)
    stats = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, stat_id, True, {"sum"}
    )
    row = stats[stat_id][0]
    return datetime.fromtimestamp(row["start"], DATA_TZ), row["sum"]


async def _setup(hass: HomeAssistant, backfill_days: int) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTERS: [BERRACASA, TANNEURS]},
        options={CONF_BACKFILL_DAYS: backfill_days},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _remock(aioclient_mock: AiohttpClientMocker, **files: str) -> None:
    aioclient_mock.clear_requests()
    mock_portal(aioclient_mock)
    mock_open_data(aioclient_mock, **files)


def _archive_calls(aioclient_mock: AiohttpClientMocker) -> int:
    url = OPEN_DATA_URL.format(serial="X2H19070220", suffix="_archive")
    return sum(1 for call in aioclient_mock.mock_calls if str(call[1]) == url)


@pytest.mark.freeze_time(NOW)
async def test_setup(hass: HomeAssistant, mock_api) -> None:
    """Le capteur montre le dernier jour publié et l'historique est importé."""
    entry = await _setup(hass, backfill_days=7)

    # Berracasa : total du 22/09, identique au site Vélocité.
    day = _state(hass, "X2H19070220_last_complete_day")
    assert day.state == "1761"
    assert day.attributes["date"] == "2026-09-22"
    assert day.attributes["statistic_id"] == STAT_BERRACASA

    # 7 jours avant le 23/09 : du 16 au 22/09, une ligne par jour à minuit.
    start, total = await _last_stat(hass, STAT_BERRACASA)
    assert start == datetime(2026, 9, 22, tzinfo=DATA_TZ)
    assert total == 1519 + 1636 + 1382 + 1066 + 1317 + 1589 + 1761
    # Tanneurs : le doublon parasite du 16/09 (454) est ignoré.
    _, total_tanneurs = await _last_stat(hass, STAT_TANNEURS)
    assert total_tanneurs == 3205 + 3266 + 3042 + 1628 + 1303 + 3018 + 3374

    # Une nouvelle mise à jour ne compte pas deux fois les mêmes jours.
    await entry.runtime_data.async_refresh()
    assert (await _last_stat(hass, STAT_BERRACASA))[1] == total

    # Le lendemain soir, le total du 23/09 est publié.
    _remock(mock_api, daily="_next")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, "X2H19070220_last_complete_day").state == "1580"
    start, new_total = await _last_stat(hass, STAT_BERRACASA)
    assert start == datetime(2026, 9, 23, tzinfo=DATA_TZ)
    assert new_total == total + 1580
    assert _archive_calls(mock_api) == 0


def _mock_files(aioclient_mock: AiohttpClientMocker, daily: str, archive: str) -> None:
    """Contenu explicite des fichiers open data des deux compteurs."""
    aioclient_mock.clear_requests()
    mock_portal(aioclient_mock)
    for serial in ("X2H19070220", "XTH19101158"):
        for suffix, text in (("", daily), ("_archive", archive)):
            aioclient_mock.get(
                OPEN_DATA_URL.format(serial=serial, suffix=suffix),
                text=text.replace("X2H19070220", serial),
            )


@pytest.mark.freeze_time(NOW)
async def test_truncated_archive_keeps_history(hass: HomeAssistant, mock_api) -> None:
    """Une archive tronquée (en cours de réécriture) n'efface pas l'historique."""
    entry = await _setup(hass, backfill_days=7)
    _, total = await _last_stat(hass, STAT_BERRACASA)

    # Archive coupée après le 08/09 : le rechargement ne doit rien réimporter.
    archive = load_fixture("od_X2H19070220_archive.json").split("\n")[0]
    _mock_files(mock_api, load_fixture("od_X2H19070220.json"), archive)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _archive_calls(mock_api) == 1
    assert (await _last_stat(hass, STAT_BERRACASA))[1] == total


@pytest.mark.freeze_time(NOW)
async def test_missing_days_are_recovered(hass: HomeAssistant, mock_api) -> None:
    """Des jours manquants (HA arrêté) déclenchent une relecture de l'archive."""
    entry = await _setup(hass, backfill_days=7)
    _, total = await _last_stat(hass, STAT_BERRACASA)

    # Le fichier du jour passe au 25/09 alors que la statistique s'arrête au 22/09.
    daily = load_fixture("od_X2H19070220_next.json").replace("2026-09-23", "2026-09-25")
    _mock_files(mock_api, daily, load_fixture("od_X2H19070220_archive.json"))
    await entry.runtime_data.async_refresh()

    assert _archive_calls(mock_api) == 1
    start, new_total = await _last_stat(hass, STAT_BERRACASA)
    assert start == datetime(2026, 9, 25, tzinfo=DATA_TZ)
    assert new_total == total + 1580


@pytest.mark.freeze_time(NOW)
async def test_obsolete_sensors_removed(hass: HomeAssistant, mock_api) -> None:
    """Les capteurs horaires des versions 0.1.x sont supprimés."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_COUNTERS: [BERRACASA]},
        options={CONF_BACKFILL_DAYS: 0},
    )
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create(
        "sensor", DOMAIN, "X2H19070220_last_hour", config_entry=entry
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get(old.entity_id) is None
    assert _state(hass, "X2H19070220_last_complete_day").state == "1761"
    # Durée d'historique nulle : seul le dernier jour publié est importé.
    assert (await _last_stat(hass, STAT_BERRACASA))[1] == 1761
