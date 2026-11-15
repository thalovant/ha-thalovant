"""Plain words never reach Assist when they would act on an exposed lock, alarm, siren, valve, garage door or gate."""

# ruff: noqa: F811
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thalovant.const import CONF_STRUCTURED_SENSITIVE
from custom_components.thalovant.sensitive_words import refused_words
from homeassistant.components import conversation
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, intent
from homeassistant.setup import async_setup_component

from .conftest import FakeHubConnection
from .test_handler import FakeAgent, _ask, _request, _result, loaded_entry, use_agent  # noqa: F401


async def _house(hass: HomeAssistant, *, sensitive: bool = True) -> None:
    """A light and a fan always; the sensitive entities when asked."""
    assert await async_setup_component(hass, "homeassistant", {})
    entities = {
        "light.kitchen": ("on", {"friendly_name": "Kitchen light"}),
        "fan.bedroom": ("off", {"friendly_name": "Bedroom fan"}),
        "cover.blinds": (
            "open",
            {"friendly_name": "Living blinds", "device_class": "blind"},
        ),
    }
    if sensitive:
        entities |= {
            "lock.front": ("locked", {"friendly_name": "Front door"}),
            "cover.garage": (
                "closed",
                {"friendly_name": "Garage", "device_class": "garage"},
            ),
            "alarm_control_panel.house": ("disarmed", {"friendly_name": "House alarm"}),
            "siren.hall": ("off", {"friendly_name": "Hall horn"}),
            "valve.water": ("open", {"friendly_name": "Water main"}),
            "switch.shutoff": ("on", {"friendly_name": "Cellar shutoff"}),
        }
    for entity_id, (state, attributes) in entities.items():
        hass.states.async_set(entity_id, state, attributes)
        async_expose_entity(hass, "conversation", entity_id, True)


REFUSED = [
    "turn off the front door",
    "toggle the front door",
    "open the front door",
    "let me in",
    "let us in",
    "silence the alarm",
    "stop the alarm",
    "turn off the siren",
    "open the water valve",
    "turn off the horn in the hall",
    "close the water main",
    "cellar shutoff off",
    "open the door",
    "unlock the door",
    "open the garage",
    "ouvre la porte",
    "laisse-moi entrer",
    "coupe la sirène",
    "ferme la vanne",
    "öffne die Haustür",
    "lass mich rein",
    "öffne das Ventil",
    "abre la puerta",
    "déjame entrar",
    "apri il portone",
    "fammi entrare",
    "abre o portão",
    "open de voordeur",
    "laat me binnen",
    "FRONT DOOR!",
    "open the Front-Door",
]
ORDINARY = [
    "turn on the kitchen light",
    "dim the kitchen light to 30 percent",
    "turn off the bedroom fan",
    "open the blinds",
    "close the living blinds",
    "what time is it",
    "is the kitchen light on",
    "stelle den Ventilator an",
    "allume la lumière de la cuisine",
    "enciende la luz de la cocina",
    "accendi la lampada portatile",
    "zet het licht in de keuken aan",
    "turn on the fan",
]


@pytest.mark.parametrize("text", REFUSED)
async def test_a_sentence_about_a_sensitive_entity_is_refused(
    hass: HomeAssistant, text: str
) -> None:
    await _house(hass)
    assert refused_words(hass, text), text


@pytest.mark.parametrize("text", ORDINARY)
async def test_ordinary_sentences_pass(hass: HomeAssistant, text: str) -> None:
    await _house(hass)
    assert refused_words(hass, text) is None, text


@pytest.mark.parametrize("text", REFUSED)
async def test_a_household_that_exposes_nothing_sensitive_is_never_refused(
    hass: HomeAssistant, text: str
) -> None:
    await _house(hass, sensitive=False)
    assert refused_words(hass, text) is None, text


async def test_an_entity_that_is_not_exposed_does_not_count(
    hass: HomeAssistant,
) -> None:
    await _house(hass)
    for entity_id in (
        "lock.front",
        "cover.garage",
        "alarm_control_panel.house",
        "siren.hall",
        "valve.water",
        "switch.shutoff",
    ):
        async_expose_entity(hass, "conversation", entity_id, False)
    assert refused_words(hass, "open the front door") is None


