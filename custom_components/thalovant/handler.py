"""Answer the hub's home requests through Home Assistant's conversation API."""

import asyncio
from collections.abc import Mapping
import html
import re
import time
from typing import Any

from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.generated.languages import LANGUAGES
from homeassistant.helpers import intent, issue_registry as ir, translation
from homeassistant.util import dt as dt_util, language as language_util

from .api import HubConnection, HubMessage
from .const import (
    CONF_AGENT_ID,
    CONVERSE_TIMEOUT,
    DOMAIN,
    LOGGER,
    MAX_CONCURRENT_REQUESTS,
    RESPONSE_MESSAGE_TYPE,
)
from .models import ThalovantConfigEntry

# Error codes this integration adds to the ones Assist reports.
ERROR_TIMEOUT = "timeout"
ERROR_AGENT_UNAVAILABLE = "agent_unavailable"
ERROR_UNKNOWN = intent.IntentResponseErrorCode.UNKNOWN.value

_SSML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")
_SUBTAG_SEPARATOR = re.compile(r"[-_]")


def agent_issue_id(entry_id: str) -> str:
    """The repair issue raised while an entry's conversation agent is missing."""
    return f"agent_unavailable_{entry_id}"


def canonical_language(tag: str) -> str:
    """Return a BCP 47 tag in its usual casing: en_us -> en-US, zh-hant -> zh-Hant."""
    subtags = [part for part in _SUBTAG_SEPARATOR.split(tag.strip()) if part]
    if not subtags:
        return ""
    canonical = [subtags[0].lower()]
    for subtag in subtags[1:]:
        if len(subtag) == 4 and subtag.isalpha():
            canonical.append(subtag.title())
        elif (len(subtag) == 2 and subtag.isalpha()) or (
            len(subtag) == 3 and subtag.isdigit()
        ):
            canonical.append(subtag.upper())
        else:
            canonical.append(subtag.lower())
    return "-".join(canonical)


@callback
def async_resolve_language(hass: HomeAssistant, lang: Any, agent_id: str) -> str:
    """Pick the language to hand the agent for a hub language tag.

    The hub sends tags like en-us. When the agent lists the languages it
    supports, the closest one wins (fr-FR -> fr); an agent that takes any
    language gets the canonical tag. No tag at all means Home Assistant's own
    language.
    """
    if not isinstance(lang, str) or not (tag := canonical_language(lang)):
        return hass.config.language
    try:
        supported = conversation.async_get_conversation_languages(hass, agent_id)
    except ValueError:
        return tag
    if supported == MATCH_ALL or not supported:
        return tag
    for candidate in supported:
        if candidate.casefold() == tag.casefold():
            return candidate
    if matches := language_util.matches(tag, supported, country=hass.config.country):
        return matches[0]
    return tag


def plain_speech(response: intent.IntentResponse) -> str:
    """Return the response's speech as plain text, never SSML."""
    plain = response.speech.get("plain", {}).get("speech")
    if isinstance(plain, str):
        return plain.strip()
    ssml = response.speech.get("ssml", {}).get("speech")
    if isinstance(ssml, str):
        text = html.unescape(_SSML_TAG.sub(" ", ssml))
        return _WHITESPACE.sub(" ", text).strip()
    return ""


async def async_fallback_speech(hass: HomeAssistant, lang: Any, error_code: str) -> str:
    """Say something for an error that came with no speech of its own.

    The hub speaks every reply, errors included, so an error needs a sentence.
    It comes from this integration's translations, in the language closest to
    the request's (Home Assistant's own language when there is none), and
    English when that language has no translation.
    """
    language = hass.config.language
    if isinstance(lang, str) and (tag := canonical_language(lang)):
        if matches := language_util.matches(
            tag, LANGUAGES, country=hass.config.country
        ):
            language = matches[0]
    strings = await translation.async_get_translations(
        hass, language, "common", {DOMAIN}
    )
    prefix = f"component.{DOMAIN}.common.reply_"
    return strings.get(f"{prefix}{error_code}") or strings.get(f"{prefix}unknown", "")


def error_response(
    request_id: Any, error_code: str, conversation_id: str | None = None
) -> dict[str, Any]:
    """Build an error answer; its speech is filled in before it is sent."""
    response: dict[str, Any] = {
        "request_id": request_id,
        "speech": "",
        "response_type": "error",
        "error_code": error_code,
        "continue_conversation": False,
    }
    if conversation_id:
        response["conversation_id"] = conversation_id
    return response


