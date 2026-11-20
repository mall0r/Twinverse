"""Regress the two-column monitor wall, scaled GTK geometry and placement contracts."""

# flake8: noqa: E402

import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import gi
import pytest

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

from src.core.tiling import TEMPLATES, MonitorPlan, TilingPlan
from src.gui.pages.layout_settings_page import LayoutSettingsPage
from src.gui.widgets.card_motion import CardRect
from src.gui.widgets.layout_preview import LayoutPreview, _PlayerDragPayload
from src.models import Profile

_SESSION_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR")
_DEFAULT_SIZE = (1080, 720)
_STATIC_CONTENTS = getattr(Gdk.PaintableFlags, "STATIC_CONTENTS", None) or Gdk.PaintableFlags.CONTENTS


@dataclass
class _Scene:
    """Keep the mapped page and its actual edit notifications together."""

    window: Gtk.Window
    page: LayoutSettingsPage
    profile: Profile
    orders: list = field(default_factory=list)
    edits: list = field(default_factory=list)

    @property
    def preview(self):
        return self.page.layout_preview


def _iterate_until(predicate, timeout=3.0):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        # Avoid PyGObject's asyncio override and Python 3.14's deprecated policy.
        super(GLib.MainContext, context).iteration(False)
        time.sleep(0.001)
    return predicate()


def _settle(duration=0.08):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        super(GLib.MainContext, context).iteration(False)
        time.sleep(0.001)


def _rendered(widget):
    if not widget.get_mapped() or widget.get_width() <= 0 or widget.get_height() <= 0:
        return False
    snapshot = Gtk.Snapshot()
    Gtk.WidgetPaintable.new(widget).snapshot(snapshot, widget.get_width(), widget.get_height())
    return snapshot.to_node() is not None


def _displays(count, *, portrait=False):
    displays = [{"id": index, "name": f"DP-{index + 1}", "width": 1920, "height": 1080} for index in range(count)]
    if portrait:
        displays[-1].update(width=1080, height=1920)
    return displays


def _bounds(widget, relative_to):
    found, bounds = widget.compute_bounds(relative_to)
    assert found, "Mapped monitor widgets must share a GTK coordinate space"
    assert bounds.get_width() > 0 and bounds.get_height() > 0
    return CardRect(bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height())


def _assert_inside(inner, outer):
    assert inner.x >= outer.x - 1
    assert inner.y >= outer.y - 1
    assert inner.x + inner.width <= outer.x + outer.width + 1
    assert inner.y + inner.height <= outer.y + outer.height + 1


