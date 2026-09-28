"""Fixtures for the Thalovant tests."""

import asyncio
from collections.abc import Awaitable, Callable, Generator, Mapping
from datetime import UTC, datetime
import inspect
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.api import (
    Account,
    ConnectionCredentials,
    DeviceLogin,
    Hub,
    HubMessage,
    Tokens,
)
from custom_components.thalovant.const import (
    CONF_ACCOUNT_ID,
    CONF_CREDENTIALS,
    CONF_HUB_ID,
    CONF_HUB_NAME,
    CONF_TOKENS,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

ACCOUNT_ID = "acct-7f3a"
HUB_ID = "hub-maison"
OTHER_HUB_ID = "hub-daily-desk"
CONNECTION_ID = "conn-91c2"
ACCESS_TOKEN = "tvt_access_do_not_leak"
TOKEN_ID = "tok-5b1e"
CONNECTION_SECRET = "hub-password-do-not-leak"
ACCESS_KEY = "hub-access-key-do-not-leak"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ in every test."""


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Give every test its own config directory: the integration writes to .storage."""
    return hass_tmp_config_dir


@pytest.fixture(autouse=True)
async def setup_homeassistant(hass: HomeAssistant) -> None:
    """Set up the core integration conversation relies on for exposed entities."""
    assert await async_setup_component(hass, "homeassistant", {})


@pytest.fixture(autouse=True)
def fast_polling() -> Generator[None]:
    """Let the device login poll without waiting."""
    with patch("custom_components.thalovant.config_flow.MIN_POLL_INTERVAL", 0):
        yield


@pytest.fixture
def device_login() -> DeviceLogin:
    """A started device login."""
    return DeviceLogin(
        device_code="device-code-0123456789",
        user_code="WXYZ-2345",
        verification_uri="https://dash.thalovant.com/device",
        verification_uri_complete="https://dash.thalovant.com/device?code=WXYZ-2345",
        interval=0,
        expires_in=900,
    )


@pytest.fixture
def tokens() -> Tokens:
    """Tokens from an approved login."""
    return Tokens(
        access_token=ACCESS_TOKEN,
        expires_at=datetime(2027, 9, 27, tzinfo=UTC),
        scopes=("hubs:read", "clients:read", "clients:write"),
        token_id=TOKEN_ID,
    )


@pytest.fixture
def account() -> Account:
    """The signed-in account."""
    return Account(id=ACCOUNT_ID, display_name="Gaëtan", email="gaetan@example.com")


@pytest.fixture
def hubs() -> list[Hub]:
    """The account's hubs."""
    return [
        Hub(id=HUB_ID, name="Maison"),
        Hub(id=OTHER_HUB_ID, name="Daily Desk"),
    ]


@pytest.fixture
def credentials() -> ConnectionCredentials:
    """A created connection."""
    return ConnectionCredentials(
        hub_id=HUB_ID,
        connection_id=CONNECTION_ID,
        name="Home Assistant (Maison)",
        endpoint="wss://maison.hubs.thalovant.com/ws",
        # Opaque to the integration: the SDK identity, secrets included.
        secret={
            "access_key": ACCESS_KEY,
            "password": CONNECTION_SECRET,
            "site_id": "home-assistant-maison",
            "default_master": "maison.hubs.thalovant.com",
            "default_port": 443,
            "default_path": "",
        },
        operation_url="https://api.thalovant.com/v1/operations/op-1",
    )


@pytest.fixture
def mock_auth(device_login: DeviceLogin, tokens: Tokens) -> Generator[MagicMock]:
    """ThalovantAuth, as the config flow sees it."""
    auth = MagicMock()
    auth.start_device_login = AsyncMock(return_value=device_login)
    auth.poll_device_login = AsyncMock(return_value=tokens)
    with patch(
        "custom_components.thalovant.config_flow.ThalovantAuth", return_value=auth
    ):
        yield auth


@pytest.fixture
def mock_api(
    account: Account, hubs: list[Hub], credentials: ConnectionCredentials
) -> Generator[MagicMock]:
    """ThalovantApi, for both the config flow and entry removal."""
    api = MagicMock()
    api.get_account = AsyncMock(return_value=account)
    api.list_hubs = AsyncMock(return_value=hubs)
    api.create_connection = AsyncMock(return_value=credentials)
    api.wait_for_admission = AsyncMock(return_value=None)
    api.delete_connection = AsyncMock(return_value=None)
    api.revoke_token = AsyncMock(return_value=None)
    with (
        patch("custom_components.thalovant.config_flow.ThalovantApi", return_value=api),
        patch("custom_components.thalovant.ThalovantApi", return_value=api),
    ):
        yield api


class FakeHubConnection:
    """A HubConnection whose link the test drives."""

    def __init__(self) -> None:
        """Initialize the fake."""
        self._connected = False
        self._closed = asyncio.Event()
        self.state_callbacks: list[Callable[[bool], None]] = []
        self.message_callbacks: dict[
            str, list[Callable[[HubMessage], Awaitable[None] | None]]
        ] = {}
        self.connect = AsyncMock(side_effect=self._connect)
        self.run = AsyncMock(side_effect=self._run)
        self.close = AsyncMock(side_effect=self._close)
        self.reply = AsyncMock()
        self.replies: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.reply.side_effect = self._reply

    @property
    def connected(self) -> bool:
        """Whether the link is up."""
        return self._connected

    def set_connected(self, connected: bool) -> None:
        """Change the link state and notify subscribers."""
        self._connected = connected
        for callback in list(self.state_callbacks):
            callback(connected)

    def on_state_change(self, callback: Callable[[bool], None]) -> Callable[[], None]:
        """Subscribe to state changes."""
        self.state_callbacks.append(callback)
        return lambda: self.state_callbacks.remove(callback)

    def on_message(
        self,
        msg_type: str,
        callback: Callable[[HubMessage], Awaitable[None] | None],
    ) -> Callable[[], None]:
        """Subscribe to a message type."""
        callbacks = self.message_callbacks.setdefault(msg_type, [])
        callbacks.append(callback)
        return lambda: callbacks.remove(callback)

    async def emit(
        self,
        msg_type: str,
        data: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
        *,
        age: float = 0.0,
    ) -> HubMessage:
        """Deliver a message from the hub the way the library would.

        age is how long ago it arrived, in seconds.
        """
        message = HubMessage(
            type=msg_type,
            data=data,
            context=context or {"session": "s1"},
            received_at=time.monotonic() - age,
        )
        for callback in list(self.message_callbacks.get(msg_type, [])):
            result = callback(message)
            if inspect.isawaitable(result):
                await result
        return message

    async def next_reply(self, timeout: float = 5) -> dict[str, Any]:
        """Wait for the next answer sent to the hub."""
        async with asyncio.timeout(timeout):
            return await self.replies.get()

    async def _reply(
        self, request: HubMessage, msg_type: str, data: Mapping[str, Any]
    ) -> None:
        self.replies.put_nowait(dict(data))

    async def _connect(self) -> None:
        self.set_connected(True)

    async def _run(self) -> None:
        await self._closed.wait()

    async def _close(self) -> None:
        self._closed.set()
        self._connected = False


@pytest.fixture
def mock_hub_connection() -> Generator[FakeHubConnection]:
    """The connection the integration builds at setup."""
    connection = FakeHubConnection()
    with patch(
        "custom_components.thalovant.HubConnection", return_value=connection
    ) as factory:
        connection.factory = factory  # type: ignore[attr-defined]
        yield connection


@pytest.fixture
def mock_config_entry(
    tokens: Tokens, credentials: ConnectionCredentials
) -> MockConfigEntry:
    """A linked hub."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Maison",
        unique_id=f"{ACCOUNT_ID}:{HUB_ID}",
        data={
            CONF_ACCOUNT_ID: ACCOUNT_ID,
            CONF_HUB_ID: HUB_ID,
            CONF_HUB_NAME: "Maison",
            CONF_TOKENS: tokens.to_dict(),
            CONF_CREDENTIALS: credentials.to_dict(),
        },
        version=1,
        minor_version=1,
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Keep config flow tests from setting the entry up."""
    with patch(
        "custom_components.thalovant.async_setup_entry", return_value=True
    ) as setup_entry:
        yield setup_entry
