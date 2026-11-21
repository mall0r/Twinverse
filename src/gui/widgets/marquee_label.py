"""Single-line label that smoothly scrolls overflowing text horizontally."""

# flake8: noqa: E402

from typing import Optional

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, Graphene, Gsk, Gtk, Pango

DEFAULT_PAUSE_START_SECONDS = 0.85
DEFAULT_PAUSE_END_SECONDS = 0.85
DEFAULT_FORWARD_SPEED_PX = 36.0
DEFAULT_RETURN_SPEED_PX = 52.0
_VERTICAL_PADDING = 2

_CLEAR_RGBA = Gdk.RGBA()
_CLEAR_RGBA.parse("rgba(0, 0, 0, 0)")


def compute_marquee_offset(
    elapsed_seconds: float,
    overflow: float,
    *,
    pause_start: float = DEFAULT_PAUSE_START_SECONDS,
    pause_end: float = DEFAULT_PAUSE_END_SECONDS,
    forward_speed: float = DEFAULT_FORWARD_SPEED_PX,
    return_speed: float = DEFAULT_RETURN_SPEED_PX,
) -> float:
    """Return the horizontal pixel offset for a ping-pong marquee cycle."""
    if overflow <= 0.0 or elapsed_seconds <= 0.0 or forward_speed <= 0.0 or return_speed <= 0.0:
        return 0.0
    forward_duration = overflow / forward_speed
    return_duration = overflow / return_speed
    cycle_duration = pause_start + forward_duration + pause_end + return_duration
    if cycle_duration <= 0.0:
        return 0.0
    t = elapsed_seconds % cycle_duration
    if t < pause_start:
        return 0.0
    t -= pause_start
    if t < forward_duration:
        return min(overflow, t * forward_speed)
    t -= forward_duration
    if t < pause_end:
        return overflow
    t -= pause_end
    return max(0.0, overflow - t * return_speed)


class _MarqueeLayout(Gtk.LayoutManager):
    """Cap natural horizontal width while allocating the inner label unclipped."""

    def do_get_request_mode(self, _widget):
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_measure(self, widget, orientation, _for_size):
        child = widget.get_child()
        if child is None:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.VERTICAL:
            min_h, nat_h, min_base, nat_base = child.measure(Gtk.Orientation.VERTICAL, -1)
            pad = _VERTICAL_PADDING
            return (
                min_h + 2 * pad,
                nat_h + 2 * pad,
                min_base + pad if min_base >= 0 else -1,
                nat_base + pad if nat_base >= 0 else -1,
            )
        child_min, child_nat = child.measure(Gtk.Orientation.HORIZONTAL, -1)[:2]
        natural = min(child_nat, widget.max_width)
        minimum = min(child_min, natural, 48)
        return minimum, natural, -1, -1

    def do_allocate(self, widget, width, height, baseline):
        child = widget.get_child()
        if child is None or width <= 0 or height <= 0:
            return
        label_height = min(height, max(1, child.measure(Gtk.Orientation.VERTICAL, -1)[1]))
        offset_y = (height - label_height) // 2
        transform = Gsk.Transform.new().translate(Graphene.Point().init(0.0, float(offset_y))) if offset_y else None
        child_baseline = baseline - offset_y if baseline >= 0 else -1
        if widget.animations_enabled():
            text_width = child.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            overflow = max(0.0, float(text_width - width))
            widget._set_overflow(overflow)
            child.allocate(max(width, text_width), label_height, child_baseline, transform)
        else:
            widget._set_overflow(0.0)
            child.allocate(width, label_height, child_baseline, transform)


