"""Repair Steam input-focus feedback for narrow nested Gamescope overlays.

Gamescope 3.16.25 classifies STEAM_OVERLAY windows at most 1200 pixels wide
as notifications. X11 input focus reaches Steam, but GAMESCOPE_FOCUSED_APP
still reports the game, so Steam keeps its game controller configuration.
Only repair that feedback; never change window geometry or graphics focus.
This helper runs on the host inside the instance sandbox using stdlib Python.
Its output is redirected by the webhelper gate into the shared log directory.
"""

import ctypes as C
import ctypes.util
import fcntl
import os
import sys
import time

STEAM_APP_ID = 769
OVERLAY_WIDTH_THRESHOLD = 1200
# 100 ms keeps the repair invisible when a menu opens, and a full cycle of
# reads costs about 50 microseconds, so it never competes with the game.
POLL_INTERVAL = 0.1


def desired_focus(active_app, graphics_app, overlay, input_focus, width, reported_app, repaired):
    """Return a feedback correction only for Steam's narrow interactive overlay."""
    if not graphics_app or graphics_app == STEAM_APP_ID:
        return None
    menu_active = active_app == STEAM_APP_ID and overlay and input_focus == 1
    if menu_active and 0 < width <= OVERLAY_WIDTH_THRESHOLD:
        if reported_app == graphics_app:
            return STEAM_APP_ID
    elif repaired and reported_app == STEAM_APP_ID:
        return graphics_app
    return None


class X11:
    """Provide the small Xlib subset needed to read and repair focus feedback."""

    def __init__(self):
        """Connect to the instance's DISPLAY without requiring Python Xlib."""
        self.lib = C.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.lib.XOpenDisplay.argtypes = [C.c_char_p]
        self.lib.XOpenDisplay.restype = C.c_void_p
        self.lib.XDefaultRootWindow.argtypes = [C.c_void_p]
        self.lib.XDefaultRootWindow.restype = C.c_ulong
        self.lib.XInternAtom.argtypes = [C.c_void_p, C.c_char_p, C.c_int]
        self.lib.XInternAtom.restype = C.c_ulong
        self.lib.XGetWindowProperty.argtypes = [
            C.c_void_p,
            C.c_ulong,
            C.c_ulong,
            C.c_long,
            C.c_long,
            C.c_int,
            C.c_ulong,
            C.POINTER(C.c_ulong),
            C.POINTER(C.c_int),
            C.POINTER(C.c_ulong),
            C.POINTER(C.c_ulong),
            C.POINTER(C.c_void_p),
        ]
        self.lib.XGetGeometry.argtypes = [
            C.c_void_p,
            C.c_ulong,
            C.POINTER(C.c_ulong),
            C.POINTER(C.c_int),
            C.POINTER(C.c_int),
            C.POINTER(C.c_uint),
            C.POINTER(C.c_uint),
            C.POINTER(C.c_uint),
            C.POINTER(C.c_uint),
        ]
        self.lib.XChangeProperty.argtypes = [
            C.c_void_p,
            C.c_ulong,
            C.c_ulong,
            C.c_ulong,
            C.c_int,
            C.c_int,
            C.c_void_p,
            C.c_int,
        ]
        self.lib.XFree.argtypes = [C.c_void_p]
        self.lib.XFlush.argtypes = [C.c_void_p]
        self.lib.XCloseDisplay.argtypes = [C.c_void_p]
        # Windows can disappear between reading the active XID and its properties.
        callback_type = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)
        self.error_handler = callback_type(lambda display, event: 0)
        self.lib.XSetErrorHandler.argtypes = [callback_type]
        self.lib.XSetErrorHandler(self.error_handler)
        self.display = self.lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("Cannot open instance DISPLAY")
        self.root = self.lib.XDefaultRootWindow(self.display)
        self.atoms = {}

    def atom(self, name):
        """Resolve and cache a property atom."""
        if name not in self.atoms:
            self.atoms[name] = self.lib.XInternAtom(self.display, name.encode(), False)
        return self.atoms[name]

    def get(self, window, name):
        """Read one 32-bit property, returning zero when absent."""
        actual_type = C.c_ulong()
        actual_format = C.c_int()
        count = C.c_ulong()
        remaining = C.c_ulong()
        data = C.c_void_p()
        status = self.lib.XGetWindowProperty(
            self.display,
            window,
            self.atom(name),
            0,
            1,
            False,
            0,
            C.byref(actual_type),
            C.byref(actual_format),
            C.byref(count),
            C.byref(remaining),
            C.byref(data),
        )
        try:
            if status == 0 and data and actual_format.value == 32 and count.value:
                return C.cast(data, C.POINTER(C.c_ulong))[0]
            return 0
        finally:
            if data:
                self.lib.XFree(data)

    def width(self, window):
        """Read actual geometry without resizing the window."""
        root = C.c_ulong()
        x, y = C.c_int(), C.c_int()
        width, height = C.c_uint(), C.c_uint()
        border, depth = C.c_uint(), C.c_uint()
        ok = self.lib.XGetGeometry(
            self.display,
            window,
            C.byref(root),
            C.byref(x),
            C.byref(y),
            C.byref(width),
            C.byref(height),
            C.byref(border),
            C.byref(depth),
        )
        return width.value if ok else 0

    def set_focus(self, app_id):
        """Update only controller-focus feedback, leaving graphics focus intact."""
        value = C.c_ulong(app_id)
        self.lib.XChangeProperty(
            self.display,
            self.root,
            self.atom("GAMESCOPE_FOCUSED_APP"),
            self.atom("CARDINAL"),
            32,
            0,
            C.byref(value),
            1,
        )
        self.lib.XFlush(self.display)

    def close(self):
        """Close the X connection."""
        self.lib.XCloseDisplay(self.display)


def watch(steam_pid):
    """Follow menu focus for this Steam process, exiting with the instance."""
    with open(f"/tmp/twinverse-overlay-focus-{steam_pid}.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        x11 = X11()
        repaired = False
        try:
            if not x11.get(x11.root, "GAMESCOPE_PID"):
                return
            print(f"Twinverse: watching narrow overlay focus for Steam {steam_pid}", flush=True)
            while os.path.exists(f"/proc/{steam_pid}"):
                active = x11.get(x11.root, "_NET_ACTIVE_WINDOW")
                reported = x11.get(x11.root, "GAMESCOPE_FOCUSED_APP")
                graphics = x11.get(x11.root, "GAMESCOPE_FOCUSED_APP_GFX")
                app = x11.get(active, "STEAM_GAME") if active else 0
                overlay = x11.get(active, "STEAM_OVERLAY") if app == STEAM_APP_ID else 0
                focus = x11.get(active, "STEAM_INPUT_FOCUS") if overlay else 0
                width = x11.width(active) if overlay and focus == 1 else 0
                correction = desired_focus(app, graphics, overlay, focus, width, reported, repaired)
                if correction is not None:
                    x11.set_focus(correction)
                    repaired = correction == STEAM_APP_ID
                    print(f"Twinverse: controller focus feedback -> {correction}", flush=True)
                elif reported != STEAM_APP_ID:
                    repaired = False
                time.sleep(POLL_INTERVAL)
        finally:
            x11.close()


if __name__ == "__main__":
    try:
        watch(int(sys.argv[1]))
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Twinverse: overlay focus helper unavailable: {error}", file=sys.stderr)
