"""Keep instance positions stable across window recreation and enumeration changes."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.core.config import Config
from src.core.layout import LayoutCalculator
from src.models import Profile
from src.services.cmd_builder import CommandBuilder
from src.services.kde_manager import KdeManager
from src.services.kwin_layout import INSTANCE_ENV, resolve_instance


@pytest.fixture
def kde(monkeypatch, tmp_path):
    """Build the real script generator with only its external D-Bus calls mocked."""
    bus = Mock()
    bus.con.get_unique_name.return_value = ":1.42"
    bus.con.call_sync.return_value = SimpleNamespace(unpack=lambda: (0,))
    bus.get.return_value.isScriptLoaded.return_value = False
    bus.get.return_value.unloadScript.return_value = True
    monkeypatch.setattr("src.services.kde_manager.pydbus.SessionBus", lambda: bus)
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(Config, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "src.services.kde_manager.DeviceManager.get_ordered_monitors",
        lambda: [SimpleNamespace(name="HDMI-A-1"), SimpleNamespace(name="DP-1")],
    )
    return KdeManager()


def test_native_identity_survives_process_replacement(monkeypatch):
    """Different processes carrying the same explicit instance ID resolve identically."""
    monkeypatch.setattr("src.services.kwin_layout.Utils.is_flatpak", lambda: False)
    for _ in range(2):
        env = dict(os.environ, **{INSTANCE_ENV: "3"})
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; print('ready', flush=True); sys.stdin.read()"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=env,
        )
        try:
            assert process.stdout is not None
            assert process.stdout.readline() == b"ready\n"
            assert resolve_instance(process.pid) == 3
        finally:
            process.communicate(timeout=3)


@pytest.mark.parametrize("data", [b"PATH=/bin\0", b"TWINVERSE_KWIN_INSTANCE=-1\0", b"TWINVERSE_KWIN_INSTANCE=bad\0"])
def test_unidentified_process_is_never_given_an_arbitrary_slot(monkeypatch, data):
    """An unrelated or malformed process cannot enter the instance layout."""
    monkeypatch.setattr("src.services.kwin_layout.Utils.is_flatpak", lambda: False)
    monkeypatch.setattr(Path, "read_bytes", lambda _path: data)
    assert resolve_instance(123) == -1


@pytest.mark.parametrize("pid", [0, -1, 2**31, True, "1;anything"])
def test_invalid_pid_never_reaches_the_host(monkeypatch, pid):
    """Reject invalid process identifiers before constructing paths or commands."""
    spawn = Mock()
    monkeypatch.setattr("src.services.kwin_layout.Utils.flatpak_spawn_host", spawn)
    assert resolve_instance(pid) == -1
    spawn.assert_not_called()


def test_flatpak_resolves_the_host_pid_without_transferring_other_environment(monkeypatch):
    """Resolve the host PID without reading it in the Flatpak process namespace."""
    monkeypatch.setattr("src.services.kwin_layout.Utils.is_flatpak", lambda: True)
    spawn = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"TWINVERSE_KWIN_INSTANCE=5\n"))
    monkeypatch.setattr("src.services.kwin_layout.Utils.flatpak_spawn_host", spawn)
    assert resolve_instance(123) == 5
    command = spawn.call_args.args[0]
    assert command[-1] == "123"
    assert "grep -m1" in command[2]
    assert INSTANCE_ENV in command[2]
    assert spawn.call_args.kwargs["timeout"] == 3


def test_disappeared_process_is_unidentified(monkeypatch):
    """A process that exited during the lookup must not inherit another slot."""
    monkeypatch.setattr("src.services.kwin_layout.Utils.is_flatpak", lambda: False)
    monkeypatch.setattr(Path, "read_bytes", Mock(side_effect=FileNotFoundError))
    assert resolve_instance(123) == -1


def test_identity_service_round_trip_on_a_private_bus():
    """Exercise actual Gio registration, worker reply and GLib dispatch without KWin."""
    dbus_run = shutil.which("dbus-run-session")
    if not dbus_run:
        pytest.skip("dbus-run-session is needed for the D-Bus integration test")
    source = """
