"""Text from outside is plain words before it reaches a repair issue or a translated sentence."""

import pytest

from custom_components.thalovant.const import DOMAIN
from custom_components.thalovant.text import escape_markdown
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

HOSTILE = "x](http://evil.example) `code` <script>"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (HOSTILE, "x http evil.example code script"),
        ("Kitchen [1]", "Kitchen 1"),
        ("a\nb\x1b[31m", "a b 31m"),
        (None, ""),
        (7, "7"),
        ("  ", ""),
        ("x" * 500, "x" * 120),
    ],
)
def test_markdown_is_taken_out(given: object, expected: str) -> None:
    assert escape_markdown(given) == expected


def test_nothing_that_makes_a_link_survives() -> None:
    for text in (HOSTILE, "![i](u)", "<http://a>", "[a]: http://b", "http://c"):
        out = escape_markdown(text)
        assert not any(ch in out for ch in "[]()`<>") and "://" not in out


async def test_a_player_name_is_plain_in_a_repair_issue(hass: HomeAssistant) -> None:
    from custom_components.thalovant.rooms import PlayerChecker

    checker = PlayerChecker.__new__(PlayerChecker)
    checker._hass = hass
    checker._raised = set()
    checker._raise("issue-1", "player_missing", {"player": HOSTILE, "hub": HOSTILE})
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "issue-1")
    assert issue is not None
    for value in issue.translation_placeholders.values():
        assert not any(ch in value for ch in "[]()`<>") and "://" not in value


async def test_an_action_answer_never_says_markup(hass: HomeAssistant) -> None:
    from custom_components.thalovant.actions import ActionResult
    from custom_components.thalovant.handler import async_action_speech

    speech = await async_action_speech(
        hass,
        "en",
        ActionResult("action_state", "action_state", {"name": HOSTILE, "state": "on"}),
    )
    assert not any(ch in speech for ch in "[]()`<>") and "://" not in speech