async def test_an_alias_is_a_name(hass: HomeAssistant) -> None:
    await _house(hass)
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "lock", "test", "1", suggested_object_id="side"
    )
    hass.states.async_set(entry.entity_id, "locked", {"friendly_name": "Side"})
    async_expose_entity(hass, "conversation", entry.entity_id, True)
    registry.async_update_entity(entry.entity_id, aliases={"sesame"})
    assert refused_words(hass, "hey open sesame") == "name"


async def test_the_refusal_reaches_the_hub_and_assist_is_never_asked(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    await _house(hass)
    agent = use_agent(FakeAgent(lambda _: None))  # type: ignore[arg-type]
    for text in (
        "toggle the front door",
        "let me in",
        "silence the alarm",
        "open the water valve",
    ):
        response = await _ask(hass, mock_hub_connection, _request(utterance=text))
        assert (
            response["response_type"] == "error"
            and "sensitive actions are turned off" in response["speech"]
        )
        assert response["error_code"] == "failed_to_handle"
    assert not agent.inputs


async def test_an_ordinary_sentence_still_goes_to_assist(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    await _house(hass)

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Done.")

    agent = use_agent(FakeAgent(answer))
    response = await _ask(
        hass, mock_hub_connection, _request(utterance="turn on the kitchen light")
    )
    assert response["speech"] == "Done." and len(agent.inputs) == 1


async def test_the_household_option_lets_the_words_through(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    await _house(hass)

    async def answer(
        _: conversation.ConversationInput,
    ) -> conversation.ConversationResult:
        return _result(intent.IntentResponseType.ACTION_DONE, "Opened.")

    agent = use_agent(FakeAgent(answer))
    hass.config_entries.async_update_entry(
        loaded_entry, options={**loaded_entry.options, CONF_STRUCTURED_SENSITIVE: True}
    )
    response = await _ask(
        hass, mock_hub_connection, _request(utterance="open the front door")
    )
    assert response["speech"] == "Opened." and len(agent.inputs) == 1


async def test_a_follow_up_is_guarded_too(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    await _house(hass)
    agent = use_agent(FakeAgent(lambda _: None))  # type: ignore[arg-type]
    response = await _ask(
        hass,
        mock_hub_connection,
        _request(utterance="the front door", conversation_id="c1"),
    )
    assert response["response_type"] == "error" and not agent.inputs


async def test_a_sentence_of_only_punctuation_is_nothing(hass: HomeAssistant) -> None:
    await _house(hass)
    assert refused_words(hass, "?!...") is None


async def test_a_registered_entity_without_aliases_is_matched_by_its_name(
    hass: HomeAssistant,
) -> None:
    await _house(hass)
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "lock", "test", "2", suggested_object_id="shed"
    )
    hass.states.async_set(entry.entity_id, "locked", {"friendly_name": "Shed"})
    async_expose_entity(hass, "conversation", entry.entity_id, True)
    assert refused_words(hass, "open the shed") == "name"


async def test_the_refusal_is_still_spoken_when_its_translation_fails(
    hass: HomeAssistant,
    mock_hub_connection: FakeHubConnection,
    use_agent,
    loaded_entry: MockConfigEntry,
) -> None:
    await _house(hass)
    agent = use_agent(FakeAgent(lambda _: None))  # type: ignore[arg-type]
    with patch(
        "custom_components.thalovant.handler.async_action_speech",
        side_effect=RuntimeError("no translations"),
    ):
        response = await _ask(
            hass, mock_hub_connection, _request(utterance="open the front door")
        )
    assert response["response_type"] == "error"
    assert "sensitive actions are turned off" in response["speech"]
    assert not agent.inputs


async def test_an_alias_that_is_not_said_does_not_refuse(hass: HomeAssistant) -> None:
    await _house(hass)
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "lock", "test", "3", suggested_object_id="cellar"
    )
    hass.states.async_set(entry.entity_id, "locked", {"friendly_name": "Cellar"})
    async_expose_entity(hass, "conversation", entry.entity_id, True)
    registry.async_update_entity(entry.entity_id, aliases={"vault"})
    assert refused_words(hass, "turn on the kitchen light") is None
