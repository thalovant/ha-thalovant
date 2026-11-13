"""Tests for Thalovant diagnostics."""

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.thalovant.const import (
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_RECEIVE,
    CONF_SPEAKER_AREAS,
    CONF_SPEAKER_PLAYERS,
    CONF_TTS_ENTITY,
    REQUEST_MESSAGE_TYPE,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .conftest import (
    ACCESS_KEY,
    ACCESS_TOKEN,
    ACCOUNT_ID,
    ANNOUNCEMENT_ID,
    CONNECTION_SECRET,
    SECRET_TEXT,
    FakeHubConnection,
    make_intercom_entry,
)


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    snapshot: SnapshotAssertion,
) -> None:
    """Diagnostics carry state and counts, never a secret or an utterance."""
    assert await async_setup_component(hass, "diagnostics", {})
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    await mock_hub_connection.emit(
        REQUEST_MESSAGE_TYPE,
        {"request_id": "r1", "utterance": "unlock the front door please"},
    )
    await mock_hub_connection.next_reply()

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )
    dumped = json.dumps(diagnostics)
    for secret in (
        ACCESS_TOKEN,
        CONNECTION_SECRET,
        ACCESS_KEY,
        ACCOUNT_ID,
        "front door",
        "Maison",
    ):
        assert secret not in dumped

    assert diagnostics == snapshot(
        exclude=props("last_handled_at", "last_duration_ms", "entry_id")
    )


async def test_diagnostics_hold_counts_of_announcements_never_text(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    credentials: Any,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
) -> None:
    """What was said, to whom and where it played are not in diagnostics: counts are."""
    entry = make_intercom_entry(
        credentials,
        options={
            CONF_ALLOW_ANNOUNCEMENTS: True,
            CONF_ALLOW_RECEIVE: True,
            CONF_SPEAKER_PLAYERS: ["media_player.kitchen_secret_name"],
            CONF_SPEAKER_AREAS: ["secret_area"],
            CONF_TTS_ENTITY: "tts.secret_voice",
        },
    )
    assert await async_setup_component(hass, "diagnostics", {})
    hass.states.async_set("media_player.kitchen_secret_name", "idle")
    hass.states.async_set("tts.secret_voice", "unknown")
    async_mock_service(hass, "tts", "speak")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await entry.runtime_data.intercom.async_announce(
        SECRET_TEXT, target="rooms", names=["secret room"]
    )
    await mock_hub_connection.emit(
        "speak",
        {
            "utterance": SECRET_TEXT,
            "lang": "en",
            "meta": {
                "dialog": "intercom.announce",
                "intercom": {"id": "ann-1", "priority": "normal"},
            },
        },
    )
    for _ in range(30):
        await asyncio.sleep(0)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    dumped = json.dumps(diagnostics)
    for secret in (
        SECRET_TEXT,
        "pelican",
        "secret room",
        "secret_name",
        "secret_area",
        "secret_voice",
        ANNOUNCEMENT_ID,
    ):
        assert secret not in dumped
    assert diagnostics["entry"]["options"][CONF_SPEAKER_PLAYERS] == "**REDACTED**"
    assert diagnostics["intercom"] == {
        "announcements_enabled": True,
        "urgent_enabled": False,
        "receive_enabled": True,
        "players_chosen": 2,
        "sent": {"normal": 1},
        "send_outcomes": {"completed": 1},
        "received": {"played": 1},
        "last_sent_at": diagnostics["intercom"]["last_sent_at"],
        "last_received_at": diagnostics["intercom"]["last_received_at"],
    }
    assert diagnostics["intercom"]["last_sent_at"] is not None
    assert diagnostics["intercom"]["last_received_at"] is not None


async def test_diagnostics_never_hold_the_alarm_code(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """The alarm code disarms a panel; a diagnostics file is pasted into public issues."""
    assert await async_setup_component(hass, "diagnostics", {})
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, "alarm_code": "482913"},
    )
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )
    assert "482913" not in json.dumps(diagnostics)
    assert diagnostics["entry"]["options"]["alarm_code"] == "**REDACTED**"
