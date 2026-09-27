"""Tests for answering the hub's home requests."""

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import Any, Literal, override
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.const import (
    CONF_AGENT_ID,
    DOMAIN,
    MAX_CONCURRENT_REQUESTS,
    REQUEST_MESSAGE_TYPE,
    RESPONSE_MESSAGE_TYPE,
)
from custom_components.thalovant.handler import (
    agent_issue_id,
    async_resolve_language,
    canonical_language,
    plain_speech,
)
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent, issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import FakeHubConnection

AGENT_OWNER = "fake_agent"
UTTERANCE = "turn off the kitchen light"

type Answer = Callable[
    [conversation.ConversationInput], Awaitable[conversation.ConversationResult]
]


class FakeAgent(conversation.AbstractConversationAgent):
    """A conversation agent that answers what the test tells it to."""

    def __init__(
        self,
        answer: Answer,
        languages: list[str] | Literal["*"] = MATCH_ALL,
    ) -> None:
        """Initialize the agent."""
        self.answer = answer
        self.languages = languages
        self.inputs: list[conversation.ConversationInput] = []

    @property
    @override
    def supported_languages(self) -> list[str] | Literal["*"]:
        return self.languages

    @override
    async def async_process(
        self, user_input: conversation.ConversationInput
    ) -> conversation.ConversationResult:
        self.inputs.append(user_input)
        return await self.answer(user_input)


def _result(
    response_type: intent.IntentResponseType,
    speech: str,
    *,
    error_code: intent.IntentResponseErrorCode | None = None,
    conversation_id: str | None = "01J-conversation",
    continue_conversation: bool = False,
    language: str = "en",
) -> conversation.ConversationResult:
    response = intent.IntentResponse(language=language)
    if error_code is not None:
        response.async_set_error(error_code, speech)
    else:
        response.response_type = response_type
        response.async_set_speech(speech)
    return conversation.ConversationResult(
        response=response,
        conversation_id=conversation_id,
        continue_conversation=continue_conversation,
    )


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> MockConfigEntry:
    """A set-up entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry


@pytest.fixture
def use_agent(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> Callable[[FakeAgent], FakeAgent]:
    """Register a fake agent and select it in the options."""

    def _use(agent: FakeAgent) -> FakeAgent:
        owner = MockConfigEntry(domain=AGENT_OWNER)
        owner.add_to_hass(hass)
        conversation.async_set_agent(hass, owner, agent)
        hass.config_entries.async_update_entry(
            loaded_entry, options={CONF_AGENT_ID: owner.entry_id}
        )
        return agent

    return _use


async def _ask(
    hass: HomeAssistant, connection: FakeHubConnection, data: dict[str, Any]
) -> dict[str, Any]:
    """Send one request and return the answer that went back."""
    connection.reply.reset_mock()
    message = await connection.emit(REQUEST_MESSAGE_TYPE, data)
    response = await connection.next_reply()
    connection.reply.assert_awaited_once()
    replied_to, msg_type, _ = connection.reply.await_args.args
    assert replied_to is message
    assert msg_type == RESPONSE_MESSAGE_TYPE
    return response


def _request(**overrides: Any) -> dict[str, Any]:
    return {"request_id": "req-1", "utterance": UTTERANCE, "lang": "en-US", **overrides}


async def test_action_done(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """A done action comes back with Assist's speech and conversation id."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(
            intent.IntentResponseType.ACTION_DONE, "Turned off the kitchen light."
        )

    agent = use_agent(FakeAgent(answer))
    response = await _ask(hass, mock_hub_connection, _request(conversation_id="c-9"))

    assert response == {
        "request_id": "req-1",
        "speech": "Turned off the kitchen light.",
        "response_type": "action_done",
        "continue_conversation": False,
        "conversation_id": "01J-conversation",
    }
    [user_input] = agent.inputs
    assert user_input.text == UTTERANCE
    assert user_input.language == "en-US"
    assert user_input.conversation_id == "c-9"
    assert user_input.context.user_id is None


