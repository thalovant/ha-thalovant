"""Link account: Home Assistant's own OAuth 2 flow with PKCE, against Thalovant.

The person approves on the Thalovant dashboard, and the browser brings the
code back through My Home Assistant to the very Home Assistant that started
the flow: the state is signed with that Home Assistant's own secret, and the
code is worth nothing without the PKCE verifier, which never leaves it. That
is what a device code cannot promise, since a code can be passed on.

What comes back is the same setup token a device login gives, for the same
registered app: the config flow goes on with it exactly as it does after a
device login. There is no refresh token.
"""

from collections.abc import Mapping
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
    """Thalovant refused the code: used, expired (it lives 60 s), or not this flow's.

    The API answers every such failure 400 invalid_grant. Linking again,
    which makes a new code and a new verifier, is the way out.
    """


class ThalovantOAuth2Implementation(LocalOAuth2ImplementationWithPkce):
    """Thalovant's consent page and native token endpoint, for the public app.

    One per flow, so each flow has a verifier of its own. The token request
    is a JSON body, not the form Home Assistant's own implementation posts.
    """

    def __init__(self, hass: HomeAssistant, *, device_name: str) -> None:
        """Prepare a link for this installation, named as the consent page shows it."""
        super().__init__(
            hass, DOMAIN, LINK_CLIENT_ID, LINK_AUTHORIZE_URL, LINK_TOKEN_URL
        )
        self._device_name = device_name[:LINK_DEVICE_NAME_MAX]

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
            "scope": " ".join(LOGIN_SCOPES),
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
