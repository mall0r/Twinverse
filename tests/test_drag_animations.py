"""Integrate real GTK drag controllers, frozen cards and the rendered session canvas."""

# flake8: noqa: E402

import os
import time
from dataclasses import dataclass, field

import gi
import pytest

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, Gtk

from src.gui.pages.layout_settings_page import LayoutSettingsPage
from src.gui.widgets.card_motion import CardRect
from src.gui.widgets.layout_preview import _PlayerDragPayload
from src.models import Profile

_SESSION_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR")
_STATIC_CONTENTS = getattr(Gdk.PaintableFlags, "STATIC_CONTENTS", None) or Gdk.PaintableFlags.CONTENTS
_STATIC_SIZE = getattr(Gdk.PaintableFlags, "STATIC_SIZE", None) or Gdk.PaintableFlags.SIZE


@dataclass
class _Scene:
    window: Gtk.Window
    page: LayoutSettingsPage
    paintable: Gtk.WidgetPaintable
    orders: list[list[int]] = field(default_factory=list)
    edits: list[list[int]] = field(default_factory=list)

    @property
    def preview(self):
        return self.page.layout_preview


def _iterate_until(predicate, timeout=3.0):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        # Bypass PyGObject's asyncio override and its deprecated Python 3.14 policy.
        super(GLib.MainContext, context).iteration(False)
        time.sleep(0.001)
    return predicate()


def _snapshot(paintable, width, height):
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, width, height)
    return snapshot.to_node()


def _visual_bytes(paintable, width, height):
    node = _snapshot(paintable, width, height)
    return None if node is None else bytes(node.serialize().get_data())


def _widget_node(widget):
    if not widget.get_mapped() or widget.get_width() <= 0 or widget.get_height() <= 0:
        return None
    return _snapshot(Gtk.WidgetPaintable.new(widget), widget.get_width(), widget.get_height())


@pytest.fixture
def gtk_settings(monkeypatch):
    # conftest isolates XDG paths, but Wayland still needs the actual display socket.
    if _SESSION_RUNTIME_DIR is not None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", _SESSION_RUNTIME_DIR)
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A native GTK display is required for drag animation integration tests")
    Adw.init()
    settings = Gtk.Settings.get_default()
    original = settings.get_property("gtk-enable-animations")
    settings.set_property("gtk-enable-animations", True)
    try:
        yield settings
    finally:
        settings.set_property("gtk-enable-animations", original)


@pytest.fixture
def devices():
    return {
        "displays": [
            {"id": 0, "name": "HDMI-A-1", "width": 1920, "height": 1080},
            {"id": 1, "name": "DP-1", "width": 2560, "height": 1440},
        ]
    }


@pytest.fixture
def scene(gtk_settings, devices):
    page = LayoutSettingsPage()
    page.load_data(Profile(num_players=6), devices, {})
    window = Gtk.Window(default_width=1200, default_height=1100)
    window.set_child(page)
    preview = page.layout_preview
    result = _Scene(window, page, Gtk.WidgetPaintable.new(preview))
    preview.connect("order-changed", lambda _preview, order: result.orders.append(list(order)))
    page.connect("settings-changed", lambda _page: result.edits.append(page.get_data()["layout_order"]))
    window.present()
    try:
        assert _iterate_until(
            lambda: _widget_node(preview) is not None
            and all(_widget_node(slot.cell) is not None for slot in preview._slots)
        ), "The entire six-player canvas must be mapped, allocated and rendered"
        assert result.orders == result.edits == []
        yield result
    finally:
        page._stop_drag_scrolling()
        preview._motion.finish()
        preview._clear_drag_state()
        if preview._activation_reset_id:
            GLib.source_remove(preview._activation_reset_id)
            preview._restore_player_activation()
        window.destroy()


def _controller(widget, controller_type):
    controllers = widget.observe_controllers()
    for index in range(controllers.get_n_items()):
        controller = controllers.get_item(index)
        if isinstance(controller, controller_type):
            return controller
    raise AssertionError(f"No native {controller_type.__name__} on {widget}")


def _prepare(preview, slot=0, x=17.0, y=23.0):
    source = _controller(preview._slots[slot].cell, Gtk.DragSource)
    provider = source.emit("prepare", x, y)
    assert isinstance(provider, Gdk.ContentProvider)
    assert provider.ref_formats().contain_gtype(_PlayerDragPayload)
    assert preview._drag_source is source
    assert preview._drag_payload.owner is preview
    return source, preview._drag_payload


def _bounds(preview, widget):
    found, bounds = widget.compute_bounds(preview)
    assert found
    return CardRect(bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height())


