"""Exercise native card snapshots and animation lifecycle on a real GTK host."""

# flake8: noqa: E402

import gc
import time
import weakref
from dataclasses import is_dataclass
from typing import cast

import gi
import pytest

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, GObject, Graphene, Gtk

from src.gui.widgets.card_motion import CardMotion, CardRect, MovingCard


class _CardImage(GObject.Object, Gdk.Paintable):
    """A static, intrinsically sizeless image recording the requested render size."""

    def __init__(self):
        super().__init__()
        self.sizes = []
        self.color = Gdk.RGBA()
        self.color.parse("steelblue")

    def do_get_flags(self):
        return Gdk.PaintableFlags.STATIC_CONTENTS | Gdk.PaintableFlags.STATIC_SIZE

    def do_get_current_image(self):
        return self

    def do_snapshot(self, snapshot, width, height):
        self.sizes.append((width, height))
        snapshot.append_color(self.color, Graphene.Rect().init(0.0, 0.0, width, height))


class _TracingSnapshot(Gtk.Snapshot):
    """Record transforms while still drawing into a real native snapshot."""

    def __init__(self):
        super().__init__()
        self.operations = []
        self.translations = []
        self.opacities = []

    def save(self):
        self.operations.append("save")
        super().save()

    def translate(self, point):
        self.operations.append("translate")
        self.translations.append((point.x, point.y))
        super().translate(point)

    def restore(self):
        self.operations.append("restore")
        super().restore()

    def push_opacity(self, opacity):
        self.operations.append("push-opacity")
        self.opacities.append(opacity)
        super().push_opacity(opacity)

    def pop(self):
        self.operations.append("pop")
        super().pop()

    def scale(self, factor_x, factor_y):
        raise AssertionError("Paintable.snapshot already scales to the supplied width and height")


