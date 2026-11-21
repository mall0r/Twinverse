"""Compact engine controls and instance-file tools for the session layout."""

# flake8: noqa: E402

import copy
import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GObject, Gtk, Pango  # noqa: E402

from src.core.config import Config
from src.core.i18n import (
    LANGUAGE_AUTO,
    LANGUAGE_EN,
    LANGUAGE_PT_BR,
    normalize_language_preference,
    subscribe,
    t,
)
from src.gui.dialogs import ErrorDialog
from src.models.profile import PlayerInstanceConfig, Profile

logger = logging.getLogger(__name__)

LANGUAGE_OPTION_IDS = (LANGUAGE_AUTO, LANGUAGE_EN, LANGUAGE_PT_BR)


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
        self.set_title(t("prefs.title"))
        self.set_default_size(840, 680)
        self.add_css_class("settings-window")
        self._profile = profile
        self._on_settings_changed = on_settings_changed
        self._updating_language = False
        self._build_ui()
        subscribe(self.retranslate)

        style = Adw.StyleManager.get_default()
        style.connect_object("notify::dark", PreferencesWindow._on_theme_changed, self)
        self._on_theme_changed()

    def _build_ui(self):
        """Use a native window header and a small, two-destination navigator."""
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self._window_title = Adw.WindowTitle(title=t("prefs.title"), subtitle="Twinverse")
        header.set_title_widget(self._window_title)
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
        caption = self._caption(description)
        intro.append(caption)
        page.append(intro)

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(page)
        self._stack.add_titled(scroller, name, title)
        return page, scroller, label, caption

    def _build_engine_page(self):
        (
            self._engine_page,
            self._engine_scroller,
            self._engine_heading_label,
            self._engine_description_label,
        ) = self._create_page(
            "engine",
            t("prefs.tab.engine"),
            t("prefs.engine.heading"),
            t("prefs.engine.description"),
        )
        self._engine_page.append(self._build_language_section())

        (
            gamescope,
            self.gamescope_row,
            self._gamescope_title_label,
            self._gamescope_desc_label,
        ) = self._create_toggle(
            t("prefs.gamescope.title"),
            t("prefs.gamescope.description"),
            self._profile.use_gamescope,
            self._on_gamescope_toggled,
        )
        self._engine_page.append(gamescope)

        compatibility = Gtk.Box(spacing=16, homogeneous=True)
        (
            steamdeck,
            self.steamdeck_row,
            self._steamdeck_title_label,
            self._steamdeck_desc_label,
        ) = self._create_toggle(
            t("prefs.steamdeck.title"),
            t("prefs.steamdeck.description"),
            self._profile.use_steamdeck_tag,
            self._on_steamdeck_tag_toggled,
        )
        (
            wsi,
            self.gamescope_wsi_row,
            self._wsi_title_label,
            self._wsi_desc_label,
        ) = self._create_toggle(
            t("prefs.wsi.title"),
            t("prefs.wsi.description"),
            self._profile.enable_gamescope_wsi,
            self._on_gamescope_wsi_toggled,
        )
        compatibility.append(steamdeck)
        compatibility.append(wsi)
        self._engine_page.append(compatibility)

        (
            network_isolation,
            self.network_isolation_row,
            self._network_title_label,
            self._network_desc_label,
        ) = self._create_toggle(
            t("prefs.isolate_network.title"),
            t("prefs.isolate_network.description"),
            self._profile.isolate_network,
            self._on_isolate_network_toggled,
        )
        self._engine_page.append(network_isolation)

        self._engine_page.append(Gtk.Box(vexpand=True))
        self._add_reset_button()

    def _language_option_labels(self) -> list[str]:
        return [t("lang.auto"), t("lang.en"), t("lang.pt_BR")]

    def _build_language_section(self):
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
        self._language_title_label = Gtk.Label(
            label=t("prefs.language.title"),
            xalign=0,
            wrap=True,
            hexpand=True,
            valign=Gtk.Align.CENTER,
        )
        self._language_title_label.add_css_class("heading")
        self._language_model = Gtk.StringList.new(self._language_option_labels())
        self.language_row = Gtk.DropDown(
            model=self._language_model,
            valign=Gtk.Align.CENTER,
        )
        self.language_row.add_css_class("dock-select")
        self._sync_language_dropdown(getattr(self._profile, "language", LANGUAGE_AUTO))
        self.language_row.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [t("prefs.language.title"), t("prefs.language.description")],
        )
        self._language_title_label.set_mnemonic_widget(self.language_row)
        self.language_row.connect("notify::selected", self._on_language_selected)
        line.append(self._language_title_label)
        line.append(self.language_row)
        content.append(line)
        self._language_desc_label = self._caption(t("prefs.language.description"))
        content.append(self._language_desc_label)
        return field

    def _sync_language_dropdown(self, preference: str):
        normalized = normalize_language_preference(preference)
        idx = LANGUAGE_OPTION_IDS.index(normalized) if normalized in LANGUAGE_OPTION_IDS else 0
        self._updating_language = True
        try:
            labels = self._language_option_labels()
            if self._language_model.get_n_items() == len(labels):
                for item_idx, text in enumerate(labels):
                    if self._language_model.get_string(item_idx) != text:
                        self._language_model.splice(item_idx, 1, [text])
            else:
                self._language_model.splice(0, self._language_model.get_n_items(), labels)
            if self.language_row.get_selected() != idx:
                self.language_row.set_selected(idx)
        finally:
            self._updating_language = False

    def _on_language_selected(self, dropdown, _pspec):
        if self._updating_language:
            return
        idx = dropdown.get_selected()
        if not isinstance(idx, int) or not 0 <= idx < len(LANGUAGE_OPTION_IDS):
            return
        selected_lang = LANGUAGE_OPTION_IDS[idx]
        self._profile.language = selected_lang
        self._on_settings_changed("language", selected_lang)

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
        desc_label = self._caption(description)
        content.append(desc_label)
        return field, switch, label, desc_label

    def _build_instances_page(self):
        (
            self._instances_page,
            self._instances_scroller,
            self._instances_heading_label,
            self._instances_description_label,
        ) = self._create_page(
            "instances",
            t("prefs.tab.instances"),
            t("prefs.instances.heading"),
            t("prefs.instances.description"),
        )
        self._instance_list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self._instance_list_box.add_css_class("settings-section")
        self._instance_list_box.set_valign(Gtk.Align.START)

        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        empty.set_margin_start(24)
        empty.set_margin_end(24)
        empty.set_margin_top(48)
        empty.set_margin_bottom(48)
        icon = Gtk.Image(icon_name="twinverse-folder-symbolic", pixel_size=48)
        icon.add_css_class("dim-label")
        empty.append(icon)
        self._instances_empty_title = Gtk.Label(label=t("prefs.instances.empty_title"))
        self._instances_empty_title.add_css_class("heading")
        empty.append(self._instances_empty_title)
        self._instances_empty_caption = self._caption(t("prefs.instances.empty_description"))
        self._instances_empty_caption.set_xalign(0.5)
        self._instances_empty_caption.set_justify(Gtk.Justification.CENTER)
        empty.append(self._instances_empty_caption)
        self._instance_list_box.set_placeholder(empty)
        self._instances_page.append(self._instance_list_box)
        self._populate_player_list()

    def retranslate(self, *_args):
        """Update all Preferences titles, tabs, cards, and instance entries live."""
        self.set_title(t("prefs.title"))
        self._window_title.set_title(t("prefs.title"))
        self._stack.get_page(self._engine_scroller).set_title(t("prefs.tab.engine"))
        self._stack.get_page(self._instances_scroller).set_title(t("prefs.tab.instances"))

        self._engine_heading_label.set_label(t("prefs.engine.heading"))
        self._engine_description_label.set_label(t("prefs.engine.description"))

        self._language_title_label.set_label(t("prefs.language.title"))
        self._language_desc_label.set_label(t("prefs.language.description"))
        self._sync_language_dropdown(getattr(self._profile, "language", LANGUAGE_AUTO))
        self.language_row.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [t("prefs.language.title"), t("prefs.language.description")],
        )

        self._gamescope_title_label.set_label(t("prefs.gamescope.title"))
        self._gamescope_desc_label.set_label(t("prefs.gamescope.description"))
        self.gamescope_row.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [t("prefs.gamescope.title"), t("prefs.gamescope.description")],
        )

        self._steamdeck_title_label.set_label(t("prefs.steamdeck.title"))
        self._steamdeck_desc_label.set_label(t("prefs.steamdeck.description"))
        self.steamdeck_row.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [t("prefs.steamdeck.title"), t("prefs.steamdeck.description")],
        )

        self._wsi_title_label.set_label(t("prefs.wsi.title"))
        self._wsi_desc_label.set_label(t("prefs.wsi.description"))
        self.gamescope_wsi_row.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [t("prefs.wsi.title"), t("prefs.wsi.description")],
        )

        self._network_title_label.set_label(t("prefs.isolate_network.title"))
        self._network_desc_label.set_label(t("prefs.isolate_network.description"))
        self.network_isolation_row.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [t("prefs.isolate_network.title"), t("prefs.isolate_network.description")],
        )

        self._reset_title_label.set_label(t("prefs.reset.title"))
        self._reset_desc_label.set_label(t("prefs.reset.description"))
        self._reset_button.set_label(t("prefs.reset.button"))
        self._reset_button.set_tooltip_text(t("prefs.reset.tooltip"))

        self._instances_heading_label.set_label(t("prefs.instances.heading"))
        self._instances_description_label.set_label(t("prefs.instances.description"))
        self._instances_empty_title.set_label(t("prefs.instances.empty_title"))
        self._instances_empty_caption.set_label(t("prefs.instances.empty_description"))
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
        player_name = self._profile.get_player_name(player_index)
        num_str = f"{player_index + 1:02d}"
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        row.add_css_class("settings-player")
        content = Gtk.Box(spacing=12)
        content.set_margin_start(14)
        content.set_margin_end(14)
        content.set_margin_top(14)
        content.set_margin_bottom(14)
        row.set_child(content)

        badge = Gtk.Label(label=num_str, width_request=42, height_request=42)
        badge.add_css_class("numeric")
        badge.add_css_class("title-3")
        content.append(badge)
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label=player_name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
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
        home_button = Gtk.Button(icon_name="twinverse-folder-open-symbolic")
        home_button.set_tooltip_text(t("prefs.instances.open_home_tooltip", name=player_name, num=num_str))
        home_button.connect("clicked", self._on_open_home_clicked, player_index)
        tools.append(home_button)
        terminal_button = Gtk.Button(icon_name="twinverse-terminal-symbolic")
        terminal_button.set_tooltip_text(t("prefs.instances.open_terminal_tooltip", name=player_name, num=num_str))
        terminal_button.connect("clicked", lambda _: self.emit("instance-terminal-requested", player_index))
        tools.append(terminal_button)
        delete_button = Gtk.Button(icon_name="twinverse-trash-symbolic")
        delete_button.set_tooltip_text(t("prefs.instances.reset_tooltip", name=player_name, num=num_str))
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
        player_label = f"{self._profile.get_player_name(player_index)} ({player_index + 1:02d})"
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=t("prefs.instances.confirm_heading", player=player_label),
            body=t("prefs.instances.confirm_body", player=player_label),
        )

        dialog.add_response("cancel", t("common.cancel"))
        dialog.add_response("reset", t("prefs.instances.confirm_reset"))
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
                ErrorDialog(self, t("common.error"), t("prefs.instances.remove_error", error=error)).present()
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
        self._reset_title_label = Gtk.Label(label=t("prefs.reset.title"), xalign=0)
        self._reset_title_label.add_css_class("heading")
        details.append(self._reset_title_label)
        self._reset_desc_label = self._caption(t("prefs.reset.description"))
        details.append(self._reset_desc_label)
        reset.append(details)
        self._reset_button = Gtk.Button(label=t("prefs.reset.button"), valign=Gtk.Align.CENTER)
        self._reset_button.set_tooltip_text(t("prefs.reset.tooltip"))
        self._reset_button.add_css_class("destructive-action")
        self._reset_button.add_css_class("settings-danger")
        self._reset_button.connect("clicked", self._on_reset_clicked)
        reset.append(self._reset_button)
        self._engine_page.append(reset)

    def _on_reset_clicked(self, button):
        """Handle reset button click."""
        default_profile = Profile()

        self._profile.use_steamdeck_tag = default_profile.use_steamdeck_tag
        self._profile.use_gamescope = default_profile.use_gamescope
        self._profile.enable_gamescope_wsi = default_profile.enable_gamescope_wsi
        self._profile.isolate_network = default_profile.isolate_network
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
        self.network_isolation_row.set_active(self._profile.isolate_network)

        self._on_settings_changed("use_steamdeck_tag", self._profile.use_steamdeck_tag)
        self._on_settings_changed("use_gamescope", self._profile.use_gamescope)
        self._on_settings_changed("enable_gamescope_wsi", self._profile.enable_gamescope_wsi)
        self._on_settings_changed("isolate_network", self._profile.isolate_network)
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

    def _on_isolate_network_toggled(self, switch_row, pspec):
        """Handle network isolation toggle."""
        state = switch_row.get_active()
        self._profile.isolate_network = state
        self._on_settings_changed("isolate_network", state)
