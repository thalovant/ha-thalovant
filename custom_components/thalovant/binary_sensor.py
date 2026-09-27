"""The hub connection sensor for the Thalovant integration."""

from typing import override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ThalovantEntity
from .models import ThalovantConfigEntry

# Push only: the connection reports its own state.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThalovantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the hub connection sensor."""
    async_add_entities([HubConnectionSensor(entry)])


class HubConnectionSensor(ThalovantEntity, BinarySensorEntity):
    """On while the hub can reach this Home Assistant.

    It stays available when the link drops: "off" is the answer, not a gap.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "hub_connection"

    def __init__(self, entry: ThalovantConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(entry, "hub_connection")
        self._connection = entry.runtime_data.connection
        self._attr_is_on = self._connection.connected

    @override
    async def async_added_to_hass(self) -> None:
        """Follow the connection's state."""
        await super().async_added_to_hass()
        self.async_on_remove(self._connection.on_state_change(self._on_state_change))
        # The link may have changed between construction and subscription.
        self._attr_is_on = self._connection.connected

    @callback
    def _on_state_change(self, connected: bool) -> None:
        self._attr_is_on = connected
        self.async_write_ha_state()
