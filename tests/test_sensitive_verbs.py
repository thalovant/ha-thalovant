"""The sensitive verbs and target domains here are the connector spec's, and each verb is refused without the household's opt-in."""

import pytest

from custom_components.thalovant.actions import (
    CAPABILITY_DOMAINS,
    SENSITIVE_VERBS,
    TARGET_DOMAINS,
    async_execute,
)
from homeassistant.core import HomeAssistant

from .test_actions import _home, action, refused


def test_the_sensitive_verbs_are_exactly_the_specs_flags() -> None:
    spec = pytest.importorskip("thalovant_connector_spec")
    flagged = {
        v.name
        for v in spec.load_registry().get("home_assistant").verbs.values()
        if v.sensitive
    }
    assert flagged == set(SENSITIVE_VERBS)


def test_the_target_domains_are_exactly_the_specs() -> None:
    spec = pytest.importorskip("thalovant_connector_spec")
    target = spec.load_registry().get("home_assistant").raw["defs"]["target"]
    assert set(target["properties"]["domain"]["enum"]) == set(TARGET_DOMAINS)


def test_every_domain_a_capability_acts_on_is_a_target_domain() -> None:
    """The closed domain list is checked first, so it must hold every domain a capability needs."""
    for capability, domains in CAPABILITY_DOMAINS.items():
        assert set(domains) <= TARGET_DOMAINS, capability


@pytest.mark.parametrize("verb", sorted(SENSITIVE_VERBS))
async def test_a_sensitive_verb_is_refused_aloud_unless_the_household_opted_in(
    hass: HomeAssistant, verb: str
) -> None:
    """Refused, and as an answer: None would hand the sentence to Assist, which could do it."""
    ids = await _home(hass)
    domain = "alarm_control_panel" if verb in ("arm", "disarm") else "lock"
    name = "house" if domain == "alarm_control_panel" else "front door"
    assert refused(
        await async_execute(
            hass, action(verb, name=name, domain=domain), device_id=ids["speaker"]
        )
    )
    # the verb alone decides: whatever it names, even nothing that exists
    assert refused(
        await async_execute(
            hass, action(verb, name="no such thing"), device_id=ids["speaker"]
        )
    )
