"""The Intercom calls of the adapter against the real SDK and a local control plane.

Skipped unless the SDK (0.12.0 or later: the one with Intercom) is installed.
The plane answers what thalovant-api documents for /v1/hubs/{id}/intercom (the
final API: speaker kind, can_play and policy_synced, the new problem codes,
Idempotency-Replayed), and for PATCH /v1/clients/{id}, so these check the whole
path a request takes, the SDK's own error classes included, and that no
request is repeated.
"""

from collections.abc import AsyncIterator
from typing import Any

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
import pytest

from custom_components.thalovant import api
from custom_components.thalovant.api import (
    ThalovantApi,
    ThalovantApiError,
    ThalovantAuthError,
    ThalovantConnectionError,
    ThalovantHubLockedError,
    ThalovantHubUnreachableError,
    ThalovantIntercomUnavailableError,
    ThalovantNotASpeakerError,
    ThalovantNotCancellableError,
    ThalovantPlanError,
    ThalovantRateLimitedError,
    ThalovantSkillNotInstalledError,
    ThalovantTooManyTargetsError,
    ThalovantUrgentBusyError,
    ThalovantUrgentScopeRequiredError,
    Tokens,
)

pytest.importorskip("thalovant.intercom")

pytestmark = pytest.mark.usefixtures("socket_enabled")

TOKEN = "tvt_access"
HUB = "hub-maison"
ANNOUNCEMENT = "0fe8d3c2-6a52-4d3b-9a4e-5c1f0b7a9e11"
SECRET = "Dinner is ready, the secret word is pelican"
ANNOUNCEMENT_BODY = {
    "id": ANNOUNCEMENT,
    "status": "completed",
    "priority": "normal",
    "created_at": "2026-11-12T00:48:58Z",
    "deliveries": [
        {
            "client_id": "c1",
            "slug": "kitchen",
            "name": "Kitchen",
            "status": "delivered",
        },
        {"client_id": "c2", "slug": "office", "name": "Office", "status": "offline"},
    ],
    "acked_by": None,
}


class IntercomPlane:
    """Enough of thalovant-api for the Intercom calls and the connection update."""

    def __init__(self) -> None:
        """Start with the happy answers."""
        self.answer: tuple[int, dict[str, Any], dict[str, str]] | None = None
        self.posts: list[dict[str, Any]] = []
        self.keys: list[str | None] = []
        self.patches: list[tuple[dict[str, Any], str | None]] = []
        self.stale_patches = 0
        self.client: dict[str, Any] = {
            "id": "conn-1",
            "etag": "etag-1",
            "spec": {"connection_type": "home_assistant", "allowedTypes": ["x"]},
        }

    def app(self) -> web.Application:
        """The routes."""
        app = web.Application()
        base = "/v1/hubs/{hub}/intercom"
        app.router.add_get(f"{base}/settings", self.settings)
        app.router.add_get(f"{base}/speakers", self.speakers)
        app.router.add_post(f"{base}/announce", self.announce)
        app.router.add_get(f"{base}/announcements/{{id}}", self.read)
        app.router.add_post(f"{base}/announcements/{{id}}/cancel", self.cancel)
        app.router.add_get("/v1/clients/{client}", self.get_client)
        app.router.add_patch("/v1/clients/{client}", self.patch_client)
        return app

    def _authorized(self, request: web.Request) -> None:
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            raise web.HTTPUnauthorized(
                text='{"detail": "Not authenticated"}', content_type="application/json"
            )

    def _forced(self) -> web.Response | None:
        if self.answer is None:
            return None
        status, body, headers = self.answer
        return web.json_response(body, status=status, headers=headers)

    async def settings(self, request: web.Request) -> web.Response:
        self._authorized(request)
        return (
            forced
            if (forced := self._forced())
            else web.json_response(
                {
                    "enabled": False,
                    "plan_allowed": True,
                    "unavailable_reason": "platform",
                }
            )
        )

    async def speakers(self, request: web.Request) -> web.Response:
        self._authorized(request)
        return web.json_response(
            {
                "items": [
                    {
                        "client_id": "c1",
                        "slug": "kitchen-speaker",
                        "name": "Kitchen Speaker",
                        "kind": "voice_satellite",
                        "can_play": True,
                        "online": True,
                        "last_seen_at": None,
                        "intercom": {
                            "receive": True,
                            "room": "kitchen",
                            "groups": ["downstairs"],
                            "dnd": {"enabled": False},
                        },
                    },
                    {
                        "client_id": "c2",
                        "slug": "home-link",
                        "name": "Home link",
                        "kind": "home_assistant",
                        "can_play": False,
                        "online": False,
                        "last_seen_at": None,
                        "intercom": {"receive": False, "room": None, "groups": []},
                    },
                ],
                "unavailable_reason": "platform",
                "policy_synced": False,
            }
        )

    async def announce(self, request: web.Request) -> web.Response:
        self._authorized(request)
        self.posts.append(await request.json())
        self.keys.append(request.headers.get("Idempotency-Key"))
        return (
            forced
            if (forced := self._forced())
            else web.json_response(ANNOUNCEMENT_BODY)
        )

    async def read(self, request: web.Request) -> web.Response:
        self._authorized(request)
        return web.json_response({**ANNOUNCEMENT_BODY, "id": request.match_info["id"]})

    async def cancel(self, request: web.Request) -> web.Response:
        self._authorized(request)
        if forced := self._forced():
            return forced
        return web.json_response(
            {**ANNOUNCEMENT_BODY, "status": "cancelled", "hub_confirmed": False}
        )

    async def get_client(self, request: web.Request) -> web.Response:
        self._authorized(request)
        return web.json_response(self.client)

    async def patch_client(self, request: web.Request) -> web.Response:
        self._authorized(request)
        if self.stale_patches:
            self.stale_patches -= 1
            self.client["etag"] = f"etag-{len(self.patches) + 2}"
            return web.json_response({"detail": "ETag mismatch"}, status=412)
        if request.headers.get("If-Match") != self.client["etag"]:
            return web.json_response({"detail": "ETag mismatch"}, status=412)
        body = await request.json()
        self.patches.append((body, request.headers.get("If-Match")))
        self.client = {**self.client, "spec": body["spec"], "etag": "etag-new"}
        return web.json_response(self.client)


