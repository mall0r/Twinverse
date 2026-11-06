"""Widget for player configuration."""

import os
from typing import Optional

import gi
from gi.repository import Adw, GLib, GObject, Gtk

from src.gui.widgets.env_variable_row import EnvVariableRow
from src.models import PlayerInstanceConfig

# The states of an instance. The interface only says "Stop" when the Steam
# client of the instance was confirmed to be up, and only goes back to "Start"
# when the instance was confirmed to be gone.
INSTANCE_IDLE = "idle"
INSTANCE_STARTING = "starting"
INSTANCE_RUNNING = "running"
INSTANCE_STOPPING = "stopping"

# How often the bar of the update pulses when the percentage is not known.
PULSE_INTERVAL_MS = 100

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
        self._state = INSTANCE_IDLE
        self._status_detail = ""
        self._env_rows: list[EnvVariableRow] = []
        self._pulse_id = 0

        self.set_title(f"Player {player_num + 1}")
        self.get_style_context().add_class("player-expander")

        self._build_ui()

    def _build_ui(self):
        """Build the UI."""
        self.checkbox = Gtk.CheckButton()
        self.checkbox.set_active(True)
        self.checkbox.get_style_context().add_class("player-checkbox")
        self.checkbox.connect("toggled", self._on_checkbox_toggled)
        self.add_prefix(self.checkbox)

        # The bar of the update of the client, in the middle of the row. It
        # only joins the row while the client updates itself, and it leaves
        # when the update is over.
        self.update_bar = Gtk.ProgressBar()
        self.update_bar.set_size_request(110, -1)
        self.update_bar.set_valign(Gtk.Align.CENTER)
        self.update_bar.get_style_context().add_class("update-bar")

        self.update_percent = Gtk.Label()
        self.update_percent.get_style_context().add_class("caption-heading")
        self.update_percent.get_style_context().add_class("update-percent")

        self.update_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.update_box.append(self.update_bar)
        self.update_box.append(self.update_percent)
        self.update_box.set_valign(Gtk.Align.CENTER)

        # The space that keeps the bar in the middle of the row.
        self._update_spacer_before = Gtk.Box(hexpand=True)
        self._update_spacer_after = Gtk.Box(hexpand=True)

        self._create_device_rows()

        self.grab_input_switch = Adw.SwitchRow(title="Grab Mouse")
        self.grab_input_switch.get_style_context().add_class("custom-switch")
        self.grab_input_switch.connect("notify::active", self._on_grab_input_toggled)
        self.add_row(self.grab_input_switch)

        audio_devices = self._devices_info.get("audio", [])
        audio_model = Gtk.StringList.new(["Default"] + [d["name"] for d in audio_devices])
        self.audio_row = Adw.ComboRow(title="Audio Device", model=audio_model)
        self.audio_row.get_style_context().add_class("audio-row")
        self.audio_row.connect("notify::selected-item", lambda *args: self.emit("settings-changed"))
        self.add_row(self.audio_row)

        self.guest_ip_row = Adw.EntryRow(title="Guest IP")
        self.guest_ip_row.set_tooltip_text(
            "Optional IPv4 address for this instance on the LAN. "
            "Leave it empty to select a free address automatically."
        )
        self.guest_ip_row.connect("changed", lambda *args: self.emit("settings-changed"))
        self.add_row(self.guest_ip_row)

        self._create_env_section()

        self.launch_button = Gtk.Button(label="Install")
        self.launch_button.get_style_context().add_class("configure-button")
        self.launch_button.set_valign(Gtk.Align.CENTER)
        self.launch_button.connect("clicked", self._on_launch_clicked)
        self.add_suffix(self.launch_button)

        self.status_icon = None

    def _create_device_rows(self):
        """Create device selection rows."""
        joysticks = self._devices_info.get("joystick", [])
        joystick_model = Gtk.StringList.new(["None"] + [d["name"] for d in joysticks])
        self.joystick_row = Adw.ComboRow(title="Gamepad", model=joystick_model)
        self.joystick_row.get_style_context().add_class("joystick-row")
        self.joystick_row.connect("notify::selected-item", lambda *args: self.emit("settings-changed"))

        info_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        info_icon.set_tooltip_text(
            "If the gamepads don't appear, you'll need \n"
            "to add your user to the input group; \n"
            "see the GUIDE for more details."
        )
        info_icon.set_margin_start(6)
        self.joystick_row.add_suffix(info_icon)

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
        self.emit("refresh-devices-requested")

    def _on_launch_clicked(self, button):
        """Handle launch button clicked."""
        self.emit("launch-clicked", self._player_num)

    def _on_checkbox_toggled(self, *args):
        """Handle the selection checkbox toggled."""
        if not self._is_loading:
            self.emit("settings-changed")

    def set_selected(self, selected: bool):
        """Set the selection state without reporting a settings change."""
        self._is_loading = True
        self.checkbox.set_active(selected)
        self._is_loading = False

    def _on_grab_input_toggled(self, switch_row, gparam):
        """Handle grab input toggled."""
        if not self._is_loading:
            self.emit("settings-changed")
        if hasattr(self, "_parent_page"):
            self._parent_page._handle_grab_input_exclusivity(self._player_num)

    def set_parent_page(self, parent_page):
        """Set reference to parent page for exclusivity handling."""
        self._parent_page = parent_page

    def update_devices(self, devices_info: dict):
        """Update devices info and rebuild device rows."""
        self._devices_info = devices_info

        current_joystick = self._get_combo_device_id(self.joystick_row, devices_info.get("joystick", []))
        current_audio = self._get_combo_device_id(self.audio_row, devices_info.get("audio", []))

        joysticks = devices_info.get("joystick", [])
        joystick_model = Gtk.StringList.new(["None"] + [d["name"] for d in joysticks])
        self.joystick_row.set_model(joystick_model)
        self._set_combo_selection(self.joystick_row, joysticks, current_joystick)

        audio_devices = devices_info.get("audio", [])
        audio_model = Gtk.StringList.new(["Default"] + [d["name"] for d in audio_devices])
        self.audio_row.set_model(audio_model)
        self._set_combo_selection(self.audio_row, audio_devices, current_audio)

    def load_config(self, config: PlayerInstanceConfig):
        """Load configuration into the UI."""
        self._is_loading = True

        self.grab_input_switch.set_active(config.grab_input_devices)

        self._set_combo_selection(self.joystick_row, self._devices_info.get("joystick", []), config.physical_device_id)

        self._set_combo_selection(self.audio_row, self._devices_info.get("audio", []), config.audio_device_id)

        self.guest_ip_row.set_text(config.guest_ip or "")

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
            GUEST_IP=self.guest_ip_row.get_text().strip() or None,
        )

    def is_selected(self) -> bool:
        """Check if this player is selected."""
        return self.checkbox.get_active()

    def set_running_state(self, is_running: bool):
        """Set the running state."""
        self._state = INSTANCE_RUNNING if is_running else INSTANCE_IDLE
        self._is_running = is_running
        self._update_button_state()

    def set_instance_state(self, state: str):
        """Set the state of the instance and refresh its button."""
        self._state = state
        self._is_running = state == INSTANCE_RUNNING
        self._update_button_state()
        self._update_status_icon()

    def get_instance_state(self) -> str:
        """Return the state of the instance."""
        return getattr(self, "_state", INSTANCE_IDLE)

    def set_status_detail(self, detail: str):
        """Set what the status icon tells about the instance."""
        self._status_detail = detail
        self._update_status_icon()

    def set_update_progress(self, detail: str, percent: Optional[int] = None):
        """
        Show how far the update of the Steam client went.

        The percentage is the one that the Steam wrote in its log. When the
        client does not say how far it went, the bar pulses instead, so the
        user still sees that something is happening. The bar goes to the
        right of the name of the instance, and it leaves when the update is
        over.
        """
        self.update_box.set_tooltip_text(detail or "")
        if percent is None:
            self.update_percent.set_text("")
            self._start_pulsing()
        else:
            self._stop_pulsing()
            self.update_bar.set_fraction(percent / 100)
            self.update_percent.set_text(f"{percent}%")

        title_box = self._title_box()
        if title_box is not None and self.update_box.get_parent() is None:
            # The name of the instance and the bar share the same line, and
            # the bar sits in the middle of the row.
            title_box.set_orientation(Gtk.Orientation.HORIZONTAL)
            title_box.append(self._update_spacer_before)
            title_box.append(self.update_box)
            title_box.append(self._update_spacer_after)

    def clear_update_progress(self):
        """Take the bar of the update away."""
        self._stop_pulsing()
        if self.update_box.get_parent() is not None:
            self.update_box.get_parent().remove(self.update_box)
            self._update_spacer_before.get_parent().remove(self._update_spacer_before)
            self._update_spacer_after.get_parent().remove(self._update_spacer_after)

    def _title_box(self):
        """Find the box that holds the name of the instance."""
        return self._find_by_style(self, "title")

    def _find_by_style(self, widget, style_class: str):
        """Find the first widget with the given style class."""
        if widget.get_style_context().has_class(style_class):
            return widget
        child = widget.get_first_child()
        while child is not None:
            found = self._find_by_style(child, style_class)
            if found is not None:
                return found
            child = child.get_next_sibling()
        return None

    def _start_pulsing(self):
        """Make the bar pulse, for an update that has no percentage."""
        if self._pulse_id:
            return
        self._pulse_id = GLib.timeout_add(PULSE_INTERVAL_MS, self._pulse)

    def _stop_pulsing(self):
        """Stop the bar from pulsing."""
        if not self._pulse_id:
            return
        GLib.source_remove(self._pulse_id)
        self._pulse_id = 0

    def _pulse(self) -> bool:
        """Move the pulse of the bar."""
        self.update_bar.pulse()
        return True

    def set_verification_status(self, is_verified: bool):
        """Set the verification status and update UI."""
        self._is_verified = is_verified
        self._update_button_state()
        self._update_status_icon()

    def _update_button_state(self):
        """Update button label and style based on state."""
        state = getattr(self, "_state", INSTANCE_IDLE)
        if state == INSTANCE_RUNNING:
            self.launch_button.set_label("Stop")
            self.launch_button.set_sensitive(True)
            self.launch_button.get_style_context().add_class("destructive-action")
        elif state == INSTANCE_STARTING:
            # The Steam client did not come up yet, so the button cancels the
            # start instead of offering a stop that would not be true.
            self.launch_button.set_label("Cancel")
            self.launch_button.set_sensitive(True)
            self.launch_button.get_style_context().remove_class("destructive-action")
        elif state == INSTANCE_STOPPING:
            self.launch_button.set_label("Stopping…")
            self.launch_button.set_sensitive(False)
            self.launch_button.get_style_context().remove_class("destructive-action")
        elif getattr(self, "_is_verified", False):
            self.launch_button.set_label("Start")
            self.launch_button.set_sensitive(True)
            self.launch_button.get_style_context().remove_class("destructive-action")
        else:
            self.launch_button.set_label("Install")
            self.launch_button.set_sensitive(True)
            self.launch_button.get_style_context().remove_class("destructive-action")

    def _update_status_icon(self):
        """Show the icon that matches the state of the instance."""
        if self.status_icon and self.status_icon.get_parent():
            self.remove(self.status_icon)

        detail = getattr(self, "_status_detail", "")
        if self._state == INSTANCE_STARTING:
            # The Steam client may take a long time when it updates itself.
            # A spinner tells the user that it is still working, and the
            # tooltip tells what it is doing.
            self.status_icon = Gtk.Spinner()
            self.status_icon.set_spinning(True)
            self.status_icon.set_valign(Gtk.Align.CENTER)
            self.status_icon.set_tooltip_text(detail or "The Steam client is starting…")
            self.status_icon.get_style_context().add_class("verification-passed-icon")
        elif getattr(self, "_is_verified", False):
            self.status_icon = Gtk.Image.new_from_resource("/io/github/mall0r/Twinverse/icons/check-icon.svg")
            self.status_icon.set_tooltip_text(detail or "Press 'Start' to open this instance in desktop mode.")
            self.status_icon.get_style_context().add_class("verification-passed-icon")
        else:
            self.status_icon = Gtk.Image.new_from_resource("/io/github/mall0r/Twinverse/icons/alert-icon.svg")
            self.status_icon.set_tooltip_text(detail or "Press 'Install' to configure this instance")
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

    def set_grab_input_sensitive(self, sensitive: bool):
        """Set grab input switch sensitivity."""
        self.grab_input_switch.set_sensitive(sensitive)

    def set_grab_input_active(self, active: bool):
        """Set the grab input state without reporting a settings change."""
        self._is_loading = True
        self.grab_input_switch.set_active(active)
        self._is_loading = False

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
