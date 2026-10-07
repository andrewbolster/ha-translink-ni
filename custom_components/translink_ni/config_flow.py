"""Config flow: search for a stop by name, pick it, optionally filter services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import Stop, TranslinkClient, TranslinkError
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_SERVICES,
    CONF_STOP_ID,
    CONF_STOP_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

if TYPE_CHECKING:
    from .coordinator import TranslinkConfigEntry

CONF_QUERY = "query"


async def _services_at_stop(client: TranslinkClient, stop_id: str) -> list[str]:
    """Services seen in the next couple of pages of departures (best effort)."""
    try:
        deps = await client.get_departures(stop_id, max_pages=3)
    except TranslinkError:
        return []
    return sorted({d.service for d in deps if d.service}, key=str.lower)


def _service_selector(services: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=services,
            multiple=True,
            custom_value=True,  # services not running right now can be typed in
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class TranslinkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a stop."""

    VERSION = 1

    def __init__(self) -> None:
        """Start a new flow."""
        self._stops: dict[str, Stop] = {}
        self._stop: Stop | None = None
        self._services: list[str] = []

    @property
    def _client(self) -> TranslinkClient:
        return TranslinkClient(async_get_clientsession(self.hass))

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 1: free-text stop search."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = user_input[CONF_QUERY].strip()
            try:
                stops = await self._client.search_stops(query)
            except TranslinkError:
                errors["base"] = "cannot_connect"
            else:
                if not stops:
                    errors[CONF_QUERY] = "no_stops"
                else:
                    self._stops = {s.id: s for s in stops}
                    return await self.async_step_stop()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): TextSelector()}),
            errors=errors,
        )

    async def async_step_stop(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step 2: pick one of the matches."""
        if user_input is not None:
            self._stop = self._stops[user_input[CONF_STOP_ID]]
            await self.async_set_unique_id(self._stop.id)
            self._abort_if_unique_id_configured()
            self._services = await _services_at_stop(self._client, self._stop.id)
            return await self.async_step_services()
        options = [SelectOptionDict(value=s.id, label=s.name) for s in self._stops.values()]
        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_STOP_ID, default=options[0]["value"]): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_services(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: optionally limit to some services."""
        if self._stop is None:  # pragma: no cover - only reachable via a crafted flow
            return await self.async_step_user()
        if user_input is not None:
            return self.async_create_entry(
                title=self._stop.name,
                data={CONF_STOP_ID: self._stop.id, CONF_STOP_NAME: self._stop.name},
                options={CONF_SERVICES: user_input.get(CONF_SERVICES, [])},
            )
        return self.async_show_form(
            step_id="services",
            data_schema=vol.Schema(
                {vol.Optional(CONF_SERVICES, default=[]): _service_selector(self._services)}
            ),
            description_placeholders={
                "stop": self._stop.name,
                "seen": ", ".join(self._services) or "none right now",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: TranslinkConfigEntry,  # noqa: ARG004 (HA signature)
    ) -> OptionsFlow:
        """Options: service filter and polling interval."""
        return TranslinkOptionsFlow()


class TranslinkOptionsFlow(OptionsFlow):
    """Change filter / polling for an existing stop."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show/save the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        current = list(opts.get(CONF_SERVICES, []))
        seen = await _services_at_stop(
            TranslinkClient(async_get_clientsession(self.hass)),
            self.config_entry.data[CONF_STOP_ID],
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_SERVICES, default=current): _service_selector(
                        sorted(set(seen) | set(current), key=str.lower)
                    ),
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=900,
                            step=15,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
