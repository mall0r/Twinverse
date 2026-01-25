"""
Layout settings page module.

This module provides the UI for configuring layout settings - presentation only.
"""

import gi
from gi.repository import Adw, GObject, Gtk

from src.core.layout import LayoutCalculator
from src.gui.widgets import PlayerRow

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class LayoutSettingsPage(Adw.PreferencesPage):
    """Layout settings page - handles UI presentation only."""

    __gsignals__ = {
        "settings-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "verification-completed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "instance-launch-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "devices-refresh-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **kwargs):
        """Initialize the layout settings page."""
        super().__init__(**kwargs)
        self._is_loading = False
        self.player_rows = []
        self._num_monitors = 1  # Will be set from devices_info
        self.screen_settings_icon = None  # Will be initialized in _build_ui
        self._last_user_selected_mode = None  # Track the last mode explicitly selected by the user
        self._build_ui()

    def _update_screen_settings_icon(self):
        """Update the screen settings icon based on current settings."""
        if not self.screen_settings_icon:
            return

        screen_mode = self.screen_mode_row.get_selected_item().get_string().lower()
        num_instances = sum(1 for player_row in self.player_rows if player_row.is_selected())

        icon_name = ""

        if screen_mode == "fullscreen":
            icon_name = "fullscreen-square-symbolic"
        elif screen_mode == "splitscreen":
            # Consider groups of up to 4 instances per monitor
            first_group_size = min(num_instances, 4)

            if first_group_size == 1:
                icon_name = "fullscreen-square-symbolic"
            elif first_group_size == 4:
                icon_name = "four-square-symbolic"
            else:
                orientation = self.orientation_row.get_selected_item().get_string().lower()

                # Use LayoutCalculator to determine layout for the first group
                LayoutCalculator.get_layout_coordinates(first_group_size, orientation)

                if first_group_size == 2:
                    icon_name = f"{orientation}-square-symbolic"
                elif first_group_size == 3:
                    icon_name = f"{orientation}-three-square-symbolic"
                else:
                    icon_name = f"{orientation}-square-symbolic"

        self.screen_settings_icon.set_from_icon_name(icon_name)
        self.screen_settings_icon.set_tooltip_text("Layout Preview")

    def _build_ui(self):
        """Build the UI."""
        self.set_title("Layout Settings")

        # General layout group
        layout_group = Adw.PreferencesGroup(title="General Layout")
        layout_group.add_css_class("general-layout-group")
        self.add(layout_group)

        self.num_players_row = Adw.SpinRow(
            title="Number of Instances",
            subtitle="Choose the player count",
        )
        self.num_players_row.add_css_class("num-players-row")
        adjustment = Gtk.Adjustment(value=2, lower=1, upper=8, step_increment=1)
        self.num_players_row.set_adjustment(adjustment)
        adjustment.connect("value-changed", self._on_num_players_changed)
        layout_group.add(self.num_players_row)

        # Screen settings group
        self.gamescope_settings_group = Adw.PreferencesGroup()
        self.add(self.gamescope_settings_group)

        gamescope_expander = Adw.ExpanderRow(title="Screen Settings", expanded=True)

        # Criar um ícone para o lado direito
        self.screen_settings_icon = Gtk.Image.new_from_icon_name("horizontal-square-symbolic")
        self.screen_settings_icon.set_margin_start(6)
        gamescope_expander.add_suffix(self.screen_settings_icon)

        self.gamescope_settings_group.add(gamescope_expander)

        self.screen_modes = ["Fullscreen", "Splitscreen"]
        self.screen_mode_row = Adw.ComboRow(title="Screen Mode", model=Gtk.StringList.new(self.screen_modes))
        self.screen_mode_row.add_css_class("screen-mode-row")
        self.screen_mode_row.connect("notify::selected-item", self._on_screen_mode_changed)
        gamescope_expander.add_row(self.screen_mode_row)

        self.orientations = ["Horizontal", "Vertical"]
        self.orientation_row = Adw.ComboRow(
            title="Splitscreen Orientation", model=Gtk.StringList.new(self.orientations)
        )
        self.orientation_row.add_css_class("orientation-row")
        self.orientation_row.connect("notify::selected-item", self._on_setting_changed)
        gamescope_expander.add_row(self.orientation_row)

        # Players group
        self.players_group = Adw.PreferencesGroup(title="Instance Configurations")
        self.players_group.add_css_class("players-group")
        self.add(self.players_group)

    def load_data(self, profile, devices_info, verification_statuses):
        """Load data into the UI."""
        self._is_loading = True

        # Store number of monitors
        self._num_monitors = len(devices_info.get("displays", []))
        if self._num_monitors == 0:
            self._num_monitors = 1  # Fallback

        # Update the screen settings icon since the number of monitors affects the limits
        if not self._is_loading:
            self._update_screen_settings_icon()

        # Load general settings
        adj = self.num_players_row.get_adjustment()
        adj.set_value(profile.num_players)

        # Use the last user-selected mode if available, otherwise use the profile mode
        is_splitscreen = (self._last_user_selected_mode or profile.mode) == "splitscreen"
        self.screen_mode_row.set_selected(1 if is_splitscreen else 0)
        self._update_num_players_limits(is_splitscreen)
        self.orientation_row.set_visible(is_splitscreen)
        self.gamescope_settings_group.set_visible(profile.use_gamescope)

        if is_splitscreen and profile.splitscreen:
            orientation = profile.splitscreen.orientation.capitalize()
            self.orientation_row.set_selected(self.orientations.index(orientation))

        # Rebuild player rows
        self.rebuild_player_rows(profile.num_players, devices_info)

        # Load player configurations
        for i, player_row in enumerate(self.player_rows):
            if i < len(profile.player_configs):
                config = profile.player_configs[i]
                player_row.load_config(config)

            # Set verification status
            is_verified = verification_statuses.get(i, False)
            player_row.set_verification_status(is_verified)

        # Apply grab input exclusivity after loading
        self._apply_grab_input_exclusivity()

        # Update the screen settings icon after loading
        self._update_screen_settings_icon()

        self._is_loading = False

    def _apply_grab_input_exclusivity(self):
        """Apply grab input exclusivity rules after loading."""
        active_grab_index = -1

        # Find which player has grab input active
        for i, player_row in enumerate(self.player_rows):
            if player_row.grab_input_switch.get_active():
                active_grab_index = i
                break

        # Apply exclusivity
        if active_grab_index != -1:
            for i, player_row in enumerate(self.player_rows):
                if i != active_grab_index:
                    player_row.set_grab_input_sensitive(False)

    def rebuild_player_rows(self, num_players: int, devices_info: dict):
        """Rebuild player rows."""
        # Remove existing rows
        for player_row in self.player_rows:
            self.players_group.remove(player_row)
        self.player_rows = []

        # Create new rows
        for i in range(num_players):
            player_row = PlayerRow(i, devices_info)
            player_row.set_parent_page(self)  # Set parent reference
            player_row.connect("settings-changed", lambda *args: self._on_setting_changed())
            player_row.connect(
                "launch-clicked", lambda w, instance_num, i=i: self.emit("instance-launch-requested", instance_num)
            )
            player_row.connect("refresh-devices-requested", lambda *args: self.emit("devices-refresh-requested"))
            self.players_group.add(player_row)
            self.player_rows.append(player_row)

    def _handle_grab_input_exclusivity(self, active_index: int):
        """Handle grab input exclusivity - only one can be active."""
        if self._is_loading:
            return

        active_row = self.player_rows[active_index]
        is_active = active_row.grab_input_switch.get_active()

        for i, row in enumerate(self.player_rows):
            if i == active_index:
                continue

            if is_active:
                # Disable and deactivate others
                row.grab_input_switch.set_active(False)
                row.set_grab_input_sensitive(False)
            else:
                # Re-enable others
                row.set_grab_input_sensitive(True)

    def get_data(self) -> dict:
        """Get data from UI."""
        data = {
            "num_players": int(self.num_players_row.get_value()),
            "mode": self.screen_mode_row.get_selected_item().get_string().lower(),
            "orientation": None,
            "player_configs": [],
            "selected_players": [],
        }

        if data["mode"] == "splitscreen":
            data["orientation"] = self.orientation_row.get_selected_item().get_string().lower()

        for i, player_row in enumerate(self.player_rows):
            config = player_row.get_config()
            data["player_configs"].append(config)
            if player_row.is_selected():
                data["selected_players"].append(i)

        return data

    def get_selected_players(self) -> list[int]:
        """Get list of selected player indices."""
        return [i for i, row in enumerate(self.player_rows) if row.is_selected()]

    def set_running_state(self, is_running: bool):
        """Set running state for all player rows."""
        for player_row in self.player_rows:
            player_row.set_running_state(is_running)

    def update_verification_status(self, instance_num: int, is_verified: bool):
        """Update verification status for a specific instance."""
        if 0 <= instance_num < len(self.player_rows):
            self.player_rows[instance_num].set_verification_status(is_verified)

    def _on_num_players_changed(self, adjustment):
        """Handle number of players changed."""
        if not self._is_loading:
            self.emit("settings-changed")
            self._update_screen_settings_icon()

    def _on_screen_mode_changed(self, combo_row, *args):
        """Handle screen mode changed."""
        selected_mode = combo_row.get_selected_item().get_string().lower()
        is_splitscreen = selected_mode == "splitscreen"
        self.orientation_row.set_visible(is_splitscreen)

        # Record the user's selection
        self._last_user_selected_mode = selected_mode

        # Update the number of players limits based on screen mode
        self._update_num_players_limits(is_splitscreen)

        # Adjust the value if it exceeds the new upper limit
        adjustment = self.num_players_row.get_adjustment()
        current_value = adjustment.get_value()
        new_upper_limit = adjustment.get_upper()

        if current_value > new_upper_limit:
            adjustment.set_value(new_upper_limit)

        if not self._is_loading:
            self.emit("settings-changed")
            self._update_screen_settings_icon()

    def update_devices_info(self, devices_info: dict):
        """Update devices info in all player rows."""
        for player_row in self.player_rows:
            player_row.update_devices(devices_info)

    def _update_num_players_limits(self, is_splitscreen: bool):
        """Update the limits for number of players based on screen mode."""
        if is_splitscreen:
            # In splitscreen mode: up to 8 instances total, max 4 per monitor
            max_players = min(8, self._num_monitors * 4)
        else:
            # In fullscreen mode: up to 8 instances total, max 1 per monitor
            max_players = min(8, self._num_monitors)

        # Update the adjustment limits
        adjustment = self.num_players_row.get_adjustment()

        # Set the new upper limit
        adjustment.set_upper(max_players)

    def _on_setting_changed(self, *args):
        """Handle any setting changed."""
        if not self._is_loading:
            self.emit("settings-changed")
            self._update_screen_settings_icon()

    def set_number_of_instances_sensitive(self, sensitive: bool):
        """Set the sensitivity of the number of instances spin button."""
        self.num_players_row.set_sensitive(sensitive)

    def set_screen_settings_sensitive(self, sensitive: bool):
        """Set the sensitivity of the screen settings controls."""
        self.screen_mode_row.set_sensitive(sensitive)
        self.orientation_row.set_sensitive(sensitive)

    def set_checkboxes_sensitive(self, sensitive: bool):
        """Set the sensitivity of the instance checkboxes."""
        for player_row in self.player_rows:
            player_row.set_checkbox_sensitive(sensitive)
