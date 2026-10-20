"""Keep the launch layout and the instance settings consistent with the selection."""

from unittest.mock import Mock

import pytest

from src.core.exceptions import TwinverseError
from src.gui.controllers.settings_controller import SettingsController
from src.models import PlayerInstanceConfig, Profile
from src.services.cmd_builder import CommandBuilder
from src.services.device_manager import DeviceManager
from src.services.instance import InstanceService


@pytest.fixture
def manager(monkeypatch):
    """Report a single monitor, so the layout only depends on the selection."""
    monitors = [
        {
            "id": 0,
            "x": 0,
            "y": 0,
            "width": 1920,
            "height": 1080,
            "refresh_rate_mhz": 60000,
        }
    ]
    device_manager = DeviceManager()
    monkeypatch.setattr(device_manager, "get_screen_info", lambda: monitors)
    return device_manager


def _profile(selection, players=4):
    """Build a profile with a given selection."""
    profile = Profile(num_players=players, mode="splitscreen")
    profile.player_configs = [PlayerInstanceConfig() for _ in range(players)]
    profile.selected_players = selection
    return profile


@pytest.mark.parametrize("selection", [[0, 1], [2, 3], [0, 2], [1, 3], [0, 1, 2, 3], [3]])
def test_every_selected_instance_gets_a_valid_size(manager, selection):
    """A selection that skips an instance still fills the split from the first position."""
    profile = _profile(selection)

    for index in selection:
        width, height = manager.get_instance_dimensions(profile, index)
        assert width and height, f"instance {index} has no display size"


def test_the_command_never_executes_a_program_named_dashes(manager, tmp_path):
    """An unknown size must fail loudly instead of building a broken command."""
    profile = _profile([0, 1])
    manager.get_instance_dimensions = Mock(return_value=(None, None))
    builder = CommandBuilder(Mock(), profile, {}, manager, 0, tmp_path, None)

    with pytest.raises(TwinverseError, match="display size"):
        builder.build_command(["steam"])


def test_the_virtual_joystick_follows_the_selected_instances(monkeypatch, tmp_path):
    """Only the instances that take part in the launch need a device."""
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()
    service.virtual_device = Mock()
    service.virtual_device.create_virtual_joystick.return_value = "/dev/input/event99"
    service._virtual_joystick_path = None
    service._virtual_joystick_checked = False

    profile = _profile([2, 3])
    profile.player_configs[0] = PlayerInstanceConfig(physical_device_id="/dev/input/event1")
    profile.player_configs[1] = PlayerInstanceConfig(physical_device_id="/dev/input/event2")

    service._prepare_launch_profile(profile, None)

    service.virtual_device.create_virtual_joystick.assert_called_once()


def test_the_virtual_joystick_is_not_created_when_every_instance_has_one(monkeypatch, tmp_path):
    """A full selection with gamepads needs no virtual device."""
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()
    service.virtual_device = Mock()
    service._virtual_joystick_path = None
    service._virtual_joystick_checked = False

    profile = _profile([0, 1])
    profile.player_configs[0] = PlayerInstanceConfig(physical_device_id="/dev/input/event1")
    profile.player_configs[1] = PlayerInstanceConfig(physical_device_id="/dev/input/event2")

    service._prepare_launch_profile(profile, None)

    service.virtual_device.create_virtual_joystick.assert_not_called()


def _controller(tmp_path, monkeypatch, profile):
    """Build a settings controller that works on a temporary profile."""
    from src.core.config import Config

    monkeypatch.setattr(Config, "get_profile_path", lambda: tmp_path / "profile.json")
    controller = SettingsController.__new__(SettingsController)
    controller._device_manager = Mock()
    controller._logger = Mock()
    controller._profile = profile
    controller._on_change_callbacks = []
    return controller


def test_the_settings_of_hidden_instances_are_kept(tmp_path, monkeypatch):
    """Lowering the instance count must not throw away the settings of the others."""
    profile = Profile(num_players=4)
    profile.player_configs = [
        PlayerInstanceConfig(PHYSICAL_DEVICE_ID=f"/dev/input/event{index}", AUDIO_DEVICE_ID=f"sink{index}")
        for index in range(4)
    ]
    controller = _controller(tmp_path, monkeypatch, profile)

    controller.update_from_ui_data(
        {
            "num_players": 2,
            "mode": "splitscreen",
            "orientation": "vertical",
            "player_configs": list(profile.player_configs[:2]),
            "selected_players": [0, 1],
        }
    )

    assert len(profile.player_configs) == 4
    assert profile.player_configs[2].physical_device_id == "/dev/input/event2"
    assert profile.player_configs[3].audio_device_id == "sink3"

    # Raising the count again brings the saved settings back, because the
    # page restores the profile into the rows it creates.
    controller.update_from_ui_data(
        {
            "num_players": 4,
            "mode": "splitscreen",
            "orientation": "vertical",
            "player_configs": list(profile.player_configs),
            "selected_players": [0, 1, 2, 3],
        }
    )

    assert profile.player_configs[2].physical_device_id == "/dev/input/event2"
    assert profile.player_configs[3].audio_device_id == "sink3"


def test_the_splitscreen_orientation_survives_a_switch_to_fullscreen(tmp_path, monkeypatch):
    """Switching the mode back must not lose the chosen orientation."""
    profile = Profile(num_players=2, mode="splitscreen")
    profile.splitscreen = type(profile.splitscreen)(ORIENTATION="horizontal")
    controller = _controller(tmp_path, monkeypatch, profile)

    controller.update_from_ui_data(
        {
            "num_players": 2,
            "mode": "fullscreen",
            "orientation": None,
            "player_configs": [PlayerInstanceConfig(), PlayerInstanceConfig()],
            "selected_players": [0, 1],
        }
    )

    assert profile.splitscreen is not None
    assert profile.splitscreen.orientation == "horizontal"


def test_the_selection_is_kept_in_the_profile(tmp_path, monkeypatch):
    """The instances the user picked stay picked."""
    profile = Profile(num_players=4)
    controller = _controller(tmp_path, monkeypatch, profile)

    controller.update_from_ui_data(
        {
            "num_players": 4,
            "mode": "splitscreen",
            "orientation": "vertical",
            "player_configs": [PlayerInstanceConfig() for _ in range(4)],
            "selected_players": [0, 2, 3],
        }
    )

    assert profile.selected_players == [0, 2, 3]
    assert profile.launch_indices() == [0, 2, 3]
