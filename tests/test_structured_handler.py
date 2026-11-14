"""A request's structured action is carried out; anything it cannot do goes on as words."""

# ruff: noqa: F811
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.thalovant.const import (
    CONF_ALARM_CODE,
    CONF_MAX_VOLUME,
    CONF_STRUCTURED_ACTIONS,
    CONF_STRUCTURED_SENSITIVE,
)
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


# -- a refusal is an answer: it never goes on to Assist as words -----------------------------------

UNLOCK = {"v": 1, "capability": "unlock", "target": {"name": "front door"}}
OPEN_GARAGE = {"v": 1, "capability": "power_on", "target": {"name": "big door"}}


async def _doors(hass: HomeAssistant) -> None:
    """A lock, and a garage door that is a cover with no device class."""
    assert await async_setup_component(hass, "homeassistant", {})
    hass.states.async_set("lock.front", "locked", {"friendly_name": "Front Door"})
    hass.states.async_set("cover.big", "closed", {"friendly_name": "Big Door"})
    hass.states.async_set(
        "alarm_control_panel.house", "armed_away", {"friendly_name": "House Alarm"}
    )
    for entity_id in ("lock.front", "cover.big", "alarm_control_panel.house"):
        async_expose_entity(hass, "conversation", entity_id, True)


def _would_do_it(agent_inputs: list[Any]) -> FakeAgent:
    """An agent that does whatever it is told in words, as Assist can for an exposed entity."""

    async def answer(
        user_input: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        agent_inputs.append(user_input.text)
        return _result(intent.IntentResponseType.ACTION_DONE, "Unlocked it")

    return FakeAgent(answer)


@pytest.mark.parametrize(
    ("action", "service"),
    [(UNLOCK, ("lock", "unlock")), (OPEN_GARAGE, ("cover", "open_cover"))],
)
async def test_a_sensitive_action_that_is_refused_never_reaches_assist_as_words(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
    action: dict[str, Any],
    service: tuple[str, str],
) -> None:
    """Sensitive actions are off (the default). It used to be None here, and the words went on."""
    await _doors(hass)
    asked: list[Any] = []
    use_agent(_would_do_it(asked))
    calls = async_mock_service(hass, *service)
    response = await _ask(hass, mock_hub_connection, _request(action=action))
    assert response == {
        "request_id": "req-1",
        "speech": "Sorry, I didn't do that: sensitive actions are turned off for this home.",
        "continue_conversation": False,
        "response_type": "error",
        # the one error the hub's skills speak as it is and never retry in words
        "error_code": "failed_to_handle",
    }
    assert not asked and not calls


async def test_the_refusal_is_said_in_the_request_language(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    await _doors(hass)
    asked: list[Any] = []
    use_agent(_would_do_it(asked))
    response = await _ask(
        hass, mock_hub_connection, _request(action=UNLOCK, lang="fr-FR")
    )
    assert response["speech"].startswith("Désolé, je ne l'ai pas fait")
    assert response["error_code"] == "failed_to_handle" and not asked


async def test_with_sensitive_on_it_is_done_and_a_disarm_without_the_code_is_refused(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    await _doors(hass)
    asked: list[Any] = []
    use_agent(_would_do_it(asked))
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_STRUCTURED_SENSITIVE: True}
    )
    unlock = async_mock_service(hass, "lock", "unlock")
    disarm = async_mock_service(hass, "alarm_control_panel", "alarm_disarm")
    response = await _ask(hass, mock_hub_connection, _request(action=UNLOCK))
    assert response["response_type"] == "action_done" and len(unlock) == 1
    disarm_action = {"v": 1, "capability": "disarm", "target": {"name": "house alarm"}}
    response = await _ask(hass, mock_hub_connection, _request(action=disarm_action))
    assert (response["response_type"], response["error_code"]) == (
        "error",
        "failed_to_handle",
    )
    assert "alarm code" in response["speech"] and not disarm and not asked
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_ALARM_CODE: "1234"}
    )
    response = await _ask(hass, mock_hub_connection, _request(action=disarm_action))
    assert response["response_type"] == "action_done"
    assert disarm[0].data["code"] == "1234" and not asked


