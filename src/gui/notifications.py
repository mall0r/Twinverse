"""Desktop notifications, so a message is seen even with the window hidden.

The toasts of the application live inside the window. When it is minimized,
or in the background behind a game, the user would never see them. The
notification portal is used for that, because it is the interface that a
sandboxed application is allowed to use.
"""

import logging
import uuid

import gi

# flake8: noqa: E402


gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_INTERFACE = "org.freedesktop.portal.Notification"
PORTAL_TIMEOUT_MS = 5000


def send_desktop_notification(title: str, body: str, icon: str = "dialog-warning") -> bool:
    """
    Show a notification on the desktop of the user.

    It returns whether the notification was accepted. A desktop without the
    portal, or a session bus that is not reachable, is not an error: the
    message is simply kept inside the window.
    """
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        notification = {
            "title": GLib.Variant("s", title),
            "body": GLib.Variant("s", body),
            "icon": GLib.Variant("s", icon),
        }
        identifier = f"twinverse-{uuid.uuid4().hex[:8]}"
        bus.call_sync(
            PORTAL_BUS,
            PORTAL_PATH,
            PORTAL_INTERFACE,
            "AddNotification",
            GLib.Variant("(sa{sv})", (identifier, notification)),
            None,
            Gio.DBusCallFlags.NONE,
            PORTAL_TIMEOUT_MS,
            None,
        )
        return True
    except Exception as error:
        logger.debug("Could not show the desktop notification: %s", error)
        return False
