"""Verify current monitor frequencies follow the instance layout."""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.models import PlayerInstanceConfig, Profile
from src.services.cmd_builder import CommandBuilder
from src.services.device_manager import DeviceManager
from src.services.kde_manager import KdeManager


@pytest.fixture
def manager(monkeypatch):
    """Enumerate the secondary first in both APIs to catch primary assignment errors."""
    monitors = [
        SimpleNamespace(name="DP-1", x=1920, y=0, width=2560, height=1440, is_primary=False),
        SimpleNamespace(name="HDMI-A-1", x=0, y=0, width=1920, height=1080, is_primary=True),
    ]
    hdmi, dp = Mock(), Mock()
    hdmi.get_connector.return_value = "HDMI-A-1"
    hdmi.get_refresh_rate.return_value = 74973
    hdmi.get_geometry.return_value = SimpleNamespace(width=1920, height=1080)
    dp.get_connector.return_value = "DP-1"
    dp.get_refresh_rate.return_value = 143980
    dp.get_geometry.return_value = SimpleNamespace(width=2560, height=1440)
    display = Mock()
    display.get_monitors.return_value = [dp, hdmi]
    monkeypatch.setattr("src.services.device_manager.get_monitors", lambda: monitors)
    monkeypatch.setattr("src.services.device_manager.Gdk.Display.get_default", lambda: display)
    return DeviceManager()


@pytest.mark.parametrize(
    "reported, logical, expected",
    [
        ((1920, 1080), (1080, 1920), (1080, 1920)),
        ((1920, 1080), (720, 1280), (1080, 1920)),
        ((1080, 1920), (720, 1280), (1080, 1920)),
        ((1080, 1920), (1920, 1080), (1920, 1080)),
        ((1920, 1080), (1280, 720), (1920, 1080)),
        ((1920, 1080), (0, 0), (1920, 1080)),
        ((1920, 1080), (1000, 1000), (1920, 1080)),
    ],
)
@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
@pytest.mark.parametrize("players", [1, 2, 3, 4])
def test_rotated_monitor_dimensions(manager, reported, logical, expected, orientation, players):
    """Orient pixel dimensions once, even with scaling or an already rotated backend."""
    from gi.repository import Gdk

    from src.core import LayoutCalculator

    monitor = manager.get_ordered_monitors()[0]
    monitor.width, monitor.height = reported
    Gdk.Display.get_default().get_monitors()[1].get_geometry.return_value = SimpleNamespace(
        width=logical[0], height=logical[1]
    )
    profile = Profile(num_players=players, player_configs=[PlayerInstanceConfig() for _ in range(players)])
    profile.splitscreen.orientation = orientation
    info = manager.get_screen_info()[0]
    assert (info["width"], info["height"]) == expected
    # The other connector must keep its own dimensions and frequency.
    assert manager.get_screen_info()[1]["width"] == 2560
    assert manager.get_instance_refresh_rate(profile, 0) == 75
    for index in range(players):
        dimensions = LayoutCalculator.calculate_position(*expected, players, index, orientation)[2:]
        assert manager.get_instance_dimensions(profile, index) == dimensions
        command = CommandBuilder(profile, {}, manager, index, Path("/unused"), None)._build_gamescope_command(False)
        for flag, value in zip(("-W", "-H", "-w", "-h"), dimensions * 2):
            assert command[command.index(flag) + 1] == str(value)


def test_orientation_is_read_again_for_new_launch(manager):
    """Changing rotation affects the next launch without restarting the application."""
    from gi.repository import Gdk

    profile = Profile()
    assert manager.get_instance_dimensions(profile, 0) == (960, 1080)
    Gdk.Display.get_default().get_monitors()[1].get_geometry.return_value = SimpleNamespace(width=1080, height=1920)
    assert manager.get_instance_dimensions(profile, 0) == (540, 1920)


