"""Application shell for the native GTK session layout."""

# flake8: noqa: E402

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GObject, Gtk, Pango  # noqa: E402

from src.core.i18n import ngettext, subscribe, t
from src.gui.dialogs import ErrorDialog
from src.gui.notifications import INFO, send_desktop_notification
from src.gui.pages import LayoutSettingsPage
from src.gui.widgets.player_row import INSTANCE_RUNNING
from src.gui.widgets.spinner import StudioSpinner
from src.gui.widgets.toast import ToastOverlay


class MainWindow(Adw.ApplicationWindow):
    """A canvas-led workspace with a party navigator and contextual player inspector."""

    def __init__(self, application, presenter, *args, **kwargs):
        """Build the studio shell around the existing presenter contract."""
        super().__init__(*args, application=application, **kwargs)
        self._presenter = presenter
        self._session_state = "idle"
        self.set_title("Twinverse")
        self.set_default_size(1080, 720)
        self.set_size_request(660, 560)
        self.add_css_class("twinverse-studio")
        self.toast_overlay = ToastOverlay()
        self.toolbar_view = Adw.ToolbarView()
        self.toast_overlay.set_child(self.toolbar_view)
        self.set_content(self.toast_overlay)
        self._build_workspace()
        self._build_session_status()
        self._build_header()
        self._configure_adaptation()
        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", self._on_theme_changed)
        self._on_theme_changed(style, None)
        self._update_session_summary()
        subscribe(self.retranslate)
        self.connect("close-request", self._on_close_request)

    def _build_workspace(self):
        self.layout_settings_page = LayoutSettingsPage()
        page = self.layout_settings_page
        page.connect("settings-changed", lambda *_: self._presenter.on_settings_changed())
        page.connect("verification-completed", lambda *_: self._presenter.on_verification_completed())
        page.connect(
            "instance-launch-requested", lambda _w, number: self._presenter.on_instance_launch_requested(number)
        )
        page.connect("devices-refresh-requested", lambda *_: self._presenter.on_devices_refresh_requested())
        page.connect("summary-changed", lambda *_: self._update_session_summary())
        self.toolbar_view.set_content(page)

    def _build_session_status(self):
        area = self.layout_settings_page.session_controls
        line = Gtk.Box(spacing=8)
        self.session_icon = Gtk.Image(icon_name="twinverse-dot-symbolic", pixel_size=12)
        self.session_icon.add_css_class("session-indicator")
        line.append(self.session_icon)
        self.session_title = Gtk.Label(
            label=t("session.setup_title"),
            xalign=0,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
            width_chars=1,
            max_width_chars=24,
        )
        self.session_title.add_css_class("session-status-title")
        line.append(self.session_title)
        area.append(line)
        self.session_detail = Gtk.Label(
            xalign=0,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
            width_chars=1,
            max_width_chars=26,
        )
        self.session_detail.add_css_class("session-status-detail")
        area.append(self.session_detail)
        self._build_launch_button()
        area.append(self.launch_button)

    def _build_launch_button(self):
        self.launch_button = Gtk.Button(hexpand=True)
        self.launch_button.add_css_class("studio-launch")
        self.launch_button.add_css_class("launch-button")
        self.launch_button.set_sensitive(False)
        self.launch_button.set_tooltip_text(t("session.launch_tooltip"))
        self.launch_button.connect("clicked", lambda *_: self._presenter.on_launch_clicked())
        self.launch_content_box = Gtk.Box(spacing=9, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.launch_icon = Gtk.Image(icon_name="twinverse-play-symbolic")
        self.launch_label = Gtk.Label(label=t("session.launch_button"))
        self.launch_spinner = StudioSpinner(size=16)
        self.launch_content_box.append(self.launch_icon)
        self.launch_content_box.append(self.launch_label)
        self.launch_button.set_child(self.launch_content_box)

    def _build_menu_model(self) -> Gio.Menu:
        menu = Gio.Menu()
        menu.append(t("menu.preferences"), "win.preferences")
        menu.append(t("menu.about"), "win.about")
        return menu

    def _build_header(self):
        header = Adw.HeaderBar()
        header.add_css_class("studio-header")
        self.inspector_toggle = Gtk.ToggleButton(icon_name="panel-right-symbolic", valign=Gtk.Align.CENTER)
        self._panel_controls = (
            (self.layout_settings_page.inspector_split, self.inspector_toggle, "panel.player_setup", "F9"),
        )
        self._panel_bindings = []
        for split, button, title_key, shortcut in self._panel_controls:
            button.add_css_class("panel-toggle")
            self.layout_settings_page.stage_header.append(button)
            self._panel_bindings.append(
                split.bind_property(
                    "show-sidebar",
                    button,
                    "active",
                    GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
                )
            )
            split.connect("notify::show-sidebar", self._sync_panel_toggle, button, title_key, shortcut)
            self._sync_panel_toggle(split, None, button, title_key, shortcut)

        # An empty custom title also prevents the window title from appearing here.
        header.set_title_widget(Gtk.Box())

        self.theme_toggle_button = Gtk.Button()
        self.theme_toggle_button.add_css_class("flat")
        self.theme_toggle_button.set_tooltip_text(t("header.theme_tooltip"))
        self.theme_toggle_button.connect("clicked", self._toggle_theme)

        self.menu_button = Gtk.MenuButton(icon_name="twinverse-menu-symbolic", menu_model=self._build_menu_model())
        self.menu_button.add_css_class("flat")
        self.menu_button.set_tooltip_text(t("header.menu_tooltip"))
        self.header_tools = Gtk.Box(spacing=4)
        self.header_tools.append(self.theme_toggle_button)
        self.header_tools.append(self.menu_button)
        header.pack_start(self.header_tools)
        self.toolbar_view.add_top_bar(header)

        actions = {
            "about": self._presenter.on_about_clicked,
            "preferences": self._presenter.on_preferences_clicked,
            "inspector": self._toggle_inspector,
            "refresh-devices": self._presenter.on_devices_refresh_requested,
            "launch": lambda: self._presenter.on_launch_clicked() if self.launch_button.get_sensitive() else None,
        }
        for name, callback in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, target=callback: target())
            self.add_action(action)

        app = self.get_application()
        app.set_accels_for_action("win.preferences", ["<Control>comma"])
        app.set_accels_for_action("win.inspector", ["F9", "<Alt>2"])
        app.set_accels_for_action("win.refresh-devices", ["F5"])
        app.set_accels_for_action("win.launch", ["<Control>Return"])

    def retranslate(self, *_args):
        """Update header tooltips, application menu, panel toggle, and session summary."""
        self.theme_toggle_button.set_tooltip_text(t("header.theme_tooltip"))
        self.menu_button.set_tooltip_text(t("header.menu_tooltip"))
        self.menu_button.set_menu_model(self._build_menu_model())
        for split, button, title_key, shortcut in self._panel_controls:
            self._sync_panel_toggle(split, None, button, title_key, shortcut)
        if self._session_state == "starting":
            self.launch_label.set_label(t("session.starting_button"))
        elif self._session_state == "stopping":
            self.launch_label.set_label(t("session.stopping_button"))
        else:
            self.update_launch_button_action(self._session_state == "running")
        self._update_session_summary()

    def _configure_adaptation(self):
        compact = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 1120sp"))
        compact.add_setter(self.layout_settings_page.inspector_split, "collapsed", True)
        compact.add_setter(self.layout_settings_page.inspector_split, "show-sidebar", False)
        self.add_breakpoint(compact)

    def _sync_panel_toggle(self, split, _pspec, button, title_key, shortcut):
        visible = split.get_show_sidebar()
        title = t(title_key)
        tooltip = (
            t("panel.hide_tooltip", title=title, shortcut=shortcut)
            if visible
            else t("panel.show_tooltip", title=title, shortcut=shortcut)
        )
        label = t("panel.hide_label", title=title) if visible else t("panel.show_label", title=title)
        button.set_tooltip_text(tooltip)
        button.update_property([Gtk.AccessibleProperty.LABEL], [label])
        expanded = Gtk.AccessibleTristate.TRUE if visible else Gtk.AccessibleTristate.FALSE
        # EXPANDED expects an integer tristate, not a boolean GValue.
        button.update_state([Gtk.AccessibleState.EXPANDED], [int(expanded)])

    def _toggle_inspector(self):
        split = self.layout_settings_page.inspector_split
        split.set_show_sidebar(not split.get_show_sidebar())

    def _update_session_summary(self):
        if not hasattr(self, "session_title"):
            return
        rows = self.layout_settings_page.player_rows
        selected = [row for row in rows if row.is_selected()]
        ready = sum(bool(getattr(row, "_is_verified", False)) for row in selected)
        running = sum(row.get_instance_state() == INSTANCE_RUNNING for row in rows)
        state = self._session_state
        if state == "starting":
            title, detail = t("session.starting_title"), t("session.starting_detail")
        elif state == "stopping":
            title, detail = t("session.stopping_title"), t("session.stopping_detail")
        elif state == "running":
            title, detail = t("session.running_title"), t("session.running_detail", count=running)
        elif not selected:
            title, detail = t("session.empty_title"), t("session.empty_detail")
        elif ready < len(selected):
            title, detail = (
                t("session.needs_setup_title"),
                t("session.needs_setup_detail", ready=ready, total=len(selected)),
            )
        else:
            title = t("session.ready_title")
            detail = ngettext("session.ready_detail_one", "session.ready_detail_many", len(selected))
        self.session_title.set_label(title)
        self.session_detail.set_label(detail)
        for candidate in ("idle", "starting", "stopping", "running"):
            self.session_icon.remove_css_class(f"session-{candidate}")
        self.session_icon.add_css_class(f"session-{state}")

    def get_layout_page(self):
        """Expose studio settings through the presenter's existing view interface."""
        return self.layout_settings_page

    def show_launching_state(self):
        """Show pending startup without prematurely offering a stop action."""
        self._session_state = "starting"
        self.launch_label.set_label(t("session.starting_button"))
        self.launch_button.set_sensitive(False)
        self._show_spinner()
        self.layout_settings_page.set_checkboxes_sensitive(False)
        self._update_session_summary()

    def show_running_state(self):
        """Offer session termination only after clients are confirmed running."""
        self._session_state = "running"
        self.update_launch_button_action(True)
        self._hide_spinner()
        self.launch_button.set_sensitive(True)
        self.layout_settings_page.set_number_of_instances_sensitive(False)
        self.layout_settings_page.set_screen_settings_sensitive(False)
        self.layout_settings_page.set_checkboxes_sensitive(False)
        self._update_session_summary()

    def show_stopping_state(self):
        """Keep termination pending until processes are confirmed gone."""
        self._session_state = "stopping"
        self.launch_label.set_label(t("session.stopping_button"))
        self.launch_button.set_sensitive(False)
        self._show_spinner()
        self._update_session_summary()

    def show_idle_state(self):
        """Restore layout and participation controls after all active instances end."""
        self._session_state = "idle"
        self.update_launch_button_action(False)
        self._hide_spinner()
        self.layout_settings_page.set_sensitive(True)
        self.layout_settings_page.set_running_state(False)
        self.layout_settings_page.set_number_of_instances_sensitive(True)
        self.layout_settings_page.set_screen_settings_sensitive(True)
        self.layout_settings_page.set_checkboxes_sensitive(True)
        self._update_session_summary()

    def update_launch_button_action(self, is_running):
        """Keep the primary label, icon and tooltip aligned with its actual action."""
        self.launch_label.set_label(t("session.end_button") if is_running else t("session.launch_button"))
        self.launch_icon.set_from_icon_name("twinverse-stop-symbolic" if is_running else "twinverse-play-symbolic")
        self.launch_button.set_tooltip_text(t("session.stop_tooltip") if is_running else t("session.launch_tooltip"))
        self.launch_button.remove_css_class("launch-button" if is_running else "stop-button")
        self.launch_button.add_css_class("stop-button" if is_running else "launch-button")

    def _show_spinner(self):
        self.launch_icon.set_visible(False)
        if self.launch_spinner.get_parent() is None:
            self.launch_content_box.prepend(self.launch_spinner)
        self.launch_spinner.start()

    def _hide_spinner(self):
        self.launch_spinner.stop()
        if self.launch_spinner.get_parent() is not None:
            self.launch_content_box.remove(self.launch_spinner)
        self.launch_icon.set_visible(True)

    def update_launch_button_sensitivity(self, enabled):
        """Apply the presenter's launch-readiness decision to the primary action."""
        self.launch_button.set_sensitive(enabled)
        self._update_session_summary()

    def show_toast(self, message, timeout=3, level=INFO):
        """Report in-app events, using desktop notifications when the window is inactive."""
        if not self.is_active():
            send_desktop_notification("Twinverse", message, level)
        self.toast_overlay.show_toast(message, level, timeout)
        return self.toast_overlay

    def show_error(self, message, title=None):
        """Present failures without interrupting or rebuilding the workspace."""
        ErrorDialog(self, title or t("common.error"), message).present()

    def minimize_window(self):
        """Give launched games focus when the presenter confirms startup."""
        self.minimize()

    def _toggle_theme(self, _button):
        style = Adw.StyleManager.get_default()
        style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT if style.get_dark() else Adw.ColorScheme.FORCE_DARK)

    def _on_theme_changed(self, style, _pspec):
        if style.get_dark():
            self.remove_css_class("light")
        else:
            self.add_css_class("light")
        self.theme_toggle_button.set_icon_name("moon-outline-symbolic" if style.get_dark() else "sun-outline-symbolic")

    def _on_close_request(self, *_args):
        self._presenter.on_close_requested()
        return True
