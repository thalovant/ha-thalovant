"""Exercise the real SDK's private-hub connection and HA's network boundary."""

import asyncio
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path
import ssl
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

from custom_components.thalovant import self_hosted
from custom_components.thalovant.api import (
    ConnectionCredentials,
    HubConnection,
    ThalovantConnectionError,
)
from homeassistant.core import HomeAssistant

pytest.importorskip("thalovant")

ACCESS_KEY = "fixture-only-hub-access-key"
PASSWORD = "fixture-only-hub-password"


def _credentials(endpoint: str) -> ConnectionCredentials:
    """Build the fixture exactly as an admitted private identity is stored."""
    url = urlsplit(endpoint)
    return ConnectionCredentials(
        hub_id="self-hosted-test-hub",
        connection_id="self-hosted-test-connection",
        name="Test Home Assistant",
        endpoint=endpoint,
        secret={
            "access_key": ACCESS_KEY,
            "password": PASSWORD,
            "site_id": "home-assistant-fixture",
            "default_master": url.hostname,
            "default_port": url.port or 443,
            "data_plane_endpoints": {"wss": endpoint},
            "protocols": {"wss": True, "http": False, "mqtt": False},
        },
    )


async def test_private_link_dials_only_the_expected_verified_wss_endpoint(
    tmp_path: Path,
) -> None:
    """Inspect the actual SDK's WebSocket upgrade call before opening a socket."""
    calls: list[tuple[str, dict[str, Any]]] = []

    class RecordingSession:
        async def ws_connect(self, url: str, **kwargs: Any) -> None:
            calls.append((str(url), kwargs))
            raise aiohttp.ClientConnectionError("Fixture blocks network access")

    endpoint = "wss://private-hub.example:8443/ws"
    link = HubConnection(
        cast(aiohttp.ClientSession, RecordingSession()),
        _credentials(endpoint),
        state_dir=str(tmp_path / "noise"),
        self_hosted=True,
    )
    try:
        with pytest.raises(ThalovantConnectionError) as error:
            await link.connect()
    finally:
        await link.close()

    [(url, kwargs)] = calls
    parsed = urlsplit(url)
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "wss",
        "private-hub.example:8443",
        "/ws",
    )
    assert parsed.username is None and parsed.password is None
    assert set(parse_qs(parsed.query)) == {"authorization"}
    assert kwargs["ssl"] is True
    assert not link.connected
    assert ACCESS_KEY not in str(error.value)
    assert PASSWORD not in str(error.value)
    assert parsed.query not in str(error.value)


@pytest.mark.usefixtures("socket_enabled")
async def test_private_session_refuses_upgrade_redirect_before_following_it(
    hass: HomeAssistant,
) -> None:
    """A loopback server supplies a redirect and observes whether it was followed."""
    visited: list[str] = []

    async def redirect(request: web.Request) -> web.StreamResponse:
        visited.append(request.path)
        raise web.HTTPTemporaryRedirect(location="/unexpected")

    async def unexpected(request: web.Request) -> web.StreamResponse:
        visited.append(request.path)
        return web.Response(status=401)

    app = web.Application()
    app.router.add_get("/upgrade", redirect)
    app.router.add_get("/unexpected", unexpected)
    async with TestServer(app) as server:
        session = self_hosted.async_create_session(hass)
        try:
            url = server.make_url("/upgrade").with_scheme("ws")
            with pytest.raises(aiohttp.ClientError):
                await session.ws_connect(url)
        finally:
            session.detach()

    assert visited == ["/upgrade"]


def _untrusted_tls_context(tmp_path: Path) -> ssl.SSLContext:
    """Generate a short-lived fixture certificate solely for loopback testing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(minutes=5))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(IPv4Address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "test-cert.pem"
    key_path = tmp_path / "test-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


@pytest.mark.usefixtures("socket_enabled")
async def test_private_link_rejects_untrusted_tls_before_sending_credentials(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Run the SDK against a real TLS server whose certificate HA cannot trust."""
    visited: list[str] = []

    async def unexpected(request: web.Request) -> web.StreamResponse:
        visited.append(request.path)
        return web.Response(status=400)

    app = web.Application()
    app.router.add_get("/ws", unexpected)
    secure = TestServer(app)
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()

    def handle_expected_tls_rejection(
        event_loop: asyncio.AbstractEventLoop, context: dict[str, Any]
    ) -> None:
        # The fixture server sees a connection reset when its client rejects
        # the certificate. Preserve HA's normal handling for every other error.
        if context.get(
            "message"
        ) == "Error on transport creation for incoming connection" and isinstance(
            context.get("exception"), (ConnectionResetError, ssl.SSLError)
        ):
            return
        if original_handler is not None:
            original_handler(event_loop, context)
        else:
            event_loop.default_exception_handler(context)

    loop.set_exception_handler(handle_expected_tls_rejection)
    try:
        await secure.start_server(ssl=_untrusted_tls_context(tmp_path))
        session = self_hosted.async_create_session(hass)
        endpoint = str(secure.make_url("/ws").with_scheme("wss"))
        link = HubConnection(
            session,
            _credentials(endpoint),
            state_dir=str(tmp_path / "noise"),
            self_hosted=True,
        )
        try:
            with pytest.raises(ThalovantConnectionError):
                await link.connect()
        finally:
            await link.close()
            session.detach()
    finally:
        await secure.close()
        loop.set_exception_handler(original_handler)

    assert visited == []
