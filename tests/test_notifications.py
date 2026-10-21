"""Check the desktop notifications, used when the window is hidden."""

from unittest.mock import Mock

from gi.repository import Gio

from src.gui.notifications import send_desktop_notification
from src.gui.windows.main_window import MainWindow


class _Bus:
    """A session bus that only records the calls."""

    def __init__(self):
        """Start without calls."""
        self.calls = []

    def call_sync(self, *args):
        """Record the call."""
        self.calls.append(args)


def test_the_notification_goes_through_the_portal(monkeypatch):
    """The portal is the interface a sandboxed application is allowed to use."""
    bus = _Bus()
    monkeypatch.setattr(Gio, "bus_get_sync", lambda *args, **kwargs: bus)

    assert send_desktop_notification("Twinverse", "a Steam nao abriu") is True

    call = bus.calls[0]
    assert call[0] == "org.freedesktop.portal.Desktop"
    assert call[1] == "/org/freedesktop/portal/desktop"
    assert call[2] == "org.freedesktop.portal.Notification"
    assert call[3] == "AddNotification"


def test_a_notification_that_cannot_be_sent_is_not_an_error(monkeypatch):
    """A desktop without the portal must not break the application."""

    def _boom(*args, **kwargs):
        raise RuntimeError("sem portal")

    monkeypatch.setattr(Gio, "bus_get_sync", _boom)

    assert send_desktop_notification("Twinverse", "a Steam nao abriu") is False


def test_the_toast_notifies_the_desktop_when_the_window_is_hidden(monkeypatch):
    """A message with the window hidden has to reach the desktop."""
    sent = []
    monkeypatch.setattr(
        "src.gui.windows.main_window.send_desktop_notification",
        lambda title, body, icon="dialog-warning": sent.append((title, body)) or True,
    )
    window = Mock()
    window.is_active.return_value = False
    window._toast = None

    MainWindow.show_toast(window, "a Steam nao abriu")

    assert sent == [("Twinverse", "a Steam nao abriu")]


def test_the_toast_stays_inside_the_window_when_it_is_visible(monkeypatch):
    """A visible window shows the message by itself."""
    sent = []
    monkeypatch.setattr(
        "src.gui.windows.main_window.send_desktop_notification",
        lambda title, body, icon="dialog-warning": sent.append((title, body)) or True,
    )
    window = Mock()
    window.is_active.return_value = True
    window._toast = None

    MainWindow.show_toast(window, "a Steam nao abriu")

    assert sent == []
