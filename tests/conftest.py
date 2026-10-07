"""Shared fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.translink_ni.const import (
    CONF_SERVICES,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DOMAIN,
)

FIXTURES = Path(__file__).parent / "fixtures"

# All captured fixtures were requested at this moment.
CAPTURED_AT = "2026-10-07 08:37:00+00:00"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/ in every test."""
    yield


@pytest.fixture
def cambria_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Shankill, Cambria Street",
        unique_id="10012778",
        data={CONF_STOP_ID: "10012778", CONF_STOP_NAME: "Shankill, Cambria Street"},
        options={CONF_SERVICES: []},
    )
