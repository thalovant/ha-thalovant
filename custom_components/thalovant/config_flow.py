"""Config flow for the Thalovant integration."""

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any, Final, override

import probatio

from homeassistant.components import conversation
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir, translation
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    ConversationAgentSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
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
    CONF_CREDENTIALS,
    CONF_HUB_ID,
    CONF_HUB_NAME,
    CONF_LINKED_AT,
    CONF_TOKENS,
    CONNECTION_KIND,
    DOMAIN,
    LOGGER,
    LOGIN_SCOPES,
)
from .handler import agent_issue_id

# Never poll faster than this, whatever the server says.
MIN_POLL_INTERVAL: Final = 1

# How much longer than the library's own admission timeout the flow waits
# before giving up on it.
ADMISSION_GRACE: Final = 15

# The step-by-step guide, linked from the first step.
GUIDE_URL: Final = "https://docs.thalovant.com/manage/home-assistant/"

# The picker's label for a hub that cannot link, when no translation has one.
NOT_READY_LABEL: Final = "{hub} (can't link Home Assistant yet)"


class ThalovantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Link a Thalovant hub: device login, pick a hub, create its connection."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
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
        # "{hub} (can't link yet)", in Home Assistant's language.
        self._not_ready_label = NOT_READY_LABEL

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ThalovantOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain the sign-in, then start it."""
        if user_input is None:
            return self._async_show_start_form()
        return await self._async_start_login()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Renew the link when the hub rejects its credentials.

        The stored API token is tried first; a device login only follows when
        the control plane rejects it too.
        """
        try:
            self._tokens = Tokens.from_dict(entry_data[CONF_TOKENS])
        except KeyError, TypeError, ValueError:
            self._tokens = None
        self._reusing_tokens = self._tokens is not None
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask before signing in again."""
        if user_input is None:
            return self._async_show_start_form()
        return await self._async_start_login()

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
        return "reauth_confirm" if self.source == SOURCE_REAUTH else "user"

    @callback
    def _async_show_start_form(self) -> ConfigFlowResult:
        """Show the step that starts a sign-in, with the last error if any."""
        errors, self._errors = self._errors, {}
        step_id = self._start_step_id
        return self.async_show_form(
            step_id=step_id,
            data_schema=_schema({}),
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
        """Ask the control plane for a device code, unless a token is in hand.

        Each approval mints an API token, and a Free plan allows one, so a
        token that still works (a retry, or reauth with the stored token) is
        used instead of asking for another.
        """
        if self._tokens is not None:
            return await self.async_step_account()

        auth = ThalovantAuth(async_get_clientsession(self.hass))
        try:
            self._login = await auth.start_device_login(
                client_name=self._client_name, scopes=LOGIN_SCOPES
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
    """Choose the conversation agent that answers the hub."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if (
                conversation.async_get_agent_info(self.hass, user_input[CONF_AGENT_ID])
                is None
            ):
                errors[CONF_AGENT_ID] = "agent_not_found"
            else:
                ir.async_delete_issue(
                    self.hass, DOMAIN, agent_issue_id(self.config_entry.entry_id)
                )
                return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_AGENT_ID, conversation.HOME_ASSISTANT_AGENT
        )
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                {
                    probatio.Required(
                        CONF_AGENT_ID, default=current
                    ): ConversationAgentSelector()
                }
            ),
            errors=errors,
        )
