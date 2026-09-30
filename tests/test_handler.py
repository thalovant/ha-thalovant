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
    result_to_response,
    speech_text,
)
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, intent, issue_registry as ir
from homeassistant.setup import async_setup_component

from .conftest import HUB_ID, FakeHubConnection

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


async def _until(condition: Callable[[], bool], timeout: float = 5) -> None:
    """Wait for something a background task does."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


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
    # A code the hub does not know is sent as unknown.
    assert response["error_code"] == "unknown"
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


def test_error_without_code() -> None:
    """An error response without a code is reported as unknown."""
    response = intent.IntentResponse(language="en")
    response.response_type = intent.IntentResponseType.ERROR
    result = conversation.ConversationResult(response=response)
    assert result_to_response("req-1", result)["error_code"] == "unknown"


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
    ("exception", "error_code", "speech"),
    [
        (
            RuntimeError("secret utterance echo"),
            "failed_to_handle",
            "Sorry, Home Assistant couldn't do that.",
        ),
        # Home Assistant turns its own errors into an answer with their message.
        (HomeAssistantError("It broke"), "unknown", "It broke"),
    ],
)
async def test_agent_exceptions(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    caplog: pytest.LogCaptureFixture,
    exception: Exception,
    error_code: str,
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
    assert response["error_code"] == error_code
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
    # No request id is answered with an empty one.
    assert response["request_id"] == ""
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


@pytest.mark.parametrize(
    ("kind", "speech", "expected"),
    [
        (
            "ssml",
            "<speak>It is <emphasis>21</emphasis> degrees &amp; sunny.</speak>",
            "It is 21 degrees & sunny.",
        ),
        # Only real tags go: a comparison is text.
        ("plain", "5 < 6 and 7 > 3", "5 < 6 and 7 > 3"),
        # Only numeric references, the XML five and &nbsp; are decoded.
        ("plain", "Caf&eacute; &#233;t&#xE9; &lt;b&gt;", "Caf&eacute; été <b>"),
        ("plain", "  Turned\u2003off\n the light.  ", "Turned off the light."),
    ],
)
def test_speech_rules(kind: str, speech: str, expected: str) -> None:
    """Speech follows the SDK's rules, shared by every Thalovant device."""
    response = intent.IntentResponse(language="en")
    response.async_set_speech(speech, kind)
    assert speech_text(response) == expected


def test_plain_speech_empty() -> None:
    """No speech at all is an empty string."""
    assert speech_text(intent.IntentResponse(language="en")) == ""


