"""Native workspace integration, without Steam or real device discovery."""

# flake8: noqa: E402

from copy import deepcopy
from unittest.mock import Mock

import gi
import pytest

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from src.core.config import Config
from src.core.tiling import TEMPLATES
from src.gui.controllers.settings_controller import SettingsController
from src.gui.pages.layout_settings_page import LayoutSettingsPage
from src.models import MonitorLayoutConfig, Profile
from src.services.device_manager import DeviceManager


@pytest.fixture
def displays():
    return [
        dict(id=0, name="DP-1", x=0, y=0, width=1920, height=1080, refresh_rate_mhz=144000),
        dict(id=1, name="HDMI-1", x=1920, y=0, width=2560, height=1440, refresh_rate_mhz=59940),
    ]


def devices(displays):
    return dict(displays=displays, joystick=[], mouse=[], keyboard=[], audio=[])


def drain():
    context = GLib.MainContext.default()
    for _ in range(100):
        if not context.pending():
            break
        super(GLib.MainContext, context).iteration(False)


@pytest.fixture
def workspace(displays):
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A native GTK display is required")
    Adw.init()
    windows = []

    def create(profile=None):
        page = LayoutSettingsPage()
        changes = Mock()
        page.connect("settings-changed", changes)
        page.load_data(profile or Profile(num_players=3), devices(displays), {})
        window = Gtk.Window(default_width=1200, default_height=800)
        window.set_child(page)
        window.present()
        windows.append(window)
        drain()
        assert page.get_mapped()
        changes.assert_not_called()
        return page, changes

    yield create
    for window in windows:
        window.destroy()
    drain()


def click(page, connector, template):
    page.layout_preview.tiling_pickers[connector].buttons[template].emit("clicked")


def controller(widget, kind):
    model = widget.observe_controllers()
    return next(model.get_item(i) for i in range(model.get_n_items()) if isinstance(model.get_item(i), kind))


def descendant(widget, ancestor):
    while widget is not None:
        if widget is ancestor:
            return True
        widget = widget.get_parent()
    return False


def mixed(page):
    click(page, "DP-1", "columns")
    click(page, "HDMI-1", "fullscreen")


def test_native_load_has_six_choices_on_every_detected_monitor(workspace):
    page, changes = workspace()
    preview = page.layout_preview
    assert set(preview.tiling_pickers) == {"DP-1", "HDMI-1"}
    assert len(TEMPLATES) == 6
    for picker in preview.tiling_pickers.values():
        assert set(picker.buttons) == set(TEMPLATES)
        assert descendant(picker, page)
    assert preview.tiling_pickers["HDMI-1"]._selected is None
    for legacy in (page.screen_mode_row, page.orientation_row):
        assert not descendant(legacy, page)
    dock = page.gamescope_settings_group
    assert dock.has_css_class("layout-dock")
    assert descendant(page.placement_mode_row, dock)
    assert dock.get_first_child().get_next_sibling() is None
    click(page, "HDMI-1", "fullscreen")
    assert page.get_data()["monitor_layouts"]["HDMI-1"]["template"] == "fullscreen"
    assert page.placement_mode_row.get_selected() == 0
    assert page.get_data()["layout_order"] is None
    changes.assert_called_once()


def test_each_native_picker_edit_emits_once_and_allocates_two_plus_one(workspace, displays, monkeypatch):
    page, changes = workspace()
    for connector, template in (("HDMI-1", "fullscreen"), ("DP-1", "columns")):
        changes.reset_mock()
        click(page, connector, template)
        changes.assert_called_once()
    assert page.placement_mode_row.get_selected() == 0
    assert page.get_data()["layout_order"] is None
    assert page.layout_preview.instances == [0, 1, 2]
    assert page.layout_preview.monitor_slot_ranges == {"DP-1": (0, 2), "HDMI-1": (2, 3)}
    profile = Profile(num_players=3, monitor_layouts=page.get_data()["monitor_layouts"])
    manager = DeviceManager()
    monkeypatch.setattr(manager, "get_screen_info", lambda: displays)
    assert [manager.get_instance_dimensions(profile, i) for i in range(3)] == [(960, 1080), (960, 1080), (2560, 1440)]
    assert page.get_layout_error() is None


@pytest.mark.parametrize("template", TEMPLATES)
def test_independent_templates_controller_disk_roundtrip(workspace, displays, tmp_path, monkeypatch, template):
    path = tmp_path / "profile.json"
    monkeypatch.setattr(Config, "get_profile_path", staticmethod(lambda: path))
    page, _ = workspace()
    click(page, "DP-1", template)
    click(page, "HDMI-1", "rows")
    assert page.placement_mode_row.get_selected() == 0
    manager = DeviceManager()
    monkeypatch.setattr(manager, "get_screen_info", lambda: displays)
    settings = SettingsController(manager)
    settings.update_from_ui_data(page.get_data())
    settings.save_profile()
    saved = Profile.load()
    assert all(isinstance(config, MonitorLayoutConfig) for config in saved.monitor_layouts.values())
    assert saved.monitor_layouts["DP-1"].template == template
    assert saved.monitor_layouts["HDMI-1"].template == "rows"
    assert saved.layout_order is None
    expected = [
        (manager.get_instance_dimensions(saved, i), manager.get_instance_refresh_rate(saved, i)) for i in range(3)
    ]
    monkeypatch.setattr(manager, "get_screen_info", lambda: list(reversed(displays)))
    restored, changes = workspace(saved)
    assert restored.placement_mode_row.get_selected() == 0
    assert restored.get_data()["monitor_layouts"] == page.get_data()["monitor_layouts"]
    assert [
        (manager.get_instance_dimensions(saved, i), manager.get_instance_refresh_rate(saved, i)) for i in range(3)
    ] == expected
    changes.assert_not_called()


