"""Answer the hub's home requests through Home Assistant's conversation API."""

import asyncio
from collections.abc import Mapping
import re
import time
from typing import Any

from homeassistant.components import conversation
from homeassistant.const import MATCH_ALL
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.generated.languages import LANGUAGES
from homeassistant.helpers import (
    device_registry as dr,
    intent,
    issue_registry as ir,
    translation,
)
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.util import dt as dt_util, language as language_util

from .api import HubConnection, HubMessage, plain_speech
from .const import (
    CONF_AGENT_ID,
    CONF_HUB_ID,
    CONVERSE_TIMEOUT,
    DOMAIN,
    HUB_TIMEOUT,
    LOGGER,
    MANUFACTURER,
    MAX_CONCURRENT_REQUESTS,
    MAX_DEVICES_PER_HUB,
    REPLY_RESERVE,
    RESPONSE_MESSAGE_TYPE,
)
from .models import ThalovantConfigEntry

# Error codes this integration adds to the ones Assist reports.
ERROR_TIMEOUT = "timeout"
ERROR_AGENT_UNAVAILABLE = "agent_unavailable"
ERROR_FAILED_TO_HANDLE = intent.IntentResponseErrorCode.FAILED_TO_HANDLE.value
ERROR_UNKNOWN = intent.IntentResponseErrorCode.UNKNOWN.value

# The codes the hub knows; anything else is sent as unknown.
ERROR_CODES = frozenset(
    {
        intent.IntentResponseErrorCode.NO_INTENT_MATCH.value,
        intent.IntentResponseErrorCode.NO_VALID_TARGETS.value,
        ERROR_FAILED_TO_HANDLE,
        ERROR_UNKNOWN,
        ERROR_TIMEOUT,
        ERROR_AGENT_UNAVAILABLE,
    }
)

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


