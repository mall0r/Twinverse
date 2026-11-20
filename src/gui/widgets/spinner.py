"""Reliable activity spinner that resumes animation after unmap/remap cycles."""

# flake8: noqa: E402

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

_HAS_ADW_SPINNER = hasattr(Adw, "Spinner")


class StudioSpinner(Gtk.Box):
    """Wrap Adw.Spinner when available (Libadwaita >= 1.6) to avoid GTK4 GtkSpinner freezes.

    In newer GTK4 releases, Gtk.Spinner stops advancing its CSS keyframe animation once
    an ancestor such as Adw.OverlaySplitView or Gtk.Stack unmaps and remaps it. Adw.Spinner
    uses AdwSpinnerPaintable tied to the widget's frame clock and cleanly pauses/resumes.
    On Libadwaita 1.5 runtimes without Adw.Spinner, this falls back to Gtk.Spinner while
    exposing the same start/stop/set_spinning/get_spinning interface.
    """

    def __init__(self, size: int = 16, **kwargs):
        """Initialize an idle spinner sized to fit inline status indicators and buttons."""
        super().__init__(**kwargs)
        self._spinning = False
        self.set_size_request(size, size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self._inner = Adw.Spinner() if _HAS_ADW_SPINNER else Gtk.Spinner()
        self._inner.set_size_request(size, size)
        self._inner.set_visible(False)
        self.append(self._inner)

    def get_spinning(self) -> bool:
        """Return whether the spinner is logically active."""
        return self._spinning

    def set_spinning(self, spinning: bool):
        """Start or stop the activity indicator."""
        self._spinning = bool(spinning)
        if not _HAS_ADW_SPINNER:
            self._inner.set_spinning(self._spinning)
        self._inner.set_visible(self._spinning)

    def start(self):
        """Activate the spinner."""
        self.set_spinning(True)

    def stop(self):
        """Deactivate the spinner."""
        self.set_spinning(False)
