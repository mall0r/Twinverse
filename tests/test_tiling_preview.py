"""Exact per-monitor preview geometry and native empty-slot placement."""

# flake8: noqa: E402

import gi
import pytest

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from src.core.tiling import TEMPLATES, MonitorPlan, TilingPlan
from src.gui.widgets.layout_preview import LayoutPreview


@pytest.fixture
def preview():
    """Create native controls without launching any game clients."""
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A GTK display is required")
    Adw.init()
    return LayoutPreview()


def monitor(key, template, players, index=0):
    """Build a deterministic monitor plan for the preview."""
    return MonitorPlan(key, index, {"name": key, "width": 1920, "height": 1080}, TEMPLATES[template], players)


def controller(widget, kind):
    """Find the real GTK drag or drop controller on a card."""
    controllers = widget.observe_controllers()
    return next(
        controllers.get_item(i) for i in range(controllers.get_n_items()) if isinstance(controllers.get_item(i), kind)
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_exact_rectangles_and_empty_capacity(preview, template):
    """Every template retains its geometry even without participating players."""
    spec = TEMPLATES[template]
    preview.configure_tiling(TilingPlan([monitor("DP-1", template, [None] * spec.capacity)], []), True)
    assert preview.instances == [None] * spec.capacity
    assert preview.monitor_slot_ranges == {"DP-1": (0, spec.capacity)}
    for slot, rect in zip(preview._slots, spec.rectangles):
        assert preview.monitor_grids[0].query_child(slot.cell) == tuple(round(v * 2) for v in rect)
        assert slot.name.get_label() == "Empty space"
        assert slot.number.get_label() == "—"
    activated = []
    preview.connect("player-activated", lambda _, player: activated.append(player))
    preview._slots[0].button.emit("clicked")
    assert activated == []


def test_native_tray_drop_into_hole_exports_only_monitors(preview):
    """Move a waiting player without saving the tray as a monitor."""
    preview.configure_tiling(
        TilingPlan(
            [
                monitor("DP-1", "columns", [0, None]),
                monitor("HDMI-1", "fullscreen", [None], 1),
            ],
            [1],
        ),
        True,
    )
    changes = []
    preview.connect("order-changed", lambda _, order: changes.append(order))
    source = controller(preview._slots[3].cell, Gtk.DragSource)
    assert source.emit("prepare", 1.0, 1.0) is not None
    target = controller(preview._slots[1].cell, Gtk.DropTarget)
    assert target.emit("drop", preview._drag_payload, 1.0, 1.0)
    assert changes == [[0, 1, None, None]]
    assert preview.get_monitor_layouts() == {
        "DP-1": {"template": "columns", "players": [0, 1]},
        "HDMI-1": {"template": "fullscreen", "players": [None]},
    }
    preview._on_drag_end(source, None, False)
    assert all(slot.cell.get_opacity() == 1 for slot in preview._slots)
    assert preview._slots[3].name.get_label() == "Empty space"


def test_picker_selection_and_repeated_runtime_lock(preview):
    """Rebuilt selectors respect runtime locks and emit only actual choices."""
    plan = TilingPlan([monitor("DP-1", "rows", [0, None])], [])
    selected = []
    preview.connect("template-selected", lambda _, key, template: selected.append((key, template)))
    preview.configure_tiling(plan, False)
    preview.set_reposition_enabled(False)
    picker = preview.tiling_pickers["DP-1"]
    picker.buttons["grid"].emit("clicked")
    assert selected == []
    assert picker._selected == "rows"
    preview.set_reposition_enabled(True)
    picker.buttons["grid"].emit("clicked")
    assert selected == [("DP-1", "grid")]
    preview.configure_tiling(plan, False)
    assert selected == [("DP-1", "grid")]
    assert not preview.tiling_pickers["DP-1"].buttons["grid"].get_sensitive()


@pytest.mark.parametrize(
    "count,orientation,expected",
    [
        (1, "horizontal", "fullscreen"),
        (2, "horizontal", "rows"),
        (2, "vertical", "columns"),
        (3, "horizontal", "main-top"),
        (3, "vertical", "main-left"),
        (4, "vertical", "grid"),
    ],
)
def test_legacy_inference_and_unused_displays(preview, count, orientation, expected):
    """Infer exact existing layouts and expose unused physical monitors."""
    displays = [{"name": "DP-1"}, {"name": "HDMI-1"}]
    preview.configure(list(range(count)), "splitscreen", orientation, displays, True)
    assert len(preview.monitor_grids) == len(preview.monitor_names) == 1
    assert preview.instances == list(range(count))
    assert preview.get_monitor_layouts() == {
        "DP-1": {"template": expected, "players": list(range(count))},
        "HDMI-1": {"template": "fullscreen", "players": []},
    }


def test_legacy_fallback_does_not_overwrite_first_monitor(preview):
    """Legacy overflow never replaces the primary monitor's saved assignment."""
    preview.configure(list(range(6)), "splitscreen", "horizontal", [{"name": "DP-1"}], True)
    assert len(preview.monitor_grids) == 2
    assert preview.get_monitor_layouts() == {"DP-1": {"template": "grid", "players": [0, 1, 2, 3]}}


def test_mapped_empty_drop_and_rebuild_restore_opacity(preview):
    """Rebuilding an animated native canvas restores the original cards."""
    window = Gtk.Window(default_width=900, default_height=700)
    window.set_child(preview)
    plan = TilingPlan([monitor("DP-1", "columns", [0, None])], [])
    preview.configure_tiling(plan, True)
    window.present()
    context = GLib.MainContext.default()
    try:
        for _ in range(100):
            if not context.pending():
                break
            super(GLib.MainContext, context).iteration(False)
        assert preview.get_mapped()
        old_cells = [slot.cell for slot in preview._slots]
        assert preview.assign_player(0, 1)
        preview.configure_tiling(plan, False)
        assert not preview._motion.active
        assert preview._drag_payload is None
        assert not preview._pending_card_images
        assert all(cell.get_opacity() == 1 for cell in old_cells)
        assert preview.instances == [0, None]
    finally:
        window.destroy()
