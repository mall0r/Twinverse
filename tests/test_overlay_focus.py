"""Exercise the narrow-overlay focus repair decisions without touching X11."""

import importlib.util
from pathlib import Path

import pytest

from src.core import Utils

STEAM = 769
GAME = 1374490


def load_helper():
    """Load the standalone helper that runs on the host inside the sandbox."""
    path = Utils.get_base_path() / "res/steam/overlay_focus.py"
    spec = importlib.util.spec_from_file_location("overlay_focus", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "reported, repaired, expected",
    [(GAME, False, STEAM), (STEAM, True, None), (GAME, True, STEAM)],
)
def test_narrow_overlay_takes_controller_focus(reported, repaired, expected):
    """Repair only Steam's narrow interactive overlay while a game is displayed."""
    decision = load_helper().desired_focus(STEAM, GAME, 1, 1, 960, reported, repaired)
    assert decision == expected


@pytest.mark.parametrize(
    "graphics, width, focus",
    [(GAME, 1920, 1), (0, 960, 1), (GAME, 0, 0), (GAME, 960, 0)],
)
def test_unrelated_states_are_left_untouched(graphics, width, focus):
    """Skip wide overlays, idle UI, and notifications without input focus."""
    assert load_helper().desired_focus(STEAM, graphics, 1, focus, width, GAME, False) is None


def test_focus_returns_to_the_game_when_the_menu_closes():
    """Restore the graphics app so the game regains the controller configuration."""
    assert load_helper().desired_focus(GAME, GAME, 0, 0, 0, STEAM, True) == GAME
    assert load_helper().desired_focus(GAME, GAME, 0, 0, 0, STEAM, False) is None


def test_poll_interval_keeps_cpu_use_negligible():
    """Poll fast enough to be invisible, while staying nearly free in CPU."""
    assert load_helper().POLL_INTERVAL == 0.1


def test_helper_only_uses_the_python_standard_library():
    """Keep the helper runnable with the host Python inside the instance sandbox."""
    source = (Path(__file__).parent.parent / "res/steam/overlay_focus.py").read_text()
    for line in source.splitlines():
        if line.startswith("import "):
            assert line.split()[1].split(".")[0] in {"ctypes", "ctypes.util", "fcntl", "os", "sys", "time"}
