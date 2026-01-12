"""
KDE manager module for the Twinverse application.

This module provides functionality to manage KDE-specific features such as
KWin scripts for window management and panel visibility control.
"""

import os
from pathlib import Path

import pydbus

from src.core import Logger
from src.models import Profile


class KdeManager:
    """Manages KDE-specific features such as KWin scripts and panel visibility."""

    def __init__(self, logger: Logger):
        """Initialize the KDE manager with necessary components."""
        self.logger = logger
        self.original_panel_states: dict[int, str] = {}
        self.kwin_script_id = None
        self.session_bus = None
        self._init_dbus()

    def _init_dbus(self):
        """Initialize D-Bus connection."""
        try:
            self.session_bus = pydbus.SessionBus()
        except Exception as e:
            self.logger.error(f"Failed to connect to session D-Bus: {e}")

    def start_kwin_script(self, profile: Profile):
        """Start the appropriate KWin script using D-Bus."""
        if not self.is_kde_desktop() or not self.session_bus:
            self.logger.warning("Not a KDE desktop or D-Bus unavailable, skipping KWin script.")
            return

        # Determine script name based on profile
        if not profile.is_splitscreen_mode or not profile.splitscreen:
            self.logger.info("Fullscreen mode, loading KWin script.")
            script_name = "kwin_gamescope.js"
        else:
            orientation = profile.splitscreen.orientation
            script_name = "kwin_gamescope_vertical.js" if orientation == "vertical" else "kwin_gamescope_horizontal.js"

        script_path = Path(__file__).parent.parent.parent / "res" / "kwin" / script_name

        if not script_path.exists():
            self.logger.error(f"KWin script not found at {script_path}")
            return

        shared_temp_path = None
        temp_script_path = None

        try:
            # Read script content
            script_content = script_path.read_text()

            # Create a temporary file accessible to KWin (in /tmp)
            shared_temp_path = f"/tmp/kwin_script_{os.getpid()}_{script_name}"
            with open(shared_temp_path, "w") as f:
                f.write(script_content)

            # Store the temp path for cleanup
            self._kwin_script_temp_path = shared_temp_path

            # Load and start script via D-Bus
            kwin_scripting = self.session_bus.get("org.kde.KWin", "/Scripting")
            self.logger.info(f"Loading KWin script from: {shared_temp_path}")

            self.kwin_script_id = kwin_scripting.loadScript(shared_temp_path)
            kwin_scripting.start()

            self.logger.info(f"KWin script loaded and started with ID: {self.kwin_script_id}")

        except Exception as e:
            self.logger.error(f"Failed to load KWin script: {e}")

            # Cleanup only if files were created
            if shared_temp_path and os.path.exists(shared_temp_path):
                os.unlink(shared_temp_path)
            if temp_script_path and os.path.exists(temp_script_path):
                os.unlink(temp_script_path)

    def stop_kwin_script(self):
        """Stop and unload the KWin script."""
        if not self.kwin_script_id or not self.session_bus:
            self.logger.info("No KWin script ID to stop or D-Bus unavailable.")
            return

        try:
            kwin_scripting = self.session_bus.get("org.kde.KWin", "/Scripting")
            self.logger.info(f"Unloading KWin script with ID: {self.kwin_script_id}")
            kwin_scripting.unloadScript(str(self.kwin_script_id))

            # Cleanup the temporary file
            if hasattr(self, "_kwin_script_temp_path") and self._kwin_script_temp_path:
                if os.path.exists(self._kwin_script_temp_path):
                    os.unlink(self._kwin_script_temp_path)

            self.logger.info("KWin script unloaded successfully.")
            self.kwin_script_id = None

        except Exception as e:
            self.logger.error(f"Failed to stop KWin script: {e}")

    def is_kde_desktop(self):
        """Check if the current desktop environment is KDE."""
        return os.environ.get("XDG_CURRENT_DESKTOP") == "KDE"

    def _run_plasmashell_script(self, script):
        """Run a Plasma Shell script using D-Bus."""
        if not self.session_bus:
            return None
        try:
            plasmashell = self.session_bus.get("org.kde.plasmashell", "/PlasmaShell")
            result = plasmashell.evaluateScript(script)
            return result
        except Exception as e:
            self.logger.error(f"Error executing plasmashell script: {e}")
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

        panel_count = self.get_panel_count()
        if panel_count == 0:
            self.logger.info("No KDE panels found.")
            return

        self.original_panel_states = {}
        for i in range(panel_count):
            script = f"print(panels()[{i}].hiding)"
            state = self._run_plasmashell_script(script)
            if state is not None:
                self.original_panel_states[i] = state
                self.logger.info(f"Saved panel {i} state: {state}")

    def set_panels_dodge_windows(self):
        """Set all panels to 'Dodge Windows' visibility."""
        if not self.is_kde_desktop() or not self.session_bus:
            return

        panel_count = self.get_panel_count()
        for i in range(panel_count):
            script = f"panels()[{i}].hiding = 'dodgewindows'"
            self._run_plasmashell_script(script)
            self.logger.info(f"Set panel {i} to 'Dodge Windows'")

    def restore_panel_states(self):
        """Restore the visibility state of all panels to their original state."""
        if not self.is_kde_desktop() or not self.session_bus or not self.original_panel_states:
            return

        for i, state in self.original_panel_states.items():
            # The 'null' state needs to be handled as a special case
            script_state = f"'{state}'" if state != "null" else "null"
            script = f"panels()[{i}].hiding = {script_state}"
            self._run_plasmashell_script(script)
            self.logger.info(f"Restored panel {i} to state: {state}")
        self.original_panel_states = {}
