"""Capteurs des éco-compteurs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_TZ, DOMAIN
from .coordinator import (
    CounterData,
    VelosMontpellierConfigEntry,
    VelosMontpellierCoordinator,
)
from .statistics import UNIT, statistic_id

# Pas de state_class : l'historique d'état daterait les valeurs à leur réception
# (8 à 30 h trop tard). Les graphiques passent par les statistiques externes.


@dataclass(frozen=True, kw_only=True)
class VelosSensorDescription(SensorEntityDescription):
    """Description d'un capteur de compteur."""

    value_fn: Callable[[CounterData], Any]
    attrs_fn: Callable[[CounterData], dict[str, Any]] = lambda _: {}


def _day_total(data: CounterData) -> int | None:
    day = data.last_complete_day
    return day[1] if day else None


def _day_attrs(data: CounterData) -> dict[str, Any]:
    day = data.last_complete_day
    return {"date": day[0].isoformat()} if day else {}


def _last_hour_attrs(data: CounterData) -> dict[str, Any]:
    last = data.last_observed
    return {"observed_at": last.astimezone(DATA_TZ).isoformat()} if last else {}


SENSORS: tuple[VelosSensorDescription, ...] = (
    VelosSensorDescription(
        key="last_complete_day",
        translation_key="last_complete_day",
        native_unit_of_measurement=UNIT,
        value_fn=_day_total,
        attrs_fn=_day_attrs,
    ),
    VelosSensorDescription(
        key="last_hour",
        translation_key="last_hour",
        native_unit_of_measurement=UNIT,
        value_fn=lambda d: d.last_hour_count,
        attrs_fn=_last_hour_attrs,
    ),
    VelosSensorDescription(
        key="last_observed",
        translation_key="last_observed",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.last_observed,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VelosMontpellierConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée les capteurs de chaque compteur suivi."""
    coordinator = entry.runtime_data
    async_add_entities(
        VelosCounterSensor(coordinator, urn, description)
        for urn in coordinator.counters
        for description in SENSORS
    )


class VelosCounterSensor(CoordinatorEntity[VelosMontpellierCoordinator], SensorEntity):
    """Capteur rattaché à un éco-compteur."""

    _attr_has_entity_name = True
    entity_description: VelosSensorDescription

    def __init__(
        self,
        coordinator: VelosMontpellierCoordinator,
        urn: str,
        description: VelosSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._urn = urn
        counter = coordinator.counters[urn]
        self._attr_unique_id = f"{counter.serial}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, urn)},
            name=counter.display_name,
            manufacturer="Eco-Counter",
            model="Éco-compteur",
            serial_number=counter.serial,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _data(self) -> CounterData | None:
        return (self.coordinator.data or {}).get(self._urn)

    @property
    def available(self) -> bool:
        return super().available and self._data is not None

    @property
    def native_value(self) -> int | datetime | None:
        data = self._data
        return self.entity_description.value_fn(data) if data else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._data
        if data is None:
            return {}
        counter = data.counter
        attrs = {
            **self.entity_description.attrs_fn(data),
            "statistic_id": statistic_id(counter),
        }
        # Coordonnées sur un seul capteur par compteur, pour la carte.
        if self.entity_description.key == "last_complete_day":
            attrs["latitude"] = counter.latitude
            attrs["longitude"] = counter.longitude
        return attrs