@pytest.mark.parametrize("available_connector", [None, "UNKNOWN"])
def test_missing_orientation_preserves_reported_dimensions(manager, monkeypatch, available_connector):
    """Keep screeninfo's dimensions when GDK cannot identify the output."""
    from gi.repository import Gdk

    display = Gdk.Display.get_default()
    if available_connector is None:
        monkeypatch.setattr("src.services.device_manager.Gdk.Display.get_default", lambda: None)
    else:
        for monitor in display.get_monitors():
            monitor.get_connector.return_value = available_connector
    assert manager.get_instance_dimensions(Profile(), 0) == (960, 1080)


@pytest.mark.parametrize(
    "mode, players, index, dimensions, hz",
    [
        ("fullscreen", 2, 0, (1920, 1080), 75),
        ("fullscreen", 2, 1, (2560, 1440), 144),
        ("splitscreen", 2, 0, (960, 1080), 75),
        ("splitscreen", 2, 1, (960, 1080), 75),
        ("splitscreen", 6, 4, (1280, 1440), 144),
        ("splitscreen", 6, 5, (1280, 1440), 144),
    ],
)
def test_refresh_follows_layout(manager, mode, players, index, dimensions, hz):
    """Both launch flags use the current rate of the monitor assigned by layout."""
    profile = Profile(mode=mode, num_players=players, player_configs=[PlayerInstanceConfig() for _ in range(players)])
    assert manager.get_instance_dimensions(profile, index) == dimensions
    builder = CommandBuilder(profile, {}, manager, index, Path("/unused"), None)
    command = builder._build_gamescope_command(False)
    assert command[command.index("-r") + 1] == str(hz)
    assert command[command.index("-o") + 1] == str(hz)


def test_instance_beyond_the_last_monitor_reuses_the_first(manager, tmp_path):
    """An instance with no monitor of its own borrows the first monitor's settings."""
    profile = Profile(mode="fullscreen", num_players=3, player_configs=[PlayerInstanceConfig() for _ in range(3)])

    # Instance 3 has no third monitor, so it must match instance 1 exactly.
    assert manager.get_instance_dimensions(profile, 2) == manager.get_instance_dimensions(profile, 0)
    assert manager.get_instance_refresh_rate(profile, 2) == manager.get_instance_refresh_rate(profile, 0)

    builder = CommandBuilder(profile, {}, manager, 2, tmp_path, None)
    command = builder._build_gamescope_command(False)
    assert command[:5] == ["gamescope", "-e", "-W", "1920", "-H"]

    # The command must stay a single valid program for bwrap to exec.
    full = builder.build_command(["steam"])
    assert full[full.index("--") + 1] == "gamescope"


def test_splitscreen_group_without_a_monitor_reuses_the_first(manager):
    """Splitscreen groups past the last monitor fall back to the first one too."""
    profile = Profile(mode="splitscreen", num_players=12, player_configs=[PlayerInstanceConfig() for _ in range(12)])
    # Two monitors, so the third group (instances 9-12) has none of its own.
    assert manager._get_instance_monitor_index(profile, 8) == 2
    assert manager._resolve_monitor_index(profile, 8, 2) == 0
    assert manager.get_instance_dimensions(profile, 8) == manager.get_instance_dimensions(profile, 0)


def test_unknown_refresh_does_not_force_sixty(manager, monkeypatch):
    """Do not invent a monitor frequency when display information is unavailable."""
    monkeypatch.setattr("src.services.device_manager.Gdk.Display.get_default", lambda: None)
    profile = Profile()
    assert manager.get_instance_refresh_rate(profile, 0) is None
    builder = CommandBuilder(profile, {}, manager, 0, Path("/unused"), None)
    command = builder._build_gamescope_command(False)
    assert "-r" not in command and "-o" not in command


def test_refresh_is_read_again_for_new_launch(manager):
    """Changing the desktop mode affects the next launch without a stored setting."""
    from gi.repository import Gdk

    monitor = Gdk.Display.get_default().get_monitors()[1]
    assert manager.get_instance_refresh_rate(Profile(), 0) == 75
    monitor.get_refresh_rate.return_value = 59940
    assert manager.get_instance_refresh_rate(Profile(), 0) == 60