class _MotionHost(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.source = Gtk.Label(label="Player one")
        self.destination = Gtk.Label(label="Player two")
        self.append(self.source)
        self.append(self.destination)
        self.motion = CardMotion(self)
        self.snapshot_count = 0

    def do_snapshot(self, snapshot):
        Gtk.Box.do_snapshot(self, snapshot)
        if self.motion is not None:
            self.motion.snapshot(snapshot)
        self.snapshot_count += 1


def _iterate_until(predicate, timeout=2.0):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        # The native API avoids PyGObject's asyncio override, which uses a
        # deprecated event-loop policy on Python 3.14. No warning filters needed.
        super(GLib.MainContext, context).iteration(False)
        time.sleep(0.001)
    return predicate()


@pytest.fixture
def gtk_settings():
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        pytest.skip("A GTK display is required for native card motion tests")
    Adw.init()
    settings = Gtk.Settings.get_default()
    original = settings.get_property("gtk-enable-animations")
    settings.set_property("gtk-enable-animations", True)
    try:
        yield settings
    finally:
        settings.set_property("gtk-enable-animations", original)


@pytest.fixture
def scene(gtk_settings):
    window = Gtk.Window(default_width=640, default_height=240)
    host = _MotionHost()
    window.set_child(host)
    window.present()
    try:
        assert _iterate_until(lambda: host.get_mapped() and host.get_width() > 0 and host.snapshot_count > 0)
        yield window, host
    finally:
        if host.motion is not None:
            host.motion.finish()
        window.destroy()


def _card(image=None):
    return MovingCard(
        image if image is not None else _CardImage(),
        CardRect(-320.0, 40.0, 120.0, 80.0),
        CardRect(640.0, 240.0, 260.0, 150.0),
    )


def _assert_finished(motion):
    assert not motion.active
    assert motion.progress == 1.0
    assert motion._animation is None
    assert motion._cards == ()
    assert motion._hidden_widgets == {}
    assert motion._settings is None
    assert motion._done_handler == motion._settings_handler == 0


def test_motion_is_a_plain_object_with_geometry_dataclasses():
    assert not issubclass(CardMotion, GObject.Object)
    assert is_dataclass(CardRect)
    assert is_dataclass(MovingCard)
    assert CardRect(-120.0, 40.0, 80.0, 60.0) == CardRect(-120.0, 40.0, 80.0, 60.0)


def test_native_animation_advances_draws_and_finishes_without_changing_cells(scene):
    _, host = scene
    first = _card()
    second = MovingCard(_CardImage(), first.destination, first.origin)
    cells = (host.source, host.destination)
    original = [(cell.get_parent(), cell.get_width(), cell.get_height(), cell.get_label()) for cell in cells]
    snapshots_before = host.snapshot_count
    assert host.motion.play([first, second], cells)
    animation = host.motion._animation
    assert isinstance(animation, Adw.TimedAnimation)
    assert animation.get_widget() is host
    assert animation.get_duration() == 280
    assert animation.get_easing() == Adw.Easing.EASE_OUT_CUBIC
    assert all(cell.get_opacity() == 0.0 for cell in cells)
    samples = []

    def completed():
        samples.append(host.motion.progress)
        return not host.motion.active

    assert _iterate_until(completed)
    assert any(0.0 < progress < 1.0 for progress in samples)
    assert samples == sorted(samples)
    assert host.snapshot_count > snapshots_before
    _assert_finished(host.motion)
    assert animation.get_state() == Adw.AnimationState.FINISHED
    assert all(cell.get_opacity() == 1.0 for cell in cells)
    assert [(cell.get_parent(), cell.get_width(), cell.get_height(), cell.get_label()) for cell in cells] == original


@pytest.mark.parametrize("progress", [0.0, 0.5, 1.0])
def test_snapshot_interpolates_both_cards_positions_and_dimensions_without_double_scaling(scene, progress):
    _, host = scene
    first = _card()
    second = MovingCard(_CardImage(), first.destination, first.origin)
    assert host.motion.play([first, second], [host.source, host.destination])
    first.paintable.sizes.clear()
    second.paintable.sizes.clear()
    host.motion._on_value(progress)
    snapshot = _TracingSnapshot()
    host.motion.snapshot(snapshot)
    for index, card in enumerate((first, second)):
        expected = [
            start * (1.0 - progress) + end * progress
            for start, end in zip(
                (card.origin.x, card.origin.y, card.origin.width, card.origin.height),
                (card.destination.x, card.destination.y, card.destination.width, card.destination.height),
            )
        ]
        assert snapshot.translations[index] == pytest.approx(expected[:2])
        assert card.paintable.sizes == [pytest.approx(expected[2:])]
    assert snapshot.operations == [
        "push-opacity",
        "save",
        "translate",
        "restore",
        "save",
        "translate",
        "restore",
        "pop",
    ]


def test_last_tenth_crossfades_to_original_cell_opacity(scene):
    _, host = scene
    host.source.set_opacity(0.6)
    original = host.source.get_opacity()
    assert host.motion.play([_card()], [host.source])
    host.motion._on_value(0.9)
    assert host.source.get_opacity() == 0.0
    host.motion._on_value(0.95)
    snapshot = _TracingSnapshot()
    host.motion.snapshot(snapshot)
    assert snapshot.opacities == pytest.approx([0.5])
    assert host.source.get_opacity() == pytest.approx(original * 0.5, abs=1.0 / 255.0)
    host.motion.finish()
    assert host.source.get_opacity() == original


@pytest.mark.parametrize("endpoint", ["origin", "destination"])
@pytest.mark.parametrize(
    "rect",
    [
        CardRect(0, 0, 0, 40),
        CardRect(0, 0, 40, 0),
        CardRect(0, 0, -1, 40),
        CardRect(0, 0, 40, -1),
        CardRect(float("nan"), 0, 40, 40),
        CardRect(0, float("inf"), 40, 40),
        CardRect(0, 0, float("nan"), 40),
        CardRect(0, 0, 40, float("inf")),
        CardRect(1e100, 0, 40, 40),
        CardRect(cast(float, None), 0, 40, 40),
    ],
)
def test_invalid_geometry_skips_the_entire_batch_without_hiding_cells(scene, endpoint, rect):
    _, host = scene
    valid = _card()
    invalid = MovingCard(
        valid.paintable,
        rect if endpoint == "origin" else valid.origin,
        rect if endpoint == "destination" else valid.destination,
    )
    assert not host.motion.play([valid, invalid], [host.source, host.destination])
    assert not host.motion.active
    assert host.source.get_opacity() == host.destination.get_opacity() == 1.0
    assert host.motion._cards == ()


@pytest.mark.parametrize("empty_size", [(0, 0), (120, 80)])
def test_empty_paintable_does_not_hide_cells(scene, empty_size):
    _, host = scene
    empty = Gdk.Paintable.new_empty(*empty_size)
    assert not host.motion.play([_card(empty)], [host.source])
    assert host.source.get_opacity() == 1.0
    assert not host.motion.active


def test_missing_paintable_does_not_hide_cells(scene):
    _, host = scene
    card = _card()
    assert not host.motion.play([MovingCard(None, card.origin, card.destination)], [host.source])
    assert host.source.get_opacity() == 1.0


def test_empty_batch_is_a_no_op(scene):
    _, host = scene
    assert not host.motion.play([], [host.source])
    assert not host.motion.active
    snapshot = _TracingSnapshot()
    host.motion.snapshot(snapshot)
    assert snapshot.operations == []
    assert host.source.get_opacity() == 1.0


def test_unmapped_host_does_not_start_animation(gtk_settings):
    host = _MotionHost()
    assert not host.motion.play([_card()], [host.source])
    assert not host.motion.active
    assert host.source.get_opacity() == 1.0


def test_disabled_animations_do_not_capture_or_hide_cells(scene, gtk_settings):
    _, host = scene
    gtk_settings.set_property("gtk-enable-animations", False)
    card = _card()
    assert not host.motion.play([card], [host.source])
    assert card.paintable.sizes == []
    assert host.source.get_opacity() == 1.0
    assert not host.motion.active


def test_finish_is_idempotent_and_restores_original_opacity_with_duplicate_cells(scene):
    _, host = scene
    host.source.set_opacity(0.0)
    host.destination.set_opacity(0.42)
    original = host.destination.get_opacity()
    assert host.motion.play([_card()], [host.source, host.destination, host.destination])
    animation = host.motion._animation
    handler = host.motion._done_handler
    host.motion.finish()
    host.motion.finish()
    _assert_finished(host.motion)
    assert host.source.get_opacity() == 0.0
    assert host.destination.get_opacity() == original
    assert animation.get_state() == Adw.AnimationState.FINISHED
    assert not animation.handler_is_connected(handler)
    snapshot = _TracingSnapshot()
    host.motion.snapshot(snapshot)
    assert snapshot.operations == []


def test_superseded_animation_cannot_complete_or_update_its_replacement(scene):
    _, host = scene
    host.source.set_opacity(0.6)
    host.destination.set_opacity(0.4)
    originals = (host.source.get_opacity(), host.destination.get_opacity())
    assert host.motion.play([_card()], [host.source, host.destination])
    previous = host.motion._animation
    host.motion._on_value(0.95)
    assert host.motion.play([_card()], [host.destination])
    replacement = host.motion._animation
    assert replacement is not previous
    assert host.source.get_opacity() == originals[0]
    assert host.destination.get_opacity() == 0.0
    previous.play()
    previous.skip()
    host.motion._on_done(previous)
    assert host.motion.active
    assert host.motion._animation is replacement
    assert host.motion.progress == 0.0
    assert host.destination.get_opacity() == 0.0
    host.motion.finish()
    assert (host.source.get_opacity(), host.destination.get_opacity()) == originals


def test_skipped_replacement_finishes_previous_motion_first(scene):
    _, host = scene
    assert host.motion.play([_card()], [host.source])
    assert not host.motion.play([], [])
    _assert_finished(host.motion)
    assert host.source.get_opacity() == 1.0


def test_unmapping_native_host_finishes_and_restores_cells(scene):
    window, host = scene
    host.source.set_opacity(0.7)
    original = host.source.get_opacity()
    assert host.motion.play([_card()], [host.source])
    window.set_visible(False)
    assert _iterate_until(lambda: not host.motion.active)
    _assert_finished(host.motion)
    assert host.source.get_opacity() == original


def test_disabling_animations_mid_flight_finishes_and_allows_reuse(scene, gtk_settings):
    _, host = scene
    host.source.set_opacity(0.7)
    original = host.source.get_opacity()
    assert host.motion.play([_card()], [host.source])
    gtk_settings.set_property("gtk-enable-animations", False)
    _assert_finished(host.motion)
    assert host.source.get_opacity() == original
    gtk_settings.set_property("gtk-enable-animations", True)
    assert host.motion.play([_card()], [host.source])
    assert _iterate_until(lambda: not host.motion.active)
    assert host.source.get_opacity() == original


def test_live_widget_paintable_is_frozen_before_hiding_its_cell(scene):
    _, host = scene
    live = Gtk.WidgetPaintable.new(host.source)
    assert host.motion.play([_card(live)], [host.source])
    frozen = host.motion._cards[0].paintable
    assert frozen is not live
    assert frozen.get_flags() & Gdk.PaintableFlags.STATIC_CONTENTS
    snapshot = Gtk.Snapshot()
    host.motion.snapshot(snapshot)
    assert snapshot.to_node() is not None


def test_finish_releases_cells_images_and_bound_callbacks_even_if_animation_is_retained(scene):
    _, host = scene
    motion = host.motion
    image = _CardImage()
    cell = Gtk.Label(label="Detached cell")
    image_ref = weakref.ref(image)
    cell_ref = weakref.ref(cell)
    motion_ref = weakref.ref(motion)
    assert motion.play([_card(image)], [cell])
    animation = motion._animation
    del image, cell
    motion.finish()
    gc.collect()
    assert image_ref() is None
    assert cell_ref() is None
    host.motion = None
    del motion
    gc.collect()
    assert motion_ref() is None
    assert animation.get_state() == Adw.AnimationState.FINISHED