async def test_query_answer_continues(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """A question's answer keeps continue_conversation."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(
            intent.IntentResponseType.QUERY_ANSWER,
            "It is 21 degrees. Anything else?",
            continue_conversation=True,
            conversation_id=None,
        )

    use_agent(FakeAgent(answer))
    response = await _ask(hass, mock_hub_connection, _request())
    assert response == {
        "request_id": "req-1",
        "speech": "It is 21 degrees. Anything else?",
        "response_type": "query_answer",
        "continue_conversation": True,
    }


@pytest.mark.parametrize(
    "error_code",
    [
        intent.IntentResponseErrorCode.NO_INTENT_MATCH,
        intent.IntentResponseErrorCode.NO_VALID_TARGETS,
        intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
    ],
)
async def test_assist_errors(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    error_code: intent.IntentResponseErrorCode,
) -> None:
    """Assist's own errors pass through with its speech."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(
            intent.IntentResponseType.ERROR,
            "Sorry, I couldn't do that.",
            error_code=error_code,
        )

    use_agent(FakeAgent(answer))
    response = await _ask(hass, mock_hub_connection, _request())
    assert response["response_type"] == "error"
    assert response["error_code"] == error_code.value
    assert response["speech"] == "Sorry, I couldn't do that."


@pytest.mark.parametrize(
    ("lang", "error_code", "speech"),
    [
        (
            "fr-fr",
            intent.IntentResponseErrorCode.NO_VALID_TARGETS,
            "Désolé, Home Assistant n'a pas trouvé cet appareil.",
        ),
        (
            "fr_CA",
            intent.IntentResponseErrorCode.NO_INTENT_MATCH,
            "Désolé, Home Assistant n'a pas compris.",
        ),
        (
            "en-GB",
            intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
            "Sorry, Home Assistant couldn't do that.",
        ),
        (
            "de-DE",
            intent.IntentResponseErrorCode.NO_INTENT_MATCH,
            "Sorry, Home Assistant didn't understand that.",
        ),
        (
            "tlh",
            intent.IntentResponseErrorCode.NO_INTENT_MATCH,
            "Sorry, Home Assistant didn't understand that.",
        ),
        (
            None,
            intent.IntentResponseErrorCode.NO_INTENT_MATCH,
            "Sorry, Home Assistant didn't understand that.",
        ),
    ],
)
async def test_silent_errors_get_a_sentence(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    lang: str | None,
    error_code: intent.IntentResponseErrorCode,
    speech: str,
) -> None:
    """The hub speaks every reply, so an error without speech gets one in the request's language."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ERROR, "", error_code=error_code)

    use_agent(FakeAgent(answer))
    response = await _ask(hass, mock_hub_connection, _request(lang=lang))
    assert response["error_code"] == error_code.value
    assert response["speech"] == speech


async def test_unknown_assist_code_falls_back(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """A code this integration has no sentence for uses the generic one."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        result = _result(
            intent.IntentResponseType.ERROR,
            "",
            error_code=intent.IntentResponseErrorCode.UNKNOWN,
        )
        result.response.error_code = MagicMock(value="brand_new_code")
        return result

    use_agent(FakeAgent(answer))
    response = await _ask(hass, mock_hub_connection, _request())
    assert response["error_code"] == "brand_new_code"
    assert response["speech"] == "Sorry, something went wrong in Home Assistant."