def speech_text(response: intent.IntentResponse) -> str:
    """Return the response's speech as plain text, never SSML.

    The plain speech when there is one, else the SSML, both put through the
    SDK's rules, so every Thalovant device receives the same kind of text.
    """
    plain = response.speech.get("plain", {}).get("speech")
    if not isinstance(plain, str):
        plain = response.speech.get("ssml", {}).get("speech")
    return plain_speech(plain if isinstance(plain, str) else "")


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
        "speech": speech_text(intent_response),
        "continue_conversation": bool(result.continue_conversation),
    }
    if intent_response.response_type is intent.IntentResponseType.ERROR:
        code = getattr(intent_response.error_code, "value", None)
        response["response_type"] = "error"
        response["error_code"] = code if code in ERROR_CODES else ERROR_UNKNOWN
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
        """Answer one request, within the hub's limit. Never raises.

        The hub gives up HUB_TIMEOUT seconds after it sent the request, so
        everything is counted from its arrival: Assist gets its share, the
        reply what is left. An answer with no time left is not sent at all,
        since the hub would take it for the next request's.
        """
        deadline = message.received_at + HUB_TIMEOUT

        def left() -> float:
            return deadline - time.monotonic()

        data: Mapping[str, Any] = (
            message.data if isinstance(message.data, Mapping) else {}
        )
        request_id = data.get("request_id")
        if not isinstance(request_id, str):
            request_id = ""

        if self._in_flight >= MAX_CONCURRENT_REQUESTS:
            LOGGER.debug("Request %s refused: too many in flight", request_id)
            response = error_response(request_id, ERROR_UNKNOWN)
        else:
            self._in_flight += 1
            try:
                response = await self._async_converse(
                    request_id, data, min(CONVERSE_TIMEOUT, left() - 2 * REPLY_RESERVE)
                )
            finally:
                self._in_flight -= 1

        if response["response_type"] == "error" and not response["speech"]:
            # Keep REPLY_RESERVE for the reply; with nothing left, the hub
            # speaks its own sentence for the code.
            try:
                async with asyncio.timeout(max(0.0, left() - REPLY_RESERVE)):
                    response["speech"] = await async_fallback_speech(
                        self._hass, data.get("lang"), response["error_code"]
                    )
            except Exception as err:  # noqa: BLE001 - the answer still goes out
                LOGGER.debug("No fallback speech for request %s: %r", request_id, err)

        outcome = response.get("error_code") or response["response_type"]
        duration_ms = round((time.monotonic() - message.received_at) * 1000)
        self._entry.runtime_data.stats.record(outcome, dt_util.utcnow(), duration_ms)

        if (remaining := left()) <= 0:
            LOGGER.debug(
                "Request %s: no time left to answer (%s); the hub has given up on it",
                request_id,
                outcome,
            )
            return
        LOGGER.debug(
            "Request %s answered %s in %d ms", request_id, outcome, duration_ms
        )
        try:
            async with asyncio.timeout(remaining):
                await self._connection.reply(message, RESPONSE_MESSAGE_TYPE, response)
        except TimeoutError:
            LOGGER.debug(
                "Request %s: the answer could not be sent before the hub gave up",
                request_id,
            )
        except Exception as err:  # noqa: BLE001 - the hub times out on its own
            LOGGER.debug("Could not send the answer to request %s: %r", request_id, err)

    @callback
    def _async_device_id(self, device: Any) -> str | None:
        """The registry id of the Thalovant device that spoke, made on first use.

        Assist takes the room from the device's area, so each speaker is a
        device of its own under the hub's, for the user to place in an area.
        The hub says which device it was from its own record of the sender,
        never from what the device announced. No id, or a full registry,
        means no room: the request is answered as it always was.
        """
        if not isinstance(device, Mapping):
            return None
        client_id = device.get("id")
        if not isinstance(client_id, str) or not (client_id := client_id.strip()):
            return None
        name = device.get("name")
        name = name.strip() if isinstance(name, str) else ""
        hub = (DOMAIN, self._entry.data[CONF_HUB_ID])
        identifier = (DOMAIN, f"{hub[1]}:{client_id}")
        registry = dr.async_get(self._hass)
        entry_id = self._entry.entry_id
        # Identifiers are unique within a config entry, so the lookups are
        # scoped to ours (the registry-wide lookup is deprecated).
        existing = registry.async_get_device_by_identifier(identifier, entry_id)
        if existing is None:
            known = sum(
                1
                for entry in dr.async_entries_for_config_entry(registry, entry_id)
                if entry.via_device_id is not None
            )
            if known >= MAX_DEVICES_PER_HUB:
                LOGGER.debug("Device limit reached; answering without a room")
                return None
        # The speaker hangs under the hub's service device. The registry
        # takes the hub's id rather than its identifier; without a hub
        # device there is nothing to hang it under, and the link is added
        # by a later request once the hub device exists.
        hub_device = registry.async_get_device_by_identifier(hub, entry_id)
        created = registry.async_get_or_create(
            config_entry_id=entry_id,
            identifiers={identifier},
            via_device_id=hub_device.id if hub_device is not None else UNDEFINED,
            manufacturer=MANUFACTURER,
            model="Device",
            name=name or f"Thalovant device {client_id[:8]}",
        )
        return created.id

    async def _async_converse(
        self, request_id: str, data: Mapping[str, Any], budget: float
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

        if budget <= 0:
            LOGGER.debug(
                "Request %s arrived with no time left for %s", request_id, agent_id
            )
            return error_response(request_id, ERROR_TIMEOUT, conversation_id)

        language = async_resolve_language(self._hass, data.get("lang"), agent_id)
        device_id = self._async_device_id(data.get("device"))
        LOGGER.debug("Request %s: asking %s in %s", request_id, agent_id, language)
        # Its own task, waited for with asyncio.wait rather than a timeout
        # around the await: an agent that ignores cancellation must not hold
        # the answer past the hub's limit. It is cancelled and left to finish.
        task = self._entry.async_create_background_task(
            self._hass,
            conversation.async_converse(
                self._hass,
                text=utterance,
                conversation_id=conversation_id,
                context=Context(),
                language=language,
                agent_id=agent_id,
                device_id=device_id,
            ),
            name=f"{DOMAIN} converse",
        )
        done, _ = await asyncio.wait({task}, timeout=budget)
        if task not in done:
            task.cancel()
            task.add_done_callback(_ignore_late)
            LOGGER.debug(
                "Request %s: %s did not answer within %.1f s",
                request_id,
                agent_id,
                budget,
            )
            return error_response(request_id, ERROR_TIMEOUT, conversation_id)
        try:
            return result_to_response(request_id, task.result())
        except Exception as err:  # noqa: BLE001 - an error answer, never a raise
            # The type only: an agent's message can quote what was said.
            LOGGER.warning(
                "Request %s: %s failed with %s",
                request_id,
                agent_id,
                type(err).__name__,
            )
            return error_response(request_id, ERROR_FAILED_TO_HANDLE, conversation_id)


def _ignore_late(task: asyncio.Task[Any]) -> None:
    """Retrieve what an agent that had timed out ended with, so nothing is logged as lost."""
    if not task.cancelled() and task.exception() is not None:
        LOGGER.debug("An agent that had timed out failed afterwards")