@pytest.fixture
async def plane() -> AsyncIterator[tuple[IntercomPlane, ThalovantApi]]:
    """A local control plane, and the adapter pointed at it."""
    fake = IntercomPlane()
    server = TestServer(fake.app(), host="127.0.0.1")
    await server.start_server()
    async with ClientSession() as session:
        yield (
            fake,
            ThalovantApi(
                session,
                Tokens(TOKEN, None, ("intercom:read", "intercom:send"), "tok-1"),
                api_url=f"http://127.0.0.1:{server.port}",
            ),
        )
    await server.close()


async def _announce(api: ThalovantApi, **kwargs: Any) -> Any:
    return await api.announce(
        HUB,
        SECRET,
        targets=kwargs.pop("targets", {"all": True}),
        priority=kwargs.pop("priority", "normal"),
        repeat=kwargs.pop("repeat", None),
        lang=kwargs.pop("lang", None),
        idempotency_key=kwargs.pop("idempotency_key", "key-1"),
    )


async def test_reads(plane: tuple[IntercomPlane, ThalovantApi]) -> None:
    """The settings and the speakers, the way the dashboard shows them."""
    _, api = plane
    settings = await api.get_intercom_settings(HUB)
    assert (settings.enabled, settings.plan_allowed, settings.unavailable_reason) == (
        False,
        True,
        "platform",
    )
    listing = await api.list_intercom_speakers(HUB)
    speaker, link = listing.items
    assert (speaker.client_id, speaker.slug, speaker.online, speaker.receive) == (
        "c1",
        "kitchen-speaker",
        True,
        True,
    )
    assert (speaker.room, speaker.groups) == ("kitchen", ("downstairs",))
    assert (speaker.kind, speaker.can_play) == ("voice_satellite", True)
    # A Home Assistant link is a speaker only once it declared that it can play.
    assert (link.kind, link.can_play, link.receive) == ("home_assistant", False, False)
    assert (listing.policy_synced, listing.unavailable_reason) == (False, "platform")


