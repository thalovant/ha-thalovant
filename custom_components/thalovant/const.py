"""Constants for the Thalovant integration."""

import logging
from typing import Final

DOMAIN: Final = "thalovant"
LOGGER = logging.getLogger(__package__)

# Keys in ConfigEntry.data.
CONF_ACCOUNT_ID: Final = "account_id"
CONF_HUB_ID: Final = "hub_id"
CONF_HUB_NAME: Final = "hub_name"
CONF_TOKENS: Final = "tokens"
CONF_CREDENTIALS: Final = "credentials"

# Keys in ConfigEntry.options.
CONF_AGENT_ID: Final = "agent_id"

# What the device login asks for: list the account's hubs, and read, create or
# delete this installation's own connection. Never hubs:write, which the Free
# plan cannot grant, so asking for it would fail the approval.
LOGIN_SCOPES: Final = ("hubs:read", "clients:read", "clients:write")

# The kind of connection the control plane creates for Home Assistant. Its
# message grant is thalovant.home.request in, thalovant.home.response out.
CONNECTION_KIND: Final = "home_assistant"

# The hub admits a new connection in about 90 seconds.
ADMISSION_TIMEOUT: Final = 180

REQUEST_MESSAGE_TYPE: Final = "thalovant.home.request"
RESPONSE_MESSAGE_TYPE: Final = "thalovant.home.response"

# The hub gives up on a request after 10 seconds and treats silence as a
# timeout. Assist gets 8 of them so the reply still has time to travel back.
CONVERSE_TIMEOUT: Final = 8.0

# Requests handled at once. A hub has no reason to send more than a household
# can speak, so anything past this answers "unknown" at once instead of queuing
# behind a slow agent.
MAX_CONCURRENT_REQUESTS: Final = 8

# Removing an entry must not hang on an unreachable control plane.
REMOVE_TIMEOUT: Final = 10.0

DASHBOARD_URL: Final = "https://dash.thalovant.com"
MANUFACTURER: Final = "Thalovant"
