"""The Thalovant integration: answer a Thalovant hub's home requests with Assist."""

import asyncio
from datetime import datetime
from pathlib import Path
import re
import shutil

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.util import dt as dt_util

from .api import (
    ConnectionCredentials,
    HubConnection,
    ThalovantApi,
    ThalovantAuthError,
    ThalovantClientKeyRejectedError,
    ThalovantConnectionError,
    ThalovantHubKeyChangedError,
    Tokens,
)
from .const import (
    ADMISSION_GRACE_PERIOD,
    CONF_CREDENTIALS,
    CONF_LINKED_AT,
    CONF_TOKENS,
    DOMAIN,
    LOGGER,
    REMOVE_TIMEOUT,
    REQUEST_MESSAGE_TYPE,
)
from .handler import HomeRequestHandler, agent_issue_id
from .models import ThalovantConfigEntry, ThalovantRuntimeData

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR]

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")


def key_changed_issue_id(entry_id: str) -> str:
    """The repair issue raised when a hub's Noise key no longer matches its pin."""
    return f"hub_key_changed_{entry_id}"


def key_rejected_issue_id(entry_id: str) -> str:
    """The repair issue raised when the hub refuses this connection's own key."""
    return f"client_key_rejected_{entry_id}"


def _noise_root(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(STORAGE_DIR, DOMAIN))


def _noise_dir_name(connection_id: str) -> str:
    return _UNSAFE_NAME.sub("_", connection_id) or "_"


def _noise_dir(hass: HomeAssistant, entry: ThalovantConfigEntry) -> Path | None:
    """Where one connection keeps its Noise key and the hub key it pinned.

    One directory per connection: re-linking makes a new connection, so it
    starts with a new key and no pin. Kept under .storage, so it survives
    updates and is in backups.
    """
    credentials = entry.data.get(CONF_CREDENTIALS)
    connection_id = (
        credentials.get("connection_id") if isinstance(credentials, dict) else None
    )
    if not isinstance(connection_id, str):
        return None
    return _noise_root(hass) / _noise_dir_name(connection_id)


def _prune_noise_dirs(root: Path, keep: set[str]) -> None:
    """Remove what no entry's connection uses any more. Runs in the executor."""
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.name in keep:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


