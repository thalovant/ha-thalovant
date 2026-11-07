"""The private hub endpoint and its Christmas lighting request boundary."""

from collections.abc import Mapping
from hashlib import sha256
import re
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import ConnectionCredentials, HubMessage
from .const import (
    CONF_HOME_CLIENT_ID,
    CONF_HUB_ID,
    CONF_VOICE_CLIENT_ID,
    REQUEST_MESSAGE_TYPE,
)

_HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_ENDPOINT = re.compile(
    rf"wss://(?P<host>{_HOST_LABEL}(?:\.{_HOST_LABEL})+)(?::(?P<port>[1-9][0-9]{{0,4}}))?/?",
    re.IGNORECASE | re.ASCII,
)
_CLIENT_ID = re.compile(r"[1-9][0-9]{0,18}")
_SECRET = re.compile(r"[!-~]{1,256}")
_REQUEST_ID = re.compile(r"[0-9a-f]{32}")
_LIGHTING_UTTERANCE = re.compile(
    r"thalovant christmas mirror (?:begin|candle|cranberry|evergreen|photo|finale|end) [0-9a-f]{16}"
)


def normalize_endpoint(value: object) -> str:
    """Canonicalize a TLS WebSocket endpoint at the root of a DNS host."""
    if not isinstance(value, str) or len(value) > 270:
        raise ValueError("Invalid WebSocket endpoint")
    match = _ENDPOINT.fullmatch(value)
    if match is None:
        raise ValueError("Invalid WebSocket endpoint")
    host = match["host"].lower()
    port = int(match["port"] or 443)
    if len(host) > 253 or port > 65535:
        raise ValueError("Invalid WebSocket endpoint")
    return f"wss://{host}" if port == 443 else f"wss://{host}:{port}"


def _client_id(value: object) -> str:
    """Accept only an operator-assigned positive decimal database ID."""
    if not isinstance(value, str) or _CLIENT_ID.fullmatch(value) is None:
        raise ValueError("Invalid client ID")
    return value


def connection_client_ids(data: Mapping[str, Any]) -> tuple[str, str]:
    """Validate the distinct Home Assistant and Voice IDs from the operator."""
    home_id = _client_id(data.get(CONF_HOME_CLIENT_ID))
    voice_id = _client_id(data.get(CONF_VOICE_CLIENT_ID))
    if home_id == voice_id:
        raise ValueError("Home and Voice identities must be separate")
    return home_id, voice_id


def connection_secret(value: object) -> str:
    """Accept bounded credentials without changing their literal characters."""
    if not isinstance(value, str) or _SECRET.fullmatch(value) is None:
        raise ValueError("Invalid connection credential")
    return value


def credentials_for(
    endpoint: str, home_client_id: str, access_key: str, password: str
) -> ConnectionCredentials:
    """Build one WSS-only SDK identity from the validated operator fields."""
    endpoint_id = sha256(endpoint.encode()).hexdigest()
    connection_id = f"self_hosted_{endpoint_id}_{home_client_id}"
    return ConnectionCredentials(
        hub_id=f"self_hosted:{endpoint_id}",
        connection_id=connection_id,
        name="Private Christmas lighting",
        endpoint=endpoint,
        secret={
            "access_key": access_key,
            "password": password,
            "site_id": f"ha-thalovant-{home_client_id}",
            "default_master": endpoint,
            "data_plane_endpoints": {"wss": endpoint},
            "protocols": {"wss": True, "http": False, "mqtt": False},
        },
    )


def validate_credentials(
    credentials: ConnectionCredentials, entry_data: Mapping[str, Any]
) -> None:
    """Reject a persisted identity that can choose a different transport or scope."""
    home_id, _ = connection_client_ids(entry_data)
    if entry_data.get(
        CONF_HUB_ID
    ) != credentials.hub_id or credentials != credentials_for(
        normalize_endpoint(credentials.endpoint),
        home_id,
        connection_secret(credentials.secret.get("access_key")),
        connection_secret(credentials.secret.get("password")),
    ):
        raise ValueError("Invalid private hub identity")


async def _reject_redirect(
    session: aiohttp.ClientSession,
    trace_context: Any,
    params: aiohttp.TraceRequestRedirectParams,
) -> None:
    """Prevent any redirect from receiving the SDK's credential-bearing URL."""
    params.response.close()
    raise aiohttp.ClientConnectionError("The private hub redirected the connection")


@callback
def async_create_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    """Create a TLS-verifying, redirect-free session owned by the config entry."""
    trace = aiohttp.TraceConfig()
    trace.on_request_redirect.append(_reject_redirect)
    return async_create_clientsession(hass, trace_configs=[trace])


def permits_lighting_request(message: HubMessage, allowed_device: object) -> bool:
    """Accept only the trusted router's bounded lighting RPC for one Voice ID."""
    if (
        message.type != REQUEST_MESSAGE_TYPE
        or not isinstance(allowed_device, str)
        or _CLIENT_ID.fullmatch(allowed_device) is None
        or not isinstance(message.context, Mapping)
        or message.context.get("source") != "thalovant.home.router"
        or not isinstance(message.data, Mapping)
    ):
        return False

    request_id = message.data.get("request_id")
    utterance = message.data.get("utterance")
    session = message.context.get("session")
    device = message.data.get("device")
    return (
        isinstance(request_id, str)
        and _REQUEST_ID.fullmatch(request_id) is not None
        and isinstance(session, Mapping)
        and session.get("session_id") == f"home-{request_id}"
        and session.get("lang") == "en-US"
        and isinstance(device, Mapping)
        and device.get("id") == allowed_device
        and message.data.get("lang") == "en-US"
        and "conversation_id" not in message.data
        and isinstance(utterance, str)
        and _LIGHTING_UTTERANCE.fullmatch(utterance) is not None
    )
