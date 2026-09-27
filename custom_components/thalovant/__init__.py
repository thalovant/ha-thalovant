"""The Thalovant integration: answer a Thalovant hub's home requests with Assist."""

import asyncio

from aiothalovant import (
    ConnectionCredentials,
    HubConnection,
    ThalovantApi,
    ThalovantAuthError,
    ThalovantConnectionError,
    Tokens,
)

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CREDENTIALS,
    CONF_TOKENS,
    DOMAIN,
    LOGGER,
    REMOVE_TIMEOUT,
    REQUEST_MESSAGE_TYPE,
)
from .handler import HomeRequestHandler, agent_issue_id
from .models import ThalovantConfigEntry, ThalovantRuntimeData

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ThalovantConfigEntry) -> bool:
    """Connect to the hub and answer its requests."""
    try:
        credentials = ConnectionCredentials.from_dict(entry.data[CONF_CREDENTIALS])
    except (KeyError, TypeError, ValueError) as err:
        # Unreadable keys are replaced the same way rejected ones are.
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="credentials_invalid",
            translation_placeholders={"hub": entry.title},
        ) from err
    connection = HubConnection(async_get_clientsession(hass), credentials)
    entry.runtime_data = ThalovantRuntimeData(connection=connection)

    # Everything below is undone by the unload callbacks, which also run when
    # this setup raises. Subscribing before the first connect means no request
    # can arrive before something listens for it.
    entry.async_on_unload(connection.close)
    handler = HomeRequestHandler(hass, entry, connection)
    entry.async_on_unload(
        connection.on_message(REQUEST_MESSAGE_TYPE, handler.async_handle_message)
    )
    state_logger = _StateLogger(entry.title)
    entry.async_on_unload(connection.on_state_change(state_logger))

    try:
        await connection.connect()
    except ThalovantAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
            translation_placeholders={"hub": entry.title},
        ) from err
    except ThalovantConnectionError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"hub": entry.title},
        ) from err
    state_logger(connection.connected)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_create_background_task(
        hass,
        _async_keep_connected(hass, entry, connection),
        name=f"{DOMAIN} hub connection {entry.title}",
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ThalovantConfigEntry) -> bool:
    """Unload the entry; the unload callbacks close the connection."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ThalovantConfigEntry) -> None:
    """Delete this installation's connection on the hub, best effort."""
    ir.async_delete_issue(hass, DOMAIN, agent_issue_id(entry.entry_id))
    try:
        tokens = Tokens.from_dict(entry.data[CONF_TOKENS])
        connection_id: str = entry.data[CONF_CREDENTIALS]["connection_id"]
        api = ThalovantApi(async_get_clientsession(hass), tokens)
        async with asyncio.timeout(REMOVE_TIMEOUT):
            await api.delete_connection(connection_id)
    except Exception as err:  # noqa: BLE001 - removal must never fail on this
        LOGGER.warning(
            "Could not delete the Home Assistant connection on %s (%s); "
            "remove it from the Thalovant dashboard",
            entry.title,
            type(err).__name__,
        )


async def _async_keep_connected(
    hass: HomeAssistant, entry: ThalovantConfigEntry, connection: HubConnection
) -> None:
    """Run the connection until unload; a rejected credential starts reauth."""
    try:
        await connection.run()
    except ThalovantAuthError:
        LOGGER.warning("The hub %s rejected this connection's credentials", entry.title)
        entry.async_start_reauth(hass)
    except Exception:
        LOGGER.exception("The connection to %s stopped", entry.title)


class _StateLogger:
    """Log once when the link drops and once when it comes back."""

    def __init__(self, title: str) -> None:
        self._title = title
        self._up = False
        self._lost = False

    @callback
    def __call__(self, connected: bool) -> None:
        if connected:
            if self._lost:
                LOGGER.info("Reconnected to %s", self._title)
            self._up, self._lost = True, False
        elif self._up:
            LOGGER.info("Lost the connection to %s; reconnecting", self._title)
            self._up, self._lost = False, True