async def test_announce(plane: tuple[IntercomPlane, ThalovantApi]) -> None:
    """One POST with the key, the targets and the repeat; an answer with no text."""
    fake, api = plane
    result = await _announce(
        api,
        targets={"rooms": ["kitchen"]},
        priority="urgent",
        repeat=(3, 30),
        lang="fr-FR",
    )
    assert fake.posts == [
        {
            "text": SECRET,
            "targets": {"rooms": ["kitchen"]},
            "priority": "urgent",
            "repeat": {"times": 3, "interval_seconds": 30},
            "lang": "fr-FR",
        }
    ]
    assert fake.keys == ["key-1"]
    assert result.id == ANNOUNCEMENT
    assert result.delivery_counts == {"delivered": 1, "offline": 1}
    assert SECRET not in repr(result)


async def test_read_and_cancel(plane: tuple[IntercomPlane, ThalovantApi]) -> None:
    """Reading an announcement and cancelling it, with the hub's confirmation."""
    _, api = plane
    assert (await api.get_announcement(HUB, ANNOUNCEMENT)).status == "completed"
    cancelled = await api.cancel_announcement(HUB, ANNOUNCEMENT)
    assert (cancelled.status, cancelled.hub_confirmed) == ("cancelled", False)


def _problem(status: int, code: str, message: str = "m", **more: Any) -> dict[str, Any]:
    """A problem+json body as the platform sends it."""
    return {
        "type": "about:blank",
        "title": "HTTPException",
        "status": status,
        "instance": "urn:problem:1",
        "code": code,
        "message": message,
        **more,
    }


@pytest.mark.parametrize(
    ("status", "body", "headers", "expected", "attrs"),
    [
        (
            502,
            _problem(
                502,
                "hub_unreachable",
                "The hub did not take the announcement.",
                announcement_id=ANNOUNCEMENT,
            ),
            {},
            ThalovantHubUnreachableError,
            {"announcement_id": ANNOUNCEMENT},
        ),
        (
            429,
            _problem(429, "intercom_rate_limited", retry_after_seconds=12),
            {"Retry-After": "12"},
            ThalovantRateLimitedError,
            {"retry_after": 12.0},
        ),
        # The Retry-After header alone is enough.
        (
            429,
            _problem(429, "rate_limited"),
            {"Retry-After": "9"},
            ThalovantRateLimitedError,
            {"retry_after": 9.0},
        ),
        (
            429,
            _problem(
                429,
                "intercom_urgent_busy",
                "This hub already has 2 urgent announcements repeating.",
                scope="hub",
                retry_after_seconds=30,
            ),
            {"Retry-After": "30"},
            ThalovantUrgentBusyError,
            {"retry_after": 30.0},
        ),
        (
            503,
            _problem(503, "intercom_disabled_platform", "off for the platform"),
            {},
            ThalovantIntercomUnavailableError,
            {"reason": "platform", "status": 503},
        ),
        (
            503,
            _problem(503, "intercom_not_configured", "not configured"),
            {},
            ThalovantIntercomUnavailableError,
            {"reason": "not_configured"},
        ),
        (
            403,
            _problem(403, "intercom_disabled", "off for the hub"),
            {},
            ThalovantIntercomUnavailableError,
            {"reason": "hub_off"},
        ),
        (
            422,
            _problem(422, "intercom_unavailable", "never", reason="kid_hub"),
            {},
            ThalovantIntercomUnavailableError,
            {"reason": "kid_hub"},
        ),
        (
            422,
            _problem(422, "intercom_unavailable", "never", reason="public_hub"),
            {},
            ThalovantIntercomUnavailableError,
            {"reason": "public_hub"},
        ),
        (
            403,
            _problem(
                403,
                "urgent_scope_required",
                "An urgent announcement needs the intercom:urgent scope as well.",
            ),
            {},
            ThalovantUrgentScopeRequiredError,
            {"status": 403, "code": "urgent_scope_required"},
        ),
        (
            409,
            _problem(
                409, "skill_not_installed", "The Intercom skill is not installed."
            ),
            {},
            ThalovantSkillNotInstalledError,
            {"status": 409},
        ),
        (
            422,
            _problem(
                422,
                "not_a_speaker",
                "Some of these connections cannot play speech.",
                not_speakers=["home-link"],
            ),
            {},
            ThalovantNotASpeakerError,
            {"status": 422},
        ),
        (
            422,
            _problem(422, "too_many_targets", "Too many.", matched=51),
            {},
            ThalovantTooManyTargetsError,
            {},
        ),
        (
            403,
            _problem(403, "hub_locked", "This hub is locked."),
            {},
            ThalovantHubLockedError,
            {},
        ),
        (
            403,
            {"code": "plan_limit", "resource": "intercom", "detail": "plan"},
            {},
            ThalovantPlanError,
            {},
        ),
        (
            403,
            {"detail": "Insufficient scopes"},
            {},
            ThalovantAuthError,
            {"status": 403},
        ),
        (401, {"detail": "Not authenticated"}, {}, ThalovantAuthError, {"status": 401}),
        # A plain member of the tenant may read but not announce.
        (
            403,
            {"detail": "Manager role required for this tenant resource change"},
            {},
            ThalovantApiError,
            {"status": 403},
        ),
        (
            422,
            _problem(422, "invalid_targets", "no"),
            {},
            ThalovantApiError,
            {"status": 422, "code": "invalid_targets"},
        ),
        (500, {"detail": "boom"}, {}, ThalovantConnectionError, {"status": 500}),
    ],
)
async def test_announce_errors(
    plane: tuple[IntercomPlane, ThalovantApi],
    status: int,
    body: dict[str, Any],
    headers: dict[str, str],
    expected: type[Exception],
    attrs: dict[str, Any],
) -> None:
    """Every answer the platform gives is the right error, and nothing is sent twice."""
    fake, api = plane
    fake.answer = (status, body, headers)
    with pytest.raises(expected) as caught:
        await _announce(api)
    assert type(caught.value) is expected
    for name, value in attrs.items():
        assert getattr(caught.value, name) == value
    # One request: no retry of any kind, whatever the answer.
    assert len(fake.posts) == 1
    # And the text is not in the error.
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value.__dict__)


