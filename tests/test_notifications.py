"""Check the desktop notifications, used when the window is hidden."""

from unittest.mock import Mock

from gi.repository import Gio

from src.gui.notifications import BUSY, ERROR, INFO, send_desktop_notification
from src.gui.windows.main_window import MainWindow


class _Bus:
    """A session bus that only records the calls."""

    def __init__(self):
        """Start without calls."""
        self.calls = []

    def call_sync(self, *args):
        """Record the call."""
        self.calls.append(args)


def _sent_notification(monkeypatch, level) -> dict:
    """Send a notification and return what went to the portal."""
    bus = _Bus()
    monkeypatch.setattr(Gio, "bus_get_sync", lambda *args, **kwargs: bus)

    send_desktop_notification("Twinverse", "a Steam nao abriu", level)

    _, notification = bus.calls[0][4].unpack()
    return dict(notification)


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


def test_a_message_that_is_only_information_is_not_a_warning(monkeypatch):
    """A message that only tells something is shown as information."""
    notification = _sent_notification(monkeypatch, INFO)

    assert notification["icon"] == "dialog-information"
    assert notification["urgency"] == "low"


def test_a_failure_is_shown_as_an_error(monkeypatch):
    """A failure is critical, so it is not missed behind a game."""
    notification = _sent_notification(monkeypatch, ERROR)

    assert notification["icon"] == "dialog-error"
    assert notification["urgency"] == "critical"


def test_a_message_of_a_work_in_progress_shows_that_it_is_busy(monkeypatch):
    """A client that is starting, or updating, shows the icon of a refresh."""
    notification = _sent_notification(monkeypatch, BUSY)

    assert notification["icon"] == "view-refresh"
    assert notification["urgency"] == "low"


def test_the_toast_notifies_the_desktop_when_the_window_is_hidden(monkeypatch):
    """A message with the window hidden has to reach the desktop."""
    sent = []
    monkeypatch.setattr(
        "src.gui.windows.main_window.send_desktop_notification",
        lambda title, body, level=INFO: sent.append((title, body, level)) or True,
    )
    window = Mock()
    window.is_active.return_value = False

    MainWindow.show_toast(window, "a Steam nao abriu")

    assert sent == [("Twinverse", "a Steam nao abriu", INFO)]


def test_the_toast_stays_inside_the_window_when_it_is_visible(monkeypatch):
    """A visible window shows the message by itself."""
    sent = []
    monkeypatch.setattr(
        "src.gui.windows.main_window.send_desktop_notification",
        lambda title, body, level=INFO: sent.append((title, body, level)) or True,
    )
    window = Mock()
    window.is_active.return_value = True

    MainWindow.show_toast(window, "a Steam nao abriu")

    assert sent == []


def test_the_level_of_the_message_reaches_the_desktop(monkeypatch):
    """A failure is shown as an error on the desktop too."""
    sent = []
    monkeypatch.setattr(
        "src.gui.windows.main_window.send_desktop_notification",
        lambda title, body, level=INFO: sent.append((title, body, level)) or True,
    )
    window = Mock()
    window.is_active.return_value = False

    MainWindow.show_toast(window, "a Steam nao abriu", level=ERROR)

    assert sent == [("Twinverse", "a Steam nao abriu", ERROR)]