import os
from gi.repository import Gio, GLib
from src.services.kwin_layout import INTERFACE, OBJECT_PATH, KwinLayoutResolver
connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
resolver = KwinLayoutResolver(connection)
loop = GLib.MainLoop()
replies = []
def received(bus, result, _data):
    replies.append(bus.call_finish(result).unpack()[0])
    loop.quit()
connection.call(resolver.service_name, OBJECT_PATH, INTERFACE, 'ResolveInstance',
    GLib.Variant('(s)', (str(os.getpid()),)), GLib.VariantType('(i)'),
    Gio.DBusCallFlags.NONE, 3000, None, received, None)
GLib.timeout_add_seconds(5, lambda: (loop.quit(), False)[1])
loop.run()
assert replies == [6], replies
"""
    env = dict(os.environ, **{INSTANCE_ENV: "6"})
    subprocess.run([dbus_run, "--", sys.executable, "-c", source], env=env, check=True, timeout=10)


def test_gamescope_marker_cannot_be_overridden_by_user_environment(tmp_path):
    """Stamp the real instance number after all user-supplied bwrap variables."""
    profile = Profile(env={INSTANCE_ENV: "999"})
    command = CommandBuilder(profile, {}, Mock(), 2, tmp_path, None)._build_bwrap_command(2)
    positions = [i for i, value in enumerate(command) if value == INSTANCE_ENV]
    assert len(positions) == 2
    assert command[positions[-1] + 1] == "2"


def test_same_layout_does_not_load_a_competing_script(kde):
    """Repeated starts reuse the existing script, including valid script ID zero."""
    profile = Profile(num_players=4)
    kde.start_kwin_script(profile)
    kde.start_kwin_script(profile)
    assert kde.kwin_script_id == 0
    kde.session_bus.con.call_sync.assert_called_once()
    arguments = kde.session_bus.con.call_sync.call_args.args
    assert arguments[3] == "loadScript"
    assert arguments[4].unpack() == (str(kde._kwin_script_temp_path), kde._kwin_script_name)
    kde.stop_kwin_script()
    kde.session_bus.get.return_value.unloadScript.assert_called_once_with(kde._kwin_script_name)
    assert kde.kwin_script_id is None


def test_changed_layout_unloads_by_plugin_name_before_replacement(kde):
    """Changing configuration must not leave two scripts fighting over geometry."""
    profile = Profile(num_players=4)
    kde.start_kwin_script(profile)
    profile.splitscreen.orientation = "horizontal"
    kde.start_kwin_script(profile)
    scripting = kde.session_bus.get.return_value
    assert kde.session_bus.con.call_sync.call_count == 2
    scripting.unloadScript.assert_called_once_with(kde._kwin_script_name)


def test_failed_unload_does_not_start_a_second_script(kde):
    """Keep the old script state if KWin refuses to unload it."""
    profile = Profile(num_players=4)
    kde.start_kwin_script(profile)
    kde.session_bus.get.return_value.unloadScript.return_value = False
    profile.splitscreen.orientation = "horizontal"
    kde.start_kwin_script(profile)
    kde.session_bus.con.call_sync.assert_called_once()
    assert kde.kwin_script_id == 0


def test_script_from_previous_session_is_replaced_by_name(kde):
    """A new application session replaces its old layout instead of competing with it."""
    scripting = kde.session_bus.get.return_value
    scripting.isScriptLoaded.return_value = True
    kde.start_kwin_script(Profile())
    scripting.unloadScript.assert_called_once_with(kde._kwin_script_name)
    kde.session_bus.con.call_sync.assert_called_once()


def test_legacy_script_is_unloaded_using_its_original_file_name(kde, tmp_path):
    """Migrate old scripts whose numeric IDs were incorrectly used for unloading."""
    old = tmp_path / "kwin_script_123_kwin_gamescope_vertical.js"
    old.write_text("// Legacy Twinverse script\n")
    scripting = kde.session_bus.get.return_value
    scripting.isScriptLoaded.side_effect = lambda name: name == str(old)
    kde.start_kwin_script(Profile())
    scripting.unloadScript.assert_called_once_with(str(old))
    kde.session_bus.con.call_sync.assert_called_once()
    assert old.exists()


HARNESS = r"""
const assert = require('node:assert/strict');
const print = () => {};
function signal() {
  const callbacks = [];
  return {connect: fn => callbacks.push(fn), emit: (...args) => callbacks.slice().forEach(fn => fn(...args))};
}
function client(instance, pid) {
  let geometry;
  const window = {instance, pid, resourceClass: 'gamescope', caption: 'Changing game title',
    frameGeometryChanged: signal(), fullScreenChanged: signal(), windowClassChanged: signal(),
    maximizedChanged: signal(), maximizeMode: 0, writes: 0};
  window.setMaximize = (vertical, horizontal) => {
    assert.equal(vertical, false); assert.equal(horizontal, false);
    window.maximizeMode = 0; window.maximizedChanged.emit();
  };
  Object.defineProperty(window, 'frameGeometry', {
    get: () => geometry,
    set: value => { geometry = value; window.writes++; window.frameGeometryChanged.emit(); }
  });
  return window;
}
let clients = [];
let pending = [];
const identities = new Map();
function callDBus(service, path, iface, method, pid, callback) {
  assert.equal(method, 'ResolveInstance');
  assert.equal(typeof pid, 'string');
  pid = Number(pid);
  pending.push(() => callback(identities.has(pid) ? identities.get(pid) : -1));
}
function flush(reverse = false) {
  let replies = pending; pending = [];
  if (reverse) replies.reverse();
  replies.forEach(fn => fn());
}
const workspace = {
  screens: [
    {name: 'DP-1', geometry: {x: 1920, y: 0, width: 2560, height: 1440}},
    {name: 'HDMI-A-1', geometry: {x: 0, y: 0, width: 1920, height: 1080}}
  ],
  windowList: () => clients,
  activeWindow: null,
  windowAdded: signal(), windowRemoved: signal(), windowActivated: signal(), screensChanged: signal()
};
function add(instance, pid) {
  const window = client(instance, pid);
  if (instance >= 0) identities.set(pid, instance);
  clients.push(window); workspace.windowAdded.emit(window);
  return window;
}
function remove(window) {
  clients = clients.filter(item => item !== window);
  workspace.windowRemoved.emit(window);
}
"""


@pytest.mark.parametrize(
    "mode,orientation", [("fullscreen", "vertical"), ("splitscreen", "vertical"), ("splitscreen", "horizontal")]
)
@pytest.mark.parametrize("selection", [[0, 1], [1, 3], [0, 1, 2, 3, 4, 5]])
@pytest.mark.parametrize("custom", [False, True])
def test_layout_survives_reorder_recreation_and_late_identity(
    kde, mode, orientation, selection, custom, node_executable
):
    """Execute actual scripts through out-of-order arrivals, disappearance and recreation."""
    node = node_executable
    profile = Profile(mode=mode, num_players=max(selection) + 1, selected_players=selection)
    profile.splitscreen.orientation = orientation
    if custom:
        profile.layout_order = list(reversed(range(profile.num_players)))
    kde.start_kwin_script(profile)
    script = kde._kwin_script_temp_path.read_text()
    targets = {}
    fallback_targets = {}
    for slot, instance in enumerate(profile.layout_indices()):
        monitor_index = slot // 4 if mode == "splitscreen" else slot
        monitor_x, monitor_width, monitor_height = (1920, 2560, 1440) if monitor_index == 1 else (0, 1920, 1080)
        if mode == "splitscreen":
            count = min(4, len(selection) - (slot // 4) * 4)
            x, y, width, height = LayoutCalculator.calculate_position(
                monitor_width, monitor_height, count, slot % 4, orientation
            )
        else:
            x, y, width, height = 0, 0, monitor_width, monitor_height
        targets[instance] = {"x": monitor_x + x, "y": y, "width": width, "height": height}
        if mode == "splitscreen":
            x, y, width, height = LayoutCalculator.calculate_position(2560, 1440, count, slot % 4, orientation)
        else:
            x, y, width, height = 0, 0, 2560, 1440
        fallback_targets[instance] = {"x": 1920 + x, "y": y, "width": width, "height": height}
    scenario = (
        r"""
