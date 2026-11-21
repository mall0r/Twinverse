"""Exercise actual launch sizing and generated KWin JavaScript for mixed layouts."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from src.core.exceptions import TwinverseError
from src.core.tiling import TEMPLATES
from src.gui.controllers.settings_controller import SettingsController
from src.models import Profile
from src.services.cmd_builder import CommandBuilder
from src.services.device_manager import DeviceManager
from src.services.kde_manager import KdeManager


@pytest.fixture
def mixed(monkeypatch):
    """Provide mixed monitor layouts with reversed discovery order."""
    displays = [
        {"id": 1, "name": "B", "x": 1920, "y": 0, "width": 2560, "height": 1440, "refresh_rate_mhz": 143980},
        {"id": 0, "name": "A", "x": 0, "y": 0, "width": 1920, "height": 1080, "refresh_rate_mhz": 74973},
    ]
    monkeypatch.setattr(DeviceManager, "get_screen_info", lambda self: displays)
    profile = Profile(
        num_players=4,
        monitor_layouts={
            "A": {"template": "columns", "players": [1, 0]},
            "B": {"template": "fullscreen", "players": [2]},
        },
    )
    return profile, DeviceManager(), displays


@pytest.mark.parametrize(
    "index,size,rate,flag", [(0, (960, 1080), 75, "-b"), (1, (960, 1080), 75, "-b"), (2, (2560, 1440), 144, "-f")]
)
def test_mixed_commands(mixed, index, size, rate, flag):
    """Match Gamescope dimensions, refresh rate and mode to each placement."""
    profile, manager, displays = mixed
    assert manager.get_instance_dimensions(profile, index) == size
    assert manager.get_instance_refresh_rate(profile, index) == rate
    command = CommandBuilder(profile, {}, manager, index, Path("/unused"), None)._build_gamescope_command(False)
    for option, value in zip(("-W", "-H", "-w", "-h"), size * 2):
        assert command[command.index(option) + 1] == str(value)
    assert command[command.index("-r") + 1] == str(rate)
    assert flag in command and ({"-f", "-b"} - {flag}).isdisjoint(command)
    displays.reverse()
    assert manager.get_instance_dimensions(profile, index) == size


def test_overflow_does_not_launch_on_another_rectangle(mixed):
    """Refuse to launch unassigned instances over an existing placement."""
    profile, manager, _ = mixed
    assert manager.get_instance_dimensions(profile, 3) == (None, None)
    assert manager.get_instance_refresh_rate(profile, 3) is None
    with pytest.raises(TwinverseError):
        CommandBuilder(profile, {}, manager, 3, Path("/unused"), None)._build_gamescope_command(False)


@pytest.mark.parametrize("template", TEMPLATES)
def test_all_template_pixel_dimensions(mixed, template):
    """Derive pixel dimensions from every template's proportional rectangles."""
    profile, manager, _ = mixed
    profile.monitor_layouts = Profile(monitor_layouts={"A": {"template": template}}).monitor_layouts
    for index, (_, _, width, height) in enumerate(TEMPLATES[template].rectangles):
        assert manager.get_instance_dimensions(profile, index) == (int(1920 * width), int(1080 * height))


def test_settings_preserve_and_validate(mixed):
    """Preserve omitted settings and validate explicit monitor layout updates."""
    profile, manager, _ = mixed
    controller = SettingsController.__new__(SettingsController)
    controller._profile = profile
    data = {
        "num_players": 4,
        "mode": "splitscreen",
        "orientation": "vertical",
        "player_configs": [],
        "selected_players": [],
    }
    original = profile.monitor_layouts.copy()
    controller.update_from_ui_data(data)
    assert profile.monitor_layouts == original
    with pytest.raises(ValidationError):
        controller.update_from_ui_data({**data, "monitor_layouts": {"A": {"players": [False]}}})
    assert profile.monitor_layouts == original
    controller.update_from_ui_data({**data, "monitor_layouts": {}})
    assert not profile.monitor_layouts


def test_generated_kwin_mixed_geometry_and_reload(mixed, monkeypatch, tmp_path, node_executable):
    """Execute mixed KWin placements and reload when assignments change."""
    profile, _, displays = mixed
    kde = KdeManager.__new__(KdeManager)
    kde.session_bus = Mock()
    kde.session_bus.con.call_sync.return_value = SimpleNamespace(unpack=lambda: (0,))
    kde.session_bus.get.return_value.isScriptLoaded.return_value = False
    kde.kwin_script_id = None
    kde._kwin_script_name = "tiling-test"
    kde._kwin_script_signature = None
    kde._layout_resolver = SimpleNamespace(service_name=":1.42")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr("src.services.kde_manager.Config.cache_dir", lambda: tmp_path)
    kde.start_kwin_script(profile)
    source = kde._kwin_script_temp_path.read_text()
    settings = json.loads(source.splitlines()[0].removeprefix("var twinverseLayout = ").removesuffix(";"))
    assert settings["placements"] == {
        "1": {"monitor": "A", "template": "columns", "rectangle": [0, 0, 0.5, 1]},
        "0": {"monitor": "A", "template": "columns", "rectangle": [0.5, 0, 0.5, 1]},
        "2": {"monitor": "B", "template": "fullscreen", "rectangle": [0, 0, 1, 1]},
    }
    signature = kde._kwin_script_signature
    profile.monitor_layouts["A"].players = [0, 1]
    kde.start_kwin_script(profile)
    assert kde._kwin_script_signature != signature
    node = node_executable
    screens = [{"name": d["name"], "geometry": {k: d[k] for k in ("x", "y", "width", "height")}} for d in displays]
    harness = """
const clients = Array.from({length: 4}, (_, i) => ({resourceClass: 'gamescope', pid: 100+i}));
const print = () => {};
function callDBus(s,p,i,m,pid,cb) { cb(Number(pid)-100); }
const workspace = {
  screens: SCREENS, windowList: () => clients, activeWindow: clients[0],
  windowAdded: {connect: () => {}}, windowRemoved: {connect: () => {}}, windowActivated: {connect: () => {}}
};
""".replace(
        "SCREENS", json.dumps(screens)
    )
    output = subprocess.check_output(
        [node], input=harness + source + "\nconsole.log(JSON.stringify(clients));", text=True
    )
    clients = json.loads(output)
    assert clients[0]["frameGeometry"] == {"x": 960, "y": 0, "width": 960, "height": 1080}
    assert clients[1]["frameGeometry"] == {"x": 0, "y": 0, "width": 960, "height": 1080}
    assert clients[2]["frameGeometry"] == {"x": 1920, "y": 0, "width": 2560, "height": 1440}
    assert "frameGeometry" not in clients[3]
    output = subprocess.check_output(
        [node],
        input=harness
        + source
        + "\nworkspace.screens = workspace.screens.filter(s => s.name !== 'B'); delete clients[2].frameGeometry; twinverseRefresh(); console.log(JSON.stringify(clients[2]));",
        text=True,
    )
    assert "frameGeometry" not in json.loads(output)
