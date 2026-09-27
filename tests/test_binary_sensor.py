"""Tests for the hub connection sensor."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.const import DOMAIN, MANUFACTURER
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import ACCOUNT_ID, HUB_ID, FakeHubConnection

ENTITY_ID = "binary_sensor.maison_hub_connection"


async def test_hub_connection_sensor(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """The sensor follows the link and sits on a service device for the hub."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes[ATTR_DEVICE_CLASS] == BinarySensorDeviceClass.CONNECTIVITY

    mock_hub_connection.set_connected(False)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF
    mock_hub_connection.set_connected(True)
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    entry = entity_registry.async_get(ENTITY_ID)
    assert entry is not None
    assert entry.unique_id == f"{ACCOUNT_ID}:{HUB_ID}_hub_connection"
    assert entry.entity_category is EntityCategory.DIAGNOSTIC
    assert entry.translation_key == "hub_connection"

    device = device_registry.async_get(entry.device_id)
    assert device is not None
    assert device.identifiers == {(DOMAIN, HUB_ID)}
    assert device.name == "Maison"
    assert device.manufacturer == MANUFACTURER
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert device.config_entry_id == mock_config_entry.entry_id


async def test_sensor_state_at_subscription(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """A link that dropped before the entity subscribed shows off."""
    original = mock_hub_connection.on_state_change

    def drop_then_subscribe(callback):  # type: ignore[no-untyped-def]
        mock_hub_connection._connected = False
        return original(callback)

    mock_hub_connection.on_state_change = drop_then_subscribe  # type: ignore[method-assign]
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_sensor_removed_on_unload(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """Unloading unsubscribes the sensor."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert len(mock_hub_connection.state_callbacks) == 2

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_hub_connection.state_callbacks == []
