"""Fixtures communes."""

from homeassistant.components.recorder import core as recorder_core
from homeassistant.components.recorder import migration
from homeassistant.core import HomeAssistant
from homeassistant.helpers import recorder as recorder_helper
import pytest
from pytest_homeassistant_custom_component.common import load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from sqlalchemy.orm import Session

from custom_components.velos_montpellier.const import API_HOSTS, OPEN_DATA_URL

# Python 3.14 évalue les annotations lors de l'autospec du recorder par le plugin
# de test ; `Recorder` et `Session` n'y sont importés que pour le typage.
migration.Recorder = recorder_core.Recorder
recorder_helper.Session = Session

# 12h30 à Paris : dernier total publié, celui du 22/09.
NOW = "2026-09-23T10:30:00+00:00"
SERIALS = ("X2H19070220", "XTH19101158")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Active custom_components/ (le recorder, dépendance, doit précéder hass)."""


def mock_open_data(
    aioclient_mock: AiohttpClientMocker,
    daily: str = "",
    archive: str = "_archive",
) -> None:
    """Fichiers open data simulés (`daily` / `archive` : suffixe de la fixture)."""
    for serial in SERIALS:
        aioclient_mock.get(
            OPEN_DATA_URL.format(serial=serial, suffix=""),
            text=load_fixture(f"od_{serial}{daily}.json"),
        )
        aioclient_mock.get(
            OPEN_DATA_URL.format(serial=serial, suffix="_archive"),
            text=load_fixture(f"od_{serial}{archive}.json"),
        )


def mock_portal(aioclient_mock: AiohttpClientMocker) -> None:
    """Portail API simulé à partir de réponses réelles enregistrées."""
    host = API_HOSTS[0]
    aioclient_mock.get(
        f"{host}/ngsi-ld/v1/entities", text=load_fixture("entities.json")
    )
    aioclient_mock.get(
        f"{host}/ngsi-ld/v1/temporal/entities?lastN=1",
        text=load_fixture("last_observations.json"),
    )


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Portail API et fichiers open data simulés (réponses réelles enregistrées)."""
    mock_portal(aioclient_mock)
    mock_open_data(aioclient_mock)
    return aioclient_mock


@pytest.fixture
async def montpellier_home(hass: HomeAssistant) -> None:
    """Domicile à la Comédie."""
    hass.config.latitude = 43.6085
    hass.config.longitude = 3.8797
