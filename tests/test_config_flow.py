"""Tests du config flow."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.velos_montpellier.const import (
    CONF_BACKFILL_DAYS,
    CONF_COUNTERS,
    DOMAIN,
)

from .conftest import NOW

BERRACASA = "urn:ngsi-ld:EcoCounter:X2H19070220"
TANNEURS = "urn:ngsi-ld:EcoCounter:XTH19101158"


@pytest.mark.freeze_time(NOW)
async def test_user_flow(hass: HomeAssistant, mock_api, montpellier_home) -> None:
    """Seuls les compteurs actifs sont proposés, du plus proche au plus lointain."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    selector = result["data_schema"].schema[CONF_COUNTERS]
    options = selector.config["options"]
    assert [o["value"] for o in options] == [TANNEURS, BERRACASA]
    assert options[0]["label"].startswith("Compteur Vélo Tanneurs — ")

    with patch(
        "custom_components.velos_montpellier.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_COUNTERS: [BERRACASA], CONF_BACKFILL_DAYS: 10},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_COUNTERS: [BERRACASA]}
    assert result["options"] == {CONF_BACKFILL_DAYS: 10}


@pytest.mark.freeze_time(NOW)
async def test_user_flow_requires_counter(hass: HomeAssistant, mock_api) -> None:
    """Une sélection vide est refusée."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_COUNTERS: [], CONF_BACKFILL_DAYS: 0}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_COUNTERS: "no_counter"}
