"""Base entity for the Thalovant integration."""

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONF_HUB_ID, CONF_HUB_NAME, DASHBOARD_URL, DOMAIN, MANUFACTURER
from .models import ThalovantConfigEntry


class ThalovantEntity(Entity):
    """An entity on the service device that stands for the linked hub."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ThalovantConfigEntry, key: str) -> None:
        """Initialize the entity."""
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_HUB_ID])},
            name=entry.data.get(CONF_HUB_NAME, entry.title),
            manufacturer=MANUFACTURER,
            model="Hub",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=DASHBOARD_URL,
        )
