"""Config flow for the Thalovant integration."""

import asyncio
from collections.abc import Mapping
from contextlib import suppress
import logging
from typing import TYPE_CHECKING, Any, Final, override

import probatio

from homeassistant.components import conversation
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir, translation
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2FlowHandler
from homeassistant.helpers.selector import (
    AreaSelector,
    AreaSelectorConfig,
    BooleanSelector,
    ConversationAgentSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .api import (
    Account,
    ConnectionCredentials,
    DeviceLogin,
    DeviceLoginDenied,
    DeviceLoginExpired,
    DeviceLoginPending,
    Hub,
    ThalovantAdmissionTimeoutError,
    ThalovantAlreadyLinkedError,
    ThalovantApi,
    ThalovantApiError,
    ThalovantAuth,
    ThalovantAuthError,
    ThalovantConnectionError,
    ThalovantError,
    ThalovantPlanError,
    ThalovantUnsupportedError,
    Tokens,
)
from .const import (
    ADMISSION_TIMEOUT,
    CONF_ACCOUNT_ID,
    CONF_AGENT_ID,
    CONF_ALLOW_ANNOUNCEMENTS,
    CONF_ALLOW_RECEIVE,
    CONF_ALLOW_URGENT,
    CONF_CREDENTIALS,
    CONF_HOME_CLIENT_ID,
    CONF_HUB_ID,
    CONF_HUB_NAME,
    CONF_INTERCOM_CONSENT,
    CONF_LINKED_AT,
    CONF_SELF_HOSTED,
    CONF_SPEAKER_AREAS,
    CONF_SPEAKER_PLAYERS,
    CONF_TOKENS,
    CONF_TTS_ENTITY,
    CONF_VOICE_CLIENT_ID,
    CONNECTION_KIND,
    DOMAIN,
    EXCHANGE_NETWORK_MISMATCH,
    LINK_TOKEN_TIMEOUT,
    LOGGER,
    LOGIN_SCOPES,
)
from .handler import agent_issue_id
from .intercom import scopes_for_options
from .oauth import LinkRejectedError, ThalovantOAuth2Implementation, tokens_from_answer
from .self_hosted import (
    connection_client_ids,
    connection_secret,
    credentials_for,
    normalize_endpoint,
)

# Never poll faster than this, whatever the server says.
MIN_POLL_INTERVAL: Final = 1

# How much longer than the library's own admission timeout the flow waits
# before giving up on it.
ADMISSION_GRACE: Final = 15

# The step-by-step guide, linked from the first step.
GUIDE_URL: Final = "https://docs.thalovant.com/manage/home-assistant/"

# The picker's label for a hub that cannot link, when no translation has one.
NOT_READY_LABEL: Final = "{hub} (can't link Home Assistant yet)"

_CONF_ENDPOINT: Final = "endpoint"
_CONF_ACCESS_KEY: Final = "access_key"
_CONF_PASSWORD: Final = "password"

# How the first step signs in: Home Assistant's own OAuth 2 flow through My
# Home Assistant (the default), or a device login with a one-time code.
_CONF_LINK_METHOD: Final = "link_method"
LINK_ACCOUNT: Final = "link_account"
LINK_CODE: Final = "code"


class ThalovantConfigFlow(AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Link a Thalovant hub: sign in, pick a hub, create its connection.

    Signing in is Link account by default: Home Assistant's OAuth 2 flow
    with PKCE, whose approval comes back through My Home Assistant. Link with
    a code instead is the device login. Thalovant accepts either only when it
    is approved from this Home Assistant's network. Both give the same setup
    token, and the flow goes on the same way after it.
    """

    DOMAIN = DOMAIN
    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        super().__init__()
        self._method: str = LINK_ACCOUNT
        # What the sign-in asks for: LOGIN_SCOPES, and Intercom's for any entry
        # that has announcements on (so signing in again never drops them).
        self._scopes: tuple[str, ...] = LOGIN_SCOPES
        # The whole option set to store once the person has approved the extra
        # permission, when this reauth was started by the options flow.
        self._consent: dict[str, Any] | None = None
        self._login: DeviceLogin | None = None
        self._login_task: asyncio.Task[Tokens] | None = None
        self._tokens: Tokens | None = None
        self._account: Account | None = None
        self._hubs: dict[str, Hub] = {}
        self._hub: Hub | None = None
        self._credentials: ConnectionCredentials | None = None
        self._admission_task: asyncio.Task[None] | None = None
        self._reusing_tokens = False
        # A token this flow minted and no entry holds yet: revoked if the flow
        # ends without storing it, since a Free plan allows one API token.
        self._minted: Tokens | None = None
        self._errors: dict[str, str] = {}
        # Set once Home Assistant has removed the flow: a step still running
        # then cleans up what it gets instead of keeping it.
        self._removed = False
        # "{hub} (can't link yet)", in Home Assistant's language.
        self._not_ready_label = NOT_READY_LABEL

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ThalovantOptionsFlow()

    @property
    @override
    def logger(self) -> logging.Logger:
        """The integration's logger, for Home Assistant's OAuth 2 steps."""
        return LOGGER

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain the sign-in, then start it the way the user chose."""
        if user_input is None:
            return self._async_show_start_form()
        if user_input.get(CONF_SELF_HOSTED) is True:
            return await self.async_step_self_hosted()
        self._method = user_input.get(_CONF_LINK_METHOD, LINK_ACCOUNT)
        return await self._async_start_login()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Renew the link when the hub rejects its credentials.

        The stored API token is tried first; a device login only follows when
        the control plane rejects it too.
        """
        if entry_data.get(CONF_SELF_HOSTED) is True:
            return await self.async_step_self_hosted()
        if (consent := entry_data.get(CONF_INTERCOM_CONSENT)) is not None:
            # The stored token lacks the permission being asked for, so it is
            # not tried: only a new approval can carry it.
            self._consent = dict(consent)
            self._tokens = None
            self._reusing_tokens = False
            return await self.async_step_intercom_consent()
        try:
            self._tokens = Tokens.from_dict(entry_data[CONF_TOKENS])
        except KeyError, TypeError, ValueError:
            self._tokens = None
        self._reusing_tokens = self._tokens is not None
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask before signing in again, the way the user chooses."""
        if user_input is None:
            return self._async_show_start_form()
        self._method = user_input.get(_CONF_LINK_METHOD, LINK_ACCOUNT)
        return await self._async_start_login()

    async def async_step_intercom_consent(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask before signing in for the extra Intercom permission.

        Nothing has changed yet: the options that asked for it are stored only
        once Thalovant has granted it, and stay as they were otherwise.
        """
        if user_input is None:
            return self._async_show_start_form()
        self._method = user_input.get(_CONF_LINK_METHOD, LINK_ACCOUNT)
        return await self._async_start_login()

    async def async_step_no_my_home_assistant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Say why Link account cannot work here, and offer a code instead."""
        if user_input is None:
            return self.async_show_form(step_id="no_my_home_assistant")
        self._method = LINK_CODE
        return await self._async_start_login()

    @override
    async def async_step_creation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Trade the approved code for the setup token, then go on as after a code.

        Replaces Home Assistant's own step, which stores an OAuth token in a
        new entry: this token is the same setup token a device login gives,
        and the flow still has a hub to pick and a connection to make.
        """
        # The code is single-use; nothing keeps it past this step.
        external_data, self.external_data = self.external_data, None
        error: str
        try:
            async with asyncio.timeout(LINK_TOKEN_TIMEOUT):
                answer = await self.flow_impl.async_resolve_external_data(external_data)
            tokens = tokens_from_answer(answer)
        except LinkRejectedError as err:
            LOGGER.warning(
                "Thalovant did not accept the approval (HTTP %s, %s, %s)",
                err.status,
                err.detail,
                err.code,
            )
            # Only the API's own code says "another network". Any other 400
            # (detail invalid_grant: an expired or used code, or an API that
            # predates the code) is the generic refusal. Another status is
            # not one the API sends for a code, so it is not explained as one.
            if err.code == EXCHANGE_NETWORK_MISMATCH:
                error = "link_wrong_network"
            elif err.status == 400:
                error = "link_failed"
            else:
                error = "unknown"
        except ThalovantConnectionError, TimeoutError:
            error = "cannot_connect"
        except ThalovantApiError as err:
            LOGGER.warning("Could not read Thalovant's answer to the link: %s", err)
            error = "unknown"
        except Exception:
            LOGGER.exception("Unexpected error while linking the account")
            error = "unknown"
        else:
            if self._removed:
                # Closed while Thalovant answered: async_remove has run, and
                # nothing will hold this token, so it is revoked now.
                self.hass.async_create_background_task(
                    self._async_revoke(tokens), name=f"{DOMAIN} revoke unused link"
                )
                return self.async_abort(reason="link_closed")
            self._tokens = self._minted = tokens
            return await self.async_step_account()
        self._errors = {"base": error}
        return self._async_show_start_form()

    @override
    async def async_step_authorize_rejected(
        self, data: None = None
    ) -> ConfigFlowResult:
        """The browser came back without a code: declined, or refused."""
        external_data, self.external_data = self.external_data, None
        reason = external_data["error"]
        if reason == "access_denied":
            self._errors = {"base": "login_denied"}
        else:
            # Not a refused code, so not link_failed's "expired or used".
            LOGGER.warning("Thalovant did not link the account: %s", reason)
            self._errors = {"base": "unknown"}
        return self._async_show_start_form()

    async def async_step_self_hosted(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pair operator-issued credentials for a private Christmas hub."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                endpoint = normalize_endpoint(user_input.get(_CONF_ENDPOINT))
                home_id, voice_id = connection_client_ids(user_input)
                credentials = credentials_for(
                    endpoint,
                    home_id,
                    connection_secret(user_input.get(_CONF_ACCESS_KEY)),
                    connection_secret(user_input.get(_CONF_PASSWORD)),
                )
            except ValueError:
                errors["base"] = "invalid_private_link"
            else:
                await self.async_set_unique_id(credentials.hub_id)
                data = {
                    CONF_HUB_ID: credentials.hub_id,
                    CONF_HUB_NAME: credentials.name,
                    CONF_CREDENTIALS: credentials.to_dict(),
                    CONF_SELF_HOSTED: True,
                    CONF_HOME_CLIENT_ID: home_id,
                    CONF_VOICE_CLIENT_ID: voice_id,
                }
                if self.source == SOURCE_REAUTH:
                    entry = self._get_reauth_entry()
                    self._abort_if_unique_id_mismatch(reason="different_private_hub")
                    if entry.data.get(CONF_VOICE_CLIENT_ID) != voice_id:
                        return self.async_abort(reason="different_private_hub")
                    return self.async_update_reload_and_abort(entry, data=data)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=credentials.name, data=data)

        return self.async_show_form(
            step_id="self_hosted",
            data_schema=_schema(
                {
                    probatio.Required(_CONF_ENDPOINT): TextSelector(),
                    probatio.Required(CONF_HOME_CLIENT_ID): TextSelector(),
                    probatio.Required(CONF_VOICE_CLIENT_ID): TextSelector(),
                    probatio.Required(_CONF_ACCESS_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    probatio.Required(_CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the code and wait for the user to approve it."""
        if TYPE_CHECKING:
            assert self._login is not None

        if self._login_task is None:
            self._login_task = self.hass.async_create_task(
                self._async_wait_for_login(self._login), eager_start=False
            )
        if not self._login_task.done():
            return self.async_show_progress(
                step_id="login",
                progress_action="wait_for_login",
                description_placeholders={
                    "url": self._login.verification_uri_complete
                    or self._login.verification_uri,
                    "code": self._login.user_code,
                },
                progress_task=self._login_task,
            )

        task, self._login_task = self._login_task, None
        try:
            self._tokens = self._minted = task.result()
        except DeviceLoginExpired:
            self._errors = {"base": "login_expired"}
        except DeviceLoginDenied:
            self._errors = {"base": "login_denied"}
        except ThalovantConnectionError:
            self._errors = {"base": "cannot_connect"}
        except Exception:
            LOGGER.exception("Unexpected error while waiting for the sign-in")
            self._errors = {"base": "unknown"}
        if self._errors:
            return self.async_show_progress_done(next_step_id=self._start_step_id)
        return self.async_show_progress_done(next_step_id="account")

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Read the signed-in account and the hubs it may link."""
        if TYPE_CHECKING:
            assert self._tokens is not None

        if self._consent is not None:
            return await self._async_finish_consent()

        api = self._api
        try:
            self._account = await api.get_account()
            hubs = await api.list_hubs()
        except ThalovantAuthError:
            self._tokens = self._minted = None
            if self._reusing_tokens:
                # The stored token is gone too: sign in for a new one.
                self._reusing_tokens = False
                return await self._async_start_login()
            self._errors = {"base": "invalid_auth"}
        except ThalovantConnectionError:
            self._errors = {"base": "cannot_connect"}
        except Exception:
            LOGGER.exception("Unexpected error while reading the account")
            self._errors = {"base": "unknown"}
        if self._errors:
            return self._async_show_start_form()
        if TYPE_CHECKING:
            assert self._account is not None
        if self._minted is not None:
            self._async_share_token(self._account.id, self._minted)

        self._hubs = {hub.id: hub for hub in hubs}
        if any(hub.can_link is False for hub in hubs):
            self._not_ready_label = await self._async_not_ready_label()

        if self.source == SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            await self.async_set_unique_id(
                f"{self._account.id}:{entry.data[CONF_HUB_ID]}"
            )
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            if (hub := self._hubs.get(entry.data[CONF_HUB_ID])) is None:
                return self.async_abort(reason="hub_not_found")
            return await self._async_link_hub(hub)

        if not self._hubs:
            return self.async_abort(reason="no_hubs")
        linked = {
            entry.unique_id
            for entry in self._async_current_entries(include_ignore=False)
        }
        if all(f"{self._account.id}:{hub_id}" in linked for hub_id in self._hubs):
            return self.async_abort(reason="all_hubs_linked")
        return await self.async_step_hub()

    async def _async_finish_consent(self) -> ConfigFlowResult:
        """Store the approved token and the options that asked for it.

        The new token replaces the account's old one for every entry (as any
        sign-in does). The options are stored only when the token carries every
        scope they need: a plan without Intercom is not granted it, and then
        nothing is turned on.
        """
        if TYPE_CHECKING:
            assert self._tokens is not None
            assert self._consent is not None

        try:
            self._account = await self._api.get_account()
        except ThalovantAuthError:
            self._tokens = self._minted = None
            self._errors = {"base": "invalid_auth"}
        except ThalovantConnectionError:
            self._errors = {"base": "cannot_connect"}
        except Exception:
            LOGGER.exception("Unexpected error while reading the account")
            self._errors = {"base": "unknown"}
        if self._errors:
            return self._async_show_start_form()
        if TYPE_CHECKING:
            assert self._account is not None

        entry = self._get_reauth_entry()
        await self.async_set_unique_id(f"{self._account.id}:{entry.data[CONF_HUB_ID]}")
        self._abort_if_unique_id_mismatch(reason="wrong_account")
        if TYPE_CHECKING:
            assert self._tokens is not None
        tokens = self._tokens
        self._async_share_token(self._account.id, tokens)
        if not set(scopes_for_options(self._consent)) <= set(tokens.scopes):
            return self.async_abort(reason="consent_scopes_missing")
        self.hass.config_entries.async_update_entry(entry, options=self._consent)
        return self.async_abort(reason="consent_successful")

    async def async_step_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the hub whose devices may reach this Home Assistant."""
        if TYPE_CHECKING:
            assert self._account is not None

        if user_input is None:
            return self._async_show_hub_form()

        hub = self._hubs[user_input[CONF_HUB_ID]]
        if hub.can_link is False:
            # The API says it cannot route to Home Assistant: making a
            # connection there would only leave one to clean up.
            self._errors = {"base": "hub_cannot_link"}
            return self._async_show_hub_form()
        await self.async_set_unique_id(f"{self._account.id}:{hub.id}")
        self._abort_if_unique_id_configured()
        return await self._async_link_hub(hub)

    async def async_step_admission(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait while the hub admits the new connection (about 90 seconds)."""
        if TYPE_CHECKING:
            assert self._credentials is not None
            assert self._hub is not None

        if self._admission_task is None:
            # Not eager: the step always shows its progress before moving on.
            self._admission_task = self.hass.async_create_task(
                self._async_wait_for_admission(self._credentials), eager_start=False
            )
        if not self._admission_task.done():
            return self.async_show_progress(
                step_id="admission",
                progress_action="wait_for_admission",
                description_placeholders={"hub": self._hub.name},
                progress_task=self._admission_task,
            )

        task, self._admission_task = self._admission_task, None
        errors: dict[str, str] = {}
        try:
            task.result()
        except ThalovantAuthError:
            errors["base"] = "invalid_auth"
        except ThalovantAdmissionTimeoutError, TimeoutError:
            errors["base"] = "admission_timeout"
        except ThalovantConnectionError:
            errors["base"] = "cannot_connect"
        except ThalovantApiError as err:
            LOGGER.warning("The hub did not admit the connection: %s", err)
            errors["base"] = "admission_failed"
        except Exception:
            LOGGER.exception("Unexpected error while the hub admitted the connection")
            errors["base"] = "unknown"
        if not errors:
            return self.async_show_progress_done(next_step_id="finish")

        # Left behind, the half-made connection would count against the plan
        # and make the next attempt a duplicate.
        credentials, self._credentials = self._credentials, None
        await self._async_discard_connection(credentials)
        if errors["base"] == "invalid_auth":
            self._tokens = self._minted = None
        self._errors = errors
        if self._tokens is None or self.source == SOURCE_REAUTH:
            return self.async_show_progress_done(next_step_id=self._start_step_id)
        return self.async_show_progress_done(next_step_id="hub")

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Store the admitted connection."""
        if TYPE_CHECKING:
            assert self._account is not None
            assert self._credentials is not None
            assert self._hub is not None
            assert self._tokens is not None

        data = {
            CONF_ACCOUNT_ID: self._account.id,
            CONF_HUB_ID: self._hub.id,
            CONF_HUB_NAME: self._hub.name,
            CONF_TOKENS: self._tokens.to_dict(),
            CONF_CREDENTIALS: self._credentials.to_dict(),
            CONF_LINKED_AT: dt_util.utcnow().isoformat(),
        }
        # From here the entry owns the connection and the token.
        self._credentials = self._minted = None
        if self.source == SOURCE_REAUTH:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )
        return self.async_create_entry(title=self._hub.name, data=data)

    @callback
    @override
    def async_remove(self) -> None:
        """Clean up what the flow made and never stored: connection, then token."""
        self._removed = True
        credentials, self._credentials = self._credentials, None
        minted, self._minted = self._minted, None
        if credentials is not None or minted is not None:
            self.hass.async_create_background_task(
                self._async_clean_up(credentials, minted),
                name=f"{DOMAIN} clean up unused sign-in",
            )

    async def _async_clean_up(
        self, credentials: ConnectionCredentials | None, minted: Tokens | None
    ) -> None:
        """Delete an unused connection, then revoke an unused token."""
        if credentials is not None:
            await self._async_discard_connection(credentials)
        if minted is not None:
            await self._async_revoke(minted)

    async def _async_revoke(self, tokens: Tokens) -> None:
        """Revoke an API token nothing uses any more, best effort."""
        try:
            await ThalovantApi(
                async_get_clientsession(self.hass), tokens
            ).revoke_token()
        except Exception as err:  # noqa: BLE001 - best effort, and said so
            LOGGER.warning(
                "Could not revoke the unused Thalovant API token (%s); remove it "
                "from the Thalovant dashboard",
                type(err).__name__,
            )

    @callback
    def _async_share_token(self, account_id: str, tokens: Tokens) -> None:
        """Hand a new token to every entry this account has already linked.

        Home Assistant signs in as a registered app, and approving the app
        again revokes the token its last approval gave: the one those entries
        hold. They need a live one to delete their connection when they are
        removed, and to try first at reauth. From here the entries hold the
        new token, so the flow no longer revokes it if it ends early. A token
        replaced here that is still alive (one from before the integration
        signed in as the app) is revoked, since nothing holds it any more.
        """
        stored = tokens.to_dict()
        replaced: dict[str, Tokens] = {}
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_ACCOUNT_ID) != account_id:
                continue
            self._minted = None
            with suppress(KeyError, TypeError, ValueError):
                old = Tokens.from_dict(entry.data[CONF_TOKENS])
                replaced[old.access_token] = old
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_TOKENS: stored}
            )
        for old in replaced.values():
            if old.access_token != tokens.access_token:
                self.hass.async_create_background_task(
                    self._async_revoke(old), name=f"{DOMAIN} revoke replaced token"
                )

    @property
    def _start_step_id(self) -> str:
        """The step a failed sign-in goes back to."""
        if self._consent is not None:
            return "intercom_consent"
        return "reauth_confirm" if self.source == SOURCE_REAUTH else "user"

    @callback
    def _async_show_start_form(self) -> ConfigFlowResult:
        """Show the step that starts a sign-in, with the last error if any.

        Link account is the default until the user chooses a code; after
        that, the method last used is.
        """
        errors, self._errors = self._errors, {}
        step_id = self._start_step_id
        fields: dict[Any, Any] = {
            probatio.Required(_CONF_LINK_METHOD, default=self._method): SelectSelector(
                SelectSelectorConfig(
                    options=[LINK_ACCOUNT, LINK_CODE],
                    translation_key=_CONF_LINK_METHOD,
                    mode=SelectSelectorMode.LIST,
                )
            )
        }
        if step_id == "user":
            fields[probatio.Optional(CONF_SELF_HOSTED, default=False)] = (
                BooleanSelector()
            )
        return self.async_show_form(
            step_id=step_id,
            data_schema=_schema(fields),
            errors=errors,
            description_placeholders=(
                {"guide_url": GUIDE_URL} if step_id == "user" else None
            ),
        )

    @callback
    def _async_show_hub_form(self) -> ConfigFlowResult:
        """Show the hub picker, with the last error if any."""
        if TYPE_CHECKING:
            assert self._account is not None

        errors, self._errors = self._errors, {}
        linked = {
            entry.unique_id
            for entry in self._async_current_entries(include_ignore=False)
        }
        # Hubs that can link first, then those the API says nothing about,
        # then the ones that cannot, marked as such. A selector cannot grey an
        # option out, so picking one of those explains itself instead.
        options = [
            SelectOptionDict(
                value=hub.id,
                label=self._not_ready_label.format(hub=hub.name)
                if hub.can_link is False
                else hub.name,
            )
            for hub in sorted(self._hubs.values(), key=_hub_order)
            if f"{self._account.id}:{hub.id}" not in linked
        ]
        return self.async_show_form(
            step_id="hub",
            data_schema=_schema(
                {
                    probatio.Required(CONF_HUB_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "account": self._account.display_name
                or self._account.email
                or self._account.id
            },
        )

    async def _async_start_login(self) -> ConfigFlowResult:
        """Sign in the way the user chose, unless a token is in hand.

        Each approval mints an API token, and a Free plan allows one, so a
        token that still works (a retry, or reauth with the stored token) is
        used instead of asking for another.
        """
        if self._tokens is not None:
            return await self.async_step_account()
        self._scopes = self._wanted_scopes()
        if self._method == LINK_ACCOUNT:
            return await self._async_start_link_account()

        auth = ThalovantAuth(async_get_clientsession(self.hass))
        try:
            self._login = await auth.start_device_login(
                client_name=self._client_name, scopes=self._scopes
            )
        except ThalovantConnectionError:
            self._errors = {"base": "cannot_connect"}
        except Exception:
            LOGGER.exception("Unexpected error while starting the sign-in")
            self._errors = {"base": "unknown"}
        if self._errors:
            return self._async_show_start_form()
        self._login_task = None
        return await self.async_step_login()

    async def _async_start_link_account(self) -> ConfigFlowResult:
        """Open Thalovant's consent page; the answer comes to async_step_auth.

        A new implementation, and with it a new PKCE verifier, for every
        attempt. Thalovant answers only My Home Assistant's redirect, so
        without it the user is offered a code instead.
        """
        implementation = ThalovantOAuth2Implementation(
            self.hass, device_name=self._client_name, scopes=self._scopes
        )
        if not implementation.through_my_home_assistant:
            return await self.async_step_no_my_home_assistant()
        self.async_register_implementation(self.hass, implementation)
        return await self.async_step_pick_implementation({"implementation": DOMAIN})

    async def _async_wait_for_login(self, login: DeviceLogin) -> Tokens:
        """Poll until the user approves, declines, or the code expires."""
        auth = ThalovantAuth(async_get_clientsession(self.hass))
        interval = max(login.interval, MIN_POLL_INTERVAL)
        deadline = self.hass.loop.time() + login.expires_in
        while True:
            await asyncio.sleep(interval)
            try:
                return await auth.poll_device_login(login)
            except DeviceLoginPending as pending:
                # slow_down: the SDK raises Pending with the longer interval.
                if pending.interval > 0:
                    interval = max(pending.interval, MIN_POLL_INTERVAL)
            if self.hass.loop.time() + interval > deadline:
                raise DeviceLoginExpired

    async def _async_wait_for_admission(
        self, credentials: ConnectionCredentials
    ) -> None:
        """Wait for the hub to admit the connection, with a deadline of our own."""
        async with asyncio.timeout(ADMISSION_TIMEOUT + ADMISSION_GRACE):
            await self._api.wait_for_admission(credentials, timeout=ADMISSION_TIMEOUT)

    async def _async_link_hub(self, hub: Hub) -> ConfigFlowResult:
        """Create this installation's connection on the hub, then wait for it."""
        self._hub = hub
        api = self._api
        if self.source == SOURCE_REAUTH:
            # The old connection goes first: a plan that allows one connection
            # would refuse the new one while it exists.
            old = self._get_reauth_entry().data[CONF_CREDENTIALS]["connection_id"]
            try:
                await api.delete_connection(old)
            except Exception as err:  # noqa: BLE001 - it may already be gone
                LOGGER.debug("Could not delete the old connection: %r", err)

        errors: dict[str, str] = {}
        try:
            self._credentials = await api.create_connection(
                hub.id, name=f"Home Assistant ({hub.name})", kind=CONNECTION_KIND
            )
        except ThalovantAuthError:
            self._tokens = self._minted = None
            self._errors = {"base": "invalid_auth"}
            return self._async_show_start_form()
        except ThalovantConnectionError:
            errors["base"] = "cannot_connect"
        except ThalovantError as err:
            LOGGER.warning("Thalovant refused the Home Assistant connection: %s", err)
            errors["base"] = _refusal_error(err)
        except Exception:
            LOGGER.exception("Unexpected error while creating the connection")
            errors["base"] = "unknown"
        if errors:
            self._errors = errors
            if self.source == SOURCE_REAUTH:
                return self._async_show_start_form()
            return self._async_show_hub_form()

        self._admission_task = None
        return await self.async_step_admission()

    async def _async_discard_connection(
        self, credentials: ConnectionCredentials
    ) -> None:
        """Delete a connection this flow created and will not store."""
        try:
            await self._api.delete_connection(credentials.connection_id)
        except Exception as err:  # noqa: BLE001 - best effort, and said so
            LOGGER.warning(
                "Could not delete the unused connection %s (%s); remove it from "
                "the Thalovant dashboard",
                credentials.name,
                type(err).__name__,
            )

    async def _async_not_ready_label(self) -> str:
        """The label for a hub that cannot link, in Home Assistant's language."""
        strings = await translation.async_get_translations(
            self.hass, self.hass.config.language, "common", {DOMAIN}
        )
        label = strings.get(f"component.{DOMAIN}.common.hub_not_ready", "")
        return label if "{hub}" in label else NOT_READY_LABEL

    def _wanted_scopes(self) -> tuple[str, ...]:
        """LOGIN_SCOPES, plus Intercom's for anything that has them turned on.

        A new token replaces the account's old one for every entry, so it must
        carry what each entry's options still need, and what this flow's
        consent asks for. With nothing turned on this is LOGIN_SCOPES.
        """
        wanted = dict.fromkeys(LOGIN_SCOPES)
        option_sets: list[Mapping[str, Any]] = [
            entry.options
            for entry in self._async_current_entries(include_ignore=False)
            if entry.data.get(CONF_SELF_HOSTED) is not True
        ]
        if self._consent is not None:
            option_sets.append(self._consent)
        for options in option_sets:
            wanted.update(dict.fromkeys(scopes_for_options(options)))
        return tuple(wanted)

    @property
    def _api(self) -> ThalovantApi:
        """The control plane, as the signed-in account."""
        if TYPE_CHECKING:
            assert self._tokens is not None
        return ThalovantApi(async_get_clientsession(self.hass), self._tokens)

    @property
    def _client_name(self) -> str:
        """How this installation is named on the sign-in page."""
        return f"Home Assistant ({self.hass.config.location_name})"


def _hub_order(hub: Hub) -> tuple[int, str]:
    """Sort linkable hubs first, unknown next, the ones that cannot last."""
    rank = {True: 0, None: 1, False: 2}[hub.can_link]
    return rank, hub.name.casefold()


def _schema(fields: dict[Any, Any]) -> Any:
    """Build a form schema.

    Home Assistant 2026.9 still types flow schemas as voluptuous.Schema;
    probatio is its drop-in replacement and the type core uses from 2026.10.
    """
    return probatio.Schema(fields)


def _refusal_error(err: ThalovantError) -> str:
    """Name the reason the control plane refused a connection."""
    if isinstance(err, ThalovantUnsupportedError):
        return "hub_cannot_link"
    if isinstance(err, ThalovantAlreadyLinkedError):
        return "already_linked"
    if isinstance(err, ThalovantPlanError):
        # 402: a Free plan links public hubs only. 403 plan_limit: no room left.
        return "public_hubs_only" if err.status == 402 else "plan_limit"
    return "connection_refused"


class ThalovantOptionsFlow(OptionsFlow):
    """Choose the conversation agent, and whether Intercom announces or plays.

    Everything about Intercom is off until it is turned on here. Turning
    announcements on asks Thalovant for the extra permission first, and stays
    off if it is refused.
    """

    def __init__(self) -> None:
        """Start with no options chosen."""
        self._options: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if self.config_entry.data.get(CONF_SELF_HOSTED) is True:
            return self.async_abort(reason="private_agent_fixed")
        options = self.config_entry.options
        errors: dict[str, str] = {}
        if user_input is not None:
            if (
                conversation.async_get_agent_info(self.hass, user_input[CONF_AGENT_ID])
                is None
            ):
                errors[CONF_AGENT_ID] = "agent_not_found"
            elif (
                user_input.get(CONF_ALLOW_URGENT) is True
                and user_input.get(CONF_ALLOW_ANNOUNCEMENTS) is not True
            ):
                errors[CONF_ALLOW_URGENT] = "urgent_needs_announcements"
            else:
                ir.async_delete_issue(
                    self.hass, DOMAIN, agent_issue_id(self.config_entry.entry_id)
                )
                # Only what is on is stored: an entry that never used Intercom
                # is stored exactly as it was before it existed.
                self._options = {CONF_AGENT_ID: user_input[CONF_AGENT_ID]} | {
                    key: True
                    for key in (
                        CONF_ALLOW_ANNOUNCEMENTS,
                        CONF_ALLOW_URGENT,
                        CONF_ALLOW_RECEIVE,
                    )
                    if user_input.get(key) is True
                }
                if self._options.get(CONF_ALLOW_RECEIVE) is True:
                    return await self.async_step_receive()
                return self._async_finish()

        current = options.get(CONF_AGENT_ID, conversation.HOME_ASSISTANT_AGENT)
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                {
                    probatio.Required(
                        CONF_AGENT_ID, default=current
                    ): ConversationAgentSelector(),
                    probatio.Optional(
                        CONF_ALLOW_ANNOUNCEMENTS,
                        default=options.get(CONF_ALLOW_ANNOUNCEMENTS) is True,
                    ): BooleanSelector(),
                    probatio.Optional(
                        CONF_ALLOW_URGENT,
                        default=options.get(CONF_ALLOW_URGENT) is True,
                    ): BooleanSelector(),
                    probatio.Optional(
                        CONF_ALLOW_RECEIVE,
                        default=options.get(CONF_ALLOW_RECEIVE) is True,
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_receive(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose where announcements from the hub are played."""
        options = self.config_entry.options
        errors: dict[str, str] = {}
        if user_input is not None:
            players = list(user_input.get(CONF_SPEAKER_PLAYERS, []))
            areas = list(user_input.get(CONF_SPEAKER_AREAS, []))
            if not players and not areas:
                errors["base"] = "receive_needs_players"
            else:
                self._options[CONF_SPEAKER_PLAYERS] = players
                self._options[CONF_SPEAKER_AREAS] = areas
                if tts_entity := user_input.get(CONF_TTS_ENTITY):
                    self._options[CONF_TTS_ENTITY] = tts_entity
                return self._async_finish()

        return self.async_show_form(
            step_id="receive",
            data_schema=_schema(
                {
                    probatio.Optional(
                        CONF_SPEAKER_PLAYERS,
                        default=options.get(CONF_SPEAKER_PLAYERS, []),
                    ): EntitySelector(
                        EntitySelectorConfig(domain="media_player", multiple=True)
                    ),
                    probatio.Optional(
                        CONF_SPEAKER_AREAS,
                        default=options.get(CONF_SPEAKER_AREAS, []),
                    ): AreaSelector(AreaSelectorConfig(multiple=True)),
                    probatio.Optional(
                        CONF_TTS_ENTITY,
                        description={"suggested_value": options.get(CONF_TTS_ENTITY)},
                    ): EntitySelector(EntitySelectorConfig(domain="tts")),
                }
            ),
            errors=errors,
        )

    @callback
    def _async_finish(self) -> ConfigFlowResult:
        """Store the options, or first ask for the permission they need.

        When the token lacks a scope the options need, nothing is stored: a
        re-consent flow (a reauth) carries the whole option set and stores it
        only once Thalovant has granted the permission.
        """
        entry = self.config_entry
        needed = set(scopes_for_options(self._options)) - set(LOGIN_SCOPES)
        try:
            granted = set(Tokens.from_dict(entry.data[CONF_TOKENS]).scopes)
        except KeyError, TypeError, ValueError:
            granted = set()
        if not needed - granted:
            return self.async_create_entry(data=self._options)
        if any(entry.async_get_active_flows(self.hass, {SOURCE_REAUTH})):
            return self.async_abort(reason="consent_pending")
        entry.async_start_reauth(self.hass, data={CONF_INTERCOM_CONSENT: self._options})
        return self.async_abort(reason="consent_required")
