"""Config and options flow."""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.translink_ni.api import DEPARTURES_URL, LOCATION_URL
from custom_components.translink_ni.const import (
    CONF_SCAN_INTERVAL,
    CONF_SERVICES,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DOMAIN,
)

from .conftest import CAPTURED_AT, load

pytestmark = pytest.mark.freeze_time(CAPTURED_AT)


async def test_search_pick_filter_creates_entry(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(LOCATION_URL, json=load("location_find.json"))
    aioclient_mock.post(DEPARTURES_URL, json=load("departures_cambria.json"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"query": "Cambria Street"}
    )
    assert result["step_id"] == "stop"
    options = result["data_schema"].schema[CONF_STOP_ID].config["options"]
    assert [o["label"] for o in options] == ["Shankill, Cambria Street", "Shankill, Flax Street"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STOP_ID: "10012778"}
    )
    assert result["step_id"] == "services"
    assert result["description_placeholders"]["seen"] == "11e"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SERVICES: ["11e", "11f"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Shankill, Cambria Street"
    assert result["data"] == {CONF_STOP_ID: "10012778", CONF_STOP_NAME: "Shankill, Cambria Street"}
    assert result["options"] == {CONF_SERVICES: ["11e", "11f"]}
    assert result["result"].unique_id == "10012778"


async def test_no_matches(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(LOCATION_URL, json=load("location_none.json"))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Nowhere"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"query": "no_stops"}


async def test_cannot_connect(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(LOCATION_URL, status=503)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "x"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_duplicate_stop_aborts(hass: HomeAssistant, aioclient_mock, cambria_entry) -> None:
    cambria_entry.add_to_hass(hass)
    aioclient_mock.get(LOCATION_URL, json=load("location_find.json"))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"query": "Cambria"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STOP_ID: "10012778"}
    )
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_options_flow(hass: HomeAssistant, aioclient_mock, cambria_entry) -> None:
    aioclient_mock.post(DEPARTURES_URL, json=load("departures_cambria.json"))
    cambria_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(cambria_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(cambria_entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SERVICES: ["11f"], CONF_SCAN_INTERVAL: 120}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert cambria_entry.options == {CONF_SERVICES: ["11f"], CONF_SCAN_INTERVAL: 120}
    # Reloaded with the filter: no 11f in the fixture, so no next departure.
    assert hass.states.get("sensor.shankill_cambria_street_next_departure").state == "unknown"
