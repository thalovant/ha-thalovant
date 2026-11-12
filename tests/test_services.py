"""Tests for the announce, cancel_announcement and list_speakers actions."""

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.api import (
    IntercomSettings,
    IntercomSpeaker,
    IntercomSpeakers,
    ThalovantHubUnreachableError,
    ThalovantIntercomUnavailableError,
)
from custom_components.thalovant.const import (
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_URGENT,
    CONF_HOME_CLIENT_ID,
    CONF_SELF_HOSTED,
    CONF_VOICE_CLIENT_ID,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import (
    ANNOUNCEMENT_ID,
    SECRET_TEXT,
    FakeHubConnection,
    make_announcement,
    make_intercom_entry,
)


async def _setup(hass: HomeAssistant, *entries: MockConfigEntry) -> None:
    for entry in entries:
        entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()


async def _announce(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any] | None:
    return await hass.services.async_call(  # type: ignore[no-any-return]
        DOMAIN, "announce", data, blocking=True, return_response=True
    )


async def test_services_exist_even_when_nothing_is_on(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """The actions are registered once, so a refusal can say why."""
    await _setup(hass, mock_config_entry)
    for service in ("announce", "cancel_announcement", "list_speakers"):
        assert hass.services.has_service(DOMAIN, service)
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hello"})
    assert caught.value.translation_key == "announcements_disabled"
    assert caught.value.translation_placeholders == {"hub": "Maison"}


async def test_announce(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The response has the id, the status and counts: never the text."""
    caplog.set_level(logging.DEBUG)
    await _setup(hass, intercom_entry)

    response = await _announce(hass, {"message": f"  {SECRET_TEXT}\n"})

    assert response == {
        "announcement_id": ANNOUNCEMENT_ID,
        "status": "completed",
        "priority": "normal",
        "deliveries": {"total": 3, "by_status": {"delivered": 2, "offline": 1}},
        "acked_by": None,
        "replayed": False,
    }
    assert SECRET_TEXT not in repr(response)
    args = mock_intercom_api.announce.await_args
    assert args.args[1] == SECRET_TEXT
    assert args.kwargs["targets"] == {"all": True}
    assert args.kwargs["priority"] == "normal"
    assert SECRET_TEXT not in caplog.text


async def test_announce_urgent_with_everything(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Target, names, priority, repeat and language reach the controller."""
    mock_intercom_api.announce.return_value = make_announcement(
        "completed", priority="urgent", acked_by="Kitchen\u202e Speaker"
    )
    await _setup(hass, intercom_entry)
    response = await _announce(
        hass,
        {
            "message": "Wake up",
            "target": "speakers",
            "names": "kitchen speaker",
            "priority": "urgent",
            "repeat_times": 3,
            "repeat_interval": 30,
            "language": "fr_ca",
            "wait": True,
        },
    )
    kwargs = mock_intercom_api.announce.await_args.kwargs
    assert kwargs["targets"] == {"speakers": ["kitchen-speaker"]}
    assert kwargs["priority"] == "urgent"
    assert kwargs["repeat"] == (3, 30)
    assert kwargs["lang"] == "fr-CA"
    assert response is not None
    # A household-typed name is made safe before it leaves.
    assert response["acked_by"] == "Kitchen Speaker"


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"message": ""}, "text_empty"),
        ({"message": "x" * 281}, "text_too_long"),
        ({"message": "bell\x07"}, "text_bad_characters"),
        ({"message": "a\u202eb"}, "text_bad_characters"),
        ({"message": "Hi", "names": ["kitchen"]}, "names_not_allowed"),
        ({"message": "Hi", "target": "rooms"}, "names_required"),
        ({"message": "Hi", "target": "rooms", "names": ["a\u202eb"]}, "invalid_names"),
        (
            {"message": "Hi", "repeat_times": 2, "repeat_interval": 30},
            "repeat_urgent_only",
        ),
        (
            {"message": "Hi", "priority": "urgent", "repeat_times": 2},
            "repeat_incomplete",
        ),
        (
            {"message": "Hi", "priority": "urgent", "repeat_interval": 30},
            "repeat_incomplete",
        ),
        ({"message": "Hi", "language": "not a language"}, "invalid_language"),
    ],
)
async def test_announce_validation(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    data: dict[str, Any],
    key: str,
) -> None:
    """What the caller can fix is refused before anything is contacted."""
    await _setup(hass, intercom_entry)
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, data)
    assert caught.value.translation_key == key
    mock_intercom_api.announce.assert_not_awaited()
    # The text is not in what the caller is told.
    if data["message"].strip():
        assert data["message"].strip() not in repr(
            caught.value.translation_placeholders
        )


