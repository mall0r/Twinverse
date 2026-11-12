"""Resolve a KWin window to its explicit Twinverse instance, not its list order."""

import logging
import subprocess
import threading
from pathlib import Path

from gi.repository import Gio, GLib

from src.core.utils import Utils

logger = logging.getLogger(__name__)

INSTANCE_ENV = "TWINVERSE_KWIN_INSTANCE"
OBJECT_PATH = "/io/github/mall0r/Twinverse/Layout"
INTERFACE = "io.github.mall0r.Twinverse.Layout"
INTROSPECTION = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="ResolveInstance">
      <arg name="pid" type="s" direction="in"/>
      <arg name="instance" type="i" direction="out"/>
    </method>
  </interface>
</node>
"""


def resolve_instance(pid: int) -> int:
    """Read only our instance marker from the window owner's process environment."""
    if not isinstance(pid, int) or isinstance(pid, bool) or not 0 < pid < 2**31:
        return -1
    try:
        if Utils.is_flatpak():
            # KWin supplies a host PID. Do not interpret it in Flatpak's PID
            # namespace or transfer the process's other environment variables.
            result = Utils.flatpak_spawn_host(
                [
                    "sh",
                    "-c",
                    'tr "\\000" "\\n" < "/proc/$1/environ" | grep -m1 "^TWINVERSE_KWIN_INSTANCE="',
                    "twinverse-window-instance",
                    str(pid),
                ],
                capture_output=True,
                timeout=3,
            )
            if result.returncode:
                return -1
            entries = result.stdout.strip().split(b"\n")
        else:
            entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        prefix = INSTANCE_ENV.encode() + b"="
        for entry in entries:
            if entry.startswith(prefix):
                value = entry[len(prefix) :]
                if value.isdigit() and len(value) <= 9:
                    return int(value)
                return -1
    except (OSError, subprocess.SubprocessError):
        logger.debug("Could not identify KWin window owner PID %s", pid, exc_info=True)
    return -1


class KwinLayoutResolver:
    """Export a narrow, read-only identity lookup on the application's session bus."""

    def __init__(self, connection):
        """Register on the GUI thread so KWin requests use the running GLib loop."""
        self.connection = connection
        self.service_name = connection.get_unique_name()
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        self.registration = connection.register_object(
            OBJECT_PATH, self._node_info.interfaces[0], self._handle_call, None, None
        )

    def _handle_call(self, _connection, _sender, _path, _interface, method, parameters, invocation):
        """Resolve off the GUI thread, since Flatpak may need a short host query."""
        if method != "ResolveInstance":
            invocation.return_dbus_error(f"{INTERFACE}.UnknownMethod", "Unknown layout method")
            return
        # KWin's JavaScript numbers have backend-dependent D-Bus numeric types.
        # Use a decimal string on the wire rather than requiring uint vs int.
        text = parameters.unpack()[0]
        pid = int(text) if text.isascii() and text.isdigit() and len(text) <= 10 else 0

        def reply():
            instance = resolve_instance(pid)
            logger.debug("KWin window owner PID %s: instance %s", pid, instance + 1 if instance >= 0 else "unmanaged")
            invocation.return_value(GLib.Variant("(i)", (instance,)))

        threading.Thread(target=reply, name="twinverse-window-identity", daemon=True).start()
