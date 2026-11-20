"""Exercise native GTK drag/drop payloads and canvas repositioning."""

# flake8: noqa: E402

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk

from src.core.config import Config
from src.gui.controllers.settings_controller import SettingsController
from src.gui.pages.layout_settings_page import LayoutSettingsPage
from src.gui.widgets.layout_preview import LayoutPreview, _PlayerDragPayload
from src.models import Profile
from src.services.device_manager import DeviceManager


@pytest.fixture
def devices():
    """Make cross-monitor changes observable in geometry and refresh rate."""
    return {
        "displays": [
            {"id": 0, "name": "HDMI-A-1", "width": 1920, "height": 1080, "refresh_rate_mhz": 75000},
            {"id": 1, "name": "DP-1", "width": 2560, "height": 1440, "refresh_rate_mhz": 144000},
        ]
    }


@pytest.fixture
def page(devices):
    """Use real GTK controllers and widgets without launching Steam or touching user files."""
    if not Gtk.init_check():
        pytest.skip("A GTK display is required")
    Adw.init()
    result = LayoutSettingsPage()
    result.load_data(Profile(num_players=6), devices, {})
    return result


def _controller(widget, controller_type):
    controllers = widget.observe_controllers()
    for index in range(controllers.get_n_items()):
        controller = controllers.get_item(index)
        if isinstance(controller, controller_type):
            return controller
    raise AssertionError(f"No {controller_type.__name__} attached to the widget")


def _prepare(preview, widget):
    source = _controller(widget, Gtk.DragSource)
    provider = source.emit("prepare", 8.0, 8.0)
    assert isinstance(provider, Gdk.ContentProvider)
    assert provider.ref_formats().contain_gtype(_PlayerDragPayload)
    return source, preview._drag_payload


def test_native_drop_from_automatic_switches_to_custom_once_and_keeps_cells(page):
    """Finishing a successful drop must not recreate its GTK source or target mid-callback."""
    preview = page.layout_preview
    original_cells = [slot.cell for slot in preview._slots]
    edits = []
    page.connect("settings-changed", lambda *_: edits.append(True))
    source, payload = _prepare(preview, original_cells[0])
    target = _controller(original_cells[2], Gtk.DropTarget)
    assert target.emit("drop", payload, 10.0, 10.0)
    assert preview.instances == [2, 1, 0, 3, 4, 5]
    assert page.placement_mode_row.get_selected() == 1
    assert page.get_data()["layout_order"] == [2, 1, 0, 3, 4, 5]
    assert page._active_player == 0
    assert [slot.cell for slot in preview._slots] == original_cells
    assert source.get_widget() is original_cells[0]
    assert preview._drag_source is source
    assert edits == [True]
    preview._on_drag_end(source, None, False)
    assert preview._drag_source is None
    assert all(not slot.cell.has_css_class("slot-drop-target") for slot in preview._slots)


def test_roster_drag_can_swap_players_between_monitors(page):
    """Dragging from the party navigator uses the same atomic order as canvas dragging."""
    preview = page.layout_preview
    _source, payload = _prepare(preview, page._roster_rows[5])
    target = _controller(preview._slots[0].cell, Gtk.DropTarget)
    assert target.emit("drop", payload, 5.0, 5.0)
    assert preview.instances == [5, 1, 2, 3, 4, 0]
    assert "DP-1" in preview.slot_labels[5]
    assert "Monitor" not in preview.slot_labels[5]
    assert "Space 6" in preview.slot_labels[5]
    assert len(set(preview.instances)) == 6


def test_canvas_assignment_and_drop_stay_synchronized(page):
    """Programmatic assignment and native drops update every affected slot without feedback loops."""
    preview = page.layout_preview
    edits = []
    page.connect("settings-changed", lambda *_: edits.append(True))
    assert preview.assign_player(0, 4)
    assert preview.instances == [4, 1, 2, 3, 0, 5]
    _source, payload = _prepare(preview, preview._slots[0].cell)
    target = _controller(preview._slots[5].cell, Gtk.DropTarget)
    assert target.emit("drop", payload, 5.0, 5.0)
    assert preview.instances == [5, 1, 2, 3, 0, 4]
    assert len(edits) == 2


