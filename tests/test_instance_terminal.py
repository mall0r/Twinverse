"""Check terminal isolation and host launching without opening desktop windows."""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from src.core import Config, Utils
from src.core.exceptions import DependencyError
from src.models import PlayerInstanceConfig, Profile
from src.services.instance import InstanceService


@pytest.mark.parametrize("flatpak", [False, True])
@pytest.mark.parametrize("steamdeck", [False, True])
def test_terminal_matches_start_except_application(monkeypatch, tmp_path, flatpak, steamdeck):
    """Verify terminal launches preserve instance isolation and environment."""
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()
    service.device_manager = Mock()
    service._virtual_joystick_path = None
    service._virtual_joystick_checked = False
    service.virtual_device = Mock()
    service.virtual_device.create_virtual_joystick.return_value = "/dev/input/virtual-test"
    service.pids = {}
    service.pgids = {}
    service.processes = {}
    native_launch = Mock(return_value=(Mock(pid=123), 123))
    flatpak_launch = Mock(return_value=(Mock(pid=456), 456))
    service._launch_natively = native_launch
    service._launch_in_flatpak = flatpak_launch
    host_home = tmp_path / "host"
    monkeypatch.setattr(Path, "home", lambda: host_home)
    monkeypatch.setattr(Config, "get_steam_home_path", lambda i: tmp_path / f"player {i}")
    monkeypatch.setattr(Config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(Utils, "is_flatpak", lambda: flatpak)
    run = Mock(return_value=CompletedProcess([], 0, "/usr/bin/konsole\n", ""))
    monkeypatch.setattr("subprocess.run", run)
    value = "spaces; $(touch unexpected)"
    profile = Profile(
        enable_gamescope_wsi=True,
        use_gamescope=True,
        use_steamdeck_tag=steamdeck,
        player_configs=[
            PlayerInstanceConfig(),
            PlayerInstanceConfig(env={"TEST_VALUE": value}, audio_device_id="player-output"),
        ],
    )

    service.open_terminal(profile, 1)
    launch = flatpak_launch if flatpak else native_launch
    unused_launch = native_launch if flatpak else flatpak_launch
    _, command, terminal_env = launch.call_args.args
    service.virtual_device.create_virtual_joystick.assert_called_once()
    assert service.processes == {}

    service.launch_instance(profile, 1, use_gamescope_override=False)
    _, start_command, start_env = launch.call_args.args
    steam_command = ["steam", "-steamdeck"] if steamdeck else ["steam"]
    assert start_command[-len(steam_command) :] == steam_command
    assert command == start_command[: -len(steam_command)] + ["/usr/bin/konsole", "--separate", "-e", "bash", "-i"]
    assert terminal_env == start_env == {"ENABLE_GAMESCOPE_WSI": "0", "PULSE_SINK": "player-output"}
    assert command[0] == "bwrap"
    assert "/dev/input/virtual-test" in command
    unused_launch.assert_not_called()
    bind = command.index(str(tmp_path / "player 1"))
    assert command[bind - 1 : bind + 2] == ["--bind", str(tmp_path / "player 1"), str(host_home)]
    env = command.index("TEST_VALUE")
    assert command[env - 1 : env + 2] == ["--setenv", "TEST_VALUE", value]
    assert "gamescope" not in command
    assert "steam" not in command
    assert profile.enable_gamescope_wsi is True
    assert profile.use_gamescope is True
    assert (tmp_path / "player 1/.local/share/Steam/steamapps").is_dir()
    assert not (tmp_path / "player 0").exists()


def test_missing_terminal_reports_dependency_error(monkeypatch):
    """Verify missing host terminals raise a dependency error."""
    service = InstanceService.__new__(InstanceService)
    spawn = Mock(return_value=CompletedProcess([], 1, "", ""))
    monkeypatch.setattr(Utils, "flatpak_spawn_host", spawn)

    with pytest.raises(DependencyError, match="No supported terminal"):
        service.open_terminal(Profile(), 0)

    assert spawn.call_count == 1