@pytest.mark.parametrize(
    "data",
    [
        {"message": "Hi", "repeat_times": 11, "priority": "urgent"},
        {"message": "Hi", "repeat_interval": 4, "priority": "urgent"},
        {"message": "Hi", "target": "everyone"},
        {"message": "Hi", "priority": "loud"},
        {"message": ["not", "text"]},
        {},
    ],
)
async def test_announce_schema(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    data: dict[str, Any],
) -> None:
    """A call the schema refuses never reaches the platform."""
    await _setup(hass, intercom_entry)
    with pytest.raises(Exception):  # noqa: B017 - voluptuous or probatio Invalid
        await _announce(hass, data)
    mock_intercom_api.announce.assert_not_awaited()


async def test_urgent_refused_when_off(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Urgent is its own choice: refused clearly when only announcements are on."""
    entry = make_intercom_entry(
        credentials,
        options={CONF_ALLOW_ANNOUNCEMENTS: True},
        scopes=(
            "hubs:read",
            "clients:read",
            "clients:write",
            "intercom:read",
            "intercom:send",
        ),
    )
    await _setup(hass, entry)
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hi", "priority": "urgent"})
    assert caught.value.translation_key == "urgent_disabled"


async def test_errors_from_the_platform_reach_the_caller(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """After a 502 the caller is told it may have been spoken, with the id."""
    mock_intercom_api.announce.side_effect = ThalovantHubUnreachableError(
        announcement_id=ANNOUNCEMENT_ID
    )
    await _setup(hass, intercom_entry)
    with pytest.raises(HomeAssistantError) as caught:
        await _announce(hass, {"message": SECRET_TEXT})
    assert caught.value.translation_key == "hub_unreachable"
    assert caught.value.translation_placeholders == {
        "hub": "Maison",
        "announcement": ANNOUNCEMENT_ID,
    }
    assert mock_intercom_api.announce.await_count == 1


# --- Which hub ---------------------------------------------------------------


async def test_no_entry(hass: HomeAssistant) -> None:
    """With no hub linked, the actions say so."""
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hi"})
    assert caught.value.translation_key == "no_entries"


async def test_two_hubs(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """With two hubs announcing, the caller must say which; naming one works."""
    first = make_intercom_entry(credentials, title="Maison", hub_id="hub-maison")
    second = make_intercom_entry(credentials, title="Chalet", hub_id="hub-chalet")
    second.add_to_hass(hass)
    first.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hi"})
    assert caught.value.translation_key == "entry_required"

    await _announce(hass, {"message": "Hi", "config_entry_id": second.entry_id})
    assert mock_intercom_api.announce.await_args.args[0] == "hub-chalet"

    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hi", "config_entry_id": "nope"})
    assert caught.value.translation_key == "entry_not_found"

    # Cancel and list need a hub named too, announcements on or not.
    for service, data in (
        ("cancel_announcement", {"announcement_id": ANNOUNCEMENT_ID}),
        ("list_speakers", {}),
    ):
        with pytest.raises(ServiceValidationError) as caught:
            await hass.services.async_call(
                DOMAIN, service, data, blocking=True, return_response=True
            )
        assert caught.value.translation_key == "entry_required"


async def test_two_hubs_neither_announcing(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Two hubs and neither announcing: announcements are off, said plainly."""
    first = make_intercom_entry(credentials, options={}, hub_id="hub-maison")
    second = make_intercom_entry(
        credentials, options={}, title="Chalet", hub_id="hub-chalet"
    )
    await _setup(hass, first, second)
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hi"})
    assert caught.value.translation_key == "announcements_disabled"


async def test_entry_not_loaded(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """A link that is not running cannot announce."""
    await _setup(hass, intercom_entry)
    assert await hass.config_entries.async_unload(intercom_entry.entry_id)
    assert intercom_entry.state is ConfigEntryState.NOT_LOADED
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(
            hass, {"message": "Hi", "config_entry_id": intercom_entry.entry_id}
        )
    assert caught.value.translation_key == "entry_not_loaded"
    # Not naming it: nothing announces, so it is the option that is "off".
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hi"})
    assert caught.value.translation_key == "entry_not_loaded"


async def test_private_links_never_announce(
    hass: HomeAssistant, mock_hub_connection: FakeHubConnection
) -> None:
    """A private link has no account: it is not a hub these actions can use."""
    private = MockConfigEntry(
        domain=DOMAIN,
        title="Private",
        unique_id="self_hosted:abc",
        data={
            CONF_SELF_HOSTED: True,
            CONF_HOME_CLIENT_ID: "1",
            CONF_VOICE_CLIENT_ID: "2",
        },
    )
    private.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hi"})
    assert caught.value.translation_key == "no_entries"


# --- Cancel and list ---------------------------------------------------------


async def test_cancel(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Cancelling returns the status and whether the hub confirmed."""
    await _setup(hass, intercom_entry)
    response = await hass.services.async_call(
        DOMAIN,
        "cancel_announcement",
        {"announcement_id": f" {ANNOUNCEMENT_ID} "},
        blocking=True,
        return_response=True,
    )
    assert response == {
        "announcement_id": ANNOUNCEMENT_ID,
        "status": "cancelled",
        "hub_confirmed": True,
    }
    mock_intercom_api.cancel_announcement.assert_awaited_once_with(
        "hub-maison", ANNOUNCEMENT_ID
    )


async def test_cancel_with_announcements_off(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Cancel is allowed with the option off, for an entry that can send."""
    entry = make_intercom_entry(credentials, options={})
    await _setup(hass, entry)
    response = await hass.services.async_call(
        DOMAIN,
        "cancel_announcement",
        {"announcement_id": ANNOUNCEMENT_ID},
        blocking=True,
        return_response=True,
    )
    assert response is not None
    assert response["status"] == "cancelled"


async def test_cancel_refuses_odd_ids(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """An id that cannot be one is refused before any request."""
    await _setup(hass, intercom_entry)
    with pytest.raises(ServiceValidationError) as caught:
        await hass.services.async_call(
            DOMAIN,
            "cancel_announcement",
            {"announcement_id": "../etc"},
            blocking=True,
            return_response=True,
        )
    assert caught.value.translation_key == "invalid_announcement_id"
    mock_intercom_api.cancel_announcement.assert_not_awaited()


async def test_list_speakers(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """The speakers, rooms and groups, for the names the announce action takes."""
    mock_intercom_api.list_intercom_speakers.return_value = IntercomSpeakers(
        (
            IntercomSpeaker(
                "id-1",
                "kitchen",
                "Kitchen\u202e Speaker",
                True,
                True,
                "kitchen",
                ("downstairs", "\u202e"),
            ),
            IntercomSpeaker("id-2", None, None, False, False, None, ()),
            IntercomSpeaker(
                "id-3",
                "home-link",
                "Home link",
                False,
                False,
                None,
                (),
                kind="home_assistant\u202e",
                can_play=False,
            ),
        ),
        policy_synced=False,
        unavailable_reason="platform",
    )
    await _setup(hass, intercom_entry)
    response = await hass.services.async_call(
        DOMAIN, "list_speakers", {}, blocking=True, return_response=True
    )
    assert response == {
        "speakers": [
            {
                "id": "id-1",
                "slug": "kitchen",
                "name": "Kitchen Speaker",
                "kind": "voice_satellite",
                "can_play": True,
                "online": True,
                "receive": True,
                "room": "kitchen",
                "groups": ["downstairs"],
            },
            {
                "id": "id-2",
                "slug": None,
                "name": None,
                "kind": "voice_satellite",
                "can_play": True,
                "online": False,
                "receive": False,
                "room": None,
                "groups": [],
            },
            {
                "id": "id-3",
                "slug": "home-link",
                "name": "Home link",
                "kind": "home_assistant",
                "can_play": False,
                "online": False,
                "receive": False,
                "room": None,
                "groups": [],
            },
        ],
        "rooms": ["kitchen"],
        "groups": ["downstairs"],
        # A change may take a moment to reach the home, and Intercom is not on yet.
        "policy_synced": False,
        "unavailable_reason": "platform",
    }
    # Always fresh: it is how a person finds out what is there now.
    await hass.services.async_call(
        DOMAIN, "list_speakers", {}, blocking=True, return_response=True
    )
    assert mock_intercom_api.list_intercom_speakers.await_count == 2


async def test_unused_options_are_ignored(
    hass: HomeAssistant,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """Urgent without announcements is a stored state that announces nothing."""
    entry = make_intercom_entry(credentials, options={CONF_ALLOW_URGENT: True})
    await _setup(hass, entry)
    with pytest.raises(ServiceValidationError) as caught:
        await _announce(hass, {"message": "Hi"})
    assert caught.value.translation_key == "announcements_disabled"


async def test_the_platform_switch_is_off(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    issue_registry: ir.IssueRegistry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Intercom ships off: the actions say so, a repair explains, nothing crashes.

    The platform answers every write 503 intercom_disabled_platform, the settings
    and the speakers (reads) say unavailable_reason platform, and a cancel is the
    one write that still works, with no hub called (hub_confirmed false).
    """
    caplog.set_level(logging.DEBUG)
    mock_intercom_api.get_intercom_settings.return_value = IntercomSettings(
        enabled=False, plan_allowed=True, unavailable_reason="platform"
    )
    mock_intercom_api.announce.side_effect = ThalovantIntercomUnavailableError(
        reason="platform", status=503, code="intercom_disabled_platform"
    )
    mock_intercom_api.list_intercom_speakers.return_value = IntercomSpeakers(
        (), policy_synced=True, unavailable_reason="platform"
    )
    mock_intercom_api.cancel_announcement.return_value = make_announcement(
        "cancelled", priority="urgent", hub_confirmed=False
    )

    await _setup(hass, intercom_entry)
    # Setup finished, and a repair says Intercom is not on yet.
    assert intercom_entry.state is ConfigEntryState.LOADED
    issue = issue_registry.async_get_issue(
        DOMAIN, f"intercom_unavailable_{intercom_entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_key == "intercom_unavailable_platform"
    assert issue.is_fixable is False

    for data in (
        {"message": SECRET_TEXT},
        {
            "message": SECRET_TEXT,
            "priority": "urgent",
            "repeat_times": 3,
            "repeat_interval": 30,
        },
    ):
        with pytest.raises(HomeAssistantError) as caught:
            await _announce(hass, data)
        assert caught.value.translation_key == "intercom_unavailable_platform"
        assert SECRET_TEXT not in repr(caught.value)
    assert SECRET_TEXT not in caplog.text

    # Reads work, and say why.
    listing = await hass.services.async_call(
        DOMAIN, "list_speakers", {}, blocking=True, return_response=True
    )
    assert listing is not None
    assert (listing["speakers"], listing["unavailable_reason"]) == ([], "platform")

    # A cancel still works, and says that the hub did not confirm it.
    cancelled = await hass.services.async_call(
        DOMAIN,
        "cancel_announcement",
        {"announcement_id": ANNOUNCEMENT_ID},
        blocking=True,
        return_response=True,
    )
    assert cancelled == {
        "announcement_id": ANNOUNCEMENT_ID,
        "status": "cancelled",
        "hub_confirmed": False,
    }
