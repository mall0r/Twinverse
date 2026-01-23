"""
Player row widget module.

This module provides a custom widget for player configuration.
"""

import os

import gi
from gi.repository import Adw, GObject, Gtk

from src.gui.widgets.env_variable_row import EnvVariableRow
from src.models import PlayerInstanceConfig

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class PlayerRow(Adw.ExpanderRow):
    """Widget for configuring a single player instance."""

    __gsignals__ = {
        "settings-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "launch-clicked": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "refresh-devices-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, player_num: int, devices_info: dict, **kwargs):
        """Initialize the player row."""
        super().__init__(**kwargs)
        self._player_num = player_num
        self._devices_info = devices_info
        self._is_loading = False
        self._is_running = False
        self._env_rows: list[EnvVariableRow] = []

        self.set_title(f"Player {player_num + 1}")
        self.get_style_context().add_class("player-expander")

        self._build_ui()

    def _build_ui(self):
        """Build the UI."""
        # Checkbox for selection
        self.checkbox = Gtk.CheckButton()
        self.checkbox.set_active(True)
        self.checkbox.get_style_context().add_class("player-checkbox")
        self.checkbox.connect("toggled", lambda *args: self.emit("settings-changed"))
        self.add_prefix(self.checkbox)

        # Device rows
        self._create_device_rows()

        # Grab input switch
        self.grab_input_switch = Adw.SwitchRow(title="Grab Mouse")
        self.grab_input_switch.get_style_context().add_class("custom-switch")
        self.grab_input_switch.connect("notify::active", self._on_grab_input_toggled)
        self.add_row(self.grab_input_switch)

        # Audio device
        audio_devices = self._devices_info.get("audio", [])
        audio_model = Gtk.StringList.new(["None"] + [d["name"] for d in audio_devices])
        self.audio_row = Adw.ComboRow(title="Audio Device", model=audio_model)
        self.audio_row.get_style_context().add_class("audio-row")
        self.audio_row.connect("notify::selected-item", lambda *args: self.emit("settings-changed"))
        self.add_row(self.audio_row)

        # Refresh rate
        refresh_rates = ["60", "75", "90", "120", "144", "165", "180", "240"]
        refresh_rate_model = Gtk.StringList.new(refresh_rates)
        self.refresh_rate_row = Adw.ComboRow(title="Refresh Rate", model=refresh_rate_model)
        self.refresh_rate_row.get_style_context().add_class("refresh-rate-row")
        self.refresh_rate_row.connect("notify::selected-item", lambda *args: self.emit("settings-changed"))
        self.add_row(self.refresh_rate_row)

        # Environment variables section
        self._create_env_section()

        # Launch button
        self.launch_button = Gtk.Button(label="Install")
        self.launch_button.get_style_context().add_class("configure-button")
        self.launch_button.set_valign(Gtk.Align.CENTER)
        self.launch_button.connect("clicked", self._on_launch_clicked)
        self.add_suffix(self.launch_button)

        # Status icon (will be set later)
        self.status_icon = None

    def _create_device_rows(self):
        """Create device selection rows."""
        joysticks = self._devices_info.get("joystick", [])
        joystick_model = Gtk.StringList.new(["None"] + [d["name"] for d in joysticks])
        self.joystick_row = Adw.ComboRow(title="Gamepad", model=joystick_model)
        self.joystick_row.get_style_context().add_class("joystick-row")
        self.joystick_row.connect("notify::selected-item", lambda *args: self.emit("settings-changed"))

        # Add info icon
        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        info_icon.set_tooltip_text(
            "If the gamepads don't appear, you'll need\n"
            "to add your user to the input group;\n"
            "see the GUIDE for more information."
        )
        info_icon.set_margin_start(6)
        self.joystick_row.add_suffix(info_icon)

        # Add refresh button
        refresh_button = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text("Update device list")
        refresh_button.get_style_context().add_class("flat")
        refresh_button.connect("clicked", self._on_refresh_joysticks_clicked)
        self.joystick_row.add_suffix(refresh_button)

        self.add_row(self.joystick_row)

    def _create_env_section(self):
        """Create environment variables section."""
        env_title_row = Adw.ActionRow(title="Environment Variables")
        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.get_style_context().add_class("add-button")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.connect("clicked", lambda *args: self._add_env_row())
        env_title_row.add_suffix(add_btn)
        self.add_row(env_title_row)

    def _add_env_row(self, key: str = "", value: str = ""):
        """Add an environment variable row."""
        env_row = EnvVariableRow(key, value)
        env_row.connect("remove-requested", self._on_env_row_remove_requested)
        env_row.connect("changed", lambda *args: self.emit("settings-changed"))
        self.add_row(env_row)
        self._env_rows.append(env_row)

    def _on_env_row_remove_requested(self, env_row):
        """Handle environment row removal."""
        self.remove(env_row)
        if env_row in self._env_rows:
            self._env_rows.remove(env_row)
        self.emit("settings-changed")

    def _on_refresh_joysticks_clicked(self, button):
        """Handle joystick refresh."""
        # Emit signal to parent to refresh devices
        self.emit("refresh-devices-requested")

    def _on_launch_clicked(self, button):
        """Handle launch button clicked."""
        self.emit("launch-clicked", self._player_num)

    def _on_grab_input_toggled(self, switch_row, gparam):
        """Handle grab input toggled."""
        self.emit("settings-changed")
        # Also emit a special signal for grab input exclusivity
        if hasattr(self, "_parent_page"):
            self._parent_page._handle_grab_input_exclusivity(self._player_num)

    def set_parent_page(self, parent_page):
        """Set reference to parent page for exclusivity handling."""
        self._parent_page = parent_page

    def update_devices(self, devices_info: dict):
        """Update devices info and rebuild device rows."""
        self._devices_info = devices_info

        # Get current selections
        current_joystick = self._get_combo_device_id(self.joystick_row, devices_info.get("joystick", []))
        current_audio = self._get_combo_device_id(self.audio_row, devices_info.get("audio", []))

        # Update joystick model
        joysticks = devices_info.get("joystick", [])
        joystick_model = Gtk.StringList.new(["None"] + [d["name"] for d in joysticks])
        self.joystick_row.set_model(joystick_model)
        self._set_combo_selection(self.joystick_row, joysticks, current_joystick)

        # Update audio model
        audio_devices = devices_info.get("audio", [])
        audio_model = Gtk.StringList.new(["None"] + [d["name"] for d in audio_devices])
        self.audio_row.set_model(audio_model)
        self._set_combo_selection(self.audio_row, audio_devices, current_audio)

    def load_config(self, config: PlayerInstanceConfig):
        """Load configuration into the UI."""
        self._is_loading = True

        # Load grab input
        self.grab_input_switch.set_active(config.grab_input_devices)

        # Load joystick
        self._set_combo_selection(self.joystick_row, self._devices_info.get("joystick", []), config.physical_device_id)

        # Load audio
        self._set_combo_selection(self.audio_row, self._devices_info.get("audio", []), config.audio_device_id)

        # Load refresh rate
        refresh_rates = ["60", "75", "90", "120", "144", "165", "180", "240"]
        refresh_rate_str = str(config.refresh_rate)
        if refresh_rate_str in refresh_rates:
            self.refresh_rate_row.set_selected(refresh_rates.index(refresh_rate_str))
        else:
            self.refresh_rate_row.set_selected(0)

        # Load environment variables
        for key, value in (config.env or {}).items():
            self._add_env_row(key, value)

        self._is_loading = False

    def get_config(self) -> PlayerInstanceConfig:
        """Get configuration from the UI."""
        return PlayerInstanceConfig(
            PHYSICAL_DEVICE_ID=self._get_combo_device_id(self.joystick_row, self._devices_info.get("joystick", [])),
            GRAB_INPUT_DEVICES=self.grab_input_switch.get_active(),
            AUDIO_DEVICE_ID=self._get_combo_device_id(self.audio_row, self._devices_info.get("audio", [])),
            ENV=self._collect_env_vars(),
            REFRESH_RATE=self._get_refresh_rate(),
        )

    def is_selected(self) -> bool:
        """Check if this player is selected."""
        return self.checkbox.get_active()

    def set_running_state(self, is_running: bool):
        """Set the running state."""
        self._is_running = is_running
        self._update_button_state()

    def set_verification_status(self, is_verified: bool):
        """Set the verification status and update UI."""
        self._is_verified = is_verified
        self._update_button_state()
        self._update_status_icon(is_verified)

    def _update_button_state(self):
        """Update button label and style based on state."""
        if self._is_running:
            self.launch_button.set_label("Stop")
            self.launch_button.get_style_context().add_class("destructive-action")
        elif getattr(self, "_is_verified", False):
            self.launch_button.set_label("Start")
            self.launch_button.get_style_context().remove_class("destructive-action")
        else:
            self.launch_button.set_label("Install")
            self.launch_button.get_style_context().remove_class("destructive-action")

    def _update_status_icon(self, is_verified: bool):
        """Update the status icon."""
        # Remove existing icon
        if self.status_icon and self.status_icon.get_parent():
            self.remove(self.status_icon)

        # Create new icon
        if is_verified:
            self.status_icon = Gtk.Image.new_from_resource("/io/github/mall0r/Twinverse/icons/check-icon.svg")
            self.status_icon.set_tooltip_text("Press 'Start' to open this instance in desktop mode.")
            self.status_icon.get_style_context().add_class("verification-passed-icon")
        else:
            self.status_icon = Gtk.Image.new_from_resource("/io/github/mall0r/Twinverse/icons/alert-icon.svg")
            self.status_icon.set_tooltip_text("Press 'Install' to configure this instance")
            self.status_icon.get_style_context().add_class("verification-failed-icon")

        self.add_suffix(self.status_icon)

    def _set_combo_selection(self, combo_row, device_list, device_id):
        """Set combo row selection based on device ID."""
        if not device_id:
            combo_row.set_selected(0)
            return

        try:
            canonical_id = os.path.realpath(device_id)
            for i, device in enumerate(device_list):
                if os.path.realpath(device["id"]) == canonical_id:
                    combo_row.set_selected(i + 1)
                    return
        except Exception:
            pass

        combo_row.set_selected(0)

    def _get_combo_device_id(self, combo_row, device_list):
        """Get device ID from combo row selection."""
        selected_idx = combo_row.get_selected()
        if selected_idx > 0 and (selected_idx - 1) < len(device_list):
            return device_list[selected_idx - 1]["id"]
        return None

    def _get_refresh_rate(self) -> int:
        """Get selected refresh rate."""
        selected_item = self.refresh_rate_row.get_selected_item()
        return int(selected_item.get_string()) if selected_item else 60

    def set_grab_input_sensitive(self, sensitive: bool):
        """Set grab input switch sensitivity."""
        self.grab_input_switch.set_sensitive(sensitive)

    def set_checkbox_sensitive(self, sensitive: bool):
        """Set checkbox sensitivity."""
        self.checkbox.set_sensitive(sensitive)

    def _collect_env_vars(self) -> dict:
        """Collect environment variables from rows."""
        env = {}
        for env_row in self._env_rows:
            key, value = env_row.get_values()
            if key:
                env[key] = value
        return env
