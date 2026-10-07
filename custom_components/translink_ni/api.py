"""Minimal async client for Translink NI's journey planner endpoints.

These are the (undocumented) endpoints behind translink.co.uk's own stop
search and departure boards. No API key is required.

Kept free of Home Assistant imports so it can be tested and reused standalone.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://www.translink.co.uk"
LOCATION_URL = f"{BASE_URL}/locationApi/find"
DEPARTURES_URL = f"{BASE_URL}/JourneyPlannerApi/GetJourneyResults"
USER_AGENT = "ha-translink-ni (+https://github.com/andrewbolster/ha-translink-ni)"

# The API returns at most this many departures per request.
PAGE_SIZE = 8

# .NET DateTime ticks (100ns since 0001-01-01) -> Unix seconds.
_NET_TICKS_EPOCH = 621_355_968_000_000_000
_NET_TICKS_PER_SECOND = 10_000_000

_TIMEOUT = aiohttp.ClientTimeout(total=15)


class TranslinkError(Exception):
    """Base error for the Translink client."""


class TranslinkConnectionError(TranslinkError):
    """The Translink endpoint could not be reached or returned an HTTP error."""


class TranslinkResponseError(TranslinkError):
    """The Translink endpoint returned something we don't understand."""


@dataclass(frozen=True, slots=True)
class Stop:
    """A bus/rail stop as returned by the location search."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Departure:
    """A single (non-cancelled) departure from a stop.

    ``IsRealTime`` is deliberately not carried: it is true for every departure
    the API returns, so it says nothing about whether a bus is being tracked.
    """

    service: str
    destination: str
    planned: datetime
    expected: datetime
    transport_mode: str

    @property
    def delay_minutes(self) -> int:
        """Minutes late (negative if early), rounded."""
        return round((self.expected - self.planned).total_seconds() / 60)

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly representation (ISO timestamps)."""
        data = asdict(self)
        data["planned"] = self.planned.isoformat()
        data["expected"] = self.expected.isoformat()
        data["delay_minutes"] = self.delay_minutes
        return data


def ticks_to_datetime(ticks: int) -> datetime:
    """Convert .NET DateTime ticks (UTC) to an aware datetime."""
    return datetime.fromtimestamp((ticks - _NET_TICKS_EPOCH) / _NET_TICKS_PER_SECOND, UTC)


def _clean_service(name: str) -> str:
    """'Bus 11e' -> '11e', 'Glider G1' -> 'G1'.

    Rail services are route descriptions ('Rail Belfast - Dublin (Enterprise)')
    so only the mode word is stripped.
    """
    for prefix in ("Bus ", "Glider ", "Rail ", "Train ", "Coach "):
        if name.startswith(prefix):
            return name[len(prefix) :]
    return name


def parse_departures(raw: list[dict[str, Any]]) -> list[Departure]:
    """Parse the ``Result.Departures`` array.

    Cancelled departures are dropped: a cancelled bus is never useful as a
    "next departure", and the flag is rare (and occasionally withdrawn later).

    Only the ``Sys*`` tick fields are used for times: the string time fields
    are UTC while the response's own header time is local, which is a trap.
    """
    departures = []
    for item in raw:
        if item.get("IsCancelled"):
            continue
        try:
            departures.append(
                Departure(
                    service=_clean_service(item.get("ServiceName") or ""),
                    destination=item.get("DestinationName") or "",
                    planned=ticks_to_datetime(int(item["SysPlannedDepartureDate"])),
                    expected=ticks_to_datetime(int(item["SysActualDepartureDate"])),
                    transport_mode=item.get("TransportMode") or "",
                )
            )
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Skipping unparseable departure %s: %s", item, err)
    return departures


class TranslinkClient:
    """Async client for stop search and departures."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        try:
            async with self._session.request(
                method, url, headers=headers, timeout=_TIMEOUT, **kwargs
            ) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TranslinkConnectionError(f"{method} {url} failed: {err}") from err
        except ValueError as err:
            raise TranslinkResponseError(f"{url} returned invalid JSON") from err

    async def search_stops(self, query: str) -> list[Stop]:
        """Find stops whose name matches ``query``."""
        data = await self._request(
            "GET", LOCATION_URL, params={"SearchString": query, "StopsOnly": "true"}
        )
        if not isinstance(data, dict):
            raise TranslinkResponseError("Unexpected stop search response")
        return [
            Stop(id=str(loc["Id"]), name=loc.get("Name") or str(loc["Id"]))
            for loc in data.get("Locations") or []
            if loc.get("Id")
        ]

    async def _departures_page(
        self, stop_id: str, after: datetime
    ) -> tuple[list[Departure], datetime | None]:
        """One page: (parsed non-cancelled departures, latest raw departure time)."""
        payload = {
            "OriginId": stop_id,
            # The API interprets this as UTC. Times in the past are ignored:
            # results always start from "now".
            "DepartureOrArrivalDate": after.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        }
        data = await self._request("POST", DEPARTURES_URL, json=payload)
        if not isinstance(data, dict) or data.get("ResponseCode") not in (200, None):
            raise TranslinkResponseError(f"Unexpected departures response: {data!r:.200}")
        raw = (data.get("Result") or {}).get("Departures") or []
        last = None
        ticks = [d.get("SysActualDepartureDate") for d in raw if d.get("SysActualDepartureDate")]
        if ticks:
            last = ticks_to_datetime(int(max(ticks)))
        return parse_departures(raw), last

    async def get_departures(
        self,
        stop_id: str,
        *,
        after: datetime | None = None,
        until: datetime | None = None,
        max_pages: int = 2,
    ) -> list[Departure]:
        """Upcoming departures from ``stop_id``, oldest first.

        Fetches up to ``max_pages`` pages of 8, stopping early once ``until`` is
        passed. Duplicates across pages are removed on (service, destination,
        planned time): the API mints a fresh UniqueId per request so that
        field can't be used.
        """
        cursor = after or datetime.now(UTC)
        seen: set[tuple[str, str, datetime]] = set()
        result: list[Departure] = []
        for _ in range(max_pages):
            page, last = await self._departures_page(stop_id, cursor)
            for dep in page:
                key = (dep.service, dep.destination, dep.planned)
                if key not in seen:
                    seen.add(key)
                    result.append(dep)
            # Page on the raw times so cancelled departures don't end paging.
            if last is None or last <= cursor or (until is not None and last >= until):
                break
            # The date is an inclusive lower bound; step past the last one.
            cursor = last + timedelta(seconds=1)
        result.sort(key=lambda d: d.expected)
        if until is not None:
            result = [d for d in result if d.expected <= until]
        return result
