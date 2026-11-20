"""Compact engine controls and instance-file tools for the session studio."""

# flake8: noqa: E402

import copy
import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk, Pango  # noqa: E402

from src.core.config import Config
from src.gui.dialogs import ErrorDialog
from src.models.profile import PlayerInstanceConfig, Profile

logger = logging.getLogger(__name__)


class PreferencesWindow(Adw.Window):
    """Application-wide engine options, separate from the player workspace."""

    __gsignals__ = {
        "instance-terminal-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, parent, profile, on_settings_changed, **kwargs):
        """Keep the active profile and report edits immediately to the presenter."""
        super().__init__(**kwargs)
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Preferences")
        self.set_default_size(840, 620)
        self.add_css_class("settings-window")
        self._profile = profile
        self._on_settings_changed = on_settings_changed
        self._build_ui()

        style = Adw.StyleManager.get_default()
        style.connect_object("notify::dark", PreferencesWindow._on_theme_changed, self)
        self._on_theme_changed()

    def _build_ui(self):
        """Use a native window header and a small, two-destination navigator."""
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Preferences", subtitle="Twinverse"))
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_hhomogeneous(False)
        self._stack.set_vhomogeneous(False)
        self._navigation = Gtk.StackSwitcher(stack=self._stack, halign=Gtk.Align.CENTER)
        self._navigation.add_css_class("settings-navigation")
        self._navigation.set_margin_top(8)
        self._navigation.set_margin_bottom(8)
        content.append(self._navigation)
        content.append(self._stack)
        toolbar.set_content(content)
        self.set_content(toolbar)

        self._build_engine_page()
        self._build_instances_page()
        self._stack.set_visible_child_name("engine")

    @staticmethod
    def _caption(text):
        label = Gtk.Label(label=text, xalign=0, wrap=True)
        label.add_css_class("settings-caption")
        label.add_css_class("dim-label")
        return label

    def _create_page(self, name, title, heading, description):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, vexpand=True)
        page.add_css_class("settings-page")
        page.set_margin_start(24)
        page.set_margin_end(24)
        page.set_margin_top(16)
        page.set_margin_bottom(24)

        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label=heading, xalign=0, wrap=True)
        label.add_css_class("settings-heading")
        label.add_css_class("title-2")
        intro.append(label)
        intro.append(self._caption(description))
        page.append(intro)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(page)
        self._stack.add_titled(scroller, name, title)
        return page

    def _build_engine_page(self):
        self._engine_page = self._create_page(
            "engine",
            "Engine",
            "Launch engine",
            "Choose how every player runs. Changes save immediately and apply to the next launch.",
        )
        gamescope, self.gamescope_row = self._create_toggle(
            "Use Gamescope",
            "Give each player a Gamescope compositor. Turn this off to run Steam directly in Bubblewrap.",
            self._profile.use_gamescope,
            self._on_gamescope_toggled,
        )
        self._engine_page.append(gamescope)

        compatibility = Gtk.Box(spacing=16, homogeneous=True)
        steamdeck, self.steamdeck_row = self._create_toggle(
            "Steam Deck tag",
            "Add --mangoapp to Gamescope and -steamdeck to Steam.",
            self._profile.use_steamdeck_tag,
            self._on_steamdeck_tag_toggled,
        )
        wsi, self.gamescope_wsi_row = self._create_toggle(
            "Gamescope WSI",
            "Enable the Gamescope Wayland Support Interface (WSI).",
            self._profile.enable_gamescope_wsi,
            self._on_gamescope_wsi_toggled,
        )
        compatibility.append(steamdeck)
        compatibility.append(wsi)
        self._engine_page.append(compatibility)
        self._engine_page.append(Gtk.Box(vexpand=True))
        self._add_reset_button()

    def _create_toggle(self, title, description, active, callback):
        """Build a labelled field while keeping the existing switch API attributes."""
        field = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        field.add_css_class("settings-section")
        field.add_css_class("settings-toggle")
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        field.append(content)

        line = Gtk.Box(spacing=12)
        label = Gtk.Label(label=title, xalign=0, wrap=True, hexpand=True)
        label.add_css_class("heading")
        switch = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
        switch.update_property([Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION], [title, description])
        label.set_mnemonic_widget(switch)
        switch.connect("notify::active", callback)
        line.append(label)
        line.append(switch)
        content.append(line)
        content.append(self._caption(description))
        return field, switch

    def _build_instances_page(self):
        self._instances_page = self._create_page(
            "instances",
            "Instance data",
            "Player files",
            "Each player has an isolated Steam home. Open its files, launch a terminal, or reset just that player.",
        )
        self._instance_list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._instance_list_box.add_css_class("settings-section")
        self._instance_list_box.set_valign(Gtk.Align.START)

        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        empty.set_margin_start(24)
        empty.set_margin_end(24)
        empty.set_margin_top(48)
        empty.set_margin_bottom(48)
        icon = Gtk.Image(icon_name="folder-symbolic", pixel_size=48)
        icon.add_css_class("dim-label")
        empty.append(icon)
        title = Gtk.Label(label="No instance data yet")
        title.add_css_class("heading")
        empty.append(title)
        caption = self._caption(
            "Launch a player to create its Steam home.\nIts files and reset tools will appear here."
        )
        caption.set_xalign(0.5)
        caption.set_justify(Gtk.Justification.CENTER)
        empty.append(caption)
        self._instance_list_box.set_placeholder(empty)
        self._instances_page.append(self._instance_list_box)
        self._populate_player_list()

    def _populate_player_list(self):
        """Show existing homes, including players outside the current party."""
        # The empty-state placeholder is also a child, but is not a player row.
        row = self._instance_list_box.get_row_at_index(0)
        while row is not None:
            self._instance_list_box.remove(row)
            row = self._instance_list_box.get_row_at_index(0)

        max_home_index = -1
        for i in range(8):  # Check up to 8 players (maximum allowed)
            home_path = Config.get_steam_home_path(i)
            if home_path.exists():
                max_home_index = i

        max_config_index = max(len(self._profile.player_configs), self._profile.num_players) - 1
        max_index = min(7, max(max_home_index, max_config_index))  # Limit to maximum of 8 players (0-7)

        for i in range(max_index + 1):
            home_path = Config.get_steam_home_path(i)
            if home_path.exists():
                self._instance_list_box.append(self._create_player_row(i))

    def _create_player_row(self, player_index):
        """Create a file entry with a player badge, real path and explicit tools."""
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        row.add_css_class("settings-player")
        content = Gtk.Box(spacing=12)
        content.set_margin_start(14)
        content.set_margin_end(14)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        row.set_child(content)

        badge = Gtk.Label(label=f"{player_index + 1:02}", width_request=42, height_request=42)
        badge.add_css_class("numeric")
        badge.add_css_class("title-3")
        content.append(badge)
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label=f"Player {player_index + 1}", xalign=0)
        title.add_css_class("heading")
        details.append(title)
        home_path = str(Config.get_steam_home_path(player_index))
        path = Gtk.Label(label=home_path, xalign=0, selectable=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        path.add_css_class("settings-caption")
        path.add_css_class("dim-label")
        path.set_tooltip_text(home_path)
        details.append(path)
        content.append(details)

        tools = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        home_button = Gtk.Button(icon_name="folder-open-symbolic")
        home_button.set_tooltip_text(f"Open home directory for player {player_index + 1}")
        home_button.connect("clicked", self._on_open_home_clicked, player_index)
        tools.append(home_button)
        terminal_button = Gtk.Button(icon_name="utilities-terminal-symbolic")
        terminal_button.set_tooltip_text(f"Open terminal for player {player_index + 1}")
        terminal_button.connect("clicked", lambda _: self.emit("instance-terminal-requested", player_index))
        tools.append(terminal_button)
        delete_button = Gtk.Button(icon_name="user-trash-symbolic")
        delete_button.set_tooltip_text(f"Reset player {player_index + 1} settings and remove home directory")
        delete_button.add_css_class("destructive-action")
        delete_button.add_css_class("settings-danger")
        delete_button.connect("clicked", self._on_delete_player_clicked, player_index)
        tools.append(delete_button)
        content.append(tools)
        return row

    def _on_theme_changed(self, _pspec=None):
        """Leave colors native and expose the current scheme to the stylesheet."""
        if Adw.StyleManager.get_default().get_dark():
            self.remove_css_class("light")
        else:
            self.add_css_class("light")

    def _on_open_home_clicked(self, button, player_index):
        """Handle opening the player's home directory."""
        import subprocess
        import sys

        home_path = Config.get_steam_home_path(player_index)

        path_str = str(home_path)

        try:
            if sys.platform.startswith("darwin"):  # macOS
                subprocess.run(["open", path_str], check=True)
            elif sys.platform.startswith("win"):  # Windows
                subprocess.run(["explorer", path_str], check=True)
            else:  # Linux and other Unix-like systems
                subprocess.run(["xdg-open", path_str], check=True)
        except subprocess.CalledProcessError:
            logger.warning("Failed to open directory: %s", path_str)
        except FileNotFoundError:
            logger.warning("Directory does not exist: %s", path_str)
            home_path.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(["xdg-open", path_str], check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                logger.warning("Still failed to open directory: %s", path_str)

    def _on_delete_player_clicked(self, button, player_index):
        """Handle deletion of a player's configuration and home directory."""
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Reset Player {player_index + 1}?",
            body=f"This will reset the player settings to default and permanently delete Player {player_index + 1}'s home directory, along with all its contents. This action cannot be undone.",
        )

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Reset Player")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        dialog.connect("response", self._on_confirmation_response, player_index)
        dialog.present()

    def _on_confirmation_response(self, dialog, response, player_index):
        """Handle the confirmation dialog response."""
        if response == "reset":
            home_path = Config.get_steam_home_path(player_index)
            removed, error = self._remove_home_directory(home_path)
            if not removed:
                ErrorDialog(self, "Error", f"The home directory could not be removed completely:\n{error}").present()
                return

            default_player_config = PlayerInstanceConfig()

            if player_index < len(self._profile.player_configs):
                self._profile.player_configs[player_index] = default_player_config
            else:
                while len(self._profile.player_configs) <= player_index:
                    self._profile.player_configs.append(PlayerInstanceConfig())
                self._profile.player_configs[player_index] = default_player_config

            self._populate_player_list()

            self._on_settings_changed("player_configs", self._profile.player_configs)

            try:
                self._profile.save()
            except Exception:
                logger.exception("Error saving the profile")

    @staticmethod
    def _remove_home_directory(home_path):
        """
        Remove the home directory for a specific player.

        Returns:
            True when the directory is gone, and the error when it is not.
        """
        import shutil
        from pathlib import Path

        path = Path(home_path)
        if not path.exists():
            return True, None

        try:
            shutil.rmtree(path)
        except Exception as e:
            logger.exception("Error removing directory %s", path)
            return False, str(e)

        return True, None

    def _add_reset_button(self):
        """Keep profile reset distinct from deleting an instance's files."""
        reset = Gtk.Box(spacing=16)
        reset.add_css_class("settings-section")
        reset.add_css_class("settings-reset")
        reset.set_margin_top(8)
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        title = Gtk.Label(label="Start from defaults", xalign=0)
        title.add_css_class("heading")
        details.append(title)
        details.append(self._caption("Reset engine options, player settings and layout. Instance files stay on disk."))
        reset.append(details)
        reset_button = Gtk.Button(label="Reset all settings", valign=Gtk.Align.CENTER)
        reset_button.set_tooltip_text("Reset all settings to default values without deleting instance files")
        reset_button.add_css_class("destructive-action")
        reset_button.add_css_class("settings-danger")
        reset_button.connect("clicked", self._on_reset_clicked)
        reset.append(reset_button)
        self._engine_page.append(reset)

    def _on_reset_clicked(self, button):
        """Handle reset button click."""
        default_profile = Profile()

        self._profile.use_steamdeck_tag = default_profile.use_steamdeck_tag
        self._profile.use_gamescope = default_profile.use_gamescope
        self._profile.enable_gamescope_wsi = default_profile.enable_gamescope_wsi
        self._profile.num_players = default_profile.num_players
        self._profile.party_players = default_profile.party_players
        self._profile.mode = default_profile.mode
        # The values are copied, so the two profiles do not share the same
        # settings.
        self._profile.splitscreen = copy.deepcopy(default_profile.splitscreen)
        self._profile.player_configs = copy.deepcopy(list(default_profile.player_configs))
        self._profile.selected_players = list(default_profile.selected_players)
        self._profile.layout_order = default_profile.layout_order
        self._profile.monitor_layouts = {}
        self._profile.env = copy.deepcopy(default_profile.env)

        self.steamdeck_row.set_active(self._profile.use_steamdeck_tag)
        self.gamescope_row.set_active(self._profile.use_gamescope)
        self.gamescope_wsi_row.set_active(self._profile.enable_gamescope_wsi)

        self._on_settings_changed("use_steamdeck_tag", self._profile.use_steamdeck_tag)
        self._on_settings_changed("use_gamescope", self._profile.use_gamescope)
        self._on_settings_changed("enable_gamescope_wsi", self._profile.enable_gamescope_wsi)
        self._on_settings_changed("player_configs", self._profile.player_configs)

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
