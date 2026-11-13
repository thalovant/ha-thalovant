"""Diagnostics for the Thalovant integration."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCOUNT_ID,
    CONF_ALARM_CODE,
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_RECEIVE,
    CONF_ALLOW_URGENT,
    CONF_CREDENTIALS,
    CONF_HOME_CLIENT_ID,
    CONF_HUB_NAME,
    CONF_SELF_HOSTED,
    CONF_SPEAKER_AREAS,
    CONF_SPEAKER_PLAYERS,
    CONF_TOKENS,
    CONF_TTS_ENTITY,
    CONF_VOICE_CLIENT_ID,
)
from .models import ThalovantConfigEntry

# The tokens, the connection's credentials and the alarm code are dropped whole; the account,
# the hub name and the title can be personal, and so can the players and areas
# announcements are played on. No utterance, reply or announcement text is ever
# kept: Intercom's counters hold outcomes only.
TO_REDACT = {
    CONF_ACCOUNT_ID,
    CONF_ALARM_CODE,
    CONF_CREDENTIALS,
    CONF_HOME_CLIENT_ID,
    CONF_HUB_NAME,
    CONF_SPEAKER_AREAS,
    CONF_SPEAKER_PLAYERS,
    CONF_TOKENS,
    CONF_TTS_ENTITY,
    CONF_VOICE_CLIENT_ID,
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ThalovantConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    credentials = entry.data.get(CONF_CREDENTIALS, {})
    stats = entry.runtime_data.stats
    intercom = entry.runtime_data.intercom_stats
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
            "endpoint": (
                "**REDACTED**"
                if entry.data.get(CONF_SELF_HOSTED) is True
                else credentials.get("endpoint")
            ),
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
        "intercom": {
            "announcements_enabled": entry.options.get(CONF_ALLOW_ANNOUNCEMENTS)
            is True,
            "urgent_enabled": entry.options.get(CONF_ALLOW_URGENT) is True,
            "receive_enabled": entry.options.get(CONF_ALLOW_RECEIVE) is True,
            "players_chosen": len(entry.options.get(CONF_SPEAKER_PLAYERS, []))
            + len(entry.options.get(CONF_SPEAKER_AREAS, [])),
            "sent": dict(intercom.sent),
            "send_outcomes": dict(intercom.send_outcomes),
            "received": dict(intercom.received),
            "last_sent_at": (
                intercom.last_sent_at.isoformat() if intercom.last_sent_at else None
            ),
            "last_received_at": (
                intercom.last_received_at.isoformat()
                if intercom.last_received_at
                else None
            ),
        },
    }
