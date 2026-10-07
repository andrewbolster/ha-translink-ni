"""Next departure sensor."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TranslinkConfigEntry, TranslinkCoordinator
from .entity import TranslinkEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TranslinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the next departure sensor for a stop."""
    async_add_entities([NextDepartureSensor(entry.runtime_data)])


class NextDepartureSensor(TranslinkEntity, SensorEntity):
    """When the next bus/train actually leaves.

    State: the expected (actual) departure time. Attributes carry the scheduled
    time and delay, plus the whole board under ``departures``. The board changes
    every poll, so it is excluded from the recorder to keep the database small.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "next_departure"
    _unrecorded_attributes = frozenset({"departures"})

    def __init__(self, coordinator: TranslinkCoordinator) -> None:
        super().__init__(coordinator, "next_departure")

    @property
    def native_value(self) -> datetime | None:
        nxt = self.coordinator.next_departure
        return nxt.expected if nxt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        nxt = self.coordinator.next_departure
        attrs: dict[str, Any] = {
            "stop_id": self.coordinator.stop_id,
            "departures": [d.as_dict() for d in self.coordinator.data or []],
        }
        if nxt:
            attrs |= {
                "service": nxt.service,
                "destination": nxt.destination,
                "scheduled": nxt.planned.isoformat(),
                "delay_minutes": nxt.delay_minutes,
                "transport_mode": nxt.transport_mode,
            }
        return attrs
