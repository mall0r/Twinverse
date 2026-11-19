"""Animate frozen cards above a host's normal content without changing its layout."""

# flake8: noqa: E402

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GLib, Graphene, Gtk


@dataclass(frozen=True)
class CardRect:
    """A card's position and size in the snapshot host's coordinate space."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class MovingCard:
    """A captured card and its two rectangles, including cross-monitor destinations."""

    paintable: Gdk.Paintable
    origin: CardRect
    destination: CardRect


class CardMotion:
    """Draw motion after the host's normal snapshot; never reparent or resize widgets.

    Call ``finish()`` before rebuilding or reallocating the host, or starting a drag.
    Unmapping and disabling GTK animations also finish an active animation. The
    caller owns all assignment changes; this helper only animates their appearance.
    """

    def __init__(self, host: Gtk.Widget):
        self._host = host
        self._animation: Adw.TimedAnimation | None = None
        self._done_handler = 0
        self._settings: Gtk.Settings | None = None
        self._settings_handler = 0
        self._cards: tuple[MovingCard, ...] = ()
        self._hidden_widgets: dict[Gtk.Widget, float] = {}
        self._progress = 0.0

    @property
    def active(self) -> bool:
        """Whether an animation currently owns snapshots and hidden cells."""
        return self._animation is not None

    @property
    def progress(self) -> float:
        """The eased interpolation value, from zero to one (one after finishing)."""
        return self._progress

    def play(self, cards: Sequence[MovingCard], hidden_widgets: Sequence[Gtk.Widget]) -> bool:
        """Replace any previous motion, returning whether native animation started.

        Invalid rectangles or empty snapshots skip the entire batch without hiding
        any cells. Paintables are frozen before cells are hidden, so even a live
        ``Gtk.WidgetPaintable`` cannot track subsequent card or opacity changes.
        """
        self.finish()
        if not cards or not self._host.get_mapped():
            return False
        settings = self._host.get_settings()
        if not settings.get_property("gtk-enable-animations"):
            return False

        prepared = []
        for card in cards:
            if (
                not isinstance(card, MovingCard)
                or not isinstance(card.paintable, Gdk.Paintable)
                or not self._valid_rect(card.origin)
                or not self._valid_rect(card.destination)
            ):
                return False
            image = card.paintable.get_current_image()
            if image is None:
                return False
            probe = Gtk.Snapshot()
            image.snapshot(probe, card.origin.width, card.origin.height)
            if probe.to_node() is None:
                return False
            prepared.append(MovingCard(image, card.origin, card.destination))

        self._cards = tuple(prepared)
        self._hidden_widgets = {widget: widget.get_opacity() for widget in hidden_widgets}
        self._progress = 0.0
        target = Adw.CallbackAnimationTarget.new(self._on_value)
        animation = Adw.TimedAnimation.new(self._host, 0.0, 1.0, 280, target)
        animation.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self._animation = animation
        self._done_handler = animation.connect("done", self._on_done)
        self._settings = settings
        self._settings_handler = settings.connect("notify::gtk-enable-animations", self._on_animations_changed)
        for widget in self._hidden_widgets:
            widget.set_opacity(0.0)
        self._host.queue_draw()
        animation.play()
        return self.active

    def snapshot(self, snapshot: Gtk.Snapshot):
        """Append moving cards without clipping their path to individual monitors."""
        if not self.active:
            return
        progress = self._progress
        snapshot.push_opacity(1.0 - self._reveal_fraction())
        try:
            for card in self._cards:
                origin, destination = card.origin, card.destination
                x = origin.x * (1.0 - progress) + destination.x * progress
                y = origin.y * (1.0 - progress) + destination.y * progress
                width = origin.width * (1.0 - progress) + destination.width * progress
                height = origin.height * (1.0 - progress) + destination.height * progress
                snapshot.save()
                try:
                    snapshot.translate(Graphene.Point().init(x, y))
                    card.paintable.snapshot(snapshot, width, height)
                finally:
                    snapshot.restore()
        finally:
            snapshot.pop()

    def finish(self):
        """Stop native callbacks and restore every cell's original opacity, once."""
        animation, self._animation = self._animation, None
        settings, self._settings = self._settings, None
        hidden_widgets, self._hidden_widgets = self._hidden_widgets, {}
        self._cards = ()
        if settings is not None and self._settings_handler:
            settings.disconnect(self._settings_handler)
        self._settings_handler = 0
        if animation is not None:
            if self._done_handler:
                animation.disconnect(self._done_handler)
            # Release the bound callback even if another caller retains the animation.
            animation.set_target(Adw.CallbackAnimationTarget.new(lambda _value: None))
            animation.skip()
            self._progress = 1.0
        self._done_handler = 0
        for widget, opacity in hidden_widgets.items():
            widget.set_opacity(opacity)
        if animation is not None or hidden_widgets:
            self._host.queue_draw()

    @staticmethod
    def _valid_rect(rect: CardRect) -> bool:
        if not isinstance(rect, CardRect):
            return False
        try:
            return (
                all(
                    isfinite(value) and abs(value) <= GLib.MAXFLOAT
                    for value in (rect.x, rect.y, rect.width, rect.height)
                )
                and rect.width > 0.0
                and rect.height > 0.0
            )
        except (TypeError, ValueError, OverflowError):
            return False

    def _reveal_fraction(self) -> float:
        return max(0.0, min(1.0, (self._progress - 0.9) / 0.1))

    def _on_value(self, value: float):
        if not self.active:
            return
        self._progress = max(0.0, min(1.0, value))
        reveal = self._reveal_fraction()
        for widget, opacity in self._hidden_widgets.items():
            widget.set_opacity(opacity * reveal)
        self._host.queue_draw()

    def _on_done(self, animation: Adw.Animation):
        if animation is self._animation:
            self.finish()

    def _on_animations_changed(self, settings: Gtk.Settings, _pspec):
        if not settings.get_property("gtk-enable-animations") and self._animation is not None:
            self._animation.skip()
