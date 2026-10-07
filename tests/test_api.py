"""Client parsing and paging, using real captured responses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.translink_ni.api import (
    DEPARTURES_URL,
    TranslinkClient,
    TranslinkResponseError,
    parse_departures,
    ticks_to_datetime,
)

from .conftest import load


def test_ticks_are_utc():
    # 639269595600000000 is the 09:46 BST (08:46 UTC) Cambria Street 11e.
    assert ticks_to_datetime(639269595600000000) == datetime(2026, 10, 7, 8, 46, tzinfo=UTC)


def test_parse_cambria_drops_cancelled_and_keeps_delays():
    raw = load("departures_cambria.json")["Result"]["Departures"]
    assert len(raw) == 8
    assert sum(d["IsCancelled"] for d in raw) == 1

    deps = parse_departures(raw)

    assert len(deps) == 7  # the cancelled 10:35 is gone
    assert all(d.service == "11e" for d in deps)
    assert all(d.destination == "Belfast, CastleCourt" for d in deps)
    assert datetime(2026, 10, 7, 9, 35, tzinfo=UTC) not in {d.planned for d in deps}
    late = [d for d in deps if d.delay_minutes]
    assert [(d.planned.strftime("%H:%M"), d.delay_minutes) for d in late] == [
        ("09:55", 5),
        ("10:15", 5),
    ]
    assert all(d.expected >= d.planned for d in deps)


def test_parse_service_names_across_modes():
    deps = parse_departures(load("departures_mixed.json")["Result"]["Departures"])
    services = {d.service for d in deps}
    assert "G1" in services  # 'Glider G1'
    assert "12a" in services  # 'Bus 12a'
    assert any(s.endswith("Line") for s in services)  # 'Rail Bangor Line' -> 'Bangor Line'
    assert {d.transport_mode for d in deps} == {"Bus", "Train"}


def test_parse_skips_malformed_items():
    good = load("departures_flax.json")["Result"]["Departures"][0]
    assert len(parse_departures([good, {"ServiceName": "Bus 1"}])) == 1


def test_as_dict_is_json_friendly():
    dep = parse_departures(load("departures_cambria.json")["Result"]["Departures"])[3]
    data = dep.as_dict()
    assert data["planned"] == "2026-10-07T09:55:00+00:00"
    assert data["expected"] == "2026-10-07T10:00:00+00:00"
    assert data["delay_minutes"] == 5
    assert "is_real_time" not in data
    assert "is_cancelled" not in data


class _Resp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self) -> None:
        pass

    async def json(self, content_type=None):  # noqa: ARG002 (aiohttp signature)
        return self._payload


class FakeSession:
    """Serves a queue of payloads and records request bodies."""

    def __init__(self, *payloads: Any) -> None:
        self.payloads = list(payloads)
        self.bodies: list[dict] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Resp:  # noqa: ARG002
        assert url == DEPARTURES_URL
        self.bodies.append(kwargs["json"])
        return _Resp(self.payloads.pop(0) if self.payloads else {"ResponseCode": 200, "Result": {}})


def _page(*items: dict) -> dict:
    return {"ResponseCode": 200, "Result": {"Departures": list(items)}}


async def test_paging_dedupes_and_advances_cursor():
    raw = load("departures_cambria.json")["Result"]["Departures"]
    session = FakeSession(_page(*raw[:5]), _page(*raw[3:]))  # pages overlap by two
    client = TranslinkClient(session)  # type: ignore[arg-type]

    start = datetime(2026, 10, 7, 8, 37, tzinfo=UTC)
    deps = await client.get_departures("10012778", after=start, max_pages=2)

    assert len(deps) == 7  # 8 unique raw, minus one cancelled
    assert deps == sorted(deps, key=lambda d: d.expected)
    assert session.bodies[0]["DepartureOrArrivalDate"] == "2026-10-07T08:37:00"
    # Second page starts one second after the last raw departure of page one.
    last_page_one = max(ticks_to_datetime(d["SysActualDepartureDate"]) for d in raw[:5])
    assert session.bodies[1]["DepartureOrArrivalDate"] == (
        last_page_one + timedelta(seconds=1)
    ).strftime("%Y-%m-%dT%H:%M:%S")


async def test_page_of_only_cancelled_does_not_stop_paging():
    raw = load("departures_cambria.json")["Result"]["Departures"]
    cancelled = [d for d in raw if d["IsCancelled"]]
    later = [d for d in raw if d["SysActualDepartureDate"] > cancelled[0]["SysActualDepartureDate"]]
    session = FakeSession(_page(*cancelled), _page(*later))
    start = datetime(2026, 10, 7, 8, 37, tzinfo=UTC)
    deps = await TranslinkClient(session).get_departures(  # type: ignore[arg-type]
        "x", after=start, max_pages=2
    )
    assert len(session.bodies) == 2
    assert len(deps) == len(later)


async def test_until_trims_and_stops_early():
    raw = load("departures_cambria.json")["Result"]["Departures"]
    session = FakeSession(_page(*raw), _page(*raw))
    until = datetime(2026, 10, 7, 9, 5, tzinfo=UTC)
    start = datetime(2026, 10, 7, 8, 37, tzinfo=UTC)
    deps = await TranslinkClient(session).get_departures(  # type: ignore[arg-type]
        "x", after=start, until=until, max_pages=5
    )
    assert len(session.bodies) == 1  # first page already passed `until`
    assert [d.expected.strftime("%H:%M") for d in deps] == ["08:46", "09:04"]


async def test_error_response_code_raises():
    session = FakeSession({"ResponseCode": 500, "Result": None})
    with pytest.raises(TranslinkResponseError):
        await TranslinkClient(session).get_departures("x")  # type: ignore[arg-type]
