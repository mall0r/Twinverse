"""Use one saved placement order for preview, Gamescope dimensions and KWin."""

import json

import pytest
from pydantic import ValidationError

from src.core.config import Config
from src.gui.controllers.settings_controller import SettingsController
from src.models import PlayerInstanceConfig, Profile
from src.services.cmd_builder import CommandBuilder
from src.services.device_manager import DeviceManager


@pytest.mark.parametrize(
    "order,selected,expected",
    [
        (None, [], [0, 1, 2, 3]),
        ([2, 0, 3, 1], [], [2, 0, 3, 1]),
        ([2, 0, 3, 1], [0, 2], [2, 0]),
        ([2, 0, 3, 1], [1, 3], [3, 1]),
        ([2], [], [2, 0, 1, 3]),
        ([7, 2], [], [2, 0, 1, 3]),
        ([], [], [0, 1, 2, 3]),
    ],
)
def test_custom_layout_does_not_change_the_launch_queue(order, selected, expected):
    """Custom placement only reorders selected display slots, not process launches."""
    profile = Profile(num_players=4, selected_players=selected, layout_order=order)
    assert profile.layout_indices() == expected
    assert profile.launch_indices() == (sorted(selected) if selected else [0, 1, 2, 3])


@pytest.mark.parametrize("order", [[0, 0], [-1, 0], [True, 1], ["0", 1]])
def test_invalid_saved_assignments_are_rejected(order):
    """Reject ambiguous, duplicate or negative instance identities in custom layouts."""
    with pytest.raises(ValidationError):
        Profile(layout_order=order)


def test_order_survives_profile_save_and_reload(monkeypatch, tmp_path):
    """Persist custom placement while keeping old profiles automatic by default."""
    path = tmp_path / "profile.json"
    monkeypatch.setattr(Config, "get_profile_path", lambda: path)
    profile = Profile(num_players=4, layout_order=[2, 0, 3, 1])
    profile.save()
    assert json.loads(path.read_text())["LAYOUT_ORDER"] == [2, 0, 3, 1]
    assert Profile.load().layout_indices() == [2, 0, 3, 1]
    profile.layout_order = None
    profile.save()
    assert "LAYOUT_ORDER" not in json.loads(path.read_text())
    assert Profile.load().layout_indices() == [0, 1, 2, 3]


def test_hidden_instance_order_is_restored_when_count_grows():
    """Reducing the instance count must not discard the saved positions of hidden players."""
    profile = Profile(num_players=4, layout_order=[3, 1, 2, 0])
    profile.num_players = 2
    assert profile.layout_indices() == [1, 0]
    profile.num_players = 4
    assert profile.layout_indices() == [3, 1, 2, 0]


def test_controller_preserves_custom_and_automatic_placement():
    """Accept explicit automatic selection without overwriting placement in legacy UI data."""
    controller = SettingsController.__new__(SettingsController)
    controller._profile = Profile(num_players=3, layout_order=[2, 0, 1])
    data = {
        "num_players": 3,
        "mode": "splitscreen",
        "orientation": "vertical",
        "player_configs": [PlayerInstanceConfig() for _ in range(3)],
        "selected_players": [0, 1, 2],
    }
    controller.update_from_ui_data(data)
    assert controller.get_profile().layout_order == [2, 0, 1]
    controller.update_from_ui_data(dict(data, layout_order=[1, 2, 0]))
    assert controller.get_profile().layout_order == [1, 2, 0]
    controller.update_from_ui_data(dict(data, layout_order=None))
    assert controller.get_profile().layout_indices() == [0, 1, 2]


@pytest.fixture
def manager(monkeypatch):
    """Use two different monitor sizes and rates so incorrect assignments are detectable."""
    device_manager = DeviceManager()
    monkeypatch.setattr(
        device_manager,
        "get_screen_info",
        lambda: [
            {"id": 0, "name": "HDMI-A-1", "width": 1920, "height": 1080, "refresh_rate_mhz": 75000},
            {"id": 1, "name": "DP-1", "width": 2560, "height": 1440, "refresh_rate_mhz": 144000},
        ],
    )
    return device_manager


def test_three_player_swap_updates_gamescope_dimensions(manager, tmp_path):
    """Moving an instance into the larger three-player slot must change all four size flags."""
    profile = Profile(num_players=3, layout_order=[2, 0, 1])
    assert manager.get_instance_dimensions(profile, 2) == (960, 1080)
    assert manager.get_instance_dimensions(profile, 0) == (960, 540)
    command = CommandBuilder(profile, {}, manager, 2, tmp_path, None)._build_gamescope_command(False)
    for flag, expected in (("-W", "960"), ("-H", "1080"), ("-w", "960"), ("-h", "1080")):
        assert command[command.index(flag) + 1] == expected


@pytest.mark.parametrize("mode,players", [("fullscreen", 2), ("splitscreen", 6)])
def test_monitor_size_and_refresh_follow_custom_placement(manager, mode, players):
    """A cross-monitor swap must move the dimensions and refresh rate together."""
    profile = Profile(mode=mode, num_players=players, layout_order=list(reversed(range(players))))
    assert manager.get_instance_refresh_rate(profile, 0) == 144
    assert manager.get_instance_refresh_rate(profile, players - 1) == 75
    expected = (2560, 1440) if mode == "fullscreen" else (1280, 1440)
    assert manager.get_instance_dimensions(profile, 0) == expected


def test_partial_selection_only_allocates_slots_to_selected_instances(manager):
    """Unchecked instances never take a visible slot or shift the configured monitor group."""
    profile = Profile(num_players=6, selected_players=[0, 2, 5], layout_order=[5, 4, 3, 2, 1, 0])
    assert profile.layout_indices() == [5, 2, 0]
    assert manager.get_instance_dimensions(profile, 5) == (960, 1080)
    assert manager.get_instance_dimensions(profile, 0) == (960, 540)
    assert manager.get_instance_refresh_rate(profile, 0) == 75