def _assert_rect(actual, expected):
    assert (actual.x, actual.y, actual.width, actual.height) == pytest.approx(
        (expected.x, expected.y, expected.width, expected.height)
    )


def _assert_order(scene, expected):
    assert scene.preview.instances == expected
    assert scene.page.get_data()["layout_order"] == expected
    assert scene.page.placement_mode_row.get_selected() == 1
    assert scene.orders == [expected]
    assert scene.edits == [expected]


def _assert_drag_cleared(preview):
    assert preview._drag_source is None
    assert preview._drag_payload is None
    assert preview._drag_image is None
    assert preview._drag_hotspot == (0, 0)
    assert preview._drag_size == (0, 0)
    assert all(not slot.cell.has_css_class("player-dragging") for slot in preview._slots)
    assert all(not slot.cell.has_css_class("slot-drop-target") for slot in preview._slots)


def _assert_motion_cleared(preview):
    motion = preview._motion
    assert not motion.active
    assert motion._animation is None
    assert motion._cards == ()
    assert motion._hidden_widgets == {}
    assert motion._settings is None
    assert motion._done_handler == motion._settings_handler == 0


def _start_drop(scene, source_slot=0, target_slot=2):
    preview = scene.preview
    source, payload = _prepare(preview, source_slot)
    source.emit("drag-begin", None)
    assert source.get_widget().has_css_class("player-dragging")
    target = _controller(preview._slots[target_slot].cell, Gtk.DropTarget)
    assert target.emit("drop", payload, 41.0, 37.0)
    assert preview._motion.active
    animation = preview._motion._animation
    assert isinstance(animation, Adw.TimedAnimation)
    animation.pause()
    return source, payload, animation


@pytest.mark.parametrize("x,y", [(-100.0, 100000.0), (100000.0, -100.0), (17.6, 29.4)])
def test_prepare_freezes_nonempty_full_card_and_sets_native_icon_with_clamped_hotspot(scene, monkeypatch, x, y):
    preview = scene.preview
    cell = preview._slots[0].cell
    source = _controller(cell, Gtk.DragSource)
    native_set_icon = source.set_icon
    calls = []

    def set_icon(image, hot_x, hot_y):
        calls.append((image, hot_x, hot_y))
        native_set_icon(image, hot_x, hot_y)

    monkeypatch.setattr(source, "set_icon", set_icon)
    _source, payload = _prepare(preview, x=x, y=y)
    image = preview._drag_image
    bounds = _bounds(preview, cell)
    width, height = round(bounds.width), round(bounds.height)
    hotspot = (
        round(max(0, min(width - 1, x * width / cell.get_width()))),
        round(max(0, min(height - 1, y * height / cell.get_height()))),
    )
    assert payload.instance == 0
    assert not isinstance(image, Gtk.WidgetPaintable)
    assert image.get_flags() & _STATIC_CONTENTS
    assert image.get_flags() & _STATIC_SIZE
    assert (image.get_intrinsic_width(), image.get_intrinsic_height()) == (width, height)
    assert preview._drag_size == (width, height)
    assert preview._drag_hotspot == hotspot
    assert calls == [(image, *hotspot)]
    assert _visual_bytes(image, width, height) is not None
    assert preview.instances == list(range(6))
    assert all(slot.cell.get_opacity() == 1.0 for slot in preview._slots)
    assert scene.orders == scene.edits == []
    _assert_motion_cleared(preview)


def test_frozen_drag_image_keeps_visual_identity_after_its_slot_changes_player(scene):
    preview = scene.preview
    cell = preview._slots[0].cell
    _source, _payload = _prepare(preview)
    image = preview._drag_image
    size = preview._drag_size
    original = _visual_bytes(image, *size)
    assert original is not None
    assert preview.assign_player(0, 2)
    assert preview._slots[0].cell is cell
    assert preview._slots[0].name.get_label() == "Player 3"
    assert preview._slots[2].name.get_label() == "Player 1"
    assert _visual_bytes(image, *size) == original
    assert _visual_bytes(preview._motion._cards[1].paintable, *size) == original
    preview._motion.finish()
    live = Gtk.WidgetPaintable.new(cell)
    assert _iterate_until(lambda: _visual_bytes(live, *size) not in (None, original))
    assert _visual_bytes(image, *size) == original
    _assert_order(scene, [2, 1, 0, 3, 4, 5])


