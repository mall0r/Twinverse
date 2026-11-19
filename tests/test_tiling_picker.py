"""Real GTK controls and vector rendering for per-monitor tiling."""

# flake8: noqa: E402

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk

from src.core.tiling import TEMPLATES
from src.gui.widgets.tiling_picker import TilingPicker


@pytest.fixture
def picker():
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A GTK display is required; run these tests under xvfb-run on headless systems")
    return TilingPicker()


def active_ids(picker):
    return [key for key, button in picker.buttons.items() if button.get_active()]


def test_six_compact_native_controls(picker):
    assert list(picker.buttons) == ["fullscreen", "columns", "rows", "main-left", "main-top", "grid"]
    assert active_ids(picker) == ["fullscreen"]
    flow = picker.get_first_child()
    assert isinstance(flow, Gtk.FlowBox)
    assert flow.get_selection_mode() == Gtk.SelectionMode.NONE
    assert flow.get_min_children_per_line() == 1
    assert flow.get_max_children_per_line() == 6
    for key, button in picker.buttons.items():
        assert isinstance(button, Gtk.ToggleButton)
        assert button.get_focusable()
        assert button.get_accessible_role() == Gtk.AccessibleRole.TOGGLE_BUTTON
        assert TEMPLATES[key].title in button.get_tooltip_text()
        assert str(TEMPLATES[key].capacity) in button.get_tooltip_text()
        assert button.get_size_request() == (42, 36)
        assert button.get_child().get_size_request() == (34, 24)


def test_clicks_emit_once_and_keep_radio_selection(picker):
    changes = []
    picker.connect("template-selected", lambda _picker, key: changes.append(key))
    picker.buttons["fullscreen"].emit("clicked")
    assert active_ids(picker) == ["fullscreen"]
    assert changes == []
    for key in picker.buttons:
        picker.buttons[key].emit("clicked")
        picker.buttons[key].emit("clicked")
        assert active_ids(picker) == [key]
    assert changes == ["columns", "rows", "main-left", "main-top", "grid"]


def test_programmatic_selection_and_native_grouping(picker):
    changes = []
    picker.connect("template-selected", lambda _picker, key: changes.append(key))
    for key in picker.buttons:
        picker.set_selected(key)
        assert active_ids(picker) == [key]
    assert changes == []
    picker.buttons["rows"].set_active(True)
    assert active_ids(picker) == ["rows"]
    assert changes == ["rows"]
    with pytest.raises(KeyError):
        picker.set_selected("not-a-template")
    assert active_ids(picker) == ["rows"]


def test_locked_synthetic_clicks_cannot_change_selection(picker):
    changes = []
    picker.connect("template-selected", lambda _picker, key: changes.append(key))
    picker.set_editable(False)
    for button in picker.buttons.values():
        assert not button.is_sensitive()
        button.emit("clicked")
        assert active_ids(picker) == ["fullscreen"]
    assert changes == []
    picker.set_selected("main-top")
    assert active_ids(picker) == ["main-top"]
    assert changes == []
    picker.set_editable(True)
    assert all(button.is_sensitive() for button in picker.buttons.values())
    picker.buttons["grid"].emit("clicked")
    assert active_ids(picker) == ["grid"]
    assert changes == ["grid"]


@pytest.mark.parametrize("template_id", TEMPLATES)
def test_snapshot_contains_actual_template_rectangles(picker, template_id):
    thumbnail = picker.buttons[template_id].get_child()
    assert thumbnail.template is TEMPLATES[template_id]
    snapshot = Gtk.Snapshot()
    thumbnail.do_snapshot(snapshot)
    node = snapshot.to_node()
    assert node is not None
    bounds = node.get_bounds()
    assert bounds.get_width() == 34
    assert bounds.get_height() == 24

    class RecordingSnapshot:
        def __init__(self):
            self.cells = []

        def append_border(self, *args):
            pass

        def push_rounded_clip(self, cell):
            pass

        def append_color(self, color, rect):
            self.cells.append((rect.get_x(), rect.get_y(), rect.get_width(), rect.get_height()))

        def pop(self):
            pass

    recording = RecordingSnapshot()
    thumbnail.do_snapshot(recording)
    expected = [
        (3 + x * 28 + 0.5, 3 + y * 18 + 0.5, w * 28 - 1, h * 18 - 1) for x, y, w, h in TEMPLATES[template_id].rectangles
    ]
    assert recording.cells == expected


def test_constructor_selection(picker):
    assert active_ids(TilingPicker("main-left")) == ["main-left"]
