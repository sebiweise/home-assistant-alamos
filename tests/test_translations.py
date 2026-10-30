"""Tests that keep the translation files in sync."""

import json
from pathlib import Path
from typing import Any

from custom_components.alamos.const import FEEDBACK_RESULTS

INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / "alamos"


def _load(name: str) -> dict[str, Any]:
    return json.loads((INTEGRATION_DIR / name).read_text(encoding="utf-8"))


def _keys(data: Any, prefix: str = "") -> set[str]:
    """Return the paths of all keys of a nested dict."""
    if not isinstance(data, dict):
        return set()
    keys: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        keys.add(path)
        keys |= _keys(value, path)
    return keys


def test_english_translation_matches_strings() -> None:
    """Home Assistant loads translations/en.json, not strings.json."""
    assert _load("translations/en.json") == _load("strings.json")


def test_german_translation_has_same_keys() -> None:
    """The German translation covers exactly the keys of strings.json."""
    assert _keys(_load("translations/de.json")) == _keys(_load("strings.json"))


def test_feedback_result_states_are_translated() -> None:
    """Every state of the last_feedback ENUM sensor has a translation."""
    states = _load("strings.json")["entity"]["sensor"]["last_feedback"]["state"]
    assert set(states) == set(FEEDBACK_RESULTS)