const selection = SELECTION;
const targets = TARGETS;
const fallback = FALLBACK;
const isSplit = SPLITSCREEN;
// Arrival and D-Bus reply order must not define the slot order.
let windows = selection.slice().reverse().map((instance, i) => add(instance, 100 + i));
flush(true);
const expected = new Map(selection.map(instance => [instance, targets[instance]]));
windows.forEach(window => assert.deepEqual(window.frameGeometry, expected.get(window.instance)));
assert.equal(expected.get(twinverseLayout.instances[0]).x, 0);
clients.reverse();
workspace.windowActivated.emit();
windows.forEach(window => assert.deepEqual(window.frameGeometry, expected.get(window.instance)));

const first = windows.find(window => window.instance === selection[0]);
remove(first);
windows = windows.filter(window => window !== first);
windows.forEach(window => assert.deepEqual(window.frameGeometry, expected.get(window.instance)));
// New object, new PID, different title: same instance, same reserved slot.
let replacement = add(selection[0], 900);
replacement.caption = 'Another game';
flush();
assert.deepEqual(replacement.frameGeometry, expected.get(selection[0]));

// An asynchronous reply from a dead window must not move its replacement.
const transient = add(selection[0], 901);
remove(transient);
flush();
assert.equal(transient.writes, 0);
assert.deepEqual(replacement.frameGeometry, expected.get(selection[0]));