async def test_fallback_failure_still_answers(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """If even the translations fail, the error still goes out."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(
            intent.IntentResponseType.ERROR,
            "",
            error_code=intent.IntentResponseErrorCode.NO_INTENT_MATCH,
        )

    use_agent(FakeAgent(answer))
    with patch(
        "custom_components.thalovant.handler.translation.async_get_translations",
        side_effect=RuntimeError("broken"),
    ):
        response = await _ask(hass, mock_hub_connection, _request())
    assert response["error_code"] == "no_intent_match"
    assert response["speech"] == ""


async def test_error_without_code(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """An error response without a code is reported as unknown."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        result = _result(intent.IntentResponseType.ACTION_DONE, "Hmm.")
        result.response.response_type = intent.IntentResponseType.ERROR
        return result

    use_agent(FakeAgent(answer))
    response = await _ask(hass, mock_hub_connection, _request())
    assert response["response_type"] == "error"
    assert response["error_code"] == "unknown"


async def test_timeout(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """An agent that does not answer in time gets a timeout answer."""
    never = asyncio.Event()

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        await never.wait()
        raise AssertionError("unreachable")

    use_agent(FakeAgent(answer))
    with patch("custom_components.thalovant.handler.CONVERSE_TIMEOUT", 0.01):
        response = await _ask(
            hass, mock_hub_connection, _request(conversation_id="c-9")
        )
    assert response == {
        "request_id": "req-1",
        "speech": "Sorry, Home Assistant took too long to answer.",
        "response_type": "error",
        "error_code": "timeout",
        "continue_conversation": False,
        "conversation_id": "c-9",
    }


@pytest.mark.parametrize(
    ("exception", "speech"),
    [
        (
            RuntimeError("secret utterance echo"),
            "Sorry, something went wrong in Home Assistant.",
        ),
        (HomeAssistantError("It broke"), "It broke"),
    ],
)
async def test_agent_exceptions(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    caplog: pytest.LogCaptureFixture,
    exception: Exception,
    speech: str,
) -> None:
    """An agent that raises still gets an answer out, and never its message in logs."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        raise exception

    use_agent(FakeAgent(answer))
    response = await _ask(hass, mock_hub_connection, _request())
    assert response["response_type"] == "error"
    assert response["error_code"] == "unknown"
    assert response["speech"] == speech
    assert "secret utterance echo" not in caplog.text


async def test_agent_unavailable(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    issue_registry: ir.IssueRegistry,
) -> None:
    """A missing agent is answered as unavailable and raised as a repair issue."""
    hass.config_entries.async_update_entry(
        loaded_entry, options={CONF_AGENT_ID: "conversation.removed_agent"}
    )
    response = await _ask(hass, mock_hub_connection, _request())
    assert response["error_code"] == "agent_unavailable"
    assert response["speech"] == (
        "Sorry, the Home Assistant conversation agent isn't available right now."
    )
    issue = issue_registry.async_get_issue(
        DOMAIN, agent_issue_id(loaded_entry.entry_id)
    )
    assert issue is not None
    assert issue.translation_key == "agent_unavailable"
    assert issue.translation_placeholders == {
        "agent": "conversation.removed_agent",
        "hub": "Maison",
    }

    hass.config_entries.async_update_entry(loaded_entry, options={})
    await _ask(hass, mock_hub_connection, _request(utterance="xyzzy"))
    assert (
        issue_registry.async_get_issue(DOMAIN, agent_issue_id(loaded_entry.entry_id))
        is None
    )


@pytest.mark.parametrize(
    "data",
    [
        {"request_id": "req-1"},
        {"request_id": "req-1", "utterance": "   "},
        {"request_id": "req-1", "utterance": 42},
    ],
)
async def test_malformed_requests(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    data: dict[str, Any],
) -> None:
    """A request without an utterance is answered, not dropped."""
    response = await _ask(hass, mock_hub_connection, data)
    assert response["request_id"] == "req-1"
    assert response["error_code"] == "unknown"
    assert response["speech"] == "Sorry, something went wrong in Home Assistant."


async def test_payload_not_a_mapping(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """Even a payload that is not an object gets an error answer."""
    response = await _ask(hass, mock_hub_connection, ["not", "a", "dict"])  # type: ignore[arg-type]
    assert response["request_id"] is None
    assert response["error_code"] == "unknown"


async def test_reply_failure_is_swallowed(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """A link that drops before the answer goes out does not raise."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    use_agent(FakeAgent(answer))
    sent = asyncio.Event()

    async def broken_reply(*_: Any) -> None:
        sent.set()
        raise ConnectionResetError

    mock_hub_connection.reply.side_effect = broken_reply
    await mock_hub_connection.emit(REQUEST_MESSAGE_TYPE, _request())
    async with asyncio.timeout(5):
        await sent.wait()
    await asyncio.sleep(0)
    mock_hub_connection.reply.assert_awaited_once()


async def test_too_many_in_flight(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """Past the limit, requests are answered at once instead of queuing."""
    release = asyncio.Event()

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        await release.wait()
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    agent = use_agent(FakeAgent(answer))
    for index in range(MAX_CONCURRENT_REQUESTS + 1):
        await mock_hub_connection.emit(
            REQUEST_MESSAGE_TYPE, _request(request_id=str(index))
        )
    await asyncio.sleep(0)

    assert len(agent.inputs) == MAX_CONCURRENT_REQUESTS
    refused = await mock_hub_connection.next_reply()
    assert refused["request_id"] == str(MAX_CONCURRENT_REQUESTS)
    assert refused["error_code"] == "unknown"

    release.set()
    answered = [
        await mock_hub_connection.next_reply() for _ in range(MAX_CONCURRENT_REQUESTS)
    ]
    assert {answer["response_type"] for answer in answered} == {"action_done"}


async def test_stats_recorded(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """Outcomes are counted for diagnostics."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    use_agent(FakeAgent(answer))
    await _ask(hass, mock_hub_connection, _request())
    await _ask(hass, mock_hub_connection, {"request_id": "req-2"})

    stats = loaded_entry.runtime_data.stats
    assert stats.handled == 2
    assert stats.outcomes == {"action_done": 1, "unknown": 1}
    assert stats.last_outcome == "unknown"
    assert stats.last_handled_at is not None


async def test_debug_logs_leave_out_the_utterance(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Debug logging names the request, never what was said or answered."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Turned off the light.")

    use_agent(FakeAgent(answer))
    caplog.set_level(logging.DEBUG, logger="custom_components.thalovant")
    await _ask(hass, mock_hub_connection, _request())

    ours = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("custom_components.thalovant")
    )
    assert "req-1" in ours
    assert "kitchen" not in ours
    assert "Turned off" not in ours


async def test_default_agent_end_to_end(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
) -> None:
    """Home Assistant's own agent acts on an exposed entity."""
    assert await async_setup_component(
        hass,
        "input_boolean",
        {"input_boolean": {"kitchen_light": {"name": "Kitchen light"}}},
    )
    await hass.async_block_till_done()
    async_expose_entity(hass, conversation.DOMAIN, "input_boolean.kitchen_light", True)

    response = await _ask(
        hass,
        mock_hub_connection,
        _request(utterance="turn on the kitchen light", lang="en-us"),
    )
    assert response["response_type"] == "action_done"
    assert response["speech"]
    assert hass.states.get("input_boolean.kitchen_light").state == "on"

    response = await _ask(
        hass, mock_hub_connection, _request(utterance="xyzzy plugh frobnicate")
    )
    assert response["response_type"] == "error"
    assert response["error_code"] == "no_intent_match"


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("en-us", "en-US"),
        ("EN_us", "en-US"),
        ("zh-hant-tw", "zh-Hant-TW"),
        ("es-419", "es-419"),
        ("de-DE-1996", "de-DE-1996"),
        ("  fr ", "fr"),
        ("", ""),
        ("--", ""),
    ],
)
def test_canonical_language(tag: str, expected: str) -> None:
    """Hub tags are put in their usual casing."""
    assert canonical_language(tag) == expected


@pytest.mark.parametrize(
    ("languages", "lang", "expected"),
    [
        (["en", "fr", "pt-BR", "pt-PT"], "fr-fr", "fr"),
        (["en", "fr", "pt-BR", "pt-PT"], "pt_br", "pt-BR"),
        (["en", "fr", "pt-BR"], "PT-br", "pt-BR"),
        (["en", "fr"], "de-DE", "de-DE"),
        (["en", "fr"], None, "en"),
        (["en", "fr"], 7, "en"),
        ([], "fr-fr", "fr-FR"),
        (MATCH_ALL, "fr-fr", "fr-FR"),
    ],
)
async def test_resolve_language(
    hass: HomeAssistant,
    languages: list[str] | Literal["*"],
    lang: Any,
    expected: str,
) -> None:
    """The agent gets the closest language it supports."""
    assert await async_setup_component(hass, "conversation", {})
    owner = MockConfigEntry(domain=AGENT_OWNER)
    owner.add_to_hass(hass)

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        raise AssertionError("unused")

    conversation.async_set_agent(hass, owner, FakeAgent(answer, languages))
    assert async_resolve_language(hass, lang, owner.entry_id) == expected


async def test_resolve_language_unknown_agent(hass: HomeAssistant) -> None:
    """An agent that vanished leaves the canonical tag alone."""
    assert await async_setup_component(hass, "conversation", {})
    assert async_resolve_language(hass, "fr-fr", "conversation.gone") == "fr-FR"


def test_plain_speech_from_ssml() -> None:
    """SSML-only speech is reduced to text."""
    response = intent.IntentResponse(language="en")
    response.async_set_speech(
        "<speak>It is <emphasis>21</emphasis> degrees &amp; sunny.</speak>", "ssml"
    )
    assert plain_speech(response) == "It is 21 degrees & sunny."


def test_plain_speech_empty() -> None:
    """No speech at all is an empty string."""
    assert plain_speech(intent.IntentResponse(language="en")) == ""
