"""Shared base entity: one device per stop."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import TranslinkCoordinator


class TranslinkEntity(CoordinatorEntity[TranslinkCoordinator]):
    """Base for entities belonging to one stop."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: TranslinkCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.stop_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.stop_id)},
            name=coordinator.stop_name,
            manufacturer="Translink",
            model="Stop",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.translink.co.uk/",
        )