async def test_not_cancellable(plane: tuple[IntercomPlane, ThalovantApi]) -> None:
    """A 409 names the status the announcement has now."""
    fake, api = plane
    fake.answer = (
        409,
        _problem(
            409,
            "not_cancellable",
            "Only an announcement that is still sending can be cancelled.",
            announcement_status="completed",
        ),
        {},
    )
    with pytest.raises(ThalovantNotCancellableError) as caught:
        await api.cancel_announcement(HUB, ANNOUNCEMENT)
    assert caught.value.announcement_status == "completed"


async def test_unreachable_api() -> None:
    """An API that does not answer is a connection error: the outcome is unknown."""
    async with ClientSession() as session:
        api = ThalovantApi(
            session,
            Tokens(TOKEN, None, ("intercom:send",), "tok-1"),
            api_url="http://127.0.0.1:1",
        )
        with pytest.raises(ThalovantConnectionError) as caught:
            await _announce(api)
    assert type(caught.value) is ThalovantConnectionError
    assert SECRET not in str(caught.value)


async def test_the_sdk_refuses_what_it_cannot_send(
    plane: tuple[IntercomPlane, ThalovantApi],
) -> None:
    """A request the SDK refuses before sending is a ValueError, and sends nothing."""
    fake, api = plane
    with pytest.raises(ValueError, match="repeat"):
        await _announce(api, repeat=(3, 30))
    assert fake.posts == []


async def test_can_play(plane: tuple[IntercomPlane, ThalovantApi]) -> None:
    """The connection's spec is written back whole, with can_play as its only intercom key."""
    fake, api = plane
    await api.set_connection_can_play("conn-1", True)
    assert fake.patches == [
        (
            {
                "spec": {
                    "connection_type": "home_assistant",
                    "allowedTypes": ["x"],
                    "intercom": {"can_play": True},
                }
            },
            "etag-1",
        )
    ]
    # Already so: nothing more is written.
    await api.set_connection_can_play("conn-1", True)
    assert len(fake.patches) == 1
    await api.set_connection_can_play("conn-1", False)
    assert fake.patches[-1][0]["spec"]["intercom"] == {"can_play": False}
    assert fake.patches[-1][1] == "etag-new"


async def test_can_play_when_the_connection_changed_meanwhile(
    plane: tuple[IntercomPlane, ThalovantApi],
) -> None:
    """A 412 reads the connection again and writes once more; twice is an error."""
    fake, api = plane
    fake.stale_patches = 1
    await api.set_connection_can_play("conn-1", True)
    assert len(fake.patches) == 1

    fake.stale_patches = 2
    fake.client["spec"] = {"connection_type": "home_assistant"}
    with pytest.raises(ThalovantApiError) as caught:
        await api.set_connection_can_play("conn-1", False)
    assert caught.value.status == 412


