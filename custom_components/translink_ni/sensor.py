"""Next departure sensor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity

from .entity import TranslinkEntity

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import TranslinkConfigEntry, TranslinkCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: TranslinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the next departure sensor for a stop."""
    async_add_entities([NextDepartureSensor(entry.runtime_data)])


class NextDepartureSensor(TranslinkEntity, SensorEntity):
    """
    When the next bus/train actually leaves.

    State: the expected (actual) departure time. Attributes carry the scheduled
    time and delay, plus the whole board under ``departures``. The board changes
    every poll, so it is excluded from the recorder to keep the database small.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "next_departure"
    _unrecorded_attributes = frozenset({"departures"})

    def __init__(self, coordinator: TranslinkCoordinator) -> None:
        """Create the sensor for a stop."""
        super().__init__(coordinator, "next_departure")

    @property
    def native_value(self) -> datetime | None:
        """Expected (actual) time of the next departure."""
        nxt = self.coordinator.next_departure
        return nxt.expected if nxt else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Next departure details plus the board."""
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