def test_reused_tile_source_resolves_its_new_occupant(page):
    """A previous swap must not leave drag handlers pointing to an old player identity."""
    preview = page.layout_preview
    cell = preview._slots[0].cell
    assert preview.assign_player(5, 0)
    _source, payload = _prepare(preview, cell)
    assert payload.instance == 5
    target = _controller(preview._slots[2].cell, Gtk.DropTarget)
    assert target.emit("drop", payload, 4.0, 4.0)
    assert preview.instances[2] == 5


@pytest.mark.parametrize("state", ["starting", "running", "stopping"])
def test_runtime_states_block_repositioning_immediately(page, state):
    """Even before the presenter locks global controls, a busy player locks all placement."""
    preview = page.layout_preview
    _source, payload = _prepare(preview, preview._slots[0].cell)
    target = _controller(preview._slots[1].cell, Gtk.DropTarget)
    page.player_rows[0].set_instance_state(state)
    assert not preview._allow_reposition
    assert not target.emit("drop", payload, 4.0, 4.0)
    source = _controller(preview._slots[0].cell, Gtk.DragSource)
    assert source.emit("prepare", 4.0, 4.0) is None
    assert not preview.assign_player(0, 1)
    assert page.get_data()["layout_order"] is None
    page.player_rows[0].set_instance_state("idle")
    assert preview._allow_reposition


def test_foreign_owner_and_same_destination_are_rejected_without_autosave(page):
    """Only players originating in this studio can affect its saved order."""
    preview = page.layout_preview
    target = _controller(preview._slots[0].cell, Gtk.DropTarget)
    foreign = _PlayerDragPayload(LayoutPreview(), 1)
    edits = []
    page.connect("settings-changed", lambda *_: edits.append(True))
    assert not target.emit("drop", foreign, 5.0, 5.0)
    _source, own = _prepare(preview, preview._slots[0].cell)
    assert not target.emit("drop", own, 5.0, 5.0)
    assert not preview.assign_player(-1, 0)
    assert not preview.assign_player(0, 99)
    assert not preview.assign_player(True, 0)
    assert edits == []
    assert page.get_data()["layout_order"] is None


def test_cancelled_or_superseded_drag_payload_cannot_change_positions(page):
    """Queued drop data must not outlive the particular drag that created it."""
    preview = page.layout_preview
    source, stale = _prepare(preview, preview._slots[0].cell)
    target = _controller(preview._slots[1].cell, Gtk.DropTarget)
    preview._on_drag_cancel(source, None, Gdk.DragCancelReason.USER_CANCELLED)
    assert not target.emit("drop", stale, 4.0, 4.0)
    _prepare(preview, preview._slots[2].cell)
    assert not target.emit("drop", stale, 4.0, 4.0)
    assert preview.instances == list(range(6))
    assert page.get_data()["layout_order"] is None


def test_excluded_players_cannot_be_dragged_or_assigned(page):
    """An unchecked player must never take a position from participating players."""
    page.player_rows[1].checkbox.set_active(False)
    source = _controller(page._roster_rows[1], Gtk.DragSource)
    assert source.emit("prepare", 8.0, 8.0) is None
    assert not page.layout_preview.assign_player(1, 0)


def test_selection_press_keeps_inspector_closed_until_activation_and_roster_always_visible(page):
    """Pointer selection must not open the inspector prematurely, and the party sidebar stays always open."""
    assert not hasattr(page, "roster_split")
    assert page.roster_sidebar.get_visible()
    page.inspector_split.set_collapsed(True)
    page.inspector_split.set_show_sidebar(False)
    page.roster.select_row(page._roster_rows[2])
    assert page._active_player == 2
    assert page.roster_sidebar.get_visible()
    assert not page.inspector_split.get_show_sidebar()
    page.roster.emit("row-activated", page._roster_rows[2])
    assert page.inspector_split.get_show_sidebar()
    assert page.roster_sidebar.get_visible()


