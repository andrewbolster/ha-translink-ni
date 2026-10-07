"""Setup, the next_departure sensor, the calendar and the get_departures action."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.translink_ni.api import DEPARTURES_URL
from custom_components.translink_ni.const import DOMAIN
from custom_components.translink_ni.sensor import NextDepartureSensor

from .conftest import CAPTURED_AT, load

pytestmark = pytest.mark.freeze_time(CAPTURED_AT)

SENSOR = "sensor.shankill_cambria_street_next_departure"
CALENDAR = "calendar.shankill_cambria_street_departures"


@pytest.fixture
async def loaded(hass: HomeAssistant, aioclient_mock, cambria_entry):
    await hass.config.async_set_time_zone("Europe/London")  # harness defaults to US/Pacific
    aioclient_mock.post(DEPARTURES_URL, json=load("departures_cambria.json"))
    cambria_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(cambria_entry.entry_id)
    await hass.async_block_till_done()
    return cambria_entry


async def test_next_departure_state_is_actual_time(hass: HomeAssistant, loaded) -> None:
    state = hass.states.get(SENSOR)
    assert state.state == "2026-10-07T08:46:00+00:00"
    attrs = state.attributes
    assert attrs["device_class"] == "timestamp"
    assert attrs["service"] == "11e"
    assert attrs["destination"] == "Belfast, CastleCourt"
    assert attrs["scheduled"] == "2026-10-07T08:46:00+00:00"
    assert attrs["delay_minutes"] == 0
    assert attrs["attribution"] == "Data provided by Translink"
    assert len(attrs["departures"]) == 7  # cancelled 09:35 dropped
    assert "09:35" not in str([d["planned"] for d in attrs["departures"]])


async def test_late_bus_shows_actual_as_state_and_scheduled_as_attribute(
    hass: HomeAssistant, aioclient_mock, cambria_entry, freezer
) -> None:
    # Move to just before the late 09:55 (+5): the cancelled 09:35 must be skipped.
    freezer.move_to("2026-10-07 09:30:00+00:00")
    aioclient_mock.post(DEPARTURES_URL, json=load("departures_cambria.json"))
    cambria_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(cambria_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR)
    assert state.state == "2026-10-07T10:00:00+00:00"
    assert state.attributes["scheduled"] == "2026-10-07T09:55:00+00:00"
    assert state.attributes["delay_minutes"] == 5


async def test_departures_attribute_not_recorded() -> None:
    assert "departures" in NextDepartureSensor._unrecorded_attributes


async def test_calendar(hass: HomeAssistant, loaded) -> None:
    state = hass.states.get(CALENDAR)
    assert state.attributes["message"] == "11e → Belfast, CastleCourt"
    assert state.attributes["start_time"] == "2026-10-07 09:46:00"  # local (Europe/London)

    start = dt_util.utcnow()
    resp = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": CALENDAR,
            "start_date_time": start,
            "end_date_time": start + timedelta(hours=2),
        },
        blocking=True,
        return_response=True,
    )
    events = resp[CALENDAR]["events"]
    assert [e["summary"] for e in events][:5] == [
        "11e → Belfast, CastleCourt",
        "11e → Belfast, CastleCourt",
        "11e → Belfast, CastleCourt",
        "11e → Belfast, CastleCourt (+5)",
        "11e → Belfast, CastleCourt (+5)",
    ]
    assert events[3]["description"] == "Scheduled 10:55, running 5 min late"


async def test_get_departures_action(hass: HomeAssistant, loaded) -> None:
    resp = await hass.services.async_call(
        DOMAIN,
        "get_departures",
        {"config_entry_id": loaded.entry_id, "count": 3},
        blocking=True,
        return_response=True,
    )
    assert resp["stop_name"] == "Shankill, Cambria Street"
    assert [d["expected"] for d in resp["departures"]] == [
        "2026-10-07T08:46:00+00:00",
        "2026-10-07T09:04:00+00:00",
        "2026-10-07T09:15:00+00:00",
    ]
    assert resp["departures"][0]["service"] == "11e"


async def test_get_departures_rejects_unknown_entry(hass: HomeAssistant, loaded) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "get_departures",
            {"config_entry_id": "nope"},
            blocking=True,
            return_response=True,
        )


async def test_api_failure_marks_unavailable(
    hass: HomeAssistant, loaded, aioclient_mock, freezer
) -> None:
    aioclient_mock.clear_requests()
    aioclient_mock.post(DEPARTURES_URL, status=500)
    freezer.tick(timedelta(seconds=61))
    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "unavailable"


async def test_unload(hass: HomeAssistant, loaded) -> None:
    assert await hass.config_entries.async_unload(loaded.entry_id)
    assert loaded.state is ConfigEntryState.NOT_LOADED
