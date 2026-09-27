"""Diagnostics for the Thalovant integration."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_ACCOUNT_ID, CONF_CREDENTIALS, CONF_HUB_NAME, CONF_TOKENS
from .models import ThalovantConfigEntry

# The tokens and the connection's credentials are dropped whole; the account,
# the hub name and the title can be personal. No utterance or reply is ever kept.
TO_REDACT = {
    CONF_ACCOUNT_ID,
    CONF_CREDENTIALS,
    CONF_HUB_NAME,
    CONF_TOKENS,
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ThalovantConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    credentials = entry.data.get(CONF_CREDENTIALS, {})
    stats = entry.runtime_data.stats
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "connection": {
            "connected": entry.runtime_data.connection.connected,
            "endpoint": credentials.get("endpoint"),
            "has_secret": bool(credentials.get("secret")),
            "token_scopes": list(entry.data.get(CONF_TOKENS, {}).get("scopes", [])),
        },
        "requests": {
            "handled": stats.handled,
            "outcomes": dict(stats.outcomes),
            "last_outcome": stats.last_outcome,
            "last_handled_at": (
                stats.last_handled_at.isoformat() if stats.last_handled_at else None
            ),
            "last_duration_ms": stats.last_duration_ms,
        },
    }
