"""
Preferences window module for the Twinverse application.

This module provides the preferences window UI.
"""

import gi
from gi.repository import Adw, Gtk

from src.core.config import Config
from src.models.profile import PlayerInstanceConfig, Profile

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")


class PreferencesWindow(Adw.PreferencesWindow):
    """Preferences window for application settings."""

    def __init__(self, parent, profile, on_settings_changed, **kwargs):
        """Initialize the preferences window."""
        super().__init__(**kwargs)
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Preferences")
        self._profile = profile
        self._on_settings_changed = on_settings_changed
        self._build_ui()

    def _build_ui(self):
        """Build the preferences UI."""
        # Advanced options page
        self._advanced_prefs_page = Adw.PreferencesPage()
        self._advanced_prefs_page.set_title("Options")
        self._advanced_prefs_page.set_icon_name("preferences-other-symbolic")

        # Advanced options group
        self._advanced_prefs_group = Adw.PreferencesGroup(
            title="Advanced Options", description="Only modify if you know what you are doing"
        )

        # SteamDeck tag row
        self.steamdeck_row = Adw.SwitchRow()
        self.steamdeck_row.set_title("SteamDeck Tag")
        self.steamdeck_row.set_subtitle("Add --mangoapp to Gamescope and -steamdeck to Steam command when enabled")
        self.steamdeck_row.set_active(self._profile.use_steamdeck_tag)
        self.steamdeck_row.connect("notify::active", self._on_steamdeck_tag_toggled)
        self.steamdeck_row.get_style_context().add_class("custom-switch")
        self._advanced_prefs_group.add(self.steamdeck_row)

        # Gamescope toggle row
        self.gamescope_row = Adw.SwitchRow()
        self.gamescope_row.set_title("Use Gamescope")
        self.gamescope_row.set_subtitle("Disable to run Steam directly in bwrap without Gamescope")
        self.gamescope_row.set_active(self._profile.use_gamescope)
        self.gamescope_row.connect("notify::active", self._on_gamescope_toggled)
        self.gamescope_row.get_style_context().add_class("custom-switch")
        self._advanced_prefs_group.add(self.gamescope_row)

        # Gamescope WSI toggle row
        self.gamescope_wsi_row = Adw.SwitchRow()
        self.gamescope_wsi_row.set_title("Enable Gamescope WSI")
        self.gamescope_wsi_row.set_subtitle("Enable Gamescope Wayland Support Interface (WSI)")
        self.gamescope_wsi_row.set_active(self._profile.enable_gamescope_wsi)
        self.gamescope_wsi_row.connect("notify::active", self._on_gamescope_wsi_toggled)
        self.gamescope_wsi_row.get_style_context().add_class("custom-switch")
        self._advanced_prefs_group.add(self.gamescope_wsi_row)

        self._advanced_prefs_page.add(self._advanced_prefs_group)

        # Add reset button to the advanced options page in a separate group
        self._add_reset_button()

        self.add(self._advanced_prefs_page)

        # Players management page
        self._players_prefs_page = Adw.PreferencesPage()
        self._players_prefs_page.set_title("Players")
        self._players_prefs_page.set_icon_name("avatar-default-symbolic")

        # Players management group
        self._players_prefs_group = Adw.PreferencesGroup(
            title="Manage Players", description="View and manage player instances and their configurations"
        )

        # Create a list box to hold player rows
        self._player_list_box = Gtk.ListBox()
        self._player_list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._player_list_box.add_css_class("boxed-list")

        # Populate the list with players
        self._populate_player_list()

        self._players_prefs_group.add(self._player_list_box)
        self._players_prefs_page.add(self._players_prefs_group)

        self.add(self._players_prefs_page)

    def _populate_player_list(self):
        """Populate the list with player entries."""
        # Clear existing rows
        children = []
        child = self._player_list_box.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()

        for child in children:
            self._player_list_box.remove(child)

        # Add a row for each player
        num_players = max(len(self._profile.player_configs), self._profile.num_players)
        for i in range(num_players):
            row = self._create_player_row(i)
            self._player_list_box.append(row)

    def _create_player_row(self, player_index):
        """Create a row for a specific player with an associated delete button."""
        row = Adw.ActionRow()
        row.set_title(f"Player {player_index + 1}")
        row.set_subtitle(f"Instance {player_index + 1} configuration")

        # Create home button with home icon to open the instance's home directory
        home_button = Gtk.Button()
        home_button.set_icon_name("user-home-symbolic")
        home_button.set_valign(Gtk.Align.CENTER)
        home_button.set_tooltip_text(f"Open home directory for player {player_index + 1}")
        home_button.connect("clicked", self._on_open_home_clicked, player_index)

        # Add the home button as a prefix to the row
        row.add_prefix(home_button)

        # Create delete button with trash icon
        delete_button = Gtk.Button()
        delete_button.set_icon_name("user-trash-symbolic")
        delete_button.set_valign(Gtk.Align.CENTER)
        delete_button.set_tooltip_text(f"Reset player {player_index + 1} settings and remove home directory")
        delete_button.connect("clicked", self._on_delete_player_clicked, player_index)

        # Apply danger style to the delete button
        delete_button.get_style_context().add_class("destructive-action")

        row.add_suffix(delete_button)
        # Remove the activatable widget so clicking the row doesn't trigger the action
        # Only the buttons will be clickable

        return row

    def _on_open_home_clicked(self, button, player_index):
        """Handle opening the player's home directory."""
        import subprocess
        import sys

        # Get the home path for this player instance
        home_path = Config.get_steam_home_path(player_index)

        # Convert to string path
        path_str = str(home_path)

        # Open the directory using the default file manager
        try:
            if sys.platform.startswith("darwin"):  # macOS
                subprocess.run(["open", path_str], check=True)
            elif sys.platform.startswith("win"):  # Windows
                subprocess.run(["explorer", path_str], check=True)
            else:  # Linux and other Unix-like systems
                subprocess.run(["xdg-open", path_str], check=True)
        except subprocess.CalledProcessError:
            print(f"Failed to open directory: {path_str}")
        except FileNotFoundError:
            print(f"Directory does not exist: {path_str}")
            # Optionally create the directory if it doesn't exist
            home_path.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(["xdg-open", path_str], check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                print(f"Still failed to open directory: {path_str}")

    def _on_delete_player_clicked(self, button, player_index):
        """Handle deletion of a player's configuration and home directory."""
        # Show confirmation dialog before proceeding
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Reset Player {player_index + 1}?",
            body="This will reset the player settings to default and permanently delete Player 1's home directory, along with all its contents. This action cannot be undone.",
        )

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Reset Player")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)

        dialog.connect("response", self._on_confirmation_response, player_index)
        dialog.present()

    def _on_confirmation_response(self, dialog, response, player_index):
        """Handle the confirmation dialog response."""
        if response == "reset":
            # Reset the player's configuration to default
            default_player_config = PlayerInstanceConfig()

            # Update the profile with default player config
            if player_index < len(self._profile.player_configs):
                # Update the specific player config with default values
                self._profile.player_configs[player_index] = default_player_config
            else:
                # If the player index is out of bounds, extend the list with defaults
                while len(self._profile.player_configs) <= player_index:
                    self._profile.player_configs.append(PlayerInstanceConfig())
                self._profile.player_configs[player_index] = default_player_config

            # Remove the player's home directory
            home_path = Config.get_steam_home_path(player_index)
            self._remove_home_directory(home_path)

            # Refresh the player list to reflect changes
            self._populate_player_list()

            # Notify that settings have changed
            self._on_settings_changed("player_configs", self._profile.player_configs)

            # Force saving the profile to persist the changes
            try:
                self._profile.save()
            except Exception as e:
                print(f"Error saving profile: {e}")

    def _remove_home_directory(self, home_path):
        """Remove the home directory for a specific player."""
        import shutil
        from pathlib import Path

        path = Path(home_path)
        if path.exists():
            try:
                shutil.rmtree(path)
            except Exception as e:
                print(f"Error removing directory {path}: {e}")

    def _add_reset_button(self):
        """Add a reset button to the preferences window."""
        # Create reset button
        reset_button = Gtk.Button(label="Reset")
        reset_button.set_tooltip_text("Reset all settings to default values")
        reset_button.connect("clicked", self._on_reset_clicked)

        # Apply the custom CSS class for reset action
        reset_button.get_style_context().add_class("reset-action")

        # Create a new group for the reset button to separate it from other options
        reset_group = Adw.PreferencesGroup()
        reset_group.set_title("Reset Settings")
        reset_group.set_description("Restore preferences settings to their default values")
        reset_group.add(reset_button)

        # Add the reset group to the page (after the main preferences group)
        self._advanced_prefs_page.add(reset_group)

    def _on_reset_clicked(self, button):
        """Handle reset button click."""
        # Create a new profile with default values
        default_profile = Profile()

        # Update the current profile with default values
        self._profile.use_steamdeck_tag = default_profile.use_steamdeck_tag
        self._profile.use_gamescope = default_profile.use_gamescope
        self._profile.enable_gamescope_wsi = default_profile.enable_gamescope_wsi

        # Update UI elements to reflect the new values
        self.steamdeck_row.set_active(self._profile.use_steamdeck_tag)
        self.gamescope_row.set_active(self._profile.use_gamescope)
        self.gamescope_wsi_row.set_active(self._profile.enable_gamescope_wsi)

        # Notify that settings have changed
        self._on_settings_changed("use_steamdeck_tag", self._profile.use_steamdeck_tag)
        self._on_settings_changed("use_gamescope", self._profile.use_gamescope)
        self._on_settings_changed("enable_gamescope_wsi", self._profile.enable_gamescope_wsi)

    def _on_steamdeck_tag_toggled(self, switch_row, pspec):
        """Handle SteamDeck tag toggle."""
        state = switch_row.get_active()
        self._profile.use_steamdeck_tag = state
        self._on_settings_changed("use_steamdeck_tag", state)

    def _on_gamescope_toggled(self, switch_row, pspec):
        """Handle Gamescope toggle."""
        state = switch_row.get_active()
        self._profile.use_gamescope = state
        self._on_settings_changed("use_gamescope", state)

    def _on_gamescope_wsi_toggled(self, switch_row, pspec):
        """Handle Gamescope WSI toggle."""
        state = switch_row.get_active()
        self._profile.enable_gamescope_wsi = state
        self._on_settings_changed("enable_gamescope_wsi", state)
