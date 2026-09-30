"""Constants for the Thalovant integration."""

from datetime import timedelta
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
CONF_LINKED_AT: Final = "linked_at"

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

# For this long after a connection is made, the hub refusing it means "not
# admitted yet" rather than bad credentials: setup retries instead of asking
# the user to reauthenticate. The SDK's run() waits the same 600 s.
ADMISSION_GRACE_PERIOD: Final = timedelta(seconds=600)

REQUEST_MESSAGE_TYPE: Final = "thalovant.home.request"
RESPONSE_MESSAGE_TYPE: Final = "thalovant.home.response"

# The hub gives up on a request 10 seconds after sending it and treats silence
# as a timeout; an answer after that is never sent. Counted from the request's
# arrival, Assist gets at most CONVERSE_TIMEOUT of them, a fallback sentence
# for an error what is left short of REPLY_RESERVE, and the reply the rest.
HUB_TIMEOUT: Final = 10.0
CONVERSE_TIMEOUT: Final = 8.5
REPLY_RESERVE: Final = 0.5

# Requests handled at once. A hub has no reason to send more than a household
# can speak, so anything past this answers "unknown" at once instead of queuing
# behind a slow agent.
MAX_CONCURRENT_REQUESTS: Final = 8

# Devices that have spoken through one hub, kept so each can be given an area.
# A hub has no reason to have more; past this, requests are answered as before,
# with no room.
MAX_DEVICES_PER_HUB: Final = 50

# Removing an entry must not hang on an unreachable control plane.
REMOVE_TIMEOUT: Final = 10.0

DASHBOARD_URL: Final = "https://dash.thalovant.com"
MANUFACTURER: Final = "Thalovant"