def result_to_response(
    request_id: Any, result: conversation.ConversationResult
) -> dict[str, Any]:
    """Map a conversation result to a thalovant.home.response payload."""
    intent_response = result.response
    response: dict[str, Any] = {
        "request_id": request_id,
        "speech": plain_speech(intent_response),
        "continue_conversation": bool(result.continue_conversation),
    }
    if intent_response.response_type is intent.IntentResponseType.ERROR:
        response["response_type"] = "error"
        response["error_code"] = (
            intent_response.error_code.value
            if intent_response.error_code is not None
            else ERROR_UNKNOWN
        )
    elif intent_response.response_type is intent.IntentResponseType.QUERY_ANSWER:
        response["response_type"] = "query_answer"
    else:
        # action_done, and the deprecated partial_action_done: something was done.
        response["response_type"] = "action_done"
    if result.conversation_id:
        response["conversation_id"] = result.conversation_id
    return response


class HomeRequestHandler:
    """Answers thalovant.home.request messages for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ThalovantConfigEntry,
        connection: HubConnection,
    ) -> None:
        """Initialize the handler."""
        self._hass = hass
        self._entry = entry
        self._connection = connection
        self._in_flight = 0

    @callback
    def async_handle_message(self, message: HubMessage) -> None:
        """Take a request off the connection's receive path.

        The answer runs as its own task, so a slow agent never holds up the
        connection, and unloading the entry cancels it.
        """
        self._entry.async_create_background_task(
            self._hass, self.async_answer(message), name=f"{DOMAIN} home request"
        )

    async def async_answer(self, message: HubMessage) -> None:
        """Answer one request. Never raises: every failure is an error answer."""
        started = time.monotonic()
        data: Mapping[str, Any] = (
            message.data if isinstance(message.data, Mapping) else {}
        )
        request_id = data.get("request_id")

        if self._in_flight >= MAX_CONCURRENT_REQUESTS:
            LOGGER.debug("Request %s refused: too many in flight", request_id)
            response = error_response(request_id, ERROR_UNKNOWN)
        else:
            self._in_flight += 1
            try:
                response = await self._async_converse(request_id, data)
            finally:
                self._in_flight -= 1

        if response["response_type"] == "error" and not response["speech"]:
            try:
                response["speech"] = await async_fallback_speech(
                    self._hass, data.get("lang"), response["error_code"]
                )
            except Exception as err:  # noqa: BLE001 - the answer still goes out
                LOGGER.debug("No fallback speech for request %s: %r", request_id, err)

        outcome = response.get("error_code") or response["response_type"]
        duration_ms = round((time.monotonic() - started) * 1000)
        self._entry.runtime_data.stats.record(outcome, dt_util.utcnow(), duration_ms)
        LOGGER.debug(
            "Request %s answered %s in %d ms", request_id, outcome, duration_ms
        )

        try:
            await self._connection.reply(message, RESPONSE_MESSAGE_TYPE, response)
        except Exception as err:  # noqa: BLE001 - the hub times out on its own
            LOGGER.debug("Could not send the answer to request %s: %r", request_id, err)

    async def _async_converse(
        self, request_id: Any, data: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Hand the utterance to the conversation agent and map what it says."""
        conversation_id = data.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            conversation_id = None

        utterance = data.get("utterance")
        if not isinstance(utterance, str) or not utterance.strip():
            LOGGER.debug("Request %s carries no utterance", request_id)
            return error_response(request_id, ERROR_UNKNOWN, conversation_id)

        agent_id: str = self._entry.options.get(
            CONF_AGENT_ID, conversation.HOME_ASSISTANT_AGENT
        )
        if conversation.async_get_agent_info(self._hass, agent_id) is None:
            LOGGER.debug("Request %s: agent %s is not available", request_id, agent_id)
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                agent_issue_id(self._entry.entry_id),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="agent_unavailable",
                translation_placeholders={"agent": agent_id, "hub": self._entry.title},
            )
            return error_response(request_id, ERROR_AGENT_UNAVAILABLE, conversation_id)
        ir.async_delete_issue(self._hass, DOMAIN, agent_issue_id(self._entry.entry_id))

        language = async_resolve_language(self._hass, data.get("lang"), agent_id)
        LOGGER.debug("Request %s: asking %s in %s", request_id, agent_id, language)
        try:
            async with asyncio.timeout(CONVERSE_TIMEOUT):
                result = await conversation.async_converse(
                    self._hass,
                    text=utterance,
                    conversation_id=conversation_id,
                    context=Context(),
                    language=language,
                    agent_id=agent_id,
                )
        except TimeoutError:
            LOGGER.debug(
                "Request %s: %s did not answer within %s s",
                request_id,
                agent_id,
                CONVERSE_TIMEOUT,
            )
            return error_response(request_id, ERROR_TIMEOUT, conversation_id)
        except Exception as err:  # noqa: BLE001 - an error answer, never a raise
            # The type only: an agent's message can quote what was said.
            LOGGER.warning(
                "Request %s: %s failed with %s",
                request_id,
                agent_id,
                type(err).__name__,
            )
            return error_response(request_id, ERROR_UNKNOWN, conversation_id)

        return result_to_response(request_id, result)
