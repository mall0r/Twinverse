"""Check that the profile survives a change of the number of instances."""

from unittest.mock import Mock

from src.gui.controllers.settings_controller import SettingsController
from src.models import PlayerInstanceConfig, Profile


def _controller(profile):
    """Build a settings controller that works on the given profile."""
    controller = SettingsController.__new__(SettingsController)
    controller._device_manager = Mock()
    controller._logger = Mock()
    controller._profile = profile
    controller._on_change_callbacks = []
    return controller


def _ui_data(num_players, player_configs, selected_players, mode="splitscreen", orientation="vertical"):
    """Build the data the layout page reports."""
    return {
        "num_players": num_players,
        "mode": mode,
        "orientation": orientation,
        "player_configs": player_configs,
        "selected_players": selected_players,
    }


def test_profile_preservation():
    """Test that profile settings are preserved when number of players changes."""
    profile = Profile()
    profile.num_players = 2
    profile.player_configs[0].physical_device_id = "/dev/input/js0"
    profile.player_configs[0].grab_input_devices = True
    profile.player_configs[0].audio_device_id = "alsa_output.pci-0000_00_1f.3.analog-stereo"
    profile.player_configs[1].physical_device_id = "/dev/input/js1"
    profile.player_configs[1].grab_input_devices = False

    controller = _controller(profile)

    # Growing the instance count keeps the settings of the known players.
    controller.update_from_ui_data(_ui_data(3, list(profile.player_configs), [0, 1, 2]))

    assert profile.num_players == 3
    assert len(profile.player_configs) == 3
    assert profile.player_configs[0].physical_device_id == "/dev/input/js0"
    assert profile.player_configs[0].grab_input_devices is True
    assert profile.player_configs[0].audio_device_id == "alsa_output.pci-0000_00_1f.3.analog-stereo"
    assert profile.player_configs[1].physical_device_id == "/dev/input/js1"

    # Shrinking it keeps the settings of the players that are hidden.
    controller.update_from_ui_data(_ui_data(2, list(profile.player_configs[:2]), [0, 1]))

    assert profile.num_players == 2
    assert len(profile.player_configs) == 3
    assert profile.player_configs[2].physical_device_id is None

    # Growing it again restores what was configured before.
    controller.update_from_ui_data(_ui_data(3, list(profile.player_configs), [0, 1, 2]))

    assert profile.player_configs[0].physical_device_id == "/dev/input/js0"
    assert profile.player_configs[1].physical_device_id == "/dev/input/js1"


def test_settings_controller_logic():
    """Test the settings controller functionality without GUI dependencies."""
    profile = Profile()
    controller = _controller(profile)

    player_configs = []
    for i in range(4):
        config = PlayerInstanceConfig()
        config.physical_device_id = f"/dev/input/js{i}"
        config.grab_input_devices = i % 2 == 0  # Alternate grab input
        player_configs.append(config)

    controller.update_from_ui_data(_ui_data(4, player_configs, [0, 1, 2, 3], mode="fullscreen", orientation=None))

    assert profile.num_players == 4
    assert profile.mode == "fullscreen"
    assert [config.physical_device_id for config in profile.player_configs] == [f"/dev/input/js{i}" for i in range(4)]
    assert [config.grab_input_devices for config in profile.player_configs] == [True, False, True, False]