@callback
def _async_hub_key_changed(hass: HomeAssistant, entry: ThalovantConfigEntry) -> None:
    """Explain a changed hub key; retrying cannot fix it, re-linking can."""
    LOGGER.warning(
        "The hub %s presented a different key than the one it was linked with; "
        "re-link it once you know why",
        entry.title,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        key_changed_issue_id(entry.entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="hub_key_changed",
        translation_placeholders={"hub": entry.title},
    )


@callback
def _async_client_key_rejected(
    hass: HomeAssistant, entry: ThalovantConfigEntry
) -> None:
    """Explain a refused client key; retrying cannot fix it, re-linking can."""
    LOGGER.warning(
        "The hub %s no longer accepts this Home Assistant's key for the link; "
        "re-link it to make a new connection",
        entry.title,
    )
    ir.async_create_issue(
        hass,
        DOMAIN,
        key_rejected_issue_id(entry.entry_id),
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key="client_key_rejected",
        translation_placeholders={"hub": entry.title},
    )


@callback
def _async_delete_key_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Clear the repair issues about keys: the link works, or it is gone."""
    ir.async_delete_issue(hass, DOMAIN, key_changed_issue_id(entry_id))
    ir.async_delete_issue(hass, DOMAIN, key_rejected_issue_id(entry_id))


async def async_setup_entry(hass: HomeAssistant, entry: ThalovantConfigEntry) -> bool:
    """Connect to the hub and answer its requests."""
    try:
        credentials = ConnectionCredentials.from_dict(entry.data[CONF_CREDENTIALS])
        connection = HubConnection(
            async_get_clientsession(hass),
            credentials,
            state_dir=str(
                _noise_root(hass) / _noise_dir_name(credentials.connection_id)
            ),
        )
    except (KeyError, TypeError, ValueError) as err:
        # Unreadable keys are replaced the same way rejected ones are.
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="credentials_invalid",
            translation_placeholders={"hub": entry.title},
        ) from err
    entry.runtime_data = ThalovantRuntimeData(connection=connection)
    await hass.async_add_executor_job(
        _prune_noise_dirs,
        _noise_root(hass),
        {
            directory.name
            for other in hass.config_entries.async_entries(DOMAIN)
            if (directory := _noise_dir(hass, other)) is not None
        },
    )

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
    except ThalovantHubKeyChangedError as err:
        _async_hub_key_changed(hass, entry)
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="hub_key_changed",
            translation_placeholders={"hub": entry.title},
        ) from err
    except ThalovantAuthError as err:
        if _recently_linked(entry):
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="not_admitted_yet",
                translation_placeholders={"hub": entry.title},
            ) from err
        key_rejected = isinstance(err, ThalovantClientKeyRejectedError)
        if key_rejected:
            _async_client_key_rejected(hass, entry)
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="client_key_rejected" if key_rejected else "auth_failed",
            translation_placeholders={"hub": entry.title},
        ) from err
    except ThalovantConnectionError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"hub": entry.title},
        ) from err
    state_logger(connection.connected)
    _async_delete_key_issues(hass, entry.entry_id)

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
    """Delete the connection on the hub, then revoke the API token, best effort.

    The token is the account's, shared by every entry it linked (see the
    config flow), so it is revoked only with the last of them.
    """
    ir.async_delete_issue(hass, DOMAIN, agent_issue_id(entry.entry_id))
    _async_delete_key_issues(hass, entry.entry_id)
    if (directory := _noise_dir(hass, entry)) is not None:
        await hass.async_add_executor_job(shutil.rmtree, directory, True)
    try:
        tokens = Tokens.from_dict(entry.data[CONF_TOKENS])
    except KeyError, TypeError, ValueError:
        LOGGER.warning(
            "The stored Thalovant token for %s cannot be read; remove its "
            "connection and API token from the Thalovant dashboard",
            entry.title,
        )
        return
    api = ThalovantApi(async_get_clientsession(hass), tokens)
    try:
        connection_id: str = entry.data[CONF_CREDENTIALS]["connection_id"]
        async with asyncio.timeout(REMOVE_TIMEOUT):
            await api.delete_connection(connection_id)
    except Exception as err:  # noqa: BLE001 - removal must never fail on this
        LOGGER.warning(
            "Could not delete the Home Assistant connection on %s (%s); "
            "remove it from the Thalovant dashboard",
            entry.title,
            type(err).__name__,
        )
    # Deleting the connection needs the token, so the token goes last.
    if _token_in_use(hass, entry, tokens):
        return
    try:
        async with asyncio.timeout(REMOVE_TIMEOUT):
            await api.revoke_token()
    except Exception as err:  # noqa: BLE001 - removal must never fail on this
        LOGGER.warning(
            "Could not revoke the Thalovant API token of %s (%s); "
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
    except ThalovantHubKeyChangedError:
        _async_hub_key_changed(hass, entry)
        entry.async_start_reauth(hass)
    except ThalovantClientKeyRejectedError:
        _async_client_key_rejected(hass, entry)
        entry.async_start_reauth(hass)
    except ThalovantAuthError:
        LOGGER.warning("The hub %s rejected this connection's credentials", entry.title)
        entry.async_start_reauth(hass)
    except Exception:
        LOGGER.exception("The connection to %s stopped", entry.title)


def _token_in_use(
    hass: HomeAssistant, removed: ThalovantConfigEntry, tokens: Tokens
) -> bool:
    """Whether another entry still signs in with this API token."""
    for other in hass.config_entries.async_entries(DOMAIN):
        if other.entry_id == removed.entry_id:
            continue
        stored = other.data.get(CONF_TOKENS)
        if isinstance(stored, dict) and (
            stored.get("access_token") == tokens.access_token
        ):
            return True
    return False


def _recently_linked(entry: ThalovantConfigEntry) -> bool:
    """Whether the connection is young enough that the hub may not know it yet."""
    try:
        linked_at = datetime.fromisoformat(entry.data[CONF_LINKED_AT])
    except KeyError, TypeError, ValueError:
        return False
    return dt_util.utcnow() - linked_at < ADMISSION_GRACE_PERIOD


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
