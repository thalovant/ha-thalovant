"""Service actions: announce, cancel an announcement, list the speakers.

Registered once, when the integration is set up, so a call that the options do
not allow answers with a clear error instead of "service not found". Nothing is
sent unless an entry's options turned announcements on.

An announcement is spoken aloud in a home. These actions are a convenience, not
a certified safety system: they do not replace smoke or carbon monoxide alarms,
medical alert devices or emergency services. The text is never logged, put in
an event, a repair or an error message.
"""

from typing import Any

import probatio

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import Announcement, IntercomSpeaker
from .const import (
    CONF_SELF_HOSTED,
    DOMAIN,
    MAX_REPEAT_INTERVAL,
    MAX_REPEAT_TIMES,
    MIN_REPEAT_INTERVAL,
    SERVICE_ANNOUNCE,
    SERVICE_CANCEL_ANNOUNCEMENT,
    SERVICE_LIST_SPEAKERS,
)
from .intercom import (
    IntercomController,
    InvalidInputError,
    is_valid_announcement_id,
    sanitize_label,
    validate_language,
    validate_names,
    validate_text,
)
from .models import ThalovantConfigEntry

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_MESSAGE = "message"
ATTR_TARGET = "target"
ATTR_NAMES = "names"
ATTR_PRIORITY = "priority"
ATTR_REPEAT_TIMES = "repeat_times"
ATTR_REPEAT_INTERVAL = "repeat_interval"
ATTR_LANGUAGE = "language"
ATTR_WAIT = "wait"
ATTR_ANNOUNCEMENT_ID = "announcement_id"

TARGETS = ("all", "speakers", "rooms", "groups")
PRIORITIES = ("normal", "urgent")

ANNOUNCE_SCHEMA = probatio.Schema(
    {
        probatio.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        probatio.Required(ATTR_MESSAGE): cv.string,
        probatio.Optional(ATTR_TARGET, default="all"): probatio.In(TARGETS),
        probatio.Optional(ATTR_NAMES, default=list): probatio.All(
            cv.ensure_list, [cv.string]
        ),
        probatio.Optional(ATTR_PRIORITY, default="normal"): probatio.In(PRIORITIES),
        probatio.Optional(ATTR_REPEAT_TIMES): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1, max=MAX_REPEAT_TIMES)
        ),
        probatio.Optional(ATTR_REPEAT_INTERVAL): probatio.All(
            probatio.Coerce(int),
            probatio.Range(min=MIN_REPEAT_INTERVAL, max=MAX_REPEAT_INTERVAL),
        ),
        probatio.Optional(ATTR_LANGUAGE): cv.string,
        probatio.Optional(ATTR_WAIT, default=False): cv.boolean,
    }
)
CANCEL_SCHEMA = probatio.Schema(
    {
        probatio.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        probatio.Required(ATTR_ANNOUNCEMENT_ID): cv.string,
    }
)
LIST_SCHEMA = probatio.Schema({probatio.Optional(ATTR_CONFIG_ENTRY_ID): cv.string})


