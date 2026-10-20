"""KDE-specific features such as KWin scripts and panel visibility control."""

import json
import logging
import os

import pydbus

from src.core.config import Config, ensure_private_dir
from src.models import Profile
from src.services.device_manager import DeviceManager

logger = logging.getLogger(__name__)


class KdeManager:
    """Loads the KWin layout script and hides panels while games run."""

    def __init__(self):
        """Initialize the KDE manager with necessary components."""
        self.original_panel_states: dict[int, str] = {}
        self.kwin_script_id = None
        self.session_bus = None
        self._init_dbus()

    def _init_dbus(self):
        """Initialize D-Bus connection."""
        try:
            self.session_bus = pydbus.SessionBus()
        except Exception:
            logger.exception("Failed to connect to session D-Bus")

    def start_kwin_script(self, profile: Profile):
        """Start the appropriate KWin script using D-Bus."""
        if not self.is_kde_desktop() or not self.session_bus:
            logger.warning("Not a KDE desktop or D-Bus unavailable, skipping KWin script.")
            return

        if not profile.is_splitscreen_mode or not profile.splitscreen:
            logger.info("Fullscreen mode, loading KWin script.")
            script_name = "kwin_gamescope.js"
        else:
            orientation = profile.splitscreen.orientation
            script_name = "kwin_gamescope_vertical.js" if orientation == "vertical" else "kwin_gamescope_horizontal.js"

        script_path = Config.SCRIPT_DIR / "res" / "kwin" / script_name

        if not script_path.exists():
            logger.error("KWin script not found at %s", script_path)
            return

        shared_temp_path = None
        temp_script_path = None

        try:
            script_content = script_path.read_text()

            # Use the same monitor order as DeviceManager, matching KWin outputs by connector.
            monitor_names = json.dumps([monitor.name for monitor in DeviceManager.get_ordered_monitors()])
            script_content = script_content.replace(
                "var screens = workspace.screens;",
                f"var screens = {monitor_names}.map(function (name) {{"
                " return workspace.screens.find(function (screen) { return screen.name === name; });"
                " }).filter(Boolean);",
            )

            cache_dir = ensure_private_dir(Config.cache_dir())
            shared_temp_path = cache_dir / f"kwin_script_{os.getpid()}_{script_name}"
            with open(shared_temp_path, "w", encoding="utf-8") as stream:
                stream.write(script_content)

            self._kwin_script_temp_path = shared_temp_path

            kwin_scripting = self.session_bus.get("org.kde.KWin", "/Scripting")
            logger.info("Loading KWin script from %s", shared_temp_path)

            self.kwin_script_id = kwin_scripting.loadScript(str(shared_temp_path))
            kwin_scripting.start()

            logger.info("KWin script loaded and started with ID %s", self.kwin_script_id)

        except Exception:
            logger.exception("Failed to load KWin script")

            if shared_temp_path and shared_temp_path.exists():
                shared_temp_path.unlink()
            if temp_script_path and temp_script_path.exists():
                temp_script_path.unlink()

    def stop_kwin_script(self):
        """Stop and unload the KWin script."""
        if not self.kwin_script_id or not self.session_bus:
            logger.info("No KWin script ID to stop or D-Bus unavailable.")
            return

        try:
            kwin_scripting = self.session_bus.get("org.kde.KWin", "/Scripting")
            logger.info("Unloading KWin script with ID %s", self.kwin_script_id)
            kwin_scripting.unloadScript(str(self.kwin_script_id))

            if hasattr(self, "_kwin_script_temp_path") and self._kwin_script_temp_path:
                if os.path.exists(self._kwin_script_temp_path):
                    os.unlink(self._kwin_script_temp_path)

            logger.info("KWin script unloaded successfully")
            self.kwin_script_id = None

        except Exception:
            logger.exception("Failed to stop KWin script")

    def is_kde_desktop(self):
        """Check if the current desktop environment is KDE."""
        return os.environ.get("XDG_CURRENT_DESKTOP") == "KDE"

    def _run_plasmashell_script(self, script):
        """Run a Plasma Shell script using D-Bus."""
        if not self.session_bus:
            return None
        try:
            plasmashell = self.session_bus.get("org.kde.plasmashell", "/PlasmaShell")
            return plasmashell.evaluateScript(script)
        except Exception:
            logger.exception("Error executing plasmashell script")
            return None

    def get_panel_count(self):
        """Get the number of panels."""
        script = "print(panels().length)"
        count_str = self._run_plasmashell_script(script)
        try:
            return int(count_str) if count_str and count_str.isdigit() else 0
        except ValueError:
            return 0

    def save_panel_states(self):
        """Save the current visibility state of all panels."""
        if not self.is_kde_desktop() or not self.session_bus:
            return

        if self.original_panel_states:
            # The panels are already hidden, so their current state is not
            # the original one and must not overwrite the saved states.
            return

        panel_count = self.get_panel_count()
        if panel_count == 0:
            logger.info("No KDE panels found.")
            return

        self.original_panel_states = {}
        for i in range(panel_count):
            script = f"print(panels()[{i}].hiding)"
            state = self._run_plasmashell_script(script)
            if state is not None:
                # The value comes from a print statement, so it carries a
                # newline that would break the script that restores it.
                state = state.strip()
                self.original_panel_states[i] = state
                logger.info("Saved panel %s state: %s", i, state)

    def set_panels_dodge_windows(self):
        """Set all panels to 'Dodge Windows' visibility."""
        if not self.is_kde_desktop() or not self.session_bus:
            return

        panel_count = self.get_panel_count()
        for i in range(panel_count):
            script = f"panels()[{i}].hiding = 'dodgewindows'"
            self._run_plasmashell_script(script)
            logger.info("Set panel %s to 'Dodge Windows'", i)

    def restore_panel_states(self):
        """Restore the visibility state of all panels to their original state."""
        if not self.is_kde_desktop() or not self.session_bus or not self.original_panel_states:
            return

        for i, state in self.original_panel_states.items():
            # The state is a plain identifier, and it is escaped so a stray
            # quote cannot break the script.
            script_state = "null" if state == "null" else json.dumps(state)
            script = f"panels()[{i}].hiding = {script_state}"
            self._run_plasmashell_script(script)
            logger.info("Restored panel %s to state: %s", i, state)
        self.original_panel_states = {}
