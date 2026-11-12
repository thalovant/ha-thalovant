"""Tests for the Intercom notify entity."""

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.const import CONF_ALLOW_ANNOUNCEMENTS, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import ACCOUNT_ID, HUB_ID, SECRET_TEXT, FakeHubConnection

ENTITY_ID = "notify.maison_intercom"


def _register_enabled(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Pre-register the entity as enabled, as a person would have enabled it."""
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "notify",
        DOMAIN,
        f"{ACCOUNT_ID}:{HUB_ID}_intercom",
        config_entry=entry,
        suggested_object_id="maison_intercom",
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    if entry.entry_id not in {
        known.entry_id for known in hass.config_entries.async_entries()
    }:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_disabled_by_default(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """The entity exists once announcements are on, and is off until enabled."""
    await _setup(hass, intercom_entry)
    entry = entity_registry.async_get(ENTITY_ID)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry.translation_key == "intercom"
    assert hass.states.get(ENTITY_ID) is None


async def test_no_entity_without_announcements(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    entity_registry: er.EntityRegistry,
) -> None:
    """With the option off there is no notify platform at all."""
    await _setup(hass, mock_config_entry)
    assert entity_registry.async_get(ENTITY_ID) is None
    assert mock_config_entry.runtime_data.platforms == ["binary_sensor"]


async def test_send_message(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """notify.send_message makes a normal announcement to every speaker."""
    _register_enabled(hass, intercom_entry)
    await _setup(hass, intercom_entry)

    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": ENTITY_ID, "message": SECRET_TEXT, "title": "Ignored title"},
        blocking=True,
    )

    args = mock_intercom_api.announce.await_args
    assert args.args[1] == SECRET_TEXT
    assert args.kwargs["targets"] == {"all": True}
    assert args.kwargs["priority"] == "normal"
    assert SECRET_TEXT not in caplog.text
    assert "Ignored title" not in caplog.text


@pytest.mark.parametrize(
    ("message", "key"),
    [
        ("  ", "text_empty"),
        ("x" * 281, "text_too_long"),
        ("a\u202eb", "text_bad_characters"),
    ],
)
async def test_send_message_refuses_unfit_text(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    message: str,
    key: str,
) -> None:
    """Text an announcement cannot carry is refused, naming the rule."""
    _register_enabled(hass, intercom_entry)
    await _setup(hass, intercom_entry)
    with pytest.raises(ServiceValidationError) as caught:
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": ENTITY_ID, "message": message},
            blocking=True,
        )
    assert caught.value.translation_key == key
    mock_intercom_api.announce.assert_not_awaited()


async def test_platform_follows_the_option(
    hass: HomeAssistant,
    intercom_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    mock_intercom_api: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Turning announcements off and reloading removes the platform."""
    await _setup(hass, intercom_entry)
    assert intercom_entry.runtime_data.platforms == ["binary_sensor", "notify"]
    hass.config_entries.async_update_entry(intercom_entry, options={})
    await hass.async_block_till_done()
    assert intercom_entry.runtime_data.platforms == ["binary_sensor"]
    assert CONF_ALLOW_ANNOUNCEMENTS not in intercom_entry.options
