"""End-to-end tests for remembering each player's last assigned controller across disconnects."""

# flake8: noqa: E402

import json
from pathlib import Path
from unittest.mock import Mock

import gi
import pytest

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gtk

from src.core.config import Config
from src.core.utils import format_input_device_name
from src.gui.controllers.settings_controller import SettingsController
from src.gui.pages.layout_settings_page import LayoutSettingsPage
from src.models import PlayerInstanceConfig, Profile
from src.services.cmd_builder import CommandBuilder
from src.services.instance import InstanceService
from src.services.virtual_uinput import (
    ENV_HIDRAW_FILTER,
    ENV_PHYSICAL_BRIDGE,
    VirtualUinputConfig,
)


def _require_gtk_display() -> None:
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A GTK display is required")
    Adw.init()


def _setenv_map(cmd: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    idx = 0
    while idx < len(cmd):
        if cmd[idx] == "--setenv" and idx + 2 < len(cmd):
            env[cmd[idx + 1]] = cmd[idx + 2]
            idx += 3
        else:
            idx += 1
    return env


def test_format_input_device_name_produces_human_readable_labels():
    """Derive clean controller names from by-id, by-path, and event device paths."""
    assert (
        format_input_device_name("/dev/input/by-id/usb-Microsoft_X-Box_360_pad-event-joystick")
        == "Microsoft X-box 360 Pad"
    )
    assert format_input_device_name("/dev/input/by-path/pci-0000:00:14.0-usb-0:2-event-joystick") != ""
    assert "/dev/input/" not in format_input_device_name("/dev/input/by-id/usb-8BitDo_Pro_2-event-joystick")


def test_player_instance_config_normalizes_physical_device_fields():
    """Strip whitespace from device fields and clear stored name when ID is cleared."""
    cfg = PlayerInstanceConfig(
        PHYSICAL_DEVICE_ID="  /dev/input/by-id/usb-pad-event-joystick  ",
        PHYSICAL_DEVICE_NAME="  Xbox Pad  ",
    )
    assert cfg.physical_device_id == "/dev/input/by-id/usb-pad-event-joystick"
    assert cfg.physical_device_name == "Xbox Pad"

    cleared = PlayerInstanceConfig(PHYSICAL_DEVICE_ID="   ", PHYSICAL_DEVICE_NAME="Orphan Name")
    assert cleared.physical_device_id is None
    assert cleared.physical_device_name is None

    # Legacy JSON profiles without PHYSICAL_DEVICE_NAME continue to load cleanly.
    legacy = PlayerInstanceConfig.model_validate({"PHYSICAL_DEVICE_ID": "/dev/input/by-id/usb-pad-event-joystick"})
    assert legacy.physical_device_id == "/dev/input/by-id/usb-pad-event-joystick"
    assert legacy.physical_device_name is None


def test_player2_controller_persists_across_close_unplug_reopen_and_resave(monkeypatch, tmp_path: Path):
    """Assign controller to Player 2 -> save -> reopen with controller off -> save -> assignment remains."""
    _require_gtk_display()
    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(Config, "get_profile_path", lambda: profile_path)

    displays = [{"name": "HDMI-A-1", "width": 1920, "height": 1080}]
    pad_id = "/dev/input/by-id/usb-Sony_DualSense_Controller-event-joystick"
    pad_name = "DualSense Wireless Controller"

    # 1. Session 1: controller is connected and assigned to Player 2 (index 1).
    controller1 = SettingsController(Mock())
    page1 = LayoutSettingsPage()
    page1.load_data(
        controller1.get_profile(),
        {"displays": displays, "joystick": [{"id": pad_id, "name": pad_name}], "audio": []},
        {0: True, 1: True},
    )
    page1.player_rows[1].joystick_row.set_selected(1)
    controller1.update_from_ui_data(page1.get_data())
    controller1.save_profile()

    saved_raw = json.loads(profile_path.read_text(encoding="utf-8"))
    assert saved_raw["PLAYERS"][1]["PHYSICAL_DEVICE_ID"] == pad_id
    assert saved_raw["PLAYERS"][1]["PHYSICAL_DEVICE_NAME"] == pad_name

    # 2. Session 2: user closes Twinverse, turns off the controller, and reopens Twinverse.
    controller2 = SettingsController(Mock())
    page2 = LayoutSettingsPage()
    page2.load_data(
        controller2.get_profile(),
        {"displays": displays, "joystick": [], "audio": []},
        {0: True, 1: True},
    )
    player2_row = page2.player_rows[1]
    assert player2_row.has_controller_selected()
    assert not player2_row.is_controller_connected()
    assert player2_row.get_config().physical_device_id == pad_id
    assert player2_row.get_config().physical_device_name == pad_name

    # Clicking Play or changing unrelated settings triggers update_from_ui_data + save_profile;
    # Player 2's disconnected controller must NOT be wiped out.
    controller2.update_from_ui_data(page2.get_data())
    controller2.save_profile()

    reloaded = Profile.load()
    assert reloaded.player_configs[1].physical_device_id == pad_id
    assert reloaded.player_configs[1].physical_device_name == pad_name


def test_launch_pipeline_binds_hotplug_bridge_for_disconnected_remembered_controller(monkeypatch, tmp_path: Path):
    """Launching Player 2 with an unplugged saved controller wires twinverse-input-bridge for auto-reconnect."""
    saved_id = str(tmp_path / "by-id/usb-missing-pad-event-joystick")
    profile = Profile(
        NUM_PLAYERS=2,
        USE_GAMESCOPE=True,
        PLAYERS=[
            PlayerInstanceConfig(),
            PlayerInstanceConfig(
                PHYSICAL_DEVICE_ID=saved_id,
                PHYSICAL_DEVICE_NAME="DualSense Wireless Controller",
            ),
        ],
    )

    # 1. _prepare_launch_profile skips creating a virtual joystick when the launched player has a saved ID,
    #    even while that controller is disconnected.
    service = InstanceService.__new__(InstanceService)
    service.virtual_device = Mock()
    service.virtual_device.create_virtual_joystick.return_value = "/dev/input/event99"
    service._virtual_joystick_path = None
    service._virtual_joystick_checked = False

    profile_only_p2 = Profile(
        NUM_PLAYERS=2,
        selected_players=[1],
        PLAYERS=[
            PlayerInstanceConfig(),
            PlayerInstanceConfig(PHYSICAL_DEVICE_ID=saved_id, PHYSICAL_DEVICE_NAME="DualSense"),
        ],
    )
    service._prepare_launch_profile(profile_only_p2, use_gamescope_override=False)
    service.virtual_device.create_virtual_joystick.assert_not_called()

    # 2. _validate_input_devices returns resolved path=None (unplugged) while preserving joystick_device_id.
    device_info = service._validate_input_devices(profile, 1, 2)
    assert device_info["joystick_path_str_for_instance"] is None
    assert device_info["joystick_device_id_for_instance"] == saved_id

    # 3. CommandBuilder wires twinverse-input-bridge with --device-id (no --resolved-event)
    #    and enables TWINVERSE_PHYSICAL_BRIDGE=1 + TWINVERSE_HIDRAW_FILTER=1 without any placeholder joystick.
    home = tmp_path / "home_2"
    home.mkdir()
    fake_cfg = VirtualUinputConfig(
        socket_dir=Path("/home/user/.tw-in/sock"),
        preload_paths=(Path("/home/user/.tw-in/lib64/libtwinverse_uinput.so"),),
        host_socket_dir=home / ".tw-in/sock",
        bridge_binary=home / ".tw-in/bin/twinverse-input-bridge",
    )
    monkeypatch.setattr("src.services.cmd_builder.stage_virtual_uinput", lambda *a, **kw: fake_cfg)
    monkeypatch.setattr("src.services.cmd_builder.find_hidraw_devices_to_mask", lambda *a, **kw: ["/dev/hidraw0"])
    monkeypatch.setattr("src.services.cmd_builder.build_webhelper_mounts", lambda *a, **kw: [])

    dm = Mock()
    dm.get_instance_dimensions.return_value = (1280, 720)
    dm.get_instance_refresh_rate.return_value = 60

    builder = CommandBuilder(profile, device_info, dm, 1, home, "/dev/input/event99")
    cmd = builder.build_command(["steam"])

    assert builder.input_bridge_command == [
        str(home / ".tw-in/bin/twinverse-input-bridge"),
        "--socket-dir",
        str(home / ".tw-in/sock"),
        "--device-id",
        saved_id,
    ]
    assert "--resolved-event" not in builder.input_bridge_command

    env = _setenv_map(cmd)
    assert env[ENV_PHYSICAL_BRIDGE] == "1"
    assert env[ENV_HIDRAW_FILTER] == "1"
    assert not any(
        cmd[i : i + 3] == ["--dev-bind", "/dev/input/event99", "/dev/input/event99"] for i in range(len(cmd) - 2)
    )
    assert not any(cmd[i : i + 3] == ["--ro-bind", "/dev/null", "/dev/hidraw0"] for i in range(len(cmd) - 2))