def test_reduce_capacity_tray_error_expand_and_direct_mode(workspace):
    page, _ = workspace()
    mixed(page)
    click(page, "DP-1", "fullscreen")
    assert len(page._tiling_plan.unassigned) == 1
    unassigned = page._tiling_plan.unassigned[0]
    assert page.layout_preview.instances[-1] == unassigned
    assert page.get_layout_error()
    assert page.get_layout_error(unassigned)
    assigned = next(player for player in page.get_selected_players() if player != unassigned)
    assert page.get_layout_error(assigned) is None
    page.set_gamescope_enabled(False)
    assert page.get_layout_error() is None
    page.set_gamescope_enabled(True)
    assert page.get_layout_error()
    click(page, "DP-1", "grid")
    assert not page._tiling_plan.unassigned
    assert page.get_layout_error() is None


def test_native_empty_monitor_drop_preserves_source_and_switches_to_custom(workspace):
    profile = Profile(
        num_players=2,
        monitor_layouts={
            "DP-1": {"template": "columns", "players": [0, 1]},
            "HDMI-1": {"template": "fullscreen", "players": [None]},
        },
    )
    page, changes = workspace(profile)
    preview = page.layout_preview
    cells = [slot.cell for slot in preview._slots]
    source = controller(cells[0], Gtk.DragSource)
    assert source.emit("prepare", 1.0, 1.0) is not None
    target = controller(cells[2], Gtk.DropTarget)
    assert target.emit("drop", preview._drag_payload, 1.0, 1.0)
    changes.assert_called_once()
    assert [slot.cell for slot in preview._slots] == cells
    assert source.get_widget() is cells[0]
    assert preview.instances == [None, 1, 0]
    data = page.get_data()
    assert data["monitor_layouts"] == {
        "DP-1": {"template": "columns", "players": [None, 1]},
        "HDMI-1": {"template": "fullscreen", "players": [0]},
    }
    assert data["layout_order"] == [1, 0]
    assert page.placement_mode_row.get_selected() == 1
    source.emit("drag-end", None, False)
    assert not target.emit("drop", preview._drag_payload, 1.0, 1.0)


def test_tray_is_not_a_drop_destination(workspace):
    page, changes = workspace(
        Profile(
            num_players=3,
            monitor_layouts={
                "DP-1": {"template": "fullscreen"},
                "HDMI-1": {"template": "fullscreen"},
            },
        )
    )
    preview = page.layout_preview
    source = controller(preview._slots[0].cell, Gtk.DragSource)
    assert source.emit("prepare", 1.0, 1.0) is not None
    target = controller(preview._slots[-1].cell, Gtk.DropTarget)
    assert not target.emit("drop", preview._drag_payload, 1.0, 1.0)
    assert not preview.assign_player(0, 2)
    changes.assert_not_called()
    source.emit("drag-end", None, False)


def test_template_switch_stays_automatic_until_manual_move_and_automatic_clears_reservations(workspace):
    page, changes = workspace()
    mixed(page)
    assert page.placement_mode_row.get_selected() == 0
    assert page.get_data()["layout_order"] is None
    assert all(config["players"] == [] for config in page.get_data()["monitor_layouts"].values())

    # Only a manual player rearrangement switches placement to Custom.
    assert page.layout_preview.assign_player(0, 2)
    assert page.placement_mode_row.get_selected() == 1
    before = page.get_data()["monitor_layouts"]
    assert any(config["players"] for config in before.values())

    changes.reset_mock()
    page.placement_mode_row.set_selected(0)
    changes.assert_called_once()
    data = page.get_data()
    assert data["layout_order"] is None
    assert data["monitor_layouts"] == {
        key: dict(template=config["template"], players=[]) for key, config in before.items()
    }


@pytest.mark.parametrize("state", ["starting", "running", "stopping"])
def test_runtime_locks_survive_refresh_without_mutations(workspace, displays, state):
    page, changes = workspace()
    mixed(page)
    before = deepcopy(page.get_data())
    changes.reset_mock()
    page.player_rows[0].set_instance_state(state)
    for refresh in (False, True):
        if refresh:
            updated = deepcopy(displays)
            updated[0]["width"] += 100
            page.update_devices_info(devices(list(reversed(updated))))
        for picker in page.layout_preview.tiling_pickers.values():
            assert all(not button.get_sensitive() for button in picker.buttons.values())
            for button in picker.buttons.values():
                button.emit("clicked")
        assert page.get_data() == before
    changes.assert_not_called()
    page.player_rows[0].set_instance_state("idle")
    assert all(
        button.get_sensitive()
        for picker in page.layout_preview.tiling_pickers.values()
        for button in picker.buttons.values()
    )
    changes.assert_not_called()


def test_device_refresh_does_not_autosave_or_lose_connected_pickers(workspace, displays, tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    monkeypatch.setattr(Config, "get_profile_path", staticmethod(lambda: path))
    page, changes = workspace()
    mixed(page)
    settings = SettingsController(DeviceManager())
    settings.update_from_ui_data(page.get_data())
    settings.save_profile()
    saved = path.read_bytes()
    on_edit = Mock(side_effect=lambda *_: settings.save_profile())
    page.connect("settings-changed", on_edit)
    before = deepcopy(page.get_data())
    changes.reset_mock()
    page.update_devices_info(devices(list(reversed(displays))))
    assert set(page.layout_preview.tiling_pickers) == {display["name"] for display in displays}
    assert page.get_data() == before
    assert path.read_bytes() == saved
    assert Profile.load().monitor_layouts == settings.get_profile().monitor_layouts
    changes.assert_not_called()
    on_edit.assert_not_called()
    click(page, "HDMI-1", "grid")
    changes.assert_called_once()
    on_edit.assert_called_once()
