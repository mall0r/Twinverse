"""Behavioral coverage for the canvas/roster/inspector architecture."""

import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from src.gui.notifications import BUSY, ERROR, ICONS, INFO  # noqa: E402
from src.gui.windows.main_window import MainWindow  # noqa: E402
from src.gui.windows.preferences_window import PreferencesWindow  # noqa: E402
from src.models import PlayerInstanceConfig, Profile  # noqa: E402


@pytest.fixture(scope="module")
def application(tmp_path_factory):
    """Compile current resources and use real GTK without starting any Steam clients."""
    if not Gtk.init_check():
        pytest.skip("A GTK display is required")
    compiler = shutil.which("glib-compile-resources")
    if compiler is None:
        pytest.skip("glib-compile-resources is required")
    Adw.init()
    root = Path(__file__).resolve().parents[1]
    bundle = tmp_path_factory.mktemp("studio-resources") / "test.gresource"
    subprocess.run(
        [
            compiler,
            "--sourcedir=" + str(root / "res"),
            str(root / "res/twinverse.gresources.xml"),
            "--target=" + str(bundle),
        ],
        check=True,
    )
    resource = Gio.Resource.load(str(bundle))
    Gio.resources_register(resource)
    provider = Gtk.CssProvider()
    provider.load_from_path(str(root / "res/styles/style.css"))
    display = Gdk.Display.get_default()
    Gtk.IconTheme.get_for_display(display).add_resource_path("/io/github/mall0r/Twinverse/icons")
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    app = Adw.Application(application_id="io.github.mall0r.Twinverse.StudioTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    yield app
    app.quit()
    Gtk.StyleContext.remove_provider_for_display(display, provider)
    Gio.resources_unregister(resource)


@pytest.fixture
def window(application):
    """Build the shell against a presenter double, leaving profiles and hardware alone."""
    win = MainWindow(application, Mock())
    win.get_layout_page().load_data(
        Profile(), {"displays": [{"name": "HDMI-A-1", "width": 1920, "height": 1080}]}, {0: True, 1: True}
    )
    yield win
    win.destroy()


def test_new_architecture_has_no_preferences_pages_or_expandable_players(window):
    """The session is a stage and contextual inspector, not a renamed preference form."""
    page = window.get_layout_page()
    assert not isinstance(page, Adw.PreferencesPage)
    assert isinstance(page.roster, Gtk.ListBox)
    assert isinstance(page.inspector_stack, Gtk.Stack)
    assert all(isinstance(player, Gtk.Box) for player in page.player_rows)
    assert all(not isinstance(player, Adw.ExpanderRow) for player in page.player_rows)
    assert all(player.checkbox.get_parent() is not player for player in page.player_rows)
    assert not hasattr(page, "stack")


def test_roster_and_canvas_focus_one_inspector_without_editing_settings(window):
    """Inspecting another player is navigation, never an inclusion or profile change."""
    page = window.get_layout_page()
    edits = []
    page.connect("settings-changed", lambda *_: edits.append(True))
    page.select_player(1)
    assert page.inspector_stack.get_visible_child() is page.player_rows[1]
    assert page.layout_preview._active_player == 1
    assert page.get_selected_players() == [0, 1]
    page.layout_preview._slots[0].button.emit("clicked")
    assert page.inspector_stack.get_visible_child() is page.player_rows[0]
    assert page.roster.get_selected_row().get_index() == 0
    assert edits == []


def test_activating_the_selected_player_reopens_its_inspector(window):
    """Clicking the highlighted roster entry must still be a functional action."""
    page = window.get_layout_page()
    page.select_player(0)
    page.inspector_split.set_show_sidebar(False)
    page.roster.emit("row-activated", page.roster.get_selected_row())
    assert page.inspector_split.get_show_sidebar()


def test_reloading_does_not_reopen_a_deliberately_closed_inspector(window):
    """Restoring selection after a count change must not masquerade as user navigation."""
    page = window.get_layout_page()
    page.inspector_split.set_show_sidebar(False)
    page.load_data(Profile(num_players=3), {}, {})
    assert not page.inspector_split.get_show_sidebar()


def test_custom_placement_controls_return_after_runtime_refresh(window):
    """Unlocking after a session restores canvas repositioning."""
    page = window.get_layout_page()
    page.placement_mode_row.set_selected(1)
    page.set_screen_settings_sensitive(False)
    page.update_devices_info({})
    assert not page.layout_preview._allow_reposition
    assert not page.layout_preview.assign_player(0, 1)
    page.set_screen_settings_sensitive(True)
    assert page.layout_preview._allow_reposition


def test_participation_is_independent_from_inspector_selection(window):
    """Excluded players remain editable and keep their assignments."""
    page = window.get_layout_page()
    page.player_rows[1].guest_ip_row.set_text("192.168.1.42")
    page.player_rows[1].checkbox.set_active(False)
    page.select_player(1)
    assert page.get_selected_players() == [0]
    assert page.layout_preview.instances == [0]
    assert page.get_data()["player_configs"][1].guest_ip == "192.168.1.42"
    page.player_rows[1].checkbox.set_active(True)
    assert page.layout_preview.instances == [0, 1]


def test_runtime_progress_reaches_roster_and_canvas_without_autosave(window):
    """Progress on a hidden inspector must remain visible throughout the studio."""
    page = window.get_layout_page()
    edits = []
    page.connect("settings-changed", lambda *_: edits.append(True))
    page.select_player(0)
    button = page.layout_preview._slots[1].button
    player = page.player_rows[1]
    player.set_instance_state("starting")
    player.set_update_progress("Downloading Steam", 42)
    assert "42%" in page._roster_status[1].get_label()
    assert "42%" in page.layout_preview._slots[1].status.get_label()
    assert page.layout_preview._slots[1].button is button
    assert edits == []
    player.clear_update_progress()


def test_player_edits_do_not_recreate_the_canvas(window):
    """Typing IPs and environment values must preserve canvas focus and slot widgets."""
    page = window.get_layout_page()
    button = page.layout_preview._slots[0].button
    page.player_rows[0].guest_ip_row.set_text("192.168.1.23")
    page.player_rows[0]._add_env_row("EXAMPLE", "  value with spaces  ")
    assert page.layout_preview._slots[0].button is button
    assert page.player_rows[0].get_config().env["EXAMPLE"] == "  value with spaces  "


def test_running_locks_placement_but_keeps_player_navigation(window):
    """During a session, users can still select a space to stop its instance."""
    page = window.get_layout_page()
    page.placement_mode_row.set_selected(1)
    page.player_rows[0].set_instance_state("running")
    window.show_running_state()
    assert not page.screen_mode_row.is_sensitive()
    assert not page.add_player_button.is_sensitive()
    assert all(not btn.is_sensitive() for btn in page._roster_remove_buttons)
    assert not page.layout_preview.assign_player(0, 1)
    page.layout_preview._slots[1].button.emit("clicked")
    assert page.inspector_stack.get_visible_child() is page.player_rows[1]
    assert page.layout_preview._slots[1].button.is_sensitive()
    assert window.launch_label.get_label() == "End session"


def test_individual_action_targets_the_inspected_player(window):
    """An individual action must not accidentally operate on the full session."""
    page = window.get_layout_page()
    page.select_player(1)
    page.player_rows[1].launch_button.emit("clicked")
    window._presenter.on_instance_launch_requested.assert_called_once_with(1)
    window._presenter.on_launch_clicked.assert_not_called()


def test_mouse_capture_is_exclusive_between_inspectors(window):
    """The new standalone controls retain the one-mouse-owner invariant."""
    page = window.get_layout_page()
    page.player_rows[0].grab_input_switch.set_active(True)
    assert not page.player_rows[1].grab_input_switch.get_sensitive()
    page.player_rows[0].grab_input_switch.set_active(False)
    assert page.player_rows[1].grab_input_switch.get_sensitive()


def test_direct_mode_has_a_real_empty_stage_explanation(window):
    """Direct Steam remains usable without showing a misleading monitor arrangement."""
    page = window.get_layout_page()
    page.set_gamescope_enabled(False)
    assert page.displays_disabled_group.get_visible()
    assert not page.layout_preview_group.get_visible()
    assert not page.gamescope_settings_group.get_visible()
    assert page.player_rows[0].launch_button.get_sensitive()


def test_reloading_preserves_focused_player_and_replaces_env_fields(window):
    """Party-size reloads must keep context and never duplicate variable editors."""
    page = window.get_layout_page()
    page.select_player(1)
    profile = Profile(num_players=3)
    profile.player_configs[0] = PlayerInstanceConfig(ENV={"EXAMPLE": "value"})
    page.load_data(profile, {}, {})
    assert page._active_player == 1
    assert page.inspector_stack.get_visible_child() is page.player_rows[1]
    assert len(page.player_rows[0]._env_rows) == 1
    page.player_rows[0].load_config(profile.player_configs[0])
    assert len(page.player_rows[0]._env_rows) == 1


def test_session_action_and_status_track_readiness_and_transitions(window):
    """The global action stays available without a persistent footer or form page."""
    page = window.get_layout_page()
    assert window.session_title.get_label() == "Ready to play"
    page.update_verification_status(1, False)
    assert window.session_title.get_label() == "Setup needed"
    window.show_launching_state()
    assert not window.launch_button.get_sensitive()
    assert window.launch_spinner.get_spinning()
    window.show_running_state()
    assert window.launch_icon.get_visible()
    assert window.launch_label.get_label() == "End session"
    window.show_stopping_state()
    assert window.launch_label.get_label() == "Stopping…"
    window.show_idle_state()
    assert window.launch_label.get_label() == "Launch session"
    assert window.launch_spinner.get_parent() is None


def test_preferences_use_custom_native_fields_and_keep_callbacks(window, monkeypatch, tmp_path):
    """The settings window is rebuilt too, while preserving its profile callback contract."""
    from src.core.config import Config

    monkeypatch.setattr(Config, "get_steam_home_path", lambda index: tmp_path / str(index))
    changed = Mock()
    prefs = PreferencesWindow(window, Profile(), changed)
    try:
        assert isinstance(prefs, Adw.Window)
        assert not isinstance(prefs, Adw.PreferencesWindow)
        assert isinstance(prefs.gamescope_row, Gtk.Switch)
        prefs.gamescope_row.set_active(False)
        changed.assert_called_with("use_gamescope", False)
        assert prefs._instance_list_box.get_row_at_index(0) is None
        (tmp_path / "0").mkdir()
        prefs._populate_player_list()
        assert prefs._instance_list_box.get_row_at_index(0) is not None
        assert prefs._instance_list_box.get_row_at_index(1) is None
    finally:
        prefs.destroy()


def test_roster_numbers_are_centered_in_fixed_size_badges(window):
    """Numeric labels must not inherit the left alignment used by general UI text."""
    for item in window.get_layout_page()._roster_rows:
        badge = item.get_child().get_first_child()
        assert badge.get_xalign() == 0.5
        assert badge.get_yalign() == 0.5
        assert badge.get_valign() == Gtk.Align.CENTER
        assert badge.get_size_request() == (36, 36)


def test_panel_toggles_share_one_location_and_follow_real_visibility(window):
    """One control per panel opens and closes it, including externally triggered dismissals."""
    page = window.get_layout_page()
    assert window.roster_toggle.get_parent() is window.inspector_toggle.get_parent()
    for split, button in (
        (page.roster_split, window.roster_toggle),
        (page.inspector_split, window.inspector_toggle),
    ):
        split.set_show_sidebar(False)
        assert not button.get_active()
        assert button.get_tooltip_text().startswith("Show ")
        button.set_active(True)
        assert split.get_show_sidebar()
        assert button.get_tooltip_text().startswith("Hide ")
        split.set_show_sidebar(False)
        assert not button.get_active()


@pytest.mark.parametrize("visible", [False, True])
def test_panel_toggles_publish_integer_expanded_tristates(window, monkeypatch, visible):
    """Assistive technology receives the actual expanded state with GTK's required value type."""
    expected = Gtk.AccessibleTristate.TRUE if visible else Gtk.AccessibleTristate.FALSE
    for split, button, _title, _shortcut in window._panel_controls:
        split.set_show_sidebar(not visible)
        update_state = Mock(wraps=button.update_state)
        monkeypatch.setattr(button, "update_state", update_state)
        split.set_show_sidebar(visible)
        states, values = update_state.call_args.args
        assert states == [Gtk.AccessibleState.EXPANDED]
        assert type(values[0]) is int
        assert values == [int(expected)]


def test_panel_keyboard_actions_toggle_in_both_directions(window):
    """Shortcuts must have the same open/close behavior as their paired header buttons."""
    page = window.get_layout_page()
    for action_name, split in (("players", page.roster_split), ("inspector", page.inspector_split)):
        split.set_show_sidebar(False)
        action = window.lookup_action(action_name)
        action.activate(None)
        assert split.get_show_sidebar()
        action.activate(None)
        assert not split.get_show_sidebar()


def test_narrow_drawers_are_mutually_exclusive_and_toggles_stay_in_sync(window):
    """Opening one overlay must not leave the other panel covering or hiding it."""
    page = window.get_layout_page()
    for split in (page.roster_split, page.inspector_split):
        split.set_show_sidebar(False)
        split.set_collapsed(True)
    window.roster_toggle.set_active(True)
    assert page.roster_split.get_show_sidebar()
    window.inspector_toggle.set_active(True)
    assert page.inspector_split.get_show_sidebar()
    assert not page.roster_split.get_show_sidebar()
    assert not window.roster_toggle.get_active()
    window.roster_toggle.set_active(True)
    assert not page.inspector_split.get_show_sidebar()
    assert not window.inspector_toggle.get_active()


def test_header_has_only_left_aligned_tools_in_requested_order(application, monkeypatch):
    """The header has no branding or title, and groups all four controls on the left."""
    packed = []
    native_pack_start = Adw.HeaderBar.pack_start
    native_pack_end = Adw.HeaderBar.pack_end

    def pack_start(header, child):
        packed.append((header, "start", child))
        native_pack_start(header, child)

    def pack_end(header, child):
        packed.append((header, "end", child))
        native_pack_end(header, child)

    monkeypatch.setattr(Adw.HeaderBar, "pack_start", pack_start)
    monkeypatch.setattr(Adw.HeaderBar, "pack_end", pack_end)
    win = MainWindow(application, Mock())
    try:
        header = win.header_tools.get_ancestor(Adw.HeaderBar)
        assert packed == [(header, "start", win.header_tools)]
        assert isinstance(header.get_title_widget(), Gtk.Box)
        assert header.get_title_widget().get_first_child() is None
        assert win.header_tools.get_first_child() is win.theme_toggle_button
        panels = win.theme_toggle_button.get_next_sibling()
        assert panels.get_first_child() is win.roster_toggle
        assert win.roster_toggle.get_next_sibling() is win.inspector_toggle
        assert panels.get_last_child() is win.inspector_toggle
        assert panels.get_next_sibling() is win.menu_button
        assert win.header_tools.get_last_child() is win.menu_button
    finally:
        win.destroy()


def test_secondary_actions_have_a_single_menu_entry(window):
    """Preferences and discovery each have one visible entry point, plus keyboard shortcuts."""
    menu = window.menu_button.get_menu_model()
    actions = [menu.get_item_attribute_value(index, "action", None).unpack() for index in range(menu.get_n_items())]
    assert actions.count("win.preferences") == 1
    assert actions.count("win.refresh-devices") == 1
    window.lookup_action("refresh-devices").activate(None)
    window._presenter.on_devices_refresh_requested.assert_called_once_with()
    window.lookup_action("preferences").activate(None)
    window._presenter.on_preferences_clicked.assert_called_once_with()
    page = window.get_layout_page()
    assert hasattr(page, "add_player_button")
    assert not hasattr(page, "num_players_row")
    assert not hasattr(page, "inspector_button")
    assert window.launch_button.get_parent() is page.session_controls
    assert page.session_controls.get_last_child() is window.launch_button
    assert window.menu_button.get_parent() is window.header_tools
    assert window.roster_toggle.get_parent().get_parent() is window.header_tools
    assert window.header_tools.get_last_child() is window.menu_button


def test_party_add_and_per_player_remove_stay_locked_during_play(window):
    """Add player appends at the end, per-player remove works on any slot, and both lock during play."""
    page = window.get_layout_page()
    edits = []
    page.connect("settings-changed", lambda *_: edits.append(True))
    page.add_player_button.emit("clicked")
    assert page.get_data()["num_players"] == 3
    assert page.get_data()["party_players"] == [0, 1, 2]
    page._roster_remove_buttons[1].emit("clicked")
    assert page.get_data()["num_players"] == 2
    assert page.get_data()["party_players"] == [0, 2]
    assert len(edits) == 2
    page.set_number_of_instances_sensitive(False)
    assert not page.add_player_button.is_sensitive()
    assert all(not btn.is_sensitive() for btn in page._roster_remove_buttons)


def test_player_actions_explain_their_scope(window):
    """Per-player launch controls must not look like duplicates of the session action."""
    row = window.get_layout_page().player_rows[0]
    assert row.launch_button.get_label() == "Start player"
    row.set_verification_status(False)
    assert row.launch_button.get_label() == "Install Steam"
    row.set_instance_state("running")
    assert row.launch_button.get_label() == "Stop player"
    row.set_instance_state("starting")
    assert row.launch_button.get_label() == "Cancel startup"


def test_toast_levels_replace_previous_styles_and_preserve_base_classes(window):
    """Real toast widgets retain their appearance and replace the previous message's level."""
    overlay = window.toast_overlay
    level_classes = {"toast-info", "toast-error", "toast-busy"}
    for level, css_class in (
        (ERROR, "toast-error"),
        (BUSY, "toast-busy"),
        (INFO, "toast-info"),
        ("unknown", "toast-info"),
    ):
        overlay.show_toast("Session update", level, timeout=0)
        assert overlay._icon.has_css_class("toast-icon")
        assert overlay._card.has_css_class("toast-card")
        assert set(overlay._card.get_css_classes()) & level_classes == {css_class}
        assert overlay._icon.get_icon_name() == ICONS.get(level, ICONS[INFO])
        assert overlay._label.get_text() == "Session update"
        assert overlay._revealer.get_reveal_child()


def test_surface_tokens_are_neutral_in_both_themes():
    """Chrome and field backgrounds use grayscale, independently of player accent colors."""
    stylesheet = (Path(__file__).resolve().parents[1] / "res/styles/style.css").read_text()
    colors = dict(re.findall(r"@define-color\s+([\w-]+)\s+([^;]+);", stylesheet))
    for name in ("studio_bg", "studio_surface", "studio_canvas", "studio_control", "studio_border"):
        for suffix in ("", "_light"):
            token = name + suffix
            assert token in colors, token
            color = Gdk.RGBA()
            assert color.parse(colors[token]), token
            assert color.red == pytest.approx(color.green)
            assert color.green == pytest.approx(color.blue)


def test_studio_stylesheet_parses():
    """Validate native GTK CSS rather than assuming browser-CSS compatibility."""
    errors = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _p, _s, error: errors.append(str(error)))
    provider.load_from_path(str(Path(__file__).resolve().parents[1] / "res/styles/style.css"))
    assert errors == []


def test_player_console_log_is_single_line_above_action_button(window):
    """Steam console output is shown in a single-line log strip directly above the button."""
    from gi.repository import Pango

    row = window.get_layout_page().player_rows[0]
    label = row.status_detail_label

    assert not hasattr(row, "update_bar")
    assert label.get_next_sibling() is row.launch_button
    assert label.get_single_line_mode() is True
    assert label.get_wrap() is False
    assert label.get_ellipsize() == Pango.EllipsizeMode.END
    assert not label.get_visible()

    row.set_update_progress("Downloading update (100 of 500 KB)...", 20)
    row.set_status_detail("Extracting package...")
    assert label.get_visible()
    assert label.get_text() == "Extracting package..."
    assert label.get_tooltip_text() == "Extracting package..."

    row.clear_update_progress()
    row.set_status_detail("")
    assert not label.get_visible()
