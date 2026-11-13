"""The sensitive verbs here are the ones the connector spec flags, and each is refused without the household's opt-in."""

import pytest

from custom_components.thalovant.actions import SENSITIVE_VERBS, async_execute
from homeassistant.core import HomeAssistant

from .test_actions import _home, action


def test_the_sensitive_verbs_are_exactly_the_specs_flags() -> None:
    spec = pytest.importorskip("thalovant_connector_spec")
    flagged = {
        v.name
        for v in spec.load_registry().get("home_assistant").verbs.values()
        if v.sensitive
    }
    assert flagged == set(SENSITIVE_VERBS)


@pytest.mark.parametrize("verb", sorted(SENSITIVE_VERBS))
async def test_a_sensitive_verb_is_left_to_assist_unless_the_household_opted_in(
    hass: HomeAssistant, verb: str
) -> None:
    ids = await _home(hass)
    domain = "alarm_control_panel" if verb in ("arm", "disarm") else "lock"
    name = "house" if domain == "alarm_control_panel" else "front door"
    assert (
        await async_execute(
            hass, action(verb, name=name, domain=domain), device_id=ids["speaker"]
        )
        is None
    )
