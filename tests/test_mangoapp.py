"""Verify the Steam performance menu and external MangoApp share their config."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.models import Profile
from src.services.cmd_builder import CommandBuilder


def builder(home, gamescope=True, steamdeck=True):
    """Create a command builder with mocked display dimensions."""
    devices = Mock()
    devices.get_instance_dimensions.return_value = (1280, 720)
    return CommandBuilder(
        Mock(), Profile(use_gamescope=gamescope, use_steamdeck_tag=steamdeck), {}, devices, 0, home, None
    )


def test_menu_updates_the_config_read_by_mangoapp(monkeypatch, tmp_path):
    """Verify Steam and MangoApp share a config isolated from other instances."""
    host_home = tmp_path / "host"
    monkeypatch.setattr(Path, "home", lambda: host_home)
    first = builder(tmp_path / "player 0")
    second = builder(tmp_path / "player 1")
    env = first.prepare_overlay_environment()
    other_env = second.prepare_overlay_environment()
    # Neither an empty config (skips file loading) nor read_cfg (duplicates
    # preset elements in 0.8.4) should reach MangoApp.
    assert env["MANGOHUD_CONFIG"] is None
    command = first.build_command()
    inline_config = command.index("MANGOHUD_CONFIG")
    assert command[inline_config - 1] == "--unsetenv"
    index = command.index("MANGOHUD_CONFIGFILE")
    steam_path = Path(command[index + 1])
    # Resolve the sandbox path through the actual home bind from the command.
    bind = command.index(str(first.home_path))
    assert command[bind - 1 : bind + 2] == ["--bind", str(first.home_path), str(host_home)]
    shared_path = first.home_path / steam_path.relative_to(host_home)
    assert shared_path == Path(env["MANGOHUD_CONFIGFILE"])
    assert shared_path.read_text() == "no_display\n"
    shared_path.write_text("fps\n")
    assert Path(env["MANGOHUD_CONFIGFILE"]).read_text() == "fps\n"
    assert Path(other_env["MANGOHUD_CONFIGFILE"]).read_text() == "no_display\n"
    assert "--mangoapp" in command


@pytest.mark.parametrize("gamescope,steamdeck", [(False, False), (False, True), (True, False)])
def test_unmanaged_launch_does_not_prepare_overlay(tmp_path, gamescope, steamdeck):
    """Verify launches without managed MangoApp do not create its config."""
    command_builder = builder(tmp_path / "player", gamescope, steamdeck)
    assert command_builder.prepare_overlay_environment() == {}
    assert not command_builder.home_path.exists()
