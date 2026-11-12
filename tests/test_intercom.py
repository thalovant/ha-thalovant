"""Tests for sending announcements: the rules, the controller and its errors."""

import asyncio
import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.api import (
    IntercomSettings,
    IntercomSpeaker,
    IntercomSpeakers,
    ThalovantApiError,
    ThalovantAuthError,
    ThalovantConnectionError,
    ThalovantError,
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
)
from custom_components.thalovant.const import (
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_URGENT,
    CONF_TOKENS,
    DOMAIN,
    EVENT_ANNOUNCEMENT_UPDATED,
)
from custom_components.thalovant.intercom import (
    IntercomController,
    InvalidInputError,
    SlidingWindowLimiter,
    can_play_issue_id,
    clean_received_text,
    collapse_whitespace,
    has_unsafe_characters,
    is_valid_announcement_id,
    sanitize_label,
    scopes_for_options,
    unavailable_issue_id,
    validate_language,
    validate_names,
    validate_text,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir, translation
from homeassistant.setup import async_setup_component

from .conftest import (
    ANNOUNCEMENT_ID,
    SECRET_TEXT,
    FakeHubConnection,
    make_announcement,
    make_intercom_entry,
)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> IntercomController:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    controller = entry.runtime_data.intercom
    assert controller is not None
    return controller


def _events(hass: HomeAssistant) -> list[Event]:
    events: list[Event] = []

    # A callback runs in order on the loop; a plain function (events.append
    # itself) would run in the executor, and its order would depend on timing.
    @callback
    def record(event: Event) -> None:
        events.append(event)

    hass.bus.async_listen(EVENT_ANNOUNCEMENT_UPDATED, record)
    return events


# --- The rules for a text, a name and a language ---------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dinner is ready", "Dinner is ready"),
        # A line break or a tab is a space; nothing else is rewritten.
        ("  Dinner\n  is\tready  ", "Dinner is ready"),
        ("Dinner\r\n\r\nis ready\n", "Dinner is ready"),
        ("a  b", "a  b"),
        ("Café à 8 h 😀", "Café à 8 h 😀"),
        # The zero-width joiner and non-joiner are allowed: scripts and emoji need them.
        ("family 👨\u200d👩\u200d👧", "family 👨\u200d👩\u200d👧"),
        ("می\u200cخواهم", "می\u200cخواهم"),
        # Counted after NFC, as the platform counts it.
        ("e\u0301" * 280, "\u00e9" * 280),
        ("x" * 280, "x" * 280),
        ("\u00a0Dinner\u3000", "Dinner"),
    ],
)
def test_validate_text_accepts(text: str, expected: str) -> None:
    """Line breaks become spaces, the text is NFC-normalised and trimmed; nothing else changes."""
    assert validate_text(text) == expected


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "empty"),
        (" \n\t ", "empty"),
        ("\u2028", "empty"),
        ("x" * 281, "too_long"),
        # Length is checked before characters, as the platform does.
        ("<" * 281, "too_long"),
        ("e\u0301" * 281, "too_long"),
        ("temp < 5", "markup"),
        ("temp > 2", "markup"),
        ("<audio src=x>hi</audio>", "markup"),
        ("bell\x07", "bad_characters"),
        ("nul\x00", "bad_characters"),
        ("del\x7f", "bad_characters"),
        ("next\x85line", "bad_characters"),
        ("sep\x1fsep", "bad_characters"),
        ("left\u202eright", "bad_characters"),
        ("isolate\u2066x\u2069", "bad_characters"),
        ("mark\u200fmark", "bad_characters"),
        ("zero\u200bwidth", "bad_characters"),
        ("word\u2060joiner", "bad_characters"),
        ("tag\U000e0041", "bad_characters"),
        ("line\u2028break", "bad_characters"),
        ("paragraph\u2029break", "bad_characters"),
        ("private\ue000use", "bad_characters"),
        ("plane\U000f0000", "bad_characters"),
        ("lone\ud800surrogate", "bad_characters"),
    ],
)
def test_validate_text_refuses(text: str, reason: str) -> None:
    """The platform's own rule: what breaks it is refused, never cut or stripped."""
    with pytest.raises(InvalidInputError) as caught:
        validate_text(text)
    assert caught.value.reason == reason
    # What was refused is not in the error.
    assert text.strip() not in str(caught.value) or reason == "empty"


def test_validate_text_does_not_stall_on_long_white_space() -> None:
    """A huge run of blanks is cheap to refuse: nothing backtracks."""
    assert validate_text(" " * 100_000 + "a" + "\n" * 100_000) == "a"
    with pytest.raises(InvalidInputError):
        validate_text(" \n" * 200_000 + "<")


