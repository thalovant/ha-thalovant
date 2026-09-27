"""Checks on the translation files."""

import json
from pathlib import Path
import re
from typing import Any

import pytest

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
