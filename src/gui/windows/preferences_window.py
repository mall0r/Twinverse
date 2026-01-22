"""
Preferences window module for the Twinverse application.

This module provides the preferences window UI.
"""

import gi
from gi.repository import Adw

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
        prefs_page = Adw.PreferencesPage()
        prefs_page.set_title("Options")
        prefs_page.set_icon_name("preferences-other-symbolic")

        prefs_group = Adw.PreferencesGroup(
            title="Advanced Options", description="Only modify if you know what you are doing"
        )

        # SteamDeck tag row
        self.steamdeck_row = Adw.SwitchRow()
        self.steamdeck_row.set_title("SteamDeck Tag")
        self.steamdeck_row.set_subtitle("Add --mangoapp to Gamescope and -steamdeck to Steam command when enabled")
        self.steamdeck_row.set_active(self._profile.use_steamdeck_tag)
        self.steamdeck_row.connect("notify::active", self._on_steamdeck_tag_toggled)
        prefs_group.add(self.steamdeck_row)

        # Gamescope toggle row
        self.gamescope_row = Adw.SwitchRow()
        self.gamescope_row.set_title("Use Gamescope")
        self.gamescope_row.set_subtitle("Disable to run Steam directly in bwrap without Gamescope")
        self.gamescope_row.set_active(self._profile.use_gamescope)
        self.gamescope_row.connect("notify::active", self._on_gamescope_toggled)
        prefs_group.add(self.gamescope_row)

        # Gamescope WSI toggle row
        self.gamescope_wsi_row = Adw.SwitchRow()
        self.gamescope_wsi_row.set_title("Enable Gamescope WSI")
        self.gamescope_wsi_row.set_subtitle("Enable Gamescope Wayland Support Interface (WSI)")
        self.gamescope_wsi_row.set_active(self._profile.enable_gamescope_wsi)
        self.gamescope_wsi_row.connect("notify::active", self._on_gamescope_wsi_toggled)
        prefs_group.add(self.gamescope_wsi_row)

        prefs_page.add(prefs_group)
        self.add(prefs_page)

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
