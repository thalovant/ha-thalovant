"""Tests for Thalovant diagnostics."""

import json

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.thalovant.const import REQUEST_MESSAGE_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .conftest import (
    ACCESS_TOKEN,
    ACCOUNT_ID,
    CONNECTION_SECRET,
    NOISE_KEY,
    REFRESH_TOKEN,
    FakeHubConnection,
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
        REFRESH_TOKEN,
        CONNECTION_SECRET,
        NOISE_KEY,
        "hub-access-key-do-not-leak",
        ACCOUNT_ID,
        "front door",
        "Maison",
    ):
        assert secret not in dumped

    assert diagnostics == snapshot(
        exclude=props("last_handled_at", "last_duration_ms", "entry_id")
    )
