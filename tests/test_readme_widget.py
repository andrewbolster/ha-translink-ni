"""The README's next-departure widget renders as the acceptance criteria describe."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from custom_components.translink_ni.api import DEPARTURES_URL

from .conftest import load

README = Path(__file__).parent.parent / "README.md"


def _widget_template() -> str:
    block = README.read_text().split("## Widget: next departure")[1]
    yaml = re.search(r"```yaml\n(.*?)```", block, re.DOTALL).group(1)
    content = yaml.split("content: >\n", 1)[1]
    # YAML folded block: strip the 2-space indent, keep lines.
    return "\n".join(line[2:] for line in content.splitlines())


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        ("2026-10-07 08:37:00+00:00", "**09:46** · 9 min"),  # on time: scheduled only
        ("2026-10-07 09:30:00+00:00", "**10:55** → **11:00** (+5 min) · 30 min"),  # late
    ],
)
async def test_widget(hass: HomeAssistant, aioclient_mock, cambria_entry, freezer, now, expected):
    freezer.move_to(now)
    await hass.config.async_set_time_zone("Europe/London")
    aioclient_mock.post(DEPARTURES_URL, json=load("departures_cambria.json"))
    cambria_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(cambria_entry.entry_id)
    await hass.async_block_till_done()

    rendered = Template(_widget_template(), hass).async_render(parse_result=False)
    text = " ".join(rendered.split())
    assert "## 11e → Belfast, CastleCourt" in text
    assert expected in text
