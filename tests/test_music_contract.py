"""The music verbs the docs claim are the ones the code carries, and the version is one number.

``tests/music_vectors.json`` is this repository's own copy of the music behaviours (shape ``world`` +
``cases``). The connector spec's vectors are organised differently (``validation`` and ``behavior``);
the comparison below runs only where the spec package is installed.
"""

from importlib import resources
import json
from pathlib import Path
import re
import tomllib
from typing import Any

import pytest

from custom_components.thalovant.actions import BUILDERS, CAPABILITY_DOMAINS
from custom_components.thalovant.music import (
    _RUNNERS,
    MUSIC_CAPABILITIES,
    NOT_CARRIED,
    SHARED_CAPABILITIES,
)

ROOT = Path(__file__).parent.parent
CODE = re.compile(r"`([a-z_]+)`")


def _row(text: str, starts_with: str) -> str:
    """The value cell of the one table row whose first cell starts with ``starts_with``."""
    rows = [line for line in text.splitlines() if line.startswith(f"| {starts_with}")]
    assert len(rows) == 1, (starts_with, rows)
    return rows[0].split("|")[2]


def _table_verbs(text: str, heading: str) -> set[str]:
    """The verbs named in the first column of the table under ``heading``.

    A first cell names its verbs before any bracket or " with ": "`join` (`other` = ...)" is
    ``join``, "`play_media` with `favorites`" is ``play_media``.
    """
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    verbs: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cell = re.split(r" \(| with ", line.split("|")[1], maxsplit=1)[0]
        verbs.update(CODE.findall(cell))
    return verbs


def test_the_docs_list_exactly_the_verbs_the_code_carries() -> None:
    """Fails when the verb lists in music.py and the lists the docs claim differ."""
    facts = (ROOT / "QUICK_FACTS.md").read_text(encoding="utf-8")
    assert set(CODE.findall(_row(facts, "Music capabilities"))) == set(
        MUSIC_CAPABILITIES
    )
    assert set(CODE.findall(_row(facts, "Shared media capabilities"))) == set(
        SHARED_CAPABILITIES
    )
    assert set(CODE.findall(_row(facts, "Not carried on this route"))) == set(
        NOT_CARRIED
    )
    guide = (ROOT / "docs" / "music.md").read_text(encoding="utf-8")
    assert _table_verbs(guide, "## What it does") == (
        MUSIC_CAPABILITIES | SHARED_CAPABILITIES
    )
    french = (ROOT / "docs" / "music.fr.md").read_text(encoding="utf-8")
    for verb in MUSIC_CAPABILITIES | SHARED_CAPABILITIES | NOT_CARRIED:
        assert f"`{verb}`" in french, verb
        assert f"`{verb}`" in guide, verb


def test_every_music_verb_has_its_runner_and_every_shared_one_its_builder() -> None:
    assert set(_RUNNERS) == set(MUSIC_CAPABILITIES)
    assert set(BUILDERS) >= SHARED_CAPABILITIES
    assert set(CAPABILITY_DOMAINS) >= MUSIC_CAPABILITIES | SHARED_CAPABILITIES
    assert not NOT_CARRIED & set(CAPABILITY_DOMAINS)
    assert not MUSIC_CAPABILITIES & SHARED_CAPABILITIES


def test_the_private_vectors_have_the_shape_the_docs_say() -> None:
    """``world`` + ``cases`` with a whole ``action``: not the spec's ``validation``/``behavior``."""
    vectors = json.loads((ROOT / "tests" / "music_vectors.json").read_text())
    assert set(vectors) == {"_", "world", "cases"}
    assert "own copy" in vectors["_"] and "NOT the connector spec's" in vectors["_"]
    for case in vectors["cases"]:
        assert set(case) <= {"name", "action", "expect", "device_name"}, case["name"]
        assert case["action"]["capability"] in MUSIC_CAPABILITIES, case["name"]
    for text in (
        (ROOT / "docs" / "music.md").read_text(encoding="utf-8"),
        (ROOT / "QUICK_FACTS.md").read_text(encoding="utf-8"),
    ):
        assert "own copy" in text and "`validation`" in text and "`behavior`" in text


def _spec_vectors() -> dict[str, Any]:
    pytest.importorskip("thalovant_connector_spec")
    file = resources.files("thalovant_connector_spec") / "vectors"
    return json.loads((file / "music_assistant.json").read_text(encoding="utf-8"))


def test_the_route_carries_the_specs_music_verbs_except_the_ones_it_names() -> None:
    spec = pytest.importorskip("thalovant_connector_spec")
    registry = spec.load_registry()
    carried = MUSIC_CAPABILITIES | SHARED_CAPABILITIES
    wanted = set(registry.get("music_assistant").verbs)
    # a spec older than the verb this route says it does not carry simply lacks it
    assert carried <= wanted <= carried | NOT_CARRIED
    assert carried <= set(registry.get("home_assistant").verbs)
    assert not NOT_CARRIED & set(registry.get("home_assistant").verbs)


def test_the_private_vectors_still_match_the_specs_behaviours() -> None:
    """The copy has drifted in shape; this is what says whether it has drifted in substance."""
    spec = _spec_vectors()
    mine = json.loads((ROOT / "tests" / "music_vectors.json").read_text())
    assert mine["world"] == spec["world"]
    behaviours = {b["name"]: b for b in spec["behavior"]}
    for case in mine["cases"]:
        theirs = behaviours.pop(case["name"])
        assert case["action"] == {
            "v": 1,
            "capability": theirs["verb"],
            **theirs["args"],
        }, case["name"]
        assert case["expect"] == theirs["expect"], case["name"]
        assert case.get("device_name") == theirs.get("device_name"), case["name"]
    # what the spec has and this copy lacks is only what the route does not carry
    assert {b["verb"] for b in behaviours.values()} <= NOT_CARRIED


def test_the_version_is_the_same_everywhere() -> None:
    """The manifest is what Home Assistant reads; the changelog, the facts and pyproject follow it."""
    manifest = json.loads(
        (ROOT / "custom_components" / "thalovant" / "manifest.json").read_text()
    )
    version = manifest["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## (\d+\.\d+\.\d+)", changelog, flags=re.MULTILINE)
    assert newest is not None and newest.group(1) == version
    facts = (ROOT / "QUICK_FACTS.md").read_text(encoding="utf-8")
    assert f"`thalovant`, `{version}`" in _row(facts, "Home Assistant integration")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == version