@pytest.mark.parametrize("target_slot", [2, 5], ids=["same-monitor", "different-monitor-and-size"])
def test_drop_animates_both_cards_in_canvas_coordinates_once_without_reparenting(scene, monkeypatch, target_slot):
    preview = scene.preview
    slots = tuple(preview._slots)
    grids = tuple(preview.monitor_grids)
    cells = tuple(slot.cell for slot in slots)
    tracked = (*grids, *cells, *(slot.button for slot in slots))
    parents = [(widget, widget.get_parent()) for widget in tracked]
    parent_changes = []
    for widget in tracked:
        widget.connect("notify::parent", lambda widget, _pspec: parent_changes.append(widget))
    configure_calls = []
    native_configure = preview.configure

    def configure(*args, **kwargs):
        configure_calls.append(True)
        return native_configure(*args, **kwargs)

    monkeypatch.setattr(preview, "configure", configure)
    source_rect = _bounds(preview, cells[0])
    destination_rect = _bounds(preview, cells[target_slot])
    displaced_image = Gtk.WidgetPaintable.new(cells[target_slot]).get_current_image()
    displaced_visual = _visual_bytes(displaced_image, destination_rect.width, destination_rect.height)
    assert displaced_visual is not None
    source, payload = _prepare(preview, x=31.0, y=47.0)
    frozen = preview._drag_image
    size, hotspot = preview._drag_size, preview._drag_hotspot
    frozen_visual = _visual_bytes(frozen, *size)
    source.emit("drag-begin", None)
    target = _controller(cells[target_slot], Gtk.DropTarget)
    drop_x, drop_y = cells[target_slot].get_width() * 0.63, cells[target_slot].get_height() * 0.37
    assert target.emit("drop", payload, drop_x, drop_y)
    motion = preview._motion
    assert motion.active
    animation = motion._animation
    animation.pause()
    assert animation.get_widget() is preview
    assert len(motion._cards) == 2
    displaced, moved = motion._cards
    _assert_rect(displaced.origin, destination_rect)
    _assert_rect(displaced.destination, source_rect)
    _assert_rect(
        moved.origin,
        CardRect(
            destination_rect.x + destination_rect.width * 0.63 - hotspot[0],
            destination_rect.y + destination_rect.height * 0.37 - hotspot[1],
            *size,
        ),
    )
    _assert_rect(moved.destination, destination_rect)
    assert _visual_bytes(moved.paintable, *size) == frozen_visual
    assert _visual_bytes(displaced.paintable, destination_rect.width, destination_rect.height) == displaced_visual
    if target_slot == 5:
        assert destination_rect.x > source_rect.x + source_rect.width
        assert (destination_rect.width, destination_rect.height) != (source_rect.width, source_rect.height)
        assert cells[0].get_parent() is not cells[target_slot].get_parent()
    assert set(motion._hidden_widgets) == {cells[0], cells[target_slot]}
    assert cells[0].get_opacity() == cells[target_slot].get_opacity() == 0.0
    assert all(cell.get_opacity() == 1.0 for index, cell in enumerate(cells) if index not in (0, target_slot))
    expected = list(range(6))
    expected[0], expected[target_slot] = target_slot, 0
    _assert_order(scene, expected)
    assert source.get_widget() is cells[0]
    assert target.get_widget() is cells[target_slot]
    assert tuple(preview._slots) == slots
    assert tuple(preview.monitor_grids) == grids
    assert [(widget, widget.get_parent()) for widget in tracked] == parents
    assert parent_changes == configure_calls == []

    source.emit("drag-end", None, False)
    _assert_drag_cleared(preview)
    assert motion.active
    assert motion._animation is animation
    assert motion._cards == (displaced, moved)
    assert cells[0].get_opacity() == cells[target_slot].get_opacity() == 0.0
    animation.resume()
    assert _iterate_until(lambda: not motion.active)
    _assert_motion_cleared(preview)
    assert motion.progress == 1.0
    assert animation.get_state() == Adw.AnimationState.FINISHED
    assert all(cell.get_opacity() == 1.0 for cell in cells)
    assert tuple(preview._slots) == slots
    assert [(widget, widget.get_parent()) for widget in tracked] == parents
    assert parent_changes == configure_calls == []
    _assert_order(scene, expected)


def test_manual_player_setup_assignment_animates_both_cards_between_different_monitors(scene):
    preview = scene.preview
    cells = tuple(slot.cell for slot in preview._slots)
    source_rect = _bounds(preview, cells[0])
    destination_rect = _bounds(preview, cells[5])
    assert preview.assign_player(0, 5)
    assert preview._motion.active
    preview._motion._animation.pause()
    displaced, moved = preview._motion._cards
    _assert_rect(displaced.origin, destination_rect)
    _assert_rect(displaced.destination, source_rect)
    _assert_rect(moved.origin, source_rect)
    _assert_rect(moved.destination, destination_rect)
    assert (source_rect.width, source_rect.height) != (destination_rect.width, destination_rect.height)
    assert cells[0].get_opacity() == cells[5].get_opacity() == 0.0
    assert tuple(slot.cell for slot in preview._slots) == cells
    _assert_drag_cleared(preview)
    _assert_order(scene, [5, 1, 2, 3, 4, 0])
    preview._motion._animation.resume()
    assert _iterate_until(lambda: not preview._motion.active)
    assert all(cell.get_opacity() == 1.0 for cell in cells)
    _assert_motion_cleared(preview)
    _assert_order(scene, [5, 1, 2, 3, 4, 0])


