"""Constants for the Translink NI integration."""

from datetime import timedelta

DOMAIN = "translink_ni"
ATTRIBUTION = "Data provided by Translink"

CONF_STOP_ID = "stop_id"
CONF_STOP_NAME = "stop_name"
CONF_SERVICES = "services"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 60  # seconds
MIN_SCAN_INTERVAL = 30

# How far ahead the coordinator keeps a board for (2 pages of 8 departures).
BOARD_PAGES = 2

# Calendar range queries beyond the cached board fetch at most this many pages.
CALENDAR_MAX_PAGES = 12
CALENDAR_MAX_RANGE = timedelta(days=2)

SERVICE_GET_DEPARTURES = "get_departures"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_COUNT = "count"
ATTR_START = "start"