async def test_no_time_left(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A request the hub has already given up on is not answered, and nothing raises."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        raise AssertionError("the agent is not asked when there is no time")

    agent = use_agent(FakeAgent(answer))
    caplog.set_level(logging.DEBUG, logger="custom_components.thalovant")
    await mock_hub_connection.emit(REQUEST_MESSAGE_TYPE, _request(), age=11)
    await _until(lambda: loaded_entry.runtime_data.stats.handled == 1)
    await asyncio.sleep(0)

    assert agent.inputs == []
    mock_hub_connection.reply.assert_not_awaited()
    assert "no time left to answer" in caplog.text
    assert loaded_entry.runtime_data.stats.last_outcome == "timeout"


async def test_late_request_gets_what_is_left(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """Counted from arrival: an old request gives the agent less than its share."""
    never = asyncio.Event()

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        await never.wait()
        raise AssertionError("unreachable")

    agent = use_agent(FakeAgent(answer))
    loop = asyncio.get_running_loop()
    # Arrived 9.6 s ago: 0.4 s left, of which the reply keeps its reserve.
    with patch("custom_components.thalovant.handler.REPLY_RESERVE", 0.1):
        started = loop.time()
        await mock_hub_connection.emit(REQUEST_MESSAGE_TYPE, _request(), age=9.6)
        response = await mock_hub_connection.next_reply()
    assert loop.time() - started < 0.4
    assert len(agent.inputs) == 1
    assert response["error_code"] == "timeout"


@pytest.mark.parametrize("late", ["returns", "raises"])
async def test_agent_ignoring_cancellation(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    late: str,
) -> None:
    """An agent that swallows cancellation does not hold the answer back."""
    release = asyncio.Event()

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        while True:
            try:
                await release.wait()
                break
            except asyncio.CancelledError:
                continue
        if late == "raises":
            raise RuntimeError("too late")
        return _result(intent.IntentResponseType.ACTION_DONE, "Done, too late.")

    use_agent(FakeAgent(answer))
    with patch("custom_components.thalovant.handler.CONVERSE_TIMEOUT", 0.05):
        response = await _ask(hass, mock_hub_connection, _request())
    assert response["error_code"] == "timeout"

    # What the agent does afterwards is dropped quietly.
    converse = [
        task for task in asyncio.all_tasks() if task.get_name() == "thalovant converse"
    ]
    assert len(converse) == 1
    release.set()
    await _until(converse[0].done)
    await asyncio.sleep(0)
    mock_hub_connection.reply.assert_awaited_once()


async def test_reply_withdrawn_at_deadline(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reply that cannot go out before the hub gives up is withdrawn, quietly."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    use_agent(FakeAgent(answer))
    stuck = asyncio.Event()

    async def slow_reply(*_: Any) -> None:
        await stuck.wait()

    mock_hub_connection.reply.side_effect = slow_reply
    caplog.set_level(logging.DEBUG, logger="custom_components.thalovant")
    await mock_hub_connection.emit(REQUEST_MESSAGE_TYPE, _request(), age=9.9)
    await _until(lambda: "could not be sent before the hub gave up" in caplog.text)
    mock_hub_connection.reply.assert_awaited_once()


def _entry_id(hass: HomeAssistant) -> str:
    return hass.config_entries.async_entries(DOMAIN)[0].entry_id


def _speaker_devices(hass: HomeAssistant) -> list[dr.DeviceEntry]:
    return [
        device
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), _entry_id(hass)
        )
        if device.via_device_id is not None
    ]


async def test_device_becomes_a_registry_device_and_reaches_assist(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """The speaking device is passed to Assist, so its area gives the room."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    agent = use_agent(FakeAgent(answer))
    await _ask(
        hass, mock_hub_connection, _request(device={"id": "42", "name": "Kitchen"})
    )

    (device,) = _speaker_devices(hass)
    assert device.name == "Kitchen"
    assert device.identifiers == {(DOMAIN, f"{HUB_ID}:42")}
    assert agent.inputs[0].device_id == device.id
    (hub,) = (
        d
        for d in dr.async_entries_for_config_entry(dr.async_get(hass), _entry_id(hass))
        if (DOMAIN, HUB_ID) in d.identifiers
    )
    assert device.via_device_id == hub.id


async def test_device_is_reused_and_renamed(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """The same device keeps its registry entry, and its area, across requests."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    agent = use_agent(FakeAgent(answer))
    await _ask(
        hass, mock_hub_connection, _request(device={"id": "42", "name": "Kitchen"})
    )
    (device,) = _speaker_devices(hass)
    dr.async_get(hass).async_update_device(device.id, area_id="kitchen")

    await _ask(
        hass, mock_hub_connection, _request(device={"id": "42", "name": "Pantry"})
    )

    (same,) = _speaker_devices(hass)
    assert same.id == device.id
    assert same.name == "Pantry"
    assert same.area_id == "kitchen"
    assert [i.device_id for i in agent.inputs] == [device.id, device.id]


async def test_user_chosen_name_survives_a_rename(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """A name the user set in Home Assistant is never overwritten."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    use_agent(FakeAgent(answer))
    await _ask(
        hass, mock_hub_connection, _request(device={"id": "42", "name": "Kitchen"})
    )
    (device,) = _speaker_devices(hass)
    dr.async_get(hass).async_update_device(device.id, name_by_user="Mine")

    await _ask(
        hass, mock_hub_connection, _request(device={"id": "42", "name": "Pantry"})
    )

    (same,) = _speaker_devices(hass)
    assert same.name_by_user == "Mine"


@pytest.mark.parametrize(
    "device", [None, "x", {}, {"id": ""}, {"id": "  "}, {"id": 42}, {"name": "Kitchen"}]
)
async def test_no_usable_device_means_no_room(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
    device: Any,
) -> None:
    """A request without a usable device is answered as before, with no room."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    agent = use_agent(FakeAgent(answer))
    await _ask(hass, mock_hub_connection, _request(device=device))

    assert agent.inputs[0].device_id is None
    assert _speaker_devices(hass) == []


async def test_nameless_device_gets_a_name(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """A device with no name is still a device, named after its id."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    use_agent(FakeAgent(answer))
    await _ask(hass, mock_hub_connection, _request(device={"id": "1234567890"}))

    (device,) = _speaker_devices(hass)
    assert device.name == "Thalovant device 12345678"


async def test_device_limit(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    mock_hub_connection: FakeHubConnection,
    use_agent: Callable[[FakeAgent], FakeAgent],
) -> None:
    """Past the limit a new device is answered with no room; known ones still get theirs."""

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    agent = use_agent(FakeAgent(answer))
    with patch("custom_components.thalovant.handler.MAX_DEVICES_PER_HUB", 1):
        await _ask(hass, mock_hub_connection, _request(device={"id": "1", "name": "A"}))
        await _ask(hass, mock_hub_connection, _request(device={"id": "2", "name": "B"}))
        await _ask(hass, mock_hub_connection, _request(device={"id": "1", "name": "A"}))

    assert len(_speaker_devices(hass)) == 1
    first, second, third = (i.device_id for i in agent.inputs)
    assert first is not None
    assert second is None
    assert third == first
