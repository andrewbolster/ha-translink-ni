"""Departures as calendar events (for calendar triggers and calendar cards)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .api import Departure, TranslinkError
from .const import CALENDAR_MAX_PAGES, CALENDAR_MAX_RANGE, DOMAIN
from .entity import TranslinkEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .coordinator import TranslinkConfigEntry, TranslinkCoordinator

PARALLEL_UPDATES = 0

# Calendar events need a duration; a departure is a moment.
EVENT_LENGTH = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: TranslinkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the departures calendar for a stop."""
    async_add_entities([DeparturesCalendar(entry.runtime_data)])


def _to_event(dep: Departure) -> CalendarEvent:
    scheduled = dt_util.as_local(dep.planned).strftime("%H:%M")
    if dep.delay_minutes:
        description = f"Scheduled {scheduled}, running {dep.delay_minutes} min late"
        summary = f"{dep.service} → {dep.destination} (+{dep.delay_minutes})"
    else:
        description = f"Scheduled {scheduled}"
        summary = f"{dep.service} → {dep.destination}"
    return CalendarEvent(
        start=dep.expected,
        end=dep.expected + EVENT_LENGTH,
        summary=summary,
        description=description,
        uid=f"{dep.service}|{dep.destination}|{dep.planned.isoformat()}",
    )


class DeparturesCalendar(TranslinkEntity, CalendarEntity):
    """Upcoming departures from a stop. History isn't available from the API."""

    _attr_translation_key = "departures"

    def __init__(self, coordinator: TranslinkCoordinator) -> None:
        """Create the calendar for a stop."""
        super().__init__(coordinator, "departures")

    @property
    def event(self) -> CalendarEvent | None:
        """The next departure, as an event."""
        nxt = self.coordinator.next_departure
        return _to_event(nxt) if nxt else None

    async def async_get_events(
        self,
        hass: HomeAssistant,  # noqa: ARG002 (calendar API signature)
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Departures within a window (upcoming only; the API has no history)."""
        now = dt_util.utcnow()
        start = max(dt_util.as_utc(start_date), now - EVENT_LENGTH)
        end = min(dt_util.as_utc(end_date), now + CALENDAR_MAX_RANGE)
        if end <= start:
            return []

        board = self.coordinator.data or []
        covered_until = board[-1].expected if board else now
        if end <= covered_until:
            deps = board
        else:
            try:
                deps = await self.coordinator.fetch(
                    after=start, until=end, max_pages=CALENDAR_MAX_PAGES
                )
            except TranslinkError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="request_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

        return [
            _to_event(d) for d in deps if start <= d.expected + EVENT_LENGTH and d.expected <= end
        ]