class MarqueeLabel(Adw.Bin):
    """Clip a single-line label and scroll it back and forth when it overflows.

    When GTK animations are disabled, the label falls back to standard end
    ellipsization instead of scrolling.
    """

    def __init__(self, text: str = "", max_width: int = 220, **kwargs):
        """Initialize the clipped scrolling label with a maximum natural width."""
        super().__init__(**kwargs)
        self.max_width = max(48, int(max_width))
        self._overflow = 0.0
        self._offset = 0.0
        self._tick_id = 0
        self._start_time_us: Optional[int] = None
        self._settings: Optional[Gtk.Settings] = None
        self._settings_handler = 0

        self.set_overflow(Gtk.Overflow.HIDDEN)
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.FILL)
        self.set_layout_manager(_MarqueeLayout())

        self._label = Gtk.Label(label=text, xalign=0, single_line_mode=True)
        self.set_child(self._label)
        self._sync_ellipsize()

        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def set_text(self, text: str) -> None:
        """Replace the displayed text and reset any active scroll offset."""
        text = text or ""
        if text == self._label.get_text() and self._offset == 0.0:
            return
        self.stop()
        self._overflow = 0.0
        self._label.set_text(text)
        self.queue_resize()
        self.queue_draw()

    def get_text(self) -> str:
        """Return the current label text."""
        return self._label.get_text()

    def get_overflow(self) -> float:
        """Return the overflowing pixel width beyond the allocated viewport."""
        return self._overflow

    def get_scroll_offset(self) -> float:
        """Return the current horizontal scroll offset in pixels."""
        return self._offset

    def is_scrolling(self) -> bool:
        """Return whether the frame-clock marquee ticker is currently active."""
        return self._tick_id != 0

    def animations_enabled(self) -> bool:
        """Return whether GTK animations are enabled for this widget."""
        settings = self.get_settings()
        if settings is None:
            return True
        return bool(settings.get_property("gtk-enable-animations"))

    def advance(self, elapsed_seconds: float) -> float:
        """Advance the scroll offset to ``elapsed_seconds`` and redraw if moved."""
        new_offset = compute_marquee_offset(elapsed_seconds, self._overflow) if self.animations_enabled() else 0.0
        if abs(new_offset - self._offset) >= 0.25 or (new_offset == 0.0 and self._offset != 0.0):
            self._offset = new_offset
            self.queue_draw()
        return self._offset

    def stop(self) -> None:
        """Stop scrolling and reset the text back to the leading edge."""
        if self._tick_id:
            self.remove_tick_callback(self._tick_id)
            self._tick_id = 0
        self._start_time_us = None
        if self._offset != 0.0:
            self._offset = 0.0
            self.queue_draw()

    def _sync_ellipsize(self) -> None:
        mode = Pango.EllipsizeMode.NONE if self.animations_enabled() else Pango.EllipsizeMode.END
        if self._label.get_ellipsize() != mode:
            self._label.set_ellipsize(mode)

    def _set_overflow(self, overflow: float) -> None:
        self._overflow = overflow if overflow > 1.0 else 0.0
        if self._overflow > 0.0 and self.get_mapped() and self.animations_enabled():
            self._ensure_tick()
        else:
            self.stop()

    def _ensure_tick(self) -> None:
        if self._tick_id == 0:
            self._start_time_us = None
            self._tick_id = self.add_tick_callback(self._on_tick)

    def _on_tick(self, _widget, frame_clock) -> bool:
        if not self.get_mapped() or self._overflow <= 0.0 or not self.animations_enabled():
            self._tick_id = 0
            self._start_time_us = None
            if self._offset != 0.0:
                self._offset = 0.0
                self.queue_draw()
            return False
        now = frame_clock.get_frame_time()
        if self._start_time_us is None:
            self._start_time_us = now
        elapsed = max(0.0, (now - self._start_time_us) / 1_000_000.0)
        self.advance(elapsed)
        return True

    def _on_map(self, _widget) -> None:
        self._disconnect_settings()
        settings = self.get_settings()
        if settings is not None:
            self._settings = settings
            self._settings_handler = settings.connect("notify::gtk-enable-animations", self._on_animations_changed)
        self._sync_ellipsize()
        self.stop()
        if self._overflow > 0.0 and self.animations_enabled():
            self._ensure_tick()

    def _on_unmap(self, _widget) -> None:
        self.stop()
        self._disconnect_settings()

    def _on_animations_changed(self, *_args) -> None:
        self._sync_ellipsize()
        if not self.animations_enabled():
            self.stop()
        self.queue_resize()

    def _disconnect_settings(self) -> None:
        if self._settings is not None and self._settings_handler:
            self._settings.disconnect(self._settings_handler)
        self._settings = None
        self._settings_handler = 0

    def do_snapshot(self, snapshot) -> None:
        """Translate the inner label inside the clip while damaging the full row height."""
        if self._overflow > 0.0:
            width = float(self.get_width())
            height = float(self.get_height())
            snapshot.save()
            snapshot.translate(Graphene.Point().init(-self._offset, 0.0))
            if width > 0.0 and height > 0.0:
                # Expand the diffed subtree bounds to the full widget height so partial-damage
                # renderers (such as GSK Vulkan) repaint glyph antialiasing pixels above Pango's
                # tight ink rect instead of leaving static dots along the top edge.
                snapshot.append_color(_CLEAR_RGBA, Graphene.Rect().init(0.0, 0.0, width + self._overflow, height))
            self.snapshot_child(self._label, snapshot)
            snapshot.restore()
            return
        self.snapshot_child(self._label, snapshot)
