"""The Intercom notify entity: announce to every speaker from a notify action.

Off by default (the entity is disabled when it is created) and only added
while the options let the entry announce. ``notify.send_message`` on it makes a
normal announcement to every speaker that receives. It is a convenience, not a
certified safety system.
"""

from typing import override

from homeassistant.components.notify import NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import ThalovantEntity
from .intercom import InvalidInputError, validate_text
from .models import ThalovantConfigEntry
from .services import invalid_input

# One announcement at a time per entity; the controller also rate-limits.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ThalovantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Intercom notify entity."""
    async_add_entities([IntercomNotifyEntity(entry)])


class IntercomNotifyEntity(ThalovantEntity, NotifyEntity):
    """Say a message on every speaker of the hub."""

    _attr_translation_key = "intercom"
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: ThalovantConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry, "intercom")
        self._entry = entry

    @override
    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Announce message to every speaker as one normal announcement.

        The title is not spoken. Nothing is retried: see
        IntercomController.async_announce.
        """
        controller = self._entry.runtime_data.intercom
        if controller is None:  # pragma: no cover - the platform is never loaded then
            return
        try:
            text = validate_text(message)
        except InvalidInputError as err:
            raise invalid_input(f"text_{err.reason}") from None
        await controller.async_announce(text)
