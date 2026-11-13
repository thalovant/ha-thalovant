"""A request's structured action is carried out; anything it cannot do goes on as words."""

# ruff: noqa: F811
from typing import Any
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.thalovant.const import CONF_STRUCTURED_ACTIONS
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component

from .conftest import FakeHubConnection
from .test_handler import FakeAgent, _ask, _request, _result, loaded_entry, use_agent  # noqa: F401

ACTION = {"v": 1, "capability": "brightness", "target": {"name": "desk"}, "value": 30}


async def _light(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    hass.states.async_set("light.desk", "on", {"friendly_name": "Desk"})
    async_expose_entity(hass, "conversation", "light.desk", True)


async def test_a_structured_action_is_done_without_asking_assist(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry,
) -> None:
    await _light(hass)
    agent = use_agent(FakeAgent(lambda _: None))  # type: ignore[arg-type]
    calls = async_mock_service(hass, "light", "turn_on")
    response = await _ask(hass, mock_hub_connection, _request(action=ACTION))
    assert calls[0].data["brightness_pct"] == 30
    assert response["response_type"] == "action_done" and response["speech"] == "Done."
    assert not agent.inputs


async def test_an_action_that_cannot_be_resolved_goes_on_as_words(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry,
) -> None:
    await _light(hass)

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Turned it down")

    agent = use_agent(FakeAgent(answer))
    unknown = {**ACTION, "target": {"name": "no such lamp"}}
    response = await _ask(hass, mock_hub_connection, _request(action=unknown))
    assert response["speech"] == "Turned it down" and len(agent.inputs) == 1


async def test_structured_actions_can_be_turned_off(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    await _light(hass)

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "As words")

    use_agent(FakeAgent(answer))
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_STRUCTURED_ACTIONS: False}
    )
    calls = async_mock_service(hass, "light", "turn_on")
    response = await _ask(hass, mock_hub_connection, _request(action=ACTION))
    assert response["speech"] == "As words" and not calls


async def test_a_follow_up_to_assist_is_never_structured(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry,
) -> None:
    await _light(hass)

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Follow-up")

    use_agent(FakeAgent(answer))
    calls = async_mock_service(hass, "light", "turn_on")
    response = await _ask(
        hass, mock_hub_connection, _request(action=ACTION, conversation_id="c-1")
    )
    assert response["speech"] == "Follow-up" and not calls


async def test_a_crash_in_the_resolver_goes_on_as_words(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry,
) -> None:
    await _light(hass)

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Words")

    use_agent(FakeAgent(answer))
    with patch(
        "custom_components.thalovant.handler.async_execute_action",
        side_effect=RuntimeError("x"),
    ):
        response = await _ask(hass, mock_hub_connection, _request(action=ACTION))
    assert response["speech"] == "Words"


async def test_speech_that_cannot_be_made_still_answers_and_never_asks_assist(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry,
) -> None:
    await _light(hass)
    agent = use_agent(FakeAgent(lambda _: None))  # type: ignore[arg-type]
    calls = async_mock_service(hass, "light", "turn_on")
    with patch(
        "custom_components.thalovant.handler.async_action_speech",
        side_effect=RuntimeError("no strings"),
    ):
        response = await _ask(hass, mock_hub_connection, _request(action=ACTION))
    assert calls and response["speech"] == "Done." and not agent.inputs


async def test_an_expired_request_changes_nothing(
    hass: HomeAssistant, loaded_entry
) -> None:
    from custom_components.thalovant.handler import HomeRequestHandler

    await _light(hass)
    calls = async_mock_service(hass, "light", "turn_on")
    handler = HomeRequestHandler(hass, loaded_entry, None)  # type: ignore[arg-type]
    response = await handler._async_converse(
        "req-x", {"utterance": "dim the desk", "action": ACTION}, 0.0
    )
    assert (
        response["response_type"] == "error"
        and response["error_code"] == "timeout"
        and not calls
    )


async def test_the_speech_of_an_action_follows_the_request_language(
    hass: HomeAssistant,
) -> None:
    from custom_components.thalovant.actions import ActionResult
    from custom_components.thalovant.handler import async_action_speech

    done = ActionResult("action_done", "action_done", {"name": "Desk"})
    assert await async_action_speech(hass, "fr-FR", done) == "C'est fait."
    assert await async_action_speech(hass, None, done) == "Done."
    assert await async_action_speech(hass, "xx", done) == "Done."
    # a placeholder the sentence needs but the result lacks: the sentence is said as it is
    assert "{" not in await async_action_speech(
        hass, "en", ActionResult("query_answer", "action_state", {})
    )


async def test_a_structured_action_that_runs_out_of_time_is_a_timeout_never_assist(
    hass: HomeAssistant, loaded_entry
) -> None:
    import asyncio

    from custom_components.thalovant.handler import HomeRequestHandler

    async def slow(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(5)

    handler = HomeRequestHandler(hass, loaded_entry, None)  # type: ignore[arg-type]
    with patch("custom_components.thalovant.handler.async_execute_action", slow):
        response = await handler._async_converse(
            "req-t", {"utterance": "dim", "action": ACTION}, 0.05
        )
    assert response["error_code"] == "timeout"


async def test_a_partly_done_action_is_an_error_answer(
    hass: HomeAssistant, mock_hub_connection: FakeHubConnection, use_agent, loaded_entry
) -> None:
    from custom_components.thalovant.actions import ActionResult

    await _light(hass)
    agent = use_agent(FakeAgent(lambda _: None))  # type: ignore[arg-type]

    async def partial(*args: Any, **kwargs: Any) -> ActionResult:
        return ActionResult("error", "action_partial", {"name": "Desk"}, ["light.desk"])

    with patch("custom_components.thalovant.handler.async_execute_action", partial):
        response = await _ask(hass, mock_hub_connection, _request(action=ACTION))
    assert (
        response["response_type"] == "error"
        and response["error_code"] == "failed_to_handle"
    )
    assert "part" in response["speech"] and not agent.inputs


async def test_a_timeout_after_some_entities_changed_is_a_partial_answer(
    hass: HomeAssistant, loaded_entry
) -> None:
    import asyncio

    from custom_components.thalovant.handler import HomeRequestHandler

    async def half_done(*args: Any, progress: list[str], **kwargs: Any) -> None:
        progress.append("light.desk")
        await asyncio.sleep(5)

    handler = HomeRequestHandler(hass, loaded_entry, None)  # type: ignore[arg-type]
    with patch("custom_components.thalovant.handler.async_execute_action", half_done):
        response = await handler._async_converse(
            "req-p", {"utterance": "toggle", "action": ACTION}, 0.05
        )
    assert (
        response["response_type"] == "error"
        and response["error_code"] == "failed_to_handle"
    )
    assert "part" in response["speech"]
