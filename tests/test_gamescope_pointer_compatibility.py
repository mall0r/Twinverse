"""Verify the opt-in Gamescope pointer workaround is scoped to each launch."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.models import PlayerInstanceConfig, Profile
from src.services.cmd_builder import CommandBuilder

TOUCH_MODE_ENV = "gamescope_touch_click_mode"


@pytest.fixture
def touch_mode_environment(monkeypatch, tmp_path):
    """Read the touch-mode override without starting a Steam instance."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "host")
    devices = Mock()
    devices.get_instance_dimensions.return_value = (1280, 720)
    devices.get_instance_refresh_rate.return_value = 60

    def values(profile):
        command = CommandBuilder(profile, {}, devices, 0, tmp_path / "player", None).build_command()
        return [command[i + 2] for i in range(len(command)) if command[i : i + 2] == ["--setenv", TOUCH_MODE_ENV]]

    return values


@pytest.mark.parametrize(
    "options,expected",
    [
        ({}, []),
        ({"enable_gamescope_pointer_compatibility": True}, [CommandBuilder.GAMESCOPE_POINTER_COMPATIBILITY]),
        ({"enable_gamescope_pointer_compatibility": True, "use_gamescope": False}, []),
    ],
)
def test_pointer_workaround_requires_gamescope_and_opt_in(touch_mode_environment, options, expected):
    """Leave existing profiles and direct Steam launches unchanged."""
    assert touch_mode_environment(Profile(**options)) == expected


@pytest.mark.parametrize("enabled", [False, True])
def test_manual_touch_mode_takes_precedence(touch_mode_environment, enabled):
    """Honor an explicit player override regardless of the engine preference."""
    profile = Profile(
        enable_gamescope_pointer_compatibility=enabled,
        env={TOUCH_MODE_ENV: "2"},
        player_configs=[PlayerInstanceConfig(env={TOUCH_MODE_ENV: "0"})],
    )
    assert touch_mode_environment(profile) == ["0"]


def test_profile_saves_pointer_compatibility():
    """Keep the opt-in choice across application restarts."""
    profile = Profile.load()
    assert profile.enable_gamescope_pointer_compatibility is False
    profile.enable_gamescope_pointer_compatibility = True
    profile.save()
    assert Profile.load().enable_gamescope_pointer_compatibility is True
