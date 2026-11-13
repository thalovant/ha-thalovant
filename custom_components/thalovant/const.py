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
CONF_SELF_HOSTED: Final = "self_hosted"
CONF_HOME_CLIENT_ID: Final = "home_client_id"
CONF_VOICE_CLIENT_ID: Final = "voice_client_id"

# Keys in ConfigEntry.options. Every Intercom key is absent until somebody
# turns the feature on, so an entry that never did is stored as it always was.
CONF_AGENT_ID: Final = "agent_id"
CONF_ALLOW_ANNOUNCEMENTS: Final = "allow_announcements"
CONF_ALLOW_URGENT: Final = "allow_urgent"
CONF_ALLOW_RECEIVE: Final = "allow_receive"
# Structured actions (the hub names a capability, a target and a value instead of leaving a sentence to Assist).
# On by default; sensitive ones (locks, alarm panels, garage doors, gates, valves, sirens) are off by default.
CONF_STRUCTURED_ACTIONS: Final = "structured_actions"
CONF_STRUCTURED_SENSITIVE: Final = "structured_sensitive"
CONF_ALARM_CODE: Final = "alarm_code"
CONF_SPEAKER_PLAYERS: Final = "speaker_players"
CONF_SPEAKER_AREAS: Final = "speaker_areas"
CONF_TTS_ENTITY: Final = "tts_entity"

# Every option Intercom reads: a change to any of them reloads the entry.
INTERCOM_OPTION_KEYS: Final = (
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_URGENT,
    CONF_ALLOW_RECEIVE,
    CONF_SPEAKER_PLAYERS,
    CONF_SPEAKER_AREAS,
    CONF_TTS_ENTITY,
)

# Carried by the re-consent flow (a reauth) from the options flow: the whole
# option set to store once the person has approved the extra permission.
CONF_INTERCOM_CONSENT: Final = "intercom_consent"

# What either sign-in asks for: list the account's hubs, and read, create or
# delete this installation's own connection. Never hubs:write, which the Free
# plan cannot grant, so asking for it would fail the approval.
LOGIN_SCOPES: Final = ("hubs:read", "clients:read", "clients:write")

# What turning announcements on asks for, on top of LOGIN_SCOPES: read the
# speakers and announcements, and send or cancel one. Urgent announcements
# need their own. Never hubs:write: the integration changes no hub setting, and
# the hub's owner switches Intercom on in the dashboard.
INTERCOM_READ_SCOPE: Final = "intercom:read"
INTERCOM_SEND_SCOPE: Final = "intercom:send"
INTERCOM_SCOPES: Final = (INTERCOM_READ_SCOPE, INTERCOM_SEND_SCOPE)
INTERCOM_URGENT_SCOPE: Final = "intercom:urgent"

DASHBOARD_URL: Final = "https://dash.thalovant.com"
# The control plane the SDK talks to by default (its DEFAULT_CONTROL_API_URL).
API_URL: Final = "https://api.thalovant.com"

# Link account: Home Assistant's own OAuth 2 flow with PKCE. The client is
# public (no secret) and is the same registered app a device login names, the
# SDK's HOME_ASSISTANT_CLIENT_ID, so either approval replaces the token the
# other gave. Thalovant answers it on My Home Assistant's redirect only.
LINK_CLIENT_ID: Final = "thalovant-home-assistant"
LINK_AUTHORIZE_URL: Final = f"{DASHBOARD_URL}/authorize"
LINK_TOKEN_URL: Final = f"{API_URL}/v1/auth/native/token"
# The consent page shows the device name and names the token after it.
LINK_DEVICE_NAME_MAX: Final = 120
# The code lives 60 seconds; trading it never waits longer than this.
LINK_TOKEN_TIMEOUT: Final = 30
# The problem code of a refused exchange whose code was approved from another
# network than the exchange's. Its detail is still invalid_grant.
EXCHANGE_NETWORK_MISMATCH: Final = "exchange_network_mismatch"

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

MANUFACTURER: Final = "Thalovant"

# Intercom: sending (the services and the notify entity).
SERVICE_ANNOUNCE: Final = "announce"
SERVICE_CANCEL_ANNOUNCEMENT: Final = "cancel_announcement"
SERVICE_LIST_SPEAKERS: Final = "list_speakers"

# Fired when an announcement's status is known to have changed. Its data is the
# announcement's id and status: never the text.
EVENT_ANNOUNCEMENT_UPDATED: Final = "thalovant_announcement_updated"

# The platform's limits on a text. The text is the only thing this integration
# never logs, stores, puts in an event or puts in an error.
MAX_ANNOUNCEMENT_LENGTH: Final = 280
MAX_TARGET_NAMES: Final = 50
MAX_TARGET_NAME_LENGTH: Final = 64

# Local limits per entry, kept below the platform's (20 normal a minute and 10
# urgent an hour per hub) so a runaway automation is stopped here first.
NORMAL_PER_MINUTE: Final = 20
URGENT_PER_HOUR: Final = 5

# An urgent announcement repeats at most this many times, this far apart.
MAX_REPEAT_TIMES: Final = 10
MIN_REPEAT_INTERVAL: Final = 5
MAX_REPEAT_INTERVAL: Final = 120

# Following an announcement that is still sending: how often to read it, how
# long past its last repeat to keep reading (the platform fails a message that
# is still sending a minute and a half after its last repeat), and the longest
# a service call with wait set holds its caller.
FOLLOW_INTERVAL: Final = 5.0
FOLLOW_GRACE: Final = 100.0
MAX_WAIT: Final = 300.0

# The status that says an announcement is still repeating.
STATUS_SENDING: Final = "sending"
TERMINAL_STATUSES: Final = frozenset({"completed", "partial", "failed", "cancelled"})

# How long a list of speakers is trusted when a service resolves a name.
SPEAKERS_TTL: Final = 60.0

# Intercom: receiving (Home Assistant as a speaker). The hub says an
# announcement with an ordinary speak message whose dialog names it.
SPEAK_MESSAGE_TYPE: Final = "speak"
INTERCOM_DIALOG: Final = "intercom.announce"

# At most this many new announcements are played a minute, and one announcement
# is played at most as often as the platform lets it repeat (once when normal).
RECEIVE_PER_MINUTE: Final = 6
# Announcements remembered so a repeat of one is told from a new one.
RECEIVE_REMEMBERED: Final = 64
# Plays running at once, and the longest one may take.
RECEIVE_MAX_IN_FLIGHT: Final = 4
PLAY_TIMEOUT: Final = 60.0