async def test_a_replayed_announcement_says_nothing_new_was_sent(
    plane: tuple[IntercomPlane, ThalovantApi],
) -> None:
    """Idempotency-Replayed: true is read into the answer, and the key reaches the API."""
    fake, api_ = plane
    fake.answer = (200, ANNOUNCEMENT_BODY, {"Idempotency-Replayed": "true"})
    replayed = await _announce(api_, idempotency_key="key-9")
    assert replayed.replayed is True
    assert fake.keys == ["key-9"]
    fake.answer = None
    assert (await _announce(api_)).replayed is False


async def test_cancel_is_the_sdks_public_call(
    plane: tuple[IntercomPlane, ThalovantApi],
) -> None:
    """A cancel is one POST to the cancel route; the platform may answer it while it is off."""
    fake, api_ = plane
    fake.answer = (
        200,
        {**ANNOUNCEMENT_BODY, "status": "cancelled", "hub_confirmed": False},
        {},
    )
    cancelled = await api_.cancel_announcement(HUB, ANNOUNCEMENT)
    assert (cancelled.status, cancelled.hub_confirmed) == ("cancelled", False)


def test_the_private_write_is_in_one_place() -> None:
    """The only reach into the SDK's private API is ThalovantApi.set_connection_can_play.

    SDK 0.12.0 has no public call that updates a connection. When a release has
    one, this test and that function go together; until then nothing else may
    use a private name of the SDK.
    """
    from pathlib import Path
    import re

    source = Path(api.__file__).read_text(encoding="utf-8")
    uses = re.findall(r"getattr\(\w+, \"_\w+\"", source)
    assert uses == ['getattr(control, "_request"']
    # The real SDK still has it, and still has no public way to update a client.
    import thalovant

    control = thalovant.AsyncThalovantControlPlane
    assert callable(getattr(control, "_request", None))
    assert not any(
        name in vars(control)
        for name in ("update_client", "patch_client", "set_client")
    )


def _sdk_text(text: str) -> str | None:
    """What the SDK (and so the platform) makes of a text, or None when it refuses it."""
    from thalovant.intercom import announcement_text

    try:
        return announcement_text(text)
    except ValueError:
        return None


def _our_text(text: str) -> str | None:
    """What validate_text makes of the same text, or None when it refuses it."""
    from custom_components.thalovant.intercom import InvalidInputError, validate_text

    try:
        return validate_text(text)
    except InvalidInputError:
        return None


def test_the_text_rule_is_the_platforms() -> None:
    """validate_text and the SDK's announcement_text agree on every character.

    The one difference is by design: a line break or a tab is a space for us,
    where the SDK refuses it. Everything else, character by character and at
    the length boundary, is the same answer.
    """
    codepoints = [
        *range(0x3400),
        *range(0xD7F0, 0xE100),
        *range(0xFE00, 0x10000),
        *range(0x1D170, 0x1D17C),
        0x1F600,
        *range(0xE0000, 0xE0080),
        0xF0000,
        0xFFFFD,
        0x100000,
        0x10FFFF,
    ]
    for code in codepoints:
        if chr(code) in "\t\r\n":
            continue
        for text in (f"a{chr(code)}b", chr(code), f"{chr(code)}x"):
            assert _our_text(text) == _sdk_text(text), hex(code)
    for text in (
        "",
        " ",
        "x" * 280,
        "x" * 281,
        "e\u0301" * 280,
        "e\u0301" * 281,
        "  padded  ",
        "<b>",
        "a > b",
        "ok \u200d ok",
        "ok \u200c ok",
        "ok \u200b ok",
        "\u00a0\u3000x\u3000",
        "Dinner is ready, the secret word is pelican",
    ):
        assert _our_text(text) == _sdk_text(text), repr(text)
    # What we change before the platform's rule is only a line break or a tab.
    assert _our_text("a\nb\t c") == "a b c"
    assert _sdk_text("a\nb\t c") is None


async def test_our_idempotency_key_is_one_the_sdk_takes(
    plane: tuple[IntercomPlane, ThalovantApi],
) -> None:
    """A uuid4 per announcement is a valid key, and a key is never reused for the next."""
    from uuid import uuid4

    fake, api_ = plane
    for _ in range(2):
        await _announce(api_, idempotency_key=str(uuid4()))
    assert len(set(fake.keys)) == 2