// Unrelated Gamescope windows have no marker and must remain untouched.
const unrelated = add(-1, 999);
flush();
assert.equal(unrelated.writes, 0);
const unselected = add(777, 998);
flush();
assert.equal(unselected.writes, 0);
const ordinary = client(-1, 1000);
ordinary.resourceClass = 'steam';
clients.push(ordinary);
workspace.windowAdded.emit(ordinary);
remove(ordinary);
assert.equal(pending.length, 0);
// Restore the target if Gamescope changes its outer window's geometry.
replacement.frameGeometry = {x: 9999, y: 9999, width: 800, height: 600};
assert.deepEqual(replacement.frameGeometry, expected.get(selection[0]));
const writes = replacement.writes;
twinverseRefresh();
assert.equal(replacement.writes, writes);
if (isSplit) {
  replacement.fullScreen = true;
  replacement.fullScreenChanged.emit();
  assert.equal(replacement.fullScreen, false);
  replacement.maximizeMode = 3;
  replacement.maximizedChanged.emit();
  assert.equal(replacement.maximizeMode, 0);
  assert.deepEqual(replacement.frameGeometry, expected.get(selection[0]));
}
// Repeated recreation must not leak slots or depend on a remembered PID.
for (let i = 0; i < 20; i++) {
  remove(replacement);
  replacement = add(selection[0], 2000 + i);
  flush();
  assert.deepEqual(replacement.frameGeometry, expected.get(selection[0]));
}
// Class metadata arriving late must still associate the window correctly.
const late = client(selection[0], 3000);
late.resourceClass = '';
identities.set(late.pid, late.instance);
clients.push(late);
workspace.windowAdded.emit(late);
late.resourceClass = 'gamescope';
late.windowClassChanged.emit();
flush();
assert.deepEqual(late.frameGeometry, expected.get(selection[0]));
remove(late);
// Removing a monitor must not reindex the remaining connector assignment.
workspace.screens = workspace.screens.filter(screen => screen.name !== 'HDMI-A-1');
workspace.screensChanged.emit();
assert.deepEqual(replacement.frameGeometry, fallback[replacement.instance]);
windows.forEach(window => assert.deepEqual(window.frameGeometry, fallback[window.instance]));
console.log('stable');
""".replace(
            "SELECTION", json.dumps(selection)
        )
        .replace("TARGETS", json.dumps(targets))
        .replace("FALLBACK", json.dumps(fallback_targets))
        .replace("SPLITSCREEN", json.dumps(mode == "splitscreen"))
    )
    result = subprocess.check_output([node], input=HARNESS + script + scenario, text=True, timeout=10)
    assert result.strip() == "stable"