def test_collapse_and_unsafe() -> None:
    """White space of every kind becomes one space; format characters are unsafe."""
    assert collapse_whitespace("a\u2028b  c\n") == "a b c"
    assert has_unsafe_characters("a\u200eb")
    assert not has_unsafe_characters("plain")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dinner is ready", "Dinner is ready"),
        ("a\u202eb\u200bc", "abc"),
        ("a\ue000b\ud800c", "abc"),
        ("<audio src=x>hi</audio>", "audio src=x hi /audio"),
        ("bell\x07 ring", "bell ring"),
        ("  line\none  ", "line one"),
        ("x" * 280, "x" * 280),
        ("", None),
        ("\u202e\u200b", None),
        ("<>", None),
        ("x" * 281, None),
    ],
)
def test_clean_received_text(text: str, expected: str | None) -> None:
    """Received text is cleaned, never cut: unfit text is None."""
    assert clean_received_text(text) == expected


@pytest.mark.parametrize(
    ("language", "expected"),
    [("en-us", "en-US"), ("fr_CA", "fr-CA"), ("zh-hant", "zh-Hant"), ("de", "de")],
)
def test_validate_language(language: str, expected: str) -> None:
    """A language tag is read in its usual form."""
    assert validate_language(language) == expected


@pytest.mark.parametrize("language", ["", "x", "english please", "en-" + "x" * 40])
def test_validate_language_refuses(language: str) -> None:
    """Anything that is not a tag is refused."""
    with pytest.raises(InvalidInputError) as caught:
        validate_language(language)
    assert caught.value.reason == "language"


def test_validate_names() -> None:
    """Names are trimmed, deduplicated and bounded."""
    assert validate_names([" kitchen ", "kitchen", "down  stairs"]) == [
        "kitchen",
        "down stairs",
    ]
    for bad in (["  "], ["x" * 65], ["a\u202eb"], [f"n{i}" for i in range(51)]):
        with pytest.raises(InvalidInputError):
            validate_names(bad)


def test_announcement_id_shape() -> None:
    """An id is one safe path segment."""
    assert is_valid_announcement_id(ANNOUNCEMENT_ID)
    for bad in ("", "..", "a/b", "a?b", "x" * 65, "-lead"):
        assert not is_valid_announcement_id(bad)


def test_sanitize_label() -> None:
    """A household-typed label loses control characters and is cut."""
    assert sanitize_label(None) is None
    assert sanitize_label("Kitchen\u202e Speaker\x07") == "Kitchen Speaker"
    assert sanitize_label("x" * 200) == "x" * 80
    assert sanitize_label("\u202e") is None


def test_scopes_for_options() -> None:
    """A link that has nothing on asks for exactly what it always did."""
    base = ("hubs:read", "clients:read", "clients:write")
    assert scopes_for_options({}) == base
    assert scopes_for_options({"allow_receive": True}) == base
    assert scopes_for_options({CONF_ALLOW_URGENT: True}) == base
    assert scopes_for_options({CONF_ALLOW_ANNOUNCEMENTS: True}) == (
        *base,
        "intercom:read",
        "intercom:send",
    )
    assert scopes_for_options(
        {CONF_ALLOW_ANNOUNCEMENTS: True, CONF_ALLOW_URGENT: True}
    ) == (*base, "intercom:read", "intercom:send", "intercom:urgent")


def test_sliding_window_limiter() -> None:
    """At most limit hits in any window."""
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 10.0, clock=lambda: now[0])
    assert limiter.allow()
    now[0] = 1.0
    assert limiter.allow()
    now[0] = 9.9
    assert not limiter.allow()
    now[0] = 10.0  # the first hit has left the window
    assert limiter.allow()
    assert not limiter.allow()


# --- Announcing -------------------------------------------------------------