def test_direct_mode_rejects_dragging_and_restores_on_reenable(page):
    """A hidden Gamescope canvas must not remain a backdoor to changing placement."""
    preview = page.layout_preview
    source = _controller(preview._slots[0].cell, Gtk.DragSource)
    page.set_gamescope_enabled(False)
    assert source.emit("prepare", 4.0, 4.0) is None
    assert not preview.assign_player(0, 1)
    assert not preview._allow_reposition
    page.set_gamescope_enabled(True)
    assert preview._allow_reposition


@pytest.mark.parametrize(
    "y,height,direction",
    [(0, 200, -1), (30, 200, -1), (100, 200, 0), (170, 200, 1), (200, 200, 1), (-1, 200, 0), (201, 200, 0), (0, 0, 0)],
)
def test_drag_scroll_only_activates_near_viewport_edges(page, y, height, direction):
    """Edge scrolling must not move the canvas during ordinary center-hover selection."""
    delta = page._drag_scroll_delta(y, height)
    assert (delta > 0) - (delta < 0) == direction
    assert abs(delta) <= 16


@pytest.mark.parametrize("initial,step,expected", [(0, -16, 0), (895, 16, 900), (100, 16, 116), (100, -16, 84)])
def test_drag_scroll_respects_canvas_bounds(page, monkeypatch, initial, step, expected):
    """Long multi-monitor canvases remain scrollable without overshooting either edge."""
    drop = object()
    monkeypatch.setattr(page.layout_preview, "is_player_drag", lambda current: current is drop)
    monkeypatch.setattr(page.layout_preview_group, "get_mapped", lambda: True)
    adjustment = page.layout_preview_group.get_vadjustment()
    adjustment.configure(initial, 0, 1000, 1, 100, 100)
    page._drag_scroll_drop = drop
    page._drag_scroll_step = step
    assert page._scroll_canvas_for_drag()
    assert adjustment.get_value() == expected
    page._drag_scroll_drop = None
    assert not page._scroll_canvas_for_drag()
    assert page._drag_scroll_step == 0


def test_native_canvas_drag_motion_starts_and_stops_edge_scrolling(page, monkeypatch):
    """A live drop controller scrolls only authenticated drags and releases its timer."""
    controller = _controller(page.layout_preview_group, Gtk.DropControllerMotion)
    drop = object()
    monkeypatch.setattr(controller, "get_drop", lambda: drop)
    monkeypatch.setattr(page.layout_preview, "is_player_drag", lambda current: current is drop)
    monkeypatch.setattr(page.layout_preview_group, "get_height", lambda: 200)
    try:
        controller.emit("motion", 10.0, 199.0)
        assert page._drag_scroll_id != 0
        controller.emit("motion", 10.0, 100.0)
        assert page._drag_scroll_id == 0
        controller.emit("motion", 10.0, 199.0)
        assert page._drag_scroll_id != 0
        controller.emit("leave")
        assert page._drag_scroll_id == 0
    finally:
        page._stop_drag_scrolling()


def test_saved_drag_order_drives_launch_dimensions_and_refresh(page, devices, monkeypatch, tmp_path):
    """A visual cross-monitor move must survive saving and change actual launch parameters."""
    preview = page.layout_preview
    _source, payload = _prepare(preview, page._roster_rows[5])
    assert _controller(preview._slots[0].cell, Gtk.DropTarget).emit("drop", payload, 4.0, 4.0)
    controller = SettingsController.__new__(SettingsController)
    controller._profile = Profile(num_players=6)
    controller.update_from_ui_data(page.get_data())
    monkeypatch.setattr(Config, "get_profile_path", lambda: tmp_path / "profile.json")
    controller.get_profile().save()
    profile = Profile.load()
    manager = DeviceManager.__new__(DeviceManager)
    monkeypatch.setattr(manager, "get_screen_info", lambda: devices["displays"])
    assert profile.layout_indices() == [5, 1, 2, 3, 4, 0]
    assert manager.get_instance_dimensions(profile, 5) == (960, 540)
    assert manager.get_instance_refresh_rate(profile, 5) == 75
    assert manager.get_instance_dimensions(profile, 0) == (1280, 1440)
    assert manager.get_instance_refresh_rate(profile, 0) == 144
