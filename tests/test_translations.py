"""Checks on the translation files."""

import json
from pathlib import Path
import re
from typing import Any

import pytest
import yaml

INTEGRATION = Path(__file__).parent.parent / "custom_components" / "thalovant"
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load(name: str) -> dict[str, Any]:
    return json.loads((INTEGRATION / name).read_text(encoding="utf-8"))


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


def test_english_matches_strings() -> None:
    """A custom integration ships en.json; it must be strings.json exactly."""
    assert _load("translations/en.json") == _load("strings.json")


@pytest.mark.parametrize("language", ["fr"])
def test_translation_complete(language: str) -> None:
    """Every translation has every string, with the same placeholders."""
    english = _flatten(_load("strings.json"))
    translated = _flatten(_load(f"translations/{language}.json"))
    assert translated.keys() == english.keys()
    for key, text in english.items():
        assert set(PLACEHOLDER.findall(translated[key])) == set(
            PLACEHOLDER.findall(text)
        ), key


SOURCE = Path(__file__).parent.parent / "custom_components" / "thalovant"

# The placeholders each message is given by the code. A message may use any
# subset: one the code does not give would be shown as "{name}" to a person.
EXCEPTION_PLACEHOLDERS: dict[str, set[str]] = {
    "announcements_disabled": {"hub"},
    "urgent_disabled": {"hub"},
    "scope_missing": {"hub"},
    "token_rejected": {"hub"},
    "token_unreadable": {"hub"},
    "rate_limited_normal": {"limit"},
    "rate_limited_urgent": {"limit"},
    "rate_limited_remote": {"seconds"},
    "hub_unreachable": {"announcement"},
    "not_cancellable": {"status"},
    "announcement_not_found": {"hub"},
    "request_refused": {"status", "code"},
    "unexpected": {"hub"},
    "names_required": {"target"},
    "ambiguous_speaker": {"hub"},
    "entry_not_loaded": {"hub"},
    "intercom_unavailable_hub_off": {"hub"},
    "intercom_unavailable_kid_hub": {"hub"},
    "intercom_unavailable_public_hub": {"hub"},
    "intercom_unavailable_unknown": {"hub"},
    "urgent_scope_required": {"hub"},
    "urgent_busy": {"seconds"},
    "skill_not_installed": {"hub"},
    "hub_locked": {"hub"},
    "manager_required": {"hub"},
}


LEGACY_EXCEPTIONS = {
    "auth_failed",
    "cannot_connect",
    "client_key_rejected",
    "credentials_invalid",
    "hub_key_changed",
    "not_admitted_yet",
}


def test_exception_messages_use_only_placeholders_the_code_gives() -> None:
    """Every message is shown whole: no placeholder is left unfilled."""
    strings = _load("strings.json")["exceptions"]
    for key, message in strings.items():
        allowed = EXCEPTION_PLACEHOLDERS.get(
            key, {"hub"} if key in LEGACY_EXCEPTIONS else set()
        )
        assert set(PLACEHOLDER.findall(message["message"])) <= allowed, key


def test_every_exception_key_is_raised_somewhere() -> None:
    """No message is dead text, and the families built from a reason are complete."""
    code = "\n".join(path.read_text(encoding="utf-8") for path in SOURCE.glob("*.py"))
    strings = _load("strings.json")["exceptions"]
    dynamic = ("text_", "intercom_unavailable_")
    for key in strings:
        assert key in code or key.startswith(dynamic), key
    # The families whose key is built from a reason.
    assert {k for k in strings if k.startswith("text_")} == {
        "text_empty",
        "text_too_long",
        "text_markup",
        "text_bad_characters",
    }
    assert {k for k in strings if k.startswith("intercom_unavailable_")} == {
        "intercom_unavailable_hub_off",
        "intercom_unavailable_platform",
        "intercom_unavailable_not_configured",
        "intercom_unavailable_kid_hub",
        "intercom_unavailable_public_hub",
        "intercom_unavailable_unknown",
    }


def test_every_issue_has_its_translation() -> None:
    """Each reason Intercom can be unavailable has a notice, and one more for the unknown."""
    from custom_components.thalovant.intercom import _ISSUE_REASONS

    issues = _load("strings.json")["issues"]
    wanted = {f"intercom_unavailable_{reason}" for reason in _ISSUE_REASONS.values()}
    assert wanted | {"intercom_unavailable_unknown"} <= set(issues)
    for key in [*wanted, "intercom_unavailable_unknown", "intercom_can_play"]:
        assert set(PLACEHOLDER.findall(issues[key]["description"])) <= {"hub"}, key
        assert set(PLACEHOLDER.findall(issues[key]["title"])) <= {"hub"}, key


def test_services_match_their_descriptions() -> None:
    """services.yaml and strings.json say the same things, field for field."""
    services = yaml.safe_load((SOURCE / "services.yaml").read_text(encoding="utf-8"))
    strings = _load("strings.json")
    icons = _load("icons.json")
    assert set(services) == set(strings["services"]) == set(icons["services"])
    for name, service in services.items():
        described = strings["services"][name]
        assert described["name"]
        assert described["description"]
        assert set(service["fields"]) == set(described["fields"]), name
        for field, field_strings in described["fields"].items():
            assert field_strings["name"], (name, field)
            assert field_strings["description"], (name, field)
        for field, definition in service["fields"].items():
            select = definition["selector"].get("select")
            if select is None:
                continue
            options = strings["selector"][select["translation_key"]]["options"]
            assert set(options) == set(select["options"]), (name, field)


def test_the_safety_notice_is_where_a_person_decides() -> None:
    """The options step and the announce action both say what Intercom is not."""
    for language in ("strings.json", "translations/fr.json"):
        data = _load(language)
        options = data["options"]["step"]["init"]["description"]
        announce = data["services"]["announce"]["description"]
        for text in (options, announce):
            assert "smoke" in text or "fumée" in text, (language, text[:40])
            assert "certifi" in text, (language, text[:40])


def test_no_wording_the_platform_ruled_out() -> None:
    """Amendment 2: nothing says it is spoken once, that nothing listens, or that it stops at once."""
    for language in ("strings.json", "translations/fr.json"):
        text = json.dumps(_load(language), ensure_ascii=False).lower()
        for banned in (
            "spoken once",
            "never listens",
            "stops every announcement at once",
            "dite une seule fois",
            "n'écoute jamais",
        ):
            assert banned not in text, (language, banned)


def test_every_problem_code_has_its_message() -> None:
    """Each answer the platform gives for Intercom reaches a message of its own."""
    strings = _load("strings.json")["exceptions"]
    for key in (
        "urgent_scope_required",
        "urgent_busy",
        "skill_not_installed",
        "not_a_speaker",
        "too_many_targets",
        "intercom_unavailable_platform",
        "intercom_unavailable_not_configured",
        "intercom_unavailable_kid_hub",
        "intercom_unavailable_public_hub",
        "hub_unreachable",
        "rate_limited_remote",
        "not_cancellable",
        "hub_locked",
        "manager_required",
    ):
        assert key in strings, key


def test_rolling_out_is_said_plainly() -> None:
    """Intercom is not switched on yet: where a person decides, and when it is off, that is said."""
    for language, words in (
        ("strings.json", "rolling out"),
        ("translations/fr.json", "déploiement"),
    ):
        data = _load(language)
        for text in (
            data["options"]["step"]["init"]["description"],
            data["services"]["announce"]["description"],
            data["exceptions"]["intercom_unavailable_platform"]["message"],
            data["issues"]["intercom_unavailable_platform"]["description"],
        ):
            assert words in text, (language, text[:60])