def _assert_wall(preview, count):
    wall = preview.monitor_wall
    assert isinstance(wall, Gtk.Grid)
    assert wall.get_parent() is preview
    assert len(preview.monitor_cards) == count
    children = []
    child = wall.get_first_child()
    while child is not None:
        children.append(child)
        child = child.get_next_sibling()
    assert set(children) == set(preview.monitor_cards)
    for index, card in enumerate(preview.monitor_cards):
        assert card.get_parent() is wall
        assert tuple(wall.query_child(card)) == (index % 2, index // 2, 1, 1)
        assert wall.get_child_at(index % 2, index // 2) is card


def _assert_row_major_bounds(preview):
    rects = [_bounds(card, preview) for card in preview.monitor_cards]
    for start in range(0, len(rects), 2):
        row = rects[start : start + 2]
        if len(row) == 2:
            left, right = row
            assert left.y == pytest.approx(right.y, abs=1)
            assert left.x + left.width < right.x
        if start >= 2:
            previous = rects[start - 2 : start]
            assert min(rect.y for rect in row) > max(rect.y + rect.height for rect in previous)
        if start:
            assert row[0].x == pytest.approx(rects[0].x, abs=1)
    if len(rects) == 4:
        assert rects[3].x == pytest.approx(rects[1].x, abs=1)


def _assert_monitor_ratios(preview, displays):
    for grid, display in zip(preview.monitor_grids, displays):
        frame = grid.get_parent()
        assert isinstance(frame, Gtk.AspectFrame)
        expected_ratio = display["width"] / display["height"]
        assert frame.get_ratio() == pytest.approx(expected_ratio)
        visual = _bounds(grid, preview)
        available = _bounds(frame, preview)
        _assert_inside(visual, available)
        assert visual.width / visual.height == pytest.approx(expected_ratio, rel=0.005)
        assert visual.x + visual.width / 2 == pytest.approx(available.x + available.width / 2, abs=1)
        assert visual.y + visual.height / 2 == pytest.approx(available.y + available.height / 2, abs=1)


def _controller(widget, kind):
    controllers = widget.observe_controllers()
    for index in range(controllers.get_n_items()):
        controller = controllers.get_item(index)
        if isinstance(controller, kind):
            return controller
    raise AssertionError(f"No native {kind.__name__} controller on the player cell")


@pytest.fixture
def gtk_style(monkeypatch):
    """Use real application CSS and restore all process-global GTK style settings."""
    # The shared XDG fixture must not hide the actual Wayland socket.
    if _SESSION_RUNTIME_DIR is not None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", _SESSION_RUNTIME_DIR)
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A native GTK display is required for monitor-grid regression tests")
    Adw.init()
    display = Gdk.Display.get_default()
    manager = Adw.StyleManager.get_default()
    scheme = manager.get_color_scheme()
    settings = Gtk.Settings.get_default()
    animations = settings.get_property("gtk-enable-animations")
    provider = Gtk.CssProvider()
    errors = []
    provider.connect("parsing-error", lambda _provider, _section, error: errors.append(str(error)))
    provider.load_from_path(str(Path(__file__).resolve().parents[1] / "res/styles/style.css"))
    assert errors == []
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    try:
        manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        settings.set_property("gtk-enable-animations", True)
        yield
    finally:
        Gtk.StyleContext.remove_provider_for_display(display, provider)
        settings.set_property("gtk-enable-animations", animations)
        manager.set_color_scheme(scheme)


@pytest.fixture
def map_window(gtk_style):
    """Map real windows and bound event processing, including failure-path cleanup."""
    windows = []

    def create(widget, preview, *, size=_DEFAULT_SIZE):
        window = Gtk.Window(default_width=size[0], default_height=size[1])
        window.add_css_class("twinverse-studio")
        window.add_css_class("dark")
        window.set_child(widget)
        windows.append((window, widget, preview))
        window.present()
        assert _iterate_until(lambda: _rendered(preview)), "The monitor wall must be mapped and rendered"
        _settle()
        return window

    yield create
    for window, widget, preview in reversed(windows):
        if isinstance(widget, LayoutSettingsPage):
            widget._stop_drag_scrolling()
            for row in widget.player_rows:
                row.clear_update_progress()
        preview._motion.finish()
        preview._clear_drag_state()
        if preview._activation_reset_id:
            GLib.source_remove(preview._activation_reset_id)
            preview._restore_player_activation()
        window.destroy()
    _settle()


@pytest.fixture
def workspace(map_window):
    """Load the complete roster/stage/inspector without Steam or device discovery."""

    def create(profile=None, displays=None):
        displays = _displays(2) if displays is None else displays
        if profile is None:
            order = [7, 1, 4, 0, 6, 2, 5, 3]
            profile = Profile(
                num_players=8,
                layout_order=order,
                monitor_layouts={
                    display["name"]: {"template": "grid", "players": order[index * 4 : index * 4 + 4]}
                    for index, display in enumerate(displays)
                },
            )
        page = LayoutSettingsPage()
        orders, edits = [], []
        page.layout_preview.connect("order-changed", lambda _preview, order: orders.append(list(order)))
        page.connect("settings-changed", lambda _page: edits.append(deepcopy(page.get_data())))
        page.load_data(profile, {"displays": displays}, {})
        window = map_window(page, page.layout_preview)
        assert orders == edits == [], "Loading and mapping are not user edits"
        return _Scene(window, page, profile, orders, edits)

    return create


@pytest.mark.parametrize("count", [1, 2, 3, 4])
@pytest.mark.parametrize("rendering", ["tiling", "legacy-splitscreen", "legacy-fullscreen", "legacy-unused"])
def test_monitor_wall_is_row_major_without_changing_slot_order_or_exports(gtk_style, count, rendering):
    """Both configure paths, including unused physical monitors, share a two-column wall."""
    displays = _displays(count)
    saved_displays = deepcopy(displays)
    preview = LayoutPreview()
    events = []
    for signal in ("order-changed", "template-selected", "player-activated"):
        preview.connect(signal, lambda *args: events.append(args[1:]))
    if rendering == "tiling":
        monitors = [
            MonitorPlan(
                display["name"], index, display, TEMPLATES["grid"], [index * 4 + 3, index * 4 + 1, None, index * 4]
            )
            for index, display in enumerate(displays)
        ]
        plan = TilingPlan(monitors, [99])
        saved_plan = deepcopy(plan)
        expected = {monitor.key: {"template": "grid", "players": list(monitor.players)} for monitor in monitors}
        instances = [player for monitor in monitors for player in monitor.players] + [99]
        used = count
    else:
        split = rendering != "legacy-fullscreen"
        group_size = 4 if split else 1
        used = count // 2 if rendering == "legacy-unused" else count
        instances = list(reversed(range(used * group_size)))
        expected = {
            display["name"]: {
                "template": "grid" if split and index < used else "fullscreen",
                "players": instances[index * group_size : (index + 1) * group_size],
            }
            for index, display in enumerate(displays)
        }
    saved_instances = list(instances)
    for _ in range(2):
        if rendering == "tiling":
            preview.configure_tiling(plan, True)
            assert plan == saved_plan
        else:
            preview.configure(instances, "splitscreen" if split else "fullscreen", "horizontal", displays, True)
        _assert_wall(preview, count)
        assert preview.instances == saved_instances
        assert [slot.instance for slot in preview._slots] == saved_instances
        assert preview.get_monitor_layouts() == expected
        assert preview.monitor_names == [f"DP-{index + 1}" for index in range(used)]
        assert len(preview.monitor_grids) == used
        for index in range(used, count):
            assert preview.monitor_cards[index].has_css_class("canvas-monitor-header")
        start = 0
        for index, display in enumerate(displays):
            players = expected[display["name"]]["players"]
            assert preview.monitor_slot_ranges[display["name"]] == (start, start + len(players))
            if players:
                grid = preview.monitor_grids[index]
                template = TEMPLATES[expected[display["name"]]["template"]]
                for local, rect in enumerate(template.rectangles):
                    assert tuple(grid.query_child(preview._slots[start + local].cell)) == tuple(
                        round(v * 2) for v in rect
                    )
            start += len(players)
        exported = preview.get_monitor_layouts()
        exported[displays[0]["name"]]["players"].append(-1)
        assert preview.get_monitor_layouts() == expected, "Exports must not alias live slot assignments"
        assert displays == saved_displays
        assert instances == saved_instances
        assert events == []


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_mapped_monitor_cards_never_add_a_third_column_and_second_row_is_below(map_window, count):
    """Real allocations follow 1 2 / 3 4, not a vertical stack or a four-column strip."""
    displays = _displays(count)
    plan = TilingPlan(
        [
            MonitorPlan(display["name"], index, display, TEMPLATES["grid"], list(range(index * 4, index * 4 + 4)))
            for index, display in enumerate(displays)
        ],
        [],
    )
    preview = LayoutPreview()
    preview.configure_tiling(plan, True)
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
    scroller.set_child(preview)
    map_window(scroller, preview)
    _assert_wall(preview, count)
    _assert_row_major_bounds(preview)
    _assert_monitor_ratios(preview, displays)
    assert preview.instances == list(range(count * 4))


@pytest.mark.parametrize("portrait", [False, True], ids=["landscape", "mixed-portrait"])
def test_two_four_player_monitors_fit_the_full_default_workspace_without_window_growth(workspace, portrait):
    """Scaled internal text must not enlarge the 1080x720 window or distort either monitor."""
    displays = _displays(2, portrait=portrait)
    scene = workspace(displays=displays)
    preview = scene.preview
    before = deepcopy(scene.page.get_data())
    assert tuple(scene.window.get_default_size()) == _DEFAULT_SIZE
    assert 0 < scene.window.get_width() <= _DEFAULT_SIZE[0]
    assert 0 < scene.window.get_height() <= _DEFAULT_SIZE[1]
    _assert_wall(preview, 2)
    _assert_row_major_bounds(preview)
    _assert_monitor_ratios(preview, displays)
    assert _iterate_until(lambda: all(_rendered(slot.cell) for slot in preview._slots))
    downscaled = False
    for grid in preview.monitor_grids:
        # compute_bounds includes CSS padding/borders; get_width/get_height do not.
        found, origin = grid.compute_point(preview, Graphene.Point().init(0, 0))
        assert found
        found, corner = grid.compute_point(preview, Graphene.Point().init(grid.get_width(), grid.get_height()))
        assert found
        assert 0 < corner.x - origin.x <= grid.get_width()
        assert 0 < corner.y - origin.y <= grid.get_height()
        if corner.x - origin.x < grid.get_width() and corner.y - origin.y < grid.get_height():
            downscaled = True
    assert downscaled, "Exercise genuine GTK downscaling, not window growth"
    assert preview.instances == [7, 1, 4, 0, 6, 2, 5, 3]
    assert [slot.instance for slot in preview._slots] == preview.instances
    assert preview.get_monitor_layouts() == before["monitor_layouts"]
    assert scene.page.get_data() == before
    assert scene.orders == scene.edits == []


def test_two_monitor_extent_needs_neither_scrolling_nor_drag_autoscroll(workspace):
    """Every slot is already inside the canvas viewport; there is no hidden scroll extent."""
    scene = workspace()
    scroller = scene.page.layout_preview_group
    viewport = CardRect(0, 0, scroller.get_width(), scroller.get_height())
    before = deepcopy(scene.page.get_data())
    for widget in (*scene.preview.monitor_cards, *scene.preview.monitor_grids, *(s.cell for s in scene.preview._slots)):
        _assert_inside(_bounds(widget, scroller), viewport)
    for adjustment in (scroller.get_hadjustment(), scroller.get_vadjustment()):
        assert adjustment.get_page_size() > 0
        assert adjustment.get_upper() == pytest.approx(adjustment.get_page_size(), abs=0.000001)
        assert adjustment.get_value() == adjustment.get_lower() == 0
        adjustment.set_value(adjustment.get_upper())
        assert adjustment.get_value() == 0, "There must be no range for edge autoscroll to expose"
    assert scene.page._drag_scroll_id == 0
    assert scene.page.get_data() == before
    assert scene.orders == scene.edits == []


@pytest.mark.parametrize("count", [2, 4])
def test_template_change_preserves_exact_wall_positions_and_emits_only_one_edit(workspace, count):
    """An internal rows/columns edit and subsequent resize never rearrange physical monitors."""
    displays = _displays(count)
    order = list(reversed(range(count * 2)))
    layouts = {
        display["name"]: {"template": "columns", "players": order[index * 2 : index * 2 + 2]}
        for index, display in enumerate(displays)
    }
    profile = Profile(num_players=count * 2, layout_order=order, monitor_layouts=layouts)
    saved_profile = deepcopy(profile.model_dump())
    scene = workspace(profile, displays)
    positions = [tuple(scene.preview.monitor_wall.query_child(card)) for card in scene.preview.monitor_cards]
    scene.preview.tiling_pickers["DP-1"].buttons["rows"].emit("clicked")
    _settle()
    expected = deepcopy(layouts)
    expected["DP-1"]["template"] = "rows"
    assert scene.preview.get_monitor_layouts() == scene.page.get_data()["monitor_layouts"] == expected
    assert scene.preview.instances == scene.page.get_data()["layout_order"] == order
    assert [tuple(scene.preview.monitor_wall.query_child(card)) for card in scene.preview.monitor_cards] == positions
    for index, grid in enumerate(scene.preview.monitor_grids):
        template = TEMPLATES["rows" if index == 0 else "columns"]
        for local, rect in enumerate(template.rectangles):
            assert tuple(grid.query_child(scene.preview._slots[index * 2 + local].cell)) == tuple(
                round(value * 2) for value in rect
            )
    assert scene.orders == []
    assert scene.edits == [scene.page.get_data()]
    after_edit = deepcopy(scene.page.get_data())
    scene.window.set_default_size(1260, 800)
    scene.preview.queue_resize()
    _settle()
    _assert_wall(scene.preview, count)
    _assert_row_major_bounds(scene.preview)
    assert scene.page.get_data() == after_edit
    assert scene.edits == [after_edit]
    assert profile.model_dump() == saved_profile


@pytest.mark.parametrize("source_slot,target_slot", [(0, 7), (7, 0)], ids=["left-to-right", "right-to-left"])
def test_native_cross_column_drop_uses_transformed_logical_coordinates_without_rebuilding(
    workspace, source_slot, target_slot
):
    """GTK hit testing and real drop handlers keep global slot identity under monitor scaling."""
    scene = workspace()
    preview = scene.preview
    assert _iterate_until(lambda: all(_rendered(slot.cell) for slot in preview._slots))
    cells = [slot.cell for slot in preview._slots]
    parents = [cell.get_parent() for cell in cells]
    cards, grids = list(preview.monitor_cards), list(preview.monitor_grids)
    before_profile = deepcopy(scene.profile.model_dump())
    before_data = deepcopy(scene.page.get_data())
    expected = list(preview.instances)
    player = expected[source_slot]
    expected[source_slot], expected[target_slot] = expected[target_slot], player
    destination = cells[target_slot]
    visible = _bounds(destination, preview)
    assert visible.width < destination.get_width()
    local = Graphene.Point().init(destination.get_width() * 0.63, destination.get_height() * 0.37)
    found, canvas = destination.compute_point(preview, local)
    assert found
    found, roundtrip = preview.compute_point(destination, canvas)
    assert found
    assert (roundtrip.x, roundtrip.y) == pytest.approx((local.x, local.y), abs=0.001)
    picked = preview.pick(canvas.x, canvas.y, Gtk.PickFlags.DEFAULT)
    while picked is not None and picked is not destination:
        picked = picked.get_parent()
    assert picked is destination, "Native hit testing must invert the monitor's render transform"
    source = _controller(cells[source_slot], Gtk.DragSource)
    provider = source.emit("prepare", 17.0, 23.0)
    assert isinstance(provider, Gdk.ContentProvider)
    assert provider.ref_formats().contain_gtype(_PlayerDragPayload)
    payload = preview._drag_payload
    assert payload.owner is preview and payload.instance == player
    assert scene.page.get_data() == before_data
    assert scene.orders == scene.edits == []
    source.emit("drag-begin", None)
    target = _controller(destination, Gtk.DropTarget)
    assert target.emit("drop", payload, local.x, local.y)
    assert preview.instances == scene.page.get_data()["layout_order"] == expected
    expected_layouts = {
        "DP-1": {"template": "grid", "players": expected[:4]},
        "DP-2": {"template": "grid", "players": expected[4:]},
    }
    assert preview.get_monitor_layouts() == scene.page.get_data()["monitor_layouts"] == expected_layouts
    assert scene.orders == [expected]
    assert scene.edits == [scene.page.get_data()]
    assert [slot.cell for slot in preview._slots] == cells
    assert [cell.get_parent() for cell in cells] == parents
    assert preview.monitor_cards == cards and preview.monitor_grids == grids
    _assert_wall(preview, 2)
    source.emit("drag-end", None, False)
    assert not target.emit("drop", payload, local.x, local.y), "A stale native payload is not another edit"
    assert scene.orders == [expected]
    assert scene.edits == [scene.page.get_data()]
    assert scene.profile.model_dump() == before_profile


def test_native_drag_icon_uses_the_visible_scaled_card_size(workspace):
    """Keep the ghost and grab offset identical to the card's visible size."""
    scene = workspace()
    preview = scene.preview
    cell = preview._slots[0].cell
    assert _iterate_until(lambda: _rendered(cell))
    visible = _bounds(cell, preview)
    source = _controller(cell, Gtk.DragSource)
    local = Graphene.Point().init(cell.get_width() * 0.4, cell.get_height() * 0.3)
    assert source.emit("prepare", local.x, local.y) is not None
    image = preview._drag_image
    assert isinstance(image, Gdk.Paintable)
    snapshot = Gtk.Snapshot()
    image.snapshot(snapshot, *preview._drag_size)
    assert snapshot.to_node() is not None, "The native ghost must contain the frozen player card"
    assert image.get_flags() & _STATIC_CONTENTS
    assert scene.orders == scene.edits == []
    expected_size = (visible.width, visible.height)
    assert preview._drag_size == pytest.approx(expected_size, abs=1)
    assert (image.get_intrinsic_width(), image.get_intrinsic_height()) == pytest.approx(expected_size, abs=1)
    found, canvas = cell.compute_point(preview, local)
    assert found
    assert preview._drag_hotspot == pytest.approx((canvas.x - visible.x, canvas.y - visible.y), abs=1)
