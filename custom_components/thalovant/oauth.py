"""Link account: Home Assistant's own OAuth 2 flow with PKCE, against Thalovant.

The person approves on the Thalovant dashboard, and My Home Assistant brings
the browser back to the Home Assistant it is set up for. Only the one that
started the flow can use the code: the state is signed with its own secret,
and the code is worth nothing without the PKCE verifier, which that Home
Assistant sends only to Thalovant's token endpoint, never through the
browser. That does not make approving somebody else's request safe, so
Thalovant also accepts the exchange only from the network the approval came
from: a link sent to someone on another computer or network gives them
nothing.

What comes back is the same setup token a device login gives, for the same
registered app: the config flow goes on with it exactly as it does after a
device login. There is no refresh token.
"""

from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from typing import Any, override

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    MY_AUTH_CALLBACK_PATH,
    LocalOAuth2ImplementationWithPkce,
)

from .api import ThalovantApiError, ThalovantConnectionError, ThalovantError, Tokens
from .const import (
    DOMAIN,
    LINK_AUTHORIZE_URL,
    LINK_CLIENT_ID,
    LINK_DEVICE_NAME_MAX,
    LINK_TOKEN_URL,
    LOGIN_SCOPES,
)


class LinkRejectedError(ThalovantError):
    """Thalovant refused the code, with the problem's detail and code if given.

    The API answers 400 with detail invalid_grant for every refused code.
    One approved from another network than the exchange's also carries code
    exchange_network_mismatch (EXCHANGE_NETWORK_MISMATCH); without a code,
    the code was older than 60 seconds, already used, or not this flow's,
    or the API predates that code. Linking again, which makes a new code and
    a new verifier, is the way out.
    """


class ThalovantOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    """Thalovant's consent page and native token endpoint, for the public app.

    One per flow, so each flow has a verifier of its own. The token request
    is a JSON body, not the form Home Assistant's own implementation posts.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        device_name: str,
        scopes: Sequence[str] = LOGIN_SCOPES,
    ) -> None:
        """Prepare a link for this installation, named as the consent page shows it.

        scopes is what the consent page asks for: LOGIN_SCOPES, and Intercom's
        when announcements are on.
        """
        super().__init__(
            hass, DOMAIN, LINK_CLIENT_ID, LINK_AUTHORIZE_URL, LINK_TOKEN_URL
        )
        self._device_name = device_name[:LINK_DEVICE_NAME_MAX]
        self._scopes = tuple(scopes)

    @property
    @override
    def name(self) -> str:
        """Name of the implementation."""
        return "Thalovant"

    @property
    def through_my_home_assistant(self) -> bool:
        """Whether the redirect Home Assistant computes is My Home Assistant's.

        It is the only redirect Thalovant answers for this app. Without My
        Home Assistant the redirect is this installation's own address (or
        there is none to compute), and the dashboard would refuse it.
        """
        try:
            return self.redirect_uri == MY_AUTH_CALLBACK_PATH
        except RuntimeError:
            # No My Home Assistant, and no frontend request to read a URL from.
            return False

    @property
    @override
    def extra_authorize_data(self) -> dict[str, Any]:
        """The PKCE challenge, the scopes, and how the consent page names us."""
        return {
            **super().extra_authorize_data,
            "scope": " ".join(self._scopes),
            "device_name": self._device_name,
        }

    @override
    async def async_resolve_external_data(self, external_data: Any) -> dict[str, Any]:
        """Trade the code for the token answer, as a JSON body of four fields.

        Raises LinkRejectedError when Thalovant refuses the code, and
        ThalovantConnectionError when it cannot be reached or asks to wait.
        No message carries the code, the verifier or the token.
        """
        body = {
            "code": external_data["code"],
            "code_verifier": self.code_verifier,
            "client_id": self.client_id,
            # The redirect the authorize URL carried, signed into the state.
            "redirect_uri": external_data["state"]["redirect_uri"],
        }
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(self.token_url, json=body) as response:
                status = response.status
                if status == 429 or status >= 500:
                    raise ThalovantConnectionError(
                        f"Thalovant answered the link with HTTP {status}",
                        status=status,
                    )
                if status >= 400:
                    raise LinkRejectedError(
                        f"Thalovant refused the link with HTTP {status}",
                        status=status,
                        **await _problem(response),
                    )
                answer = await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise ThalovantConnectionError(
                "Could not reach Thalovant to link the account"
            ) from err
        except ValueError as err:
            raise ThalovantApiError(
                "Thalovant's answer to the link is not JSON"
            ) from err
        if not isinstance(answer, Mapping):
            raise ThalovantApiError("Thalovant's answer to the link is not an object")
        return dict(answer)

    @override
    async def _async_refresh_token(self, token: dict[str, Any]) -> dict[str, Any]:
        """There is no refresh token: the setup token lives a year."""
        raise ThalovantApiError(
            "A Thalovant link has no refresh token; link the account again"
        )


async def _problem(response: aiohttp.ClientResponse) -> dict[str, str | None]:
    """A refusal's Problem+JSON detail and code, each only when it is a string."""
    try:
        body = await response.json(content_type=None)
    except ValueError:
        body = None
    if not isinstance(body, Mapping):
        body = {}
    return {
        key: value if isinstance(value := body.get(key), str) else None
        for key in ("detail", "code")
    }


def tokens_from_answer(answer: Mapping[str, Any]) -> Tokens:
    """Read the token answer the way the SDK reads a device login's.

    The same fields, the same leniency: scopes that are not strings are left
    out, an unreadable expiry or token id is None. Only a missing access
    token is an error.
    """
    access_token = answer.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ThalovantApiError("Thalovant's answer to the link has no access token")
    raw_scopes = answer.get("scopes")
    scopes = (
        tuple(scope for scope in raw_scopes if isinstance(scope, str))
        if isinstance(raw_scopes, list)
        else ()
    )
    expires = answer.get("expires_at")
    expires_at: datetime | None = None
    if isinstance(expires, str) and expires:
        with suppress(ValueError):
            expires_at = datetime.fromisoformat(expires)
    token_id = answer.get("token_id")
    return Tokens(
        access_token=access_token,
        expires_at=expires_at,
        scopes=scopes,
        token_id=token_id if isinstance(token_id, str) and token_id else None,
    )
