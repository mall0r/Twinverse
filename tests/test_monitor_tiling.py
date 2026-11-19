"""Connector-based planning and saved profile validation."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.core.tiling import TEMPLATES, build_tiling_plan, monitor_key
from src.models import MonitorLayoutConfig, Profile


def test_profile_roundtrip():
    """Preserve typed monitor settings through aliased profile serialization."""
    profile = Profile(MONITOR_LAYOUTS={"DP-1": {"template": "columns", "players": [1, None]}})
    assert isinstance(profile.monitor_layouts["DP-1"], MonitorLayoutConfig)
    assert Profile.model_validate_json(profile.model_dump_json(by_alias=True)) == profile
    assert "MONITOR_LAYOUTS" in profile.model_dump(by_alias=True)
    assert Profile().monitor_layouts == {}


@pytest.mark.parametrize(
    "config",
    [
        {"template": "invalid"},
        {"template": "fullscreen", "players": [0, None]},
        {"template": "grid", "players": [1, 1]},
        {"players": [-1]},
        {"players": [True]},
        {"players": ["0"]},
        {"players": [0.0]},
    ],
)
def test_invalid_configs(config):
    """Reject invalid templates, capacities and player identifiers."""
    with pytest.raises(ValidationError):
        MonitorLayoutConfig(**config)


@pytest.mark.parametrize(
    "template,rectangles",
    [
        ("fullscreen", ((0, 0, 1, 1),)),
        ("columns", ((0, 0, 0.5, 1), (0.5, 0, 0.5, 1))),
        ("rows", ((0, 0, 1, 0.5), (0, 0.5, 1, 0.5))),
        ("main-left", ((0, 0, 0.5, 1), (0.5, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5))),
        ("main-top", ((0, 0, 1, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5))),
        ("grid", ((0, 0, 0.5, 0.5), (0.5, 0, 0.5, 0.5), (0, 0.5, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5))),
    ],
)
def test_templates(template, rectangles):
    """Verify each template's rectangles, capacity and overflow handling."""
    assert TEMPLATES[template].rectangles == rectangles
    plan = build_tiling_plan(list(range(5)), [{"id": 0, "name": "DP"}], {"DP": {"template": template}})
    assert plan.monitors[0].players == list(range(len(rectangles)))
    assert plan.unassigned == list(range(len(rectangles), 5))


def test_reservations_precede_fill_and_inputs_unchanged():
    """Reserve explicit players before filling holes without mutating inputs."""
    displays = [{"id": 1, "name": "B"}, {"id": 0, "name": "A"}]
    configs = {"A": {"template": "grid", "players": [99, 2, 2, 5]}, "B": {"players": [0]}, "offline": {"players": [1]}}
    instances = [0, 1, 2, 3]
    before = deepcopy((instances, displays, configs))
    plan = build_tiling_plan(instances, displays, configs)
    assert [(m.key, m.index, m.players) for m in plan.monitors] == [("A", 0, [1, 2, 3, None]), ("B", 1, [0])]
    assert (instances, displays, configs) == before
    assert not plan.unassigned
    assert build_tiling_plan(instances, list(reversed(displays)), configs) == plan


def test_empty_missing_and_overflow():
    """Handle missing displays, default layouts and unassigned players."""
    assert build_tiling_plan([2, 0], [], {"offline": {}}).unassigned == [2, 0]
    plan = build_tiling_plan([2, 0], [{"id": 8}], {})
    assert plan.monitors[0].template.id == "fullscreen"
    assert plan.monitors[0].players == [2]
    assert plan.unassigned == [0]
    assert build_tiling_plan([], [{"name": "A"}], {}).monitors[0].players == [None]
    assert monitor_key({"id": 0}, 4) == "monitor-0"
    assert monitor_key({}, 4) == "monitor-4"
