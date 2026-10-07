"""Translink NI departures for Home Assistant."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import PAGE_SIZE, TranslinkClient, TranslinkError
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_COUNT,
    ATTR_START,
    DOMAIN,
    SERVICE_GET_DEPARTURES,
)
from .coordinator import TranslinkConfigEntry, TranslinkCoordinator

if TYPE_CHECKING:
    from homeassistant.helpers.typing import ConfigType

PLATFORMS = [Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

GET_DEPARTURES_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_COUNT, default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
        vol.Optional(ATTR_START): cv.datetime,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
    """Register the get_departures action."""

    async def get_departures(call: ServiceCall) -> ServiceResponse:
        entry: TranslinkConfigEntry | None = hass.config_entries.async_get_entry(
            call.data[ATTR_CONFIG_ENTRY_ID]
        )
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_config_entry"
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        coordinator = entry.runtime_data
        count: int = call.data[ATTR_COUNT]
        start = call.data.get(ATTR_START)

        board = coordinator.data or []
        if start is None and len(board) >= count:
            deps = board
        else:
            # Need a different window or more than the cached board holds.
            after = dt_util.as_utc(start) if start else None
            try:
                deps = await coordinator.fetch(
                    after=after, max_pages=min(math.ceil(count / PAGE_SIZE) + 1, 8)
                )
            except TranslinkError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="request_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

        return {
            "stop_id": coordinator.stop_id,
            "stop_name": coordinator.stop_name,
            "departures": [d.as_dict() for d in deps[:count]],
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_DEPARTURES,
        get_departures,
        schema=GET_DEPARTURES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TranslinkConfigEntry) -> bool:
    """Set up one stop."""
    client = TranslinkClient(async_get_clientsession(hass))
    coordinator = TranslinkCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TranslinkConfigEntry) -> bool:
    """Unload a stop."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: TranslinkConfigEntry) -> None:
    """Options changed: reload so the new interval and filter apply."""
    await hass.config_entries.async_reload(entry.entry_id)