@pytest.mark.parametrize(
    ("speech_key", "said"),
    [
        ("action_sensitive_off", "sensitive actions are turned off"),
        ("action_sensitive_one", "one device at a time"),
        ("action_alarm_code", "no alarm code is set"),
        ("action_partial", "only do part of that"),
        ("action_failed", "Sorry, I couldn't do that."),
        ("music_failed", "Sorry, I couldn't do that."),
    ],
)
async def test_a_refusal_whose_sentence_cannot_be_made_is_still_said_as_what_it_is(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
    speech_key: str,
    said: str,
) -> None:
    """Without translations a refusal used to be said as "I could only do part of that"."""
    from custom_components.thalovant.actions import ActionResult

    await _light(hass)
    agent = use_agent(FakeAgent(lambda _: None))  # type: ignore[arg-type]

    async def refuse(*args: Any, **kwargs: Any) -> ActionResult:
        return ActionResult("error", speech_key)

    with (
        patch("custom_components.thalovant.handler.async_execute_action", refuse),
        patch(
            "custom_components.thalovant.handler.async_action_speech",
            side_effect=RuntimeError("no strings"),
        ),
    ):
        response = await _ask(hass, mock_hub_connection, _request(action=ACTION))
    assert said in response["speech"] and not agent.inputs
    assert response["error_code"] == "failed_to_handle"


@pytest.mark.parametrize(
    "action",
    [
        {"v": 1, "capability": "call_service", "target": {"name": "desk"}},
        {"v": 1, "capability": ["brightness"], "target": {"name": "desk"}},
        {"v": 1, "capability": "power_off", "target": {"all": True, "domain": "light"}},
        {"v": 1, "capability": "power_off", "target": {"name": "desk", "domain": "x"}},
    ],
)
async def test_an_action_outside_the_closed_lists_is_only_its_words(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
    action: dict[str, Any],
) -> None:
    """Checked first: the executor is never called for it, and Assist gets the sentence."""
    await _light(hass)

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "As words")

    agent = use_agent(FakeAgent(answer))
    off = async_mock_service(hass, "light", "turn_off")
    with patch("custom_components.thalovant.handler.async_execute_action") as executor:
        response = await _ask(hass, mock_hub_connection, _request(action=action))
    executor.assert_not_called()
    assert response["speech"] == "As words" and len(agent.inputs) == 1 and not off


async def test_the_volume_cap_option_holds_and_the_answer_says_the_level(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    assert await async_setup_component(hass, "homeassistant", {})
    hass.states.async_set(
        "media_player.den", "playing", {"friendly_name": "Den", "volume_level": 0.2}
    )
    async_expose_entity(hass, "conversation", "media_player.den", True)
    agent = use_agent(FakeAgent(lambda _: None))  # type: ignore[arg-type]
    volume = async_mock_service(hass, "media_player", "volume_set")
    louder = {"v": 1, "capability": "volume", "target": {"name": "den"}, "value": 90}
    # no cap set: carried out as asked
    response = await _ask(hass, mock_hub_connection, _request(action=louder))
    assert volume[-1].data["volume_level"] == 0.9 and response["speech"] == "Done."
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_MAX_VOLUME: 40}
    )
    response = await _ask(hass, mock_hub_connection, _request(action=louder))
    assert volume[-1].data["volume_level"] == 0.4
    assert response["response_type"] == "action_done"
    assert response["speech"] == (
        "The volume is at 40 percent, the highest allowed here."
    )
    # an option value that is not a cap is no cap
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_MAX_VOLUME: "loud"}
    )
    await _ask(hass, mock_hub_connection, _request(action=louder))
    assert volume[-1].data["volume_level"] == 0.9 and not agent.inputs