async def test_announce(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A normal announcement is one request with a fresh key, and one event."""
    caplog.set_level(logging.DEBUG)
    controller = await _setup(hass, intercom_entry)
    events = _events(hass)

    announcement = await controller.async_announce(SECRET_TEXT)
    await hass.async_block_till_done()

    assert announcement.status == "completed"
    mock_intercom_api.announce.assert_awaited_once()
    args, kwargs = mock_intercom_api.announce.await_args
    assert args == ("hub-maison", SECRET_TEXT)
    assert kwargs["targets"] == {"all": True}
    assert kwargs["priority"] == "normal"
    assert kwargs["repeat"] is None
    assert kwargs["lang"] is None
    assert len(kwargs["idempotency_key"]) == 36
    # The event carries an id and a status: never the text.
    assert [event.data for event in events] == [
        {"announcement_id": ANNOUNCEMENT_ID, "status": "completed"}
    ]
    stats = intercom_entry.runtime_data.intercom_stats
    assert stats.sent["normal"] == 1
    assert stats.send_outcomes["completed"] == 1
    assert SECRET_TEXT not in caplog.text
    assert SECRET_TEXT not in repr(stats)


async def test_every_announcement_has_its_own_key(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """The same words twice are two announcements: a key is never reused."""
    controller = await _setup(hass, intercom_entry)
    await controller.async_announce("Dinner is ready")
    await controller.async_announce("Dinner is ready")
    keys = [
        call.kwargs["idempotency_key"] for call in mock_intercom_api.announce.mock_calls
    ]
    assert len(keys) == 2
    assert keys[0] != keys[1]


async def test_announce_targets_and_repeat(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Rooms and groups go as typed, with the language and the urgent repeat."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.announce.return_value = make_announcement("completed")
    await controller.async_announce(
        "Wake up",
        target="rooms",
        names=["kitchen", "hall"],
        priority="urgent",
        repeat=(3, 30),
        lang="fr-FR",
    )
    kwargs = mock_intercom_api.announce.await_args.kwargs
    assert kwargs["targets"] == {"rooms": ["kitchen", "hall"]}
    assert kwargs["priority"] == "urgent"
    assert kwargs["repeat"] == (3, 30)
    assert kwargs["lang"] == "fr-FR"
    assert intercom_entry.runtime_data.intercom_stats.sent["urgent"] == 1


@pytest.mark.parametrize(
    ("typed", "sent"),
    [
        # An id or a slug goes as it is.
        (["kitchen-speaker", "c7c0-office"], ["kitchen-speaker", "c7c0-office"]),
        # A name becomes its speaker's slug, whatever its case.
        (["kitchen speaker", "OFFICE SPEAKER"], ["kitchen-speaker", "office-speaker"]),
        # Nobody's name goes as typed, for the platform to answer.
        (["the garage"], ["the garage"]),
    ],
)
async def test_speaker_names_are_resolved(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    typed: list[str],
    sent: list[str],
) -> None:
    """A speaker named by its display name is found; the platform gets its slug."""
    controller = await _setup(hass, intercom_entry)
    await controller.async_announce("Hello", target="speakers", names=typed)
    assert mock_intercom_api.announce.await_args.kwargs["targets"] == {"speakers": sent}


async def test_speaker_without_slug_resolves_to_its_id(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """A speaker with no slug is addressed by its id."""
    mock_intercom_api.list_intercom_speakers.return_value = IntercomSpeakers(
        (IntercomSpeaker("id-1", None, "Porch", True, True, None, ()),)
    )
    controller = await _setup(hass, intercom_entry)
    await controller.async_announce("Hello", target="speakers", names=["porch"])
    assert mock_intercom_api.announce.await_args.kwargs["targets"] == {
        "speakers": ["id-1"]
    }


async def test_ambiguous_speaker_name_is_refused(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Two speakers with one name: nothing is guessed, and nothing is sent."""
    mock_intercom_api.list_intercom_speakers.return_value = IntercomSpeakers(
        (
            IntercomSpeaker("a", "porch-1", "Porch", True, True, None, ()),
            IntercomSpeaker("b", "porch-2", "porch", True, True, None, ()),
        )
    )
    controller = await _setup(hass, intercom_entry)
    with pytest.raises(ServiceValidationError) as caught:
        await controller.async_announce("Hello", target="speakers", names=["Porch"])
    assert caught.value.translation_key == "ambiguous_speaker"
    mock_intercom_api.announce.assert_not_awaited()


async def test_unreadable_speaker_list_does_not_stop_the_announcement(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """If the speakers cannot be read, the names go as typed and the request says why."""
    mock_intercom_api.list_intercom_speakers.side_effect = ThalovantConnectionError()
    controller = await _setup(hass, intercom_entry)
    await controller.async_announce("Hello", target="speakers", names=["kitchen"])
    assert mock_intercom_api.announce.await_args.kwargs["targets"] == {
        "speakers": ["kitchen"]
    }


async def test_speakers_are_kept_for_a_minute(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """The list is read once, again when asked to be fresh, and again once stale."""
    controller = await _setup(hass, intercom_entry)
    await controller.async_list_speakers()
    await controller.async_list_speakers()
    assert mock_intercom_api.list_intercom_speakers.await_count == 1
    await controller.async_list_speakers(fresh=True)
    assert mock_intercom_api.list_intercom_speakers.await_count == 2
    with patch("custom_components.thalovant.intercom.SPEAKERS_TTL", 0.0):
        await controller.async_list_speakers()
    assert mock_intercom_api.list_intercom_speakers.await_count == 3


# --- Refusals before anything is sent ---------------------------------------


async def test_refused_when_off(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """With the option off, announcing and listing say so and contact nothing."""
    entry = make_intercom_entry(credentials, options={})
    controller = await _setup(hass, entry)
    for call in (
        controller.async_announce("Hello"),
        controller.async_list_speakers(),
    ):
        with pytest.raises(ServiceValidationError) as caught:
            await call
        assert caught.value.translation_key == "announcements_disabled"
    mock_intercom_api.announce.assert_not_awaited()
    mock_intercom_api.list_intercom_speakers.assert_not_awaited()
    # No notify platform, and no call to Thalovant at setup either.
    mock_intercom_api.get_intercom_settings.assert_not_awaited()
    mock_intercom_api.set_connection_can_play.assert_not_awaited()


async def test_refused_without_the_scopes(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """An option on with a token that lacks the permission is refused clearly."""
    entry = make_intercom_entry(
        credentials,
        options={CONF_ALLOW_ANNOUNCEMENTS: True},
        scopes=("hubs:read", "clients:read", "clients:write"),
    )
    controller = await _setup(hass, entry)
    with pytest.raises(ServiceValidationError) as caught:
        await controller.async_announce("Hello")
    assert caught.value.translation_key == "scope_missing"
    mock_intercom_api.announce.assert_not_awaited()


@pytest.mark.parametrize(
    ("options", "scopes"),
    [
        ({CONF_ALLOW_ANNOUNCEMENTS: True}, ("intercom:read", "intercom:send")),
        (
            {CONF_ALLOW_ANNOUNCEMENTS: True, CONF_ALLOW_URGENT: True},
            ("intercom:read", "intercom:send"),
        ),
    ],
)
async def test_urgent_needs_its_option_and_its_scope(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    options: dict[str, Any],
    scopes: tuple[str, ...],
) -> None:
    """Urgent is a separate choice, and a separate permission."""
    entry = make_intercom_entry(credentials, options=options, scopes=scopes)
    controller = await _setup(hass, entry)
    assert not controller.urgent_allowed
    with pytest.raises(ServiceValidationError) as caught:
        await controller.async_announce("Hello", priority="urgent")
    assert caught.value.translation_key == "urgent_disabled"
    mock_intercom_api.announce.assert_not_awaited()


async def test_local_rate_limit(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """20 normal a minute and 5 urgent an hour: then nothing is sent."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.announce.return_value = make_announcement("completed")
    for _ in range(20):
        await controller.async_announce("Hello")
    with pytest.raises(ServiceValidationError) as caught:
        await controller.async_announce("Hello")
    assert caught.value.translation_key == "rate_limited_normal"
    assert caught.value.translation_placeholders == {"limit": "20"}
    assert mock_intercom_api.announce.await_count == 20

    for _ in range(5):
        await controller.async_announce("Wake up", priority="urgent")
    with pytest.raises(ServiceValidationError) as caught:
        await controller.async_announce("Wake up", priority="urgent")
    assert caught.value.translation_key == "rate_limited_urgent"
    assert mock_intercom_api.announce.await_count == 25
    stats = intercom_entry.runtime_data.intercom_stats
    assert stats.send_outcomes["rate_limited_local"] == 2


# --- What the platform answers ----------------------------------------------


@pytest.mark.parametrize(
    ("error", "key", "placeholders"),
    [
        (
            ThalovantRateLimitedError(retry_after=12.4),
            "rate_limited_remote",
            {"seconds": "12"},
        ),
        (ThalovantRateLimitedError(), "rate_limited_remote", {"seconds": "a few"}),
        (
            ThalovantHubUnreachableError(announcement_id=ANNOUNCEMENT_ID),
            "hub_unreachable",
            {"announcement": ANNOUNCEMENT_ID},
        ),
        (
            ThalovantHubUnreachableError(),
            "hub_unreachable",
            {"announcement": "unknown"},
        ),
        (
            ThalovantIntercomUnavailableError(reason="hub_off"),
            "intercom_unavailable_hub_off",
            {},
        ),
        (
            ThalovantIntercomUnavailableError(reason="platform"),
            "intercom_unavailable_platform",
            {},
        ),
        (
            ThalovantIntercomUnavailableError(reason="not_configured"),
            "intercom_unavailable_not_configured",
            {},
        ),
        (
            ThalovantIntercomUnavailableError(reason="kid_hub"),
            "intercom_unavailable_kid_hub",
            {},
        ),
        (
            ThalovantIntercomUnavailableError(reason="public_hub"),
            "intercom_unavailable_public_hub",
            {},
        ),
        (
            ThalovantIntercomUnavailableError(reason="moon"),
            "intercom_unavailable_unknown",
            {},
        ),
        (
            ThalovantUrgentBusyError(retry_after=29.6),
            "urgent_busy",
            {"seconds": "30"},
        ),
        (ThalovantUrgentBusyError(), "urgent_busy", {"seconds": "a few"}),
        (
            ThalovantUrgentScopeRequiredError(status=403, code="urgent_scope_required"),
            "urgent_scope_required",
            {},
        ),
        (ThalovantSkillNotInstalledError(status=409), "skill_not_installed", {}),
        (ThalovantNotASpeakerError(status=422), "not_a_speaker", {}),
        (ThalovantTooManyTargetsError(status=422), "too_many_targets", {}),
        (ThalovantHubLockedError(status=403), "hub_locked", {}),
        (
            ThalovantApiError(
                status=403,
                detail="Manager role required for this tenant resource change",
            ),
            "manager_required",
            {},
        ),
        # Any other 403 with no code is just a refusal, with its status.
        (
            ThalovantApiError(status=403, detail="Forbidden"),
            "request_refused",
            {"status": "403", "code": "unknown"},
        ),
        (ThalovantPlanError(status=403, code="plan_limit"), "plan_limit", {}),
        (ThalovantAuthError(status=403), "scope_missing", {}),
        # A locked account is neither a missing permission nor a dead token.
        (
            ThalovantAuthError(status=423),
            "request_refused",
            {"status": "423", "code": "unknown"},
        ),
        (ThalovantConnectionError("dns"), "announce_outcome_unknown", {}),
        (
            ThalovantApiError(status=422, code="invalid_targets"),
            "request_refused",
            {"status": "422", "code": "invalid_targets"},
        ),
        (
            ThalovantError("odd"),
            "request_refused",
            {"status": "unknown", "code": "unknown"},
        ),
        (
            ThalovantApiError(status=404),
            "request_refused",
            {"status": "404", "code": "unknown"},
        ),
    ],
)
async def test_announce_errors(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
    caplog: pytest.LogCaptureFixture,
    error: ThalovantError,
    key: str,
    placeholders: dict[str, str],
) -> None:
    """Each answer is a clear error, with one request and no retry."""
    caplog.set_level(logging.DEBUG)
    controller = await _setup(hass, intercom_entry)
    events = _events(hass)
    mock_intercom_api.announce.side_effect = error

    with pytest.raises(HomeAssistantError) as caught:
        await controller.async_announce(SECRET_TEXT)
    await hass.async_block_till_done()

    assert caught.value.translation_key == key
    assert caught.value.translation_domain == DOMAIN
    assert {
        k: v
        for k, v in (caught.value.translation_placeholders or {}).items()
        if k != "hub"
    } == placeholders
    # Never retried, never a success event, and the text is nowhere.
    assert mock_intercom_api.announce.await_count == 1
    assert events == []
    assert SECRET_TEXT not in caplog.text
    assert SECRET_TEXT not in repr(caught.value)
    stats = intercom_entry.runtime_data.intercom_stats
    assert sum(stats.send_outcomes.values()) == 1
    assert stats.sent == {}


async def test_unavailable_error_raises_the_repair(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Learning that Intercom is off for the hub shows it in Repairs."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.announce.side_effect = ThalovantIntercomUnavailableError(
        reason="platform"
    )
    with pytest.raises(HomeAssistantError):
        await controller.async_announce("Hello")
    issue = issue_registry.async_get_issue(
        DOMAIN, unavailable_issue_id(intercom_entry.entry_id)
    )
    assert issue is not None
    assert issue.translation_key == "intercom_unavailable_platform"


@pytest.mark.parametrize(
    ("reason", "issue"),
    [
        ("platform", "platform"),
        ("not_configured", "platform"),
        ("hub_off", "hub_off"),
        ("kid_hub", "kid_hub"),
        ("public_hub", "public_hub"),
        ("moon", "unknown"),
    ],
)
async def test_every_unavailable_reason_raises_its_repair(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
    reason: str,
    issue: str,
) -> None:
    """Whatever the platform says about Intercom being off is a repair that says why."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.announce.side_effect = ThalovantIntercomUnavailableError(
        reason=reason
    )
    with pytest.raises(HomeAssistantError):
        await controller.async_announce("Hello")
    found = issue_registry.async_get_issue(
        DOMAIN, unavailable_issue_id(intercom_entry.entry_id)
    )
    assert found is not None
    assert found.translation_key == f"intercom_unavailable_{issue}"
    assert found.is_fixable is False


async def test_a_missing_urgent_scope_is_not_a_dead_sign_in(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """The platform's urgent_scope_required says what to do; it starts no re-authentication."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.announce.side_effect = ThalovantUrgentScopeRequiredError(
        status=403, code="urgent_scope_required"
    )
    with (
        patch("homeassistant.config_entries.ConfigEntry.async_start_reauth") as reauth,
        pytest.raises(HomeAssistantError) as caught,
    ):
        await controller.async_announce("Wake up", priority="urgent")
    assert caught.value.translation_key == "urgent_scope_required"
    reauth.assert_not_called()


async def test_token_rejected_starts_reauth(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """A token Thalovant no longer accepts asks for a new sign-in."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.announce.side_effect = ThalovantAuthError(status=401)
    with (
        patch("homeassistant.config_entries.ConfigEntry.async_start_reauth") as reauth,
        pytest.raises(HomeAssistantError) as caught,
    ):
        await controller.async_announce("Hello")
    assert caught.value.translation_key == "token_rejected"
    reauth.assert_called_once()


async def test_value_error_and_surprises(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The SDK refusing a request is a validation error; a surprise is only typed in the log."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.announce.side_effect = ValueError(SECRET_TEXT)
    with pytest.raises(ServiceValidationError) as caught:
        await controller.async_announce("Hello")
    assert caught.value.translation_key == "invalid_request"
    # Even an SDK that echoed the text would not reach the error or the chain.
    assert caught.value.__cause__ is None
    assert SECRET_TEXT not in repr(caught.value)

    mock_intercom_api.announce.side_effect = RuntimeError(SECRET_TEXT)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(HomeAssistantError) as caught2:
        await controller.async_announce("Hello")
    assert caught2.value.translation_key == "unexpected"
    assert caught2.value.__cause__ is None
    assert "RuntimeError" in caplog.text
    assert SECRET_TEXT not in caplog.text


async def test_token_unreadable(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """A stored token that cannot be read is an error that names the fix."""
    controller = await _setup(hass, intercom_entry)
    hass.config_entries.async_update_entry(
        intercom_entry, data={**intercom_entry.data, CONF_TOKENS: {"scopes": 7}}
    )
    # Its scopes are unknown now, so announcing is refused before anything else.
    with pytest.raises(ServiceValidationError) as caught:
        await controller.async_announce("Hello")
    assert caught.value.translation_key == "scope_missing"
    # And an API call that needs the token says it is unreadable.
    with pytest.raises(HomeAssistantError) as caught2:
        controller._api()
    assert caught2.value.translation_key == "token_unreadable"


# --- Following an announcement that is still sending ----------------------


@pytest.fixture
def fast_follow() -> Any:
    """Read an announcement that is sending without waiting."""
    with patch("custom_components.thalovant.intercom.FOLLOW_INTERVAL", 0.0):
        yield


async def test_urgent_announcement_is_followed(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    fast_follow: None,
) -> None:
    """An urgent announcement returns at once; each change of status is an event."""
    controller = await _setup(hass, intercom_entry)
    events = _events(hass)
    sending = make_announcement("sending", priority="urgent")
    mock_intercom_api.announce.return_value = sending
    mock_intercom_api.get_announcement.side_effect = [
        sending,
        sending,
        make_announcement("completed", priority="urgent", acked_by="Kitchen"),
    ]

    announcement = await controller.async_announce(
        "Wake up", priority="urgent", repeat=(3, 30)
    )
    assert announcement.status == "sending"
    # The following is a background task: wait for it to end by itself.
    await asyncio.gather(*controller._followers.values())
    await hass.async_block_till_done()

    assert [event.data["status"] for event in events] == ["sending", "completed"]
    assert mock_intercom_api.get_announcement.await_count == 3
    assert controller._followers == {}


async def test_wait_returns_the_final_state(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    fast_follow: None,
) -> None:
    """With wait, the call holds until the announcement ends."""
    controller = await _setup(hass, intercom_entry)
    sending = make_announcement("sending", priority="urgent")
    mock_intercom_api.announce.return_value = sending
    mock_intercom_api.get_announcement.return_value = make_announcement(
        "partial", priority="urgent"
    )
    announcement = await controller.async_announce(
        "Wake up", priority="urgent", repeat=(2, 10), wait=True
    )
    assert announcement.status == "partial"
    assert controller._followers == {}


async def test_wait_gives_up_at_its_cap(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    fast_follow: None,
) -> None:
    """An announcement still sending at the cap is returned as it is."""
    controller = await _setup(hass, intercom_entry)
    sending = make_announcement("sending", priority="urgent")
    mock_intercom_api.announce.return_value = sending
    mock_intercom_api.get_announcement.return_value = sending
    with patch("custom_components.thalovant.intercom.MAX_WAIT", 0.05):
        announcement = await controller.async_announce(
            "Wake up", priority="urgent", repeat=(5, 60), wait=True
        )
    assert announcement.status == "sending"


async def test_following_stops_when_a_read_fails(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    fast_follow: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed read ends the following; the announcement itself is untouched."""
    caplog.set_level(logging.DEBUG)
    controller = await _setup(hass, intercom_entry)
    sending = make_announcement("sending", priority="urgent")
    mock_intercom_api.announce.return_value = sending
    mock_intercom_api.get_announcement.side_effect = ThalovantConnectionError("down")
    announcement = await controller.async_announce(
        "Wake up", priority="urgent", repeat=(2, 10), wait=True
    )
    assert announcement.status == "sending"
    assert "Could not follow announcement" in caplog.text
    assert "ThalovantConnectionError" in caplog.text


async def test_following_with_no_time_left(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """A budget that is already spent reads nothing."""
    controller = await _setup(hass, intercom_entry)
    sending = make_announcement("sending", priority="urgent")
    result = await controller._async_follow(sending, 0.0)
    assert result is sending
    mock_intercom_api.get_announcement.assert_not_awaited()


# --- Cancelling -------------------------------------------------------------


async def test_cancel(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    fast_follow: None,
) -> None:
    """Cancelling stops the following and fires the event."""
    controller = await _setup(hass, intercom_entry)
    events = _events(hass)
    sending = make_announcement("sending", priority="urgent")
    mock_intercom_api.announce.return_value = sending
    mock_intercom_api.get_announcement.return_value = sending
    await controller.async_announce("Wake up", priority="urgent", repeat=(5, 60))
    assert ANNOUNCEMENT_ID in controller._followers

    cancelled = await controller.async_cancel(ANNOUNCEMENT_ID)
    await hass.async_block_till_done()

    assert cancelled.status == "cancelled"
    assert cancelled.hub_confirmed is True
    mock_intercom_api.cancel_announcement.assert_awaited_once_with(
        "hub-maison", ANNOUNCEMENT_ID
    )
    assert [event.data["status"] for event in events][-1] == "cancelled"
    assert controller._followers == {}


async def test_cancel_works_with_announcements_off(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Turning announcements off never leaves one that cannot be stopped."""
    entry = make_intercom_entry(credentials, options={})
    controller = await _setup(hass, entry)
    cancelled = await controller.async_cancel(ANNOUNCEMENT_ID)
    assert cancelled.status == "cancelled"


async def test_cancel_needs_the_send_scope(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Without the permission, cancelling says so."""
    entry = make_intercom_entry(
        credentials, options={}, scopes=("hubs:read", "clients:read", "clients:write")
    )
    controller = await _setup(hass, entry)
    with pytest.raises(ServiceValidationError) as caught:
        await controller.async_cancel(ANNOUNCEMENT_ID)
    assert caught.value.translation_key == "scope_missing"


@pytest.mark.parametrize(
    ("error", "exception", "key"),
    [
        (
            ThalovantNotCancellableError(announcement_status="completed"),
            ServiceValidationError,
            "not_cancellable",
        ),
        (ThalovantNotCancellableError(), ServiceValidationError, "not_cancellable"),
        (
            ThalovantApiError(status=404),
            ServiceValidationError,
            "announcement_not_found",
        ),
        (ThalovantConnectionError(), HomeAssistantError, "cancel_outcome_unknown"),
        (ValueError("bad id"), ServiceValidationError, "invalid_request"),
        (RuntimeError("odd"), HomeAssistantError, "unexpected"),
    ],
)
async def test_cancel_errors(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    error: Exception,
    exception: type[HomeAssistantError],
    key: str,
) -> None:
    """Each answer to a cancel is a clear error."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.cancel_announcement.side_effect = error
    with pytest.raises(exception) as caught:
        await controller.async_cancel(ANNOUNCEMENT_ID)
    assert caught.value.translation_key == key


async def test_list_errors(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Reading the speakers fails with a clear error."""
    controller = await _setup(hass, intercom_entry)
    mock_intercom_api.list_intercom_speakers.side_effect = ThalovantConnectionError()
    with pytest.raises(HomeAssistantError) as caught:
        await controller.async_list_speakers()
    assert caught.value.translation_key == "cannot_reach_thalovant"
    mock_intercom_api.list_intercom_speakers.side_effect = RuntimeError("odd")
    with pytest.raises(HomeAssistantError) as caught2:
        await controller.async_list_speakers()
    assert caught2.value.translation_key == "unexpected"


# --- Repairs ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("settings", "issue_key"),
    [
        (IntercomSettings(True, True, None), None),
        (IntercomSettings(False, True, None), "intercom_unavailable_hub_off"),
        (IntercomSettings(False, False, "plan"), "intercom_unavailable_plan"),
        (IntercomSettings(False, True, "kid_hub"), "intercom_unavailable_kid_hub"),
        (
            IntercomSettings(False, True, "public_hub"),
            "intercom_unavailable_public_hub",
        ),
        (IntercomSettings(False, True, "platform"), "intercom_unavailable_platform"),
        (IntercomSettings(False, True, "moon_phase"), "intercom_unavailable_unknown"),
    ],
)
async def test_availability_issue(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
    settings: IntercomSettings,
    issue_key: str | None,
) -> None:
    """Each reason Intercom cannot run is a Repairs notice of its own, and it clears."""
    mock_intercom_api.get_intercom_settings.return_value = settings
    await _setup(hass, intercom_entry)
    issue = issue_registry.async_get_issue(
        DOMAIN, unavailable_issue_id(intercom_entry.entry_id)
    )
    if issue_key is None:
        assert issue is None
    else:
        assert issue is not None
        assert issue.translation_key == issue_key
        assert issue.translation_placeholders == {"hub": "Maison"}
        assert not issue.is_fixable

    # The platform changing its mind clears the notice.
    mock_intercom_api.get_intercom_settings.return_value = IntercomSettings(
        True, True, None
    )
    await intercom_entry.runtime_data.intercom.async_check_availability()
    assert (
        issue_registry.async_get_issue(
            DOMAIN, unavailable_issue_id(intercom_entry.entry_id)
        )
        is None
    )


async def test_availability_check_never_fails_setup(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A check that cannot be made leaves the entry loaded and raises nothing."""
    mock_intercom_api.get_intercom_settings.side_effect = ThalovantConnectionError()
    await _setup(hass, intercom_entry)
    assert intercom_entry.state.value == "loaded"
    assert (
        issue_registry.async_get_issue(
            DOMAIN, unavailable_issue_id(intercom_entry.entry_id)
        )
        is None
    )


@pytest.mark.parametrize("can_play", [True, False])
async def test_can_play(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
    can_play: bool,
) -> None:
    """Telling the platform works, and failing to leaves a notice only when it matters."""
    entry = make_intercom_entry(credentials, options={})
    controller = await _setup(hass, entry)
    issue_id = can_play_issue_id(entry.entry_id)

    await controller.async_set_can_play(can_play)
    mock_intercom_api.set_connection_can_play.assert_awaited_once_with(
        "conn-91c2", can_play
    )
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None

    mock_intercom_api.set_connection_can_play.side_effect = ThalovantApiError(
        status=403
    )
    await controller.async_set_can_play(can_play)
    assert (issue_registry.async_get_issue(DOMAIN, issue_id) is not None) is can_play

    mock_intercom_api.set_connection_can_play.side_effect = None
    await controller.async_set_can_play(can_play)
    assert issue_registry.async_get_issue(DOMAIN, issue_id) is None


async def test_exception_messages_read_well(hass: HomeAssistant) -> None:
    """The messages a person reads say what happened and what to do, with their ids."""
    assert await async_setup_component(hass, DOMAIN, {})
    strings = await translation.async_get_translations(
        hass, "en", "exceptions", {DOMAIN}
    )
    unreachable = strings[f"component.{DOMAIN}.exceptions.hub_unreachable.message"]
    text = unreachable.format(announcement=ANNOUNCEMENT_ID)
    assert ANNOUNCEMENT_ID in text
    assert "may still have been spoken" in text
    assert "does not retry" in text
    unknown = strings[f"component.{DOMAIN}.exceptions.announce_outcome_unknown.message"]
    assert "may still have been spoken" in unknown