def test_layout_preview_produces_nonempty_snapshots_while_native_animation_progresses(scene, monkeypatch):
    preview = scene.preview
    motion = preview._motion
    native_snapshot = motion.snapshot
    rendered_progress = []

    def snapshot(native):
        if motion.active:
            rendered_progress.append(motion.progress)
        native_snapshot(native)

    monkeypatch.setattr(motion, "snapshot", snapshot)
    assert preview.assign_player(0, 5)
    animation = motion._animation
    assert isinstance(animation, Adw.TimedAnimation)
    # Leave a generous observation window; do not require a particular frame time.
    animation.set_duration(2000)

    def rendered_motion():
        if motion.active and any(0.0 < progress < 1.0 for progress in rendered_progress):
            animation.pause()
            return True
        return False

    assert _iterate_until(rendered_motion)
    assert 0.0 < motion.progress < 1.0
    assert _snapshot(scene.paintable, preview.get_width(), preview.get_height()) is not None
    floating_cards = Gtk.Snapshot()
    motion.snapshot(floating_cards)
    assert floating_cards.to_node() is not None
    assert motion.active
    assert animation.get_state() == Adw.AnimationState.PAUSED
    _assert_order(scene, [5, 1, 2, 3, 4, 0])


@pytest.mark.parametrize("interaction", ["drop", "manual-assignment"])
def test_reduced_motion_updates_the_model_immediately_without_hiding_cells(scene, gtk_settings, interaction):
    preview = scene.preview
    cells = tuple(slot.cell for slot in preview._slots)
    gtk_settings.set_property("gtk-enable-animations", False)
    if interaction == "drop":
        source, payload = _prepare(preview)
        target = _controller(cells[5], Gtk.DropTarget)
        assert target.emit("drop", payload, 63.0, 51.0)
        source.emit("drag-end", None, False)
    else:
        assert preview.assign_player(0, 5)
    _assert_motion_cleared(preview)
    _assert_drag_cleared(preview)
    _assert_order(scene, [5, 1, 2, 3, 4, 0])
    assert tuple(slot.cell for slot in preview._slots) == cells
    assert all(cell.get_opacity() == 1.0 for cell in cells)
    assert _iterate_until(lambda: _widget_node(preview) is not None)
    assert preview._slots[0].name.get_label() == "Player 6"
    assert preview._slots[5].name.get_label() == "Player 1"


def test_cancelled_native_drag_does_not_mutate_or_hide_cards_and_rejects_stale_drop(scene):
    preview = scene.preview
    source, payload = _prepare(preview)
    source.emit("drag-begin", None)
    target = _controller(preview._slots[2].cell, Gtk.DropTarget)
    assert not source.emit("drag-cancel", None, Gdk.DragCancelReason.USER_CANCELLED)
    source.emit("drag-end", None, False)
    _assert_drag_cleared(preview)
    _assert_motion_cleared(preview)
    assert not target.emit("drop", payload, 21.0, 32.0)
    assert preview.instances == list(range(6))
    assert scene.page.get_data()["layout_order"] is None
    assert all(slot.cell.get_opacity() == 1.0 for slot in preview._slots)
    assert scene.orders == scene.edits == []
    assert _iterate_until(lambda: not preview._suppress_activation and preview._activation_reset_id == 0)


def test_noop_and_invalid_assignments_do_not_start_motion_or_hide_cards(scene):
    preview = scene.preview
    source, payload = _prepare(preview)
    target = _controller(preview._slots[0].cell, Gtk.DropTarget)
    assert not target.emit("drop", payload, 21.0, 32.0)
    for instance, slot in [(0, 0), (-1, 2), (0, 99), (True, 2)]:
        assert not preview.assign_player(instance, slot)
    assert preview.instances == list(range(6))
    assert scene.page.get_data()["layout_order"] is None
    assert scene.orders == scene.edits == []
    assert all(slot.cell.get_opacity() == 1.0 for slot in preview._slots)
    _assert_motion_cleared(preview)
    source.emit("drag-end", None, False)
    _assert_drag_cleared(preview)


