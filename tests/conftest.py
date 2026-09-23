"""Fixtures communes."""

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.velos_montpellier.const import API_HOSTS

# 12h30 à Paris : dernières données publiées la veille au soir.
NOW = "2026-09-23T10:30:00+00:00"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Active custom_components/ (le recorder, dépendance, doit précéder hass)."""


@pytest.fixture
def mock_api(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Portail API simulé à partir de réponses réelles enregistrées."""
    host = API_HOSTS[0]
    aioclient_mock.get(
        f"{host}/ngsi-ld/v1/entities", text=load_fixture("entities.json")
    )
    aioclient_mock.get(
        f"{host}/ngsi-ld/v1/temporal/entities?lastN=1",
        text=load_fixture("last_observations.json"),
    )
    aioclient_mock.get(
        f"{host}/ngsi-ld/v1/temporal/entities?timerel=between",
        text=load_fixture("hourly.json"),
    )
    return aioclient_mock


@pytest.fixture
async def montpellier_home(hass: HomeAssistant) -> None:
    """Domicile à la Comédie."""
    hass.config.latitude = 43.6085
    hass.config.longitude = 3.8797
