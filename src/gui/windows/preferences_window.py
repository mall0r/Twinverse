"""
Preferences window module for the Twinverse application.

This module provides the preferences window UI.
"""

import gi
from gi.repository import Adw, Gtk

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
        self._prefs_page = Adw.PreferencesPage()
        self._prefs_page.set_title("Options")
        self._prefs_page.set_icon_name("preferences-other-symbolic")

        # Advanced options group
        self._prefs_group = Adw.PreferencesGroup(
            title="Advanced Options", description="Only modify if you know what you are doing"
        )

        # SteamDeck tag row
        self.steamdeck_row = Adw.SwitchRow()
        self.steamdeck_row.set_title("SteamDeck Tag")
        self.steamdeck_row.set_subtitle("Add --mangoapp to Gamescope and -steamdeck to Steam command when enabled")
        self.steamdeck_row.set_active(self._profile.use_steamdeck_tag)
        self.steamdeck_row.connect("notify::active", self._on_steamdeck_tag_toggled)
        self.steamdeck_row.get_style_context().add_class("custom-switch")
        self._prefs_group.add(self.steamdeck_row)

        # Gamescope toggle row
        self.gamescope_row = Adw.SwitchRow()
        self.gamescope_row.set_title("Use Gamescope")
        self.gamescope_row.set_subtitle("Disable to run Steam directly in bwrap without Gamescope")
        self.gamescope_row.set_active(self._profile.use_gamescope)
        self.gamescope_row.connect("notify::active", self._on_gamescope_toggled)
        self.gamescope_row.get_style_context().add_class("custom-switch")
        self._prefs_group.add(self.gamescope_row)

        # Gamescope WSI toggle row
        self.gamescope_wsi_row = Adw.SwitchRow()
        self.gamescope_wsi_row.set_title("Enable Gamescope WSI")
        self.gamescope_wsi_row.set_subtitle("Enable Gamescope Wayland Support Interface (WSI)")
        self.gamescope_wsi_row.set_active(self._profile.enable_gamescope_wsi)
        self.gamescope_wsi_row.connect("notify::active", self._on_gamescope_wsi_toggled)
        self.gamescope_wsi_row.get_style_context().add_class("custom-switch")
        self._prefs_group.add(self.gamescope_wsi_row)

        self._prefs_page.add(self._prefs_group)

        # Add reset button to the window in a separate group
        self._add_reset_button()

        self.add(self._prefs_page)

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
        self._prefs_page.add(reset_group)

    def _on_reset_clicked(self, button):
        """Handle reset button click."""
        # Create a new profile with default values
        from src.models.profile import Profile

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