@pytest.mark.parametrize(
    "script, function, mode, players",
    [
        ("kwin_gamescope.js", "gamescopePerMonitor", "fullscreen", 2),
        ("kwin_gamescope_vertical.js", "gamescopeSplitscreen", "splitscreen", 6),
        ("kwin_gamescope_horizontal.js", "gamescopeSplitscreen", "splitscreen", 6),
    ],
)
def test_kwin_placement_matches_refresh_assignment(manager, script, function, mode, players, monkeypatch, tmp_path):
    """Execute placement scripts with a KWin monitor order opposite to the layout."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to execute the KWin placement scripts")
    profile = Profile(mode=mode, num_players=players, player_configs=[PlayerInstanceConfig() for _ in range(players)])
    if "horizontal" in script:
        profile.splitscreen.orientation = "horizontal"
    kde = KdeManager.__new__(KdeManager)
    kde.logger = Mock()
    kde.session_bus = Mock()
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr("src.services.kde_manager.Config.cache_dir", lambda: tmp_path)
    kde.start_kwin_script(profile)
    source = kde._kwin_script_temp_path.read_text()
    harness = """
const clients = Array.from({length: PLAYERS}, () => ({resourceClass: "gamescope"}));
const workspace = {
  screens: [
    {name: "DP-1", geometry: {x: 1920, y: 0, width: 2560, height: 1440}},
    {name: "HDMI-A-1", geometry: {x: 0, y: 0, width: 1920, height: 1080}}
  ],
  windowList: () => clients,
  activeWindow: clients[0],
  windowAdded: {connect: () => {}},
  windowRemoved: {connect: () => {}},
  windowActivated: {connect: () => {}}
};
""".replace(
        "PLAYERS", str(players)
    )
    result = subprocess.check_output(
        [node], input=harness + source + f"\n{function}(); console.log(JSON.stringify(clients));", text=True
    )
    for index, client in enumerate(json.loads(result)):
        monitor_hz = 75 if client["frameGeometry"]["x"] < 1920 else 144
        assert manager.get_instance_refresh_rate(profile, index) == monitor_hz
    assert json.loads(result)[0]["frameGeometry"]["x"] == 0


def test_primary_on_right_is_still_first(manager):
    """Primary status takes precedence over physical position and enumeration order."""
    monitors = manager.get_ordered_monitors()
    monitors[0].is_primary = False
    monitors[1].is_primary = True
    assert [m.name for m in manager.get_ordered_monitors()] == ["DP-1", "HDMI-A-1"]
    assert manager.get_instance_refresh_rate(Profile(mode="fullscreen"), 0) == 144
    assert manager.get_instance_refresh_rate(Profile(mode="fullscreen"), 1) == 75


def test_missing_primary_status_uses_plasma(manager, monkeypatch):
    """Handle Flatpak listing the secondary first without either primary flag."""
    from src.services.device_manager import get_monitors

    for monitor in get_monitors():
        monitor.is_primary = None
    plasma = Mock()
    plasma.evaluateScript.return_value = "HDMI-A-1\n"
    bus = Mock()
    bus.get.return_value = plasma
    monkeypatch.setattr("src.services.device_manager.pydbus.SessionBus", lambda: bus)
    assert [monitor.name for monitor in manager.get_ordered_monitors()] == ["HDMI-A-1", "DP-1"]
    bus.get.assert_called_with("org.kde.plasmashell", "/PlasmaShell")
    assert "screenForConnector(name) === 0" in plasma.evaluateScript.call_args.args[0]
    assert manager.get_instance_refresh_rate(Profile(mode="fullscreen"), 0) == 75
    assert manager.get_instance_refresh_rate(Profile(mode="fullscreen"), 1) == 144


def test_unavailable_plasma_preserves_monitor_order(manager, monkeypatch):
    """Allow non-Plasma sessions to keep their enumeration when no primary is known."""
    from src.services.device_manager import get_monitors

    for monitor in get_monitors():
        monitor.is_primary = None
    monkeypatch.setattr("src.services.device_manager.pydbus.SessionBus", Mock(side_effect=RuntimeError("Unavailable")))
    assert [monitor.name for monitor in manager.get_ordered_monitors()] == ["DP-1", "HDMI-A-1"]
