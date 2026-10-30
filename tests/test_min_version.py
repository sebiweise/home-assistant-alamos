"""The minimum Home Assistant version is maintained in hacs.json only."""

import json
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).parent.parent
BLUEPRINTS = sorted((ROOT / "blueprints" / "automation" / "alamos").glob("*.yaml"))


def _min_version() -> str:
    return json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]


class _BlueprintLoader(yaml.SafeLoader):
    """Load blueprints, keeping !input tags as plain values."""


_BlueprintLoader.add_constructor(
    "!input", lambda loader, node: loader.construct_scalar(node)
)


def test_blueprints_use_min_version() -> None:
    """Every blueprint requires the minimum version from hacs.json."""
    assert BLUEPRINTS
    for path in BLUEPRINTS:
        blueprint = yaml.load(path.read_text(encoding="utf-8"), _BlueprintLoader)
        assert (
            blueprint["blueprint"]["homeassistant"]["min_version"] == _min_version()
        ), path.name


def test_min_version_is_tested() -> None:
    """The tests-min CI job runs the minimum version from hacs.json."""
    lock = (ROOT / "requirements_test_min.txt").read_text(encoding="utf-8")
    assert re.search(rf"^homeassistant=={re.escape(_min_version())} ", lock, re.M)


def test_review_instructions_use_min_version() -> None:
    """The CodeRabbit instructions name the minimum version from hacs.json."""
    config = (ROOT / ".coderabbit.yaml").read_text(encoding="utf-8")
    assert re.findall(r"min\. HA ([0-9.]+)", config) == [_min_version()]