@pytest.mark.parametrize("interruption", ["rebuild", "runtime-lock", "unmap", "new-drag"])
def test_interruptions_finish_motion_and_restore_original_cell_opacity(scene, interruption):
    preview = scene.preview
    cells = tuple(slot.cell for slot in preview._slots)
    cells[0].set_opacity(0.63)
    cells[2].set_opacity(0.78)
    original = tuple(cell.get_opacity() for cell in cells)
    assert _iterate_until(lambda: all(_widget_node(cell) is not None for cell in cells))
    source, payload, animation = _start_drop(scene)
    assert cells[0].get_opacity() == cells[2].get_opacity() == 0.0
    assert preview._drag_payload is payload
    if interruption == "rebuild":
        scene.page.orientation_row.set_selected(1 - scene.page.orientation_row.get_selected())
        assert all(slot.cell not in cells for slot in preview._slots)
        _assert_drag_cleared(preview)
    elif interruption == "runtime-lock":
        scene.page.player_rows[0].set_instance_state("running")
        assert not preview._allow_reposition
        assert not preview.assign_player(0, 5)
        assert source.emit("prepare", 7.0, 9.0) is None
        _assert_drag_cleared(preview)
    elif interruption == "unmap":
        scene.window.set_visible(False)
        assert _iterate_until(lambda: not preview.get_mapped())
    else:
        replacement, new_payload = _prepare(preview, slot=0)
        assert replacement is source
        assert new_payload is not payload
        assert new_payload.instance == 2
        assert preview._drag_image is not None
        assert not _controller(cells[5], Gtk.DropTarget).emit("drop", payload, 7.0, 9.0)
    _assert_motion_cleared(preview)
    assert animation.get_state() == Adw.AnimationState.FINISHED
    assert preview._motion.progress == 1.0
    assert tuple(cell.get_opacity() for cell in cells) == original
    assert preview.instances == [2, 1, 0, 3, 4, 5]
    assert scene.page.get_data()["layout_order"] == [2, 1, 0, 3, 4, 5]
    assert scene.orders == [[2, 1, 0, 3, 4, 5]]


def test_new_drag_from_an_animating_slot_freezes_a_nonempty_card_for_its_current_player(scene):
    preview = scene.preview
    source, _payload, animation = _start_drop(scene)
    source.emit("drag-end", None, False)
    assert _iterate_until(lambda: _widget_node(preview) is not None)
    assert preview._motion.active
    assert preview._slots[0].cell.get_opacity() == 0.0
    assert preview._slots[0].name.get_label() == "Player 3"

    replacement, payload = _prepare(preview, slot=0)
    assert replacement is source
    assert payload.instance == 2
    _assert_motion_cleared(preview)
    assert animation.get_state() == Adw.AnimationState.FINISHED
    assert all(slot.cell.get_opacity() == 1.0 for slot in preview._slots)
    _assert_order(scene, [2, 1, 0, 3, 4, 5])
    image = preview._drag_image
    assert image.get_flags() & _STATIC_CONTENTS, "The replacement drag must not use a live card"
    assert _visual_bytes(image, *preview._drag_size) is not None


def test_disabling_animations_during_a_drop_finishes_motion_without_reverting_assignment(scene, gtk_settings):
    preview = scene.preview
    source, _payload, animation = _start_drop(scene)
    gtk_settings.set_property("gtk-enable-animations", False)
    _assert_motion_cleared(preview)
    assert animation.get_state() == Adw.AnimationState.FINISHED
    assert all(slot.cell.get_opacity() == 1.0 for slot in preview._slots)
    source.emit("drag-end", None, False)
    _assert_drag_cleared(preview)
    _assert_order(scene, [2, 1, 0, 3, 4, 5])


def test_direct_snapshot_retires_motion_captured_for_a_different_canvas_allocation(scene):
    preview = scene.preview
    source, _payload, animation = _start_drop(scene)
    source.emit("drag-end", None, False)
    original_size = preview.get_width(), preview.get_height()
    assert preview._motion_size == original_size
    assert _iterate_until(lambda: _widget_node(preview) is not None)
    # Represent the previous allocation without relying on compositor resize policy.
    preview._motion_size = (original_size[0] + 64, original_size[1])
    snapshot = Gtk.Snapshot()
    preview.do_snapshot(snapshot)
    assert snapshot.to_node() is not None
    _assert_motion_cleared(preview)
    assert animation.get_state() == Adw.AnimationState.FINISHED
    assert all(slot.cell.get_opacity() == 1.0 for slot in preview._slots)
    _assert_order(scene, [2, 1, 0, 3, 4, 5])