def invalid_input(key: str, **placeholders: str) -> ServiceValidationError:
    """A validation error with a translation, which never holds what was refused."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


def async_get_controller(
    hass: HomeAssistant, entry_id: str | None, *, announcing: bool
) -> IntercomController:
    """The controller of the entry a call is for.

    A call names an entry (config_entry_id), or, when only one linked hub has
    announcements on, means that one. announcing says whether the call needs
    the option on; cancelling does not (see IntercomController.async_cancel).
    """
    entries: list[ThalovantConfigEntry] = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.data.get(CONF_SELF_HOSTED) is not True
    ]
    if entry_id is not None:
        entries = [entry for entry in entries if entry.entry_id == entry_id]
        if not entries:
            raise invalid_input("entry_not_found")
    elif announcing:
        enabled = [
            entry
            for entry in entries
            if entry.state is ConfigEntryState.LOADED
            and entry.runtime_data.intercom is not None
            and entry.runtime_data.intercom.announcements_allowed
        ]
        if len(enabled) > 1:
            raise invalid_input("entry_required")
        if enabled:
            entries = enabled
        elif len(entries) > 1:
            raise invalid_input("announcements_disabled", hub="Thalovant")
    if not entries:
        raise invalid_input("no_entries")
    if len(entries) > 1:
        raise invalid_input("entry_required")
    entry = entries[0]
    controller = (
        entry.runtime_data.intercom if entry.state is ConfigEntryState.LOADED else None
    )
    if controller is None:
        raise invalid_input("entry_not_loaded", hub=entry.title)
    if announcing:
        controller.require_announcements()
    return controller


def _announce_request(
    data: dict[str, Any],
) -> tuple[str, str, list[str], str, tuple[int, int] | None, str | None]:
    """Check what an announce call asks for, before anything is contacted.

    Returns the text, target, names, priority, repeat and language. Raises
    ServiceValidationError, whose message never holds the text.
    """
    try:
        text = validate_text(data[ATTR_MESSAGE])
    except InvalidInputError as err:
        raise invalid_input(f"text_{err.reason}") from None
    target: str = data[ATTR_TARGET]
    try:
        names = validate_names(data[ATTR_NAMES])
    except InvalidInputError:
        raise invalid_input("invalid_names") from None
    if target == "all" and names:
        raise invalid_input("names_not_allowed")
    if target != "all" and not names:
        raise invalid_input("names_required", target=target)
    priority: str = data[ATTR_PRIORITY]
    times = data.get(ATTR_REPEAT_TIMES)
    interval = data.get(ATTR_REPEAT_INTERVAL)
    repeat: tuple[int, int] | None = None
    if times is not None or interval is not None:
        if priority != "urgent":
            raise invalid_input("repeat_urgent_only")
        if times is None or interval is None:
            raise invalid_input("repeat_incomplete")
        repeat = (times, interval)
    language: str | None = None
    if (raw := data.get(ATTR_LANGUAGE)) is not None:
        try:
            language = validate_language(raw)
        except InvalidInputError:
            raise invalid_input("invalid_language") from None
    return text, target, names, priority, repeat, language


def _announcement_response(announcement: Announcement) -> dict[str, Any]:
    """What a call returns about an announcement: counts and ids, no text."""
    return {
        "announcement_id": announcement.id,
        "status": announcement.status,
        "priority": announcement.priority,
        "deliveries": {
            "total": len(announcement.deliveries),
            "by_status": announcement.delivery_counts,
        },
        "acked_by": sanitize_label(announcement.acked_by),
        # True when the platform handed back an announcement it already had:
        # nothing new was sent.
        "replayed": announcement.replayed,
    }


def _speaker_response(speaker: IntercomSpeaker) -> dict[str, Any]:
    """A speaker as a call returns it. Names are household-typed: sanitised."""
    return {
        "id": speaker.client_id,
        "slug": sanitize_label(speaker.slug),
        "name": sanitize_label(speaker.name),
        "kind": sanitize_label(speaker.kind, 32),
        "can_play": speaker.can_play,
        "online": speaker.online,
        "receive": speaker.receive,
        "room": sanitize_label(speaker.room),
        "groups": [
            label for group in speaker.groups if (label := sanitize_label(group))
        ],
    }


async def _async_announce(call: ServiceCall) -> ServiceResponse:
    """Say a text on the hub's speakers."""
    controller = async_get_controller(
        call.hass, call.data.get(ATTR_CONFIG_ENTRY_ID), announcing=True
    )
    text, target, names, priority, repeat, language = _announce_request(dict(call.data))
    announcement = await controller.async_announce(
        text,
        target=target,
        names=names,
        priority=priority,
        repeat=repeat,
        lang=language,
        wait=call.data[ATTR_WAIT],
    )
    return _announcement_response(announcement)


async def _async_cancel(call: ServiceCall) -> ServiceResponse:
    """Stop an announcement that is still repeating."""
    announcement_id: str = call.data[ATTR_ANNOUNCEMENT_ID].strip()
    if not is_valid_announcement_id(announcement_id):
        raise invalid_input("invalid_announcement_id")
    controller = async_get_controller(
        call.hass, call.data.get(ATTR_CONFIG_ENTRY_ID), announcing=False
    )
    announcement = await controller.async_cancel(announcement_id)
    return {
        "announcement_id": announcement.id,
        "status": announcement.status,
        "hub_confirmed": announcement.hub_confirmed,
    }


async def _async_list_speakers(call: ServiceCall) -> ServiceResponse:
    """List the hub's speakers, rooms and groups, for the other calls' names."""
    controller = async_get_controller(
        call.hass, call.data.get(ATTR_CONFIG_ENTRY_ID), announcing=True
    )
    listing = await controller.async_list_speakers(fresh=True)
    rooms = sorted(
        {room for item in listing.items if (room := sanitize_label(item.room))}
    )
    groups = sorted(
        {
            label
            for item in listing.items
            for g in item.groups
            if (label := sanitize_label(g))
        }
    )
    response: dict[str, Any] = {
        "speakers": [_speaker_response(item) for item in listing.items],
        "rooms": rooms,
        "groups": groups,
        # False: a change to who receives may take a moment to reach the hub.
        "policy_synced": listing.policy_synced,
        # Why Intercom cannot run on the hub (platform: it is not switched on
        # for anybody yet), or None.
        "unavailable_reason": sanitize_label(listing.unavailable_reason, 32),
    }
    return response


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions. Called from async_setup, once."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_ANNOUNCE,
        _async_announce,
        schema=ANNOUNCE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CANCEL_ANNOUNCEMENT,
        _async_cancel,
        schema=CANCEL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_SPEAKERS,
        _async_list_speakers,
        schema=LIST_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
