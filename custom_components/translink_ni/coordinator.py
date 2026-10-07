"""Polling coordinator: one per configured stop."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Departure, TranslinkClient, TranslinkError
from .const import (
    BOARD_PAGES,
    CONF_SCAN_INTERVAL,
    CONF_SERVICES,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

type TranslinkConfigEntry = ConfigEntry[TranslinkCoordinator]


class TranslinkCoordinator(DataUpdateCoordinator[list[Departure]]):
    """Fetches the departure board for one stop."""

    config_entry: TranslinkConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: TranslinkConfigEntry, client: TranslinkClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_STOP_NAME]}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self.stop_id: str = entry.data[CONF_STOP_ID]
        self.stop_name: str = entry.data[CONF_STOP_NAME]

    @property
    def services(self) -> set[str]:
        """Services to include (lower-case); empty means all."""
        return {s.lower() for s in self.config_entry.options.get(CONF_SERVICES, [])}

    def matches(self, dep: Departure) -> bool:
        """True if the departure passes this stop's service filter."""
        return not self.services or dep.service.lower() in self.services

    async def fetch(
        self,
        *,
        after: datetime | None = None,
        until: datetime | None = None,
        max_pages: int = BOARD_PAGES,
    ) -> list[Departure]:
        """Fetch and filter departures (used by the board, calendar and action)."""
        deps = await self.client.get_departures(
            self.stop_id, after=after, until=until, max_pages=max_pages
        )
        return [d for d in deps if self.matches(d)]

    async def _async_update_data(self) -> list[Departure]:
        try:
            deps = await self.fetch()
        except TranslinkError as err:
            raise UpdateFailed(str(err)) from err
        # Drop anything already gone (the API includes the current minute).
        now = dt_util.utcnow() - timedelta(minutes=1)
        return [d for d in deps if d.expected >= now]

    @property
    def next_departure(self) -> Departure | None:
        """The next departure on the board, if any."""
        return self.data[0] if self.data else None
