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

from src.gui.notifications import BUSY, ERROR, INFO  # noqa: E402
from src.gui.pages.layout_settings_page import ROSTER_SIDEBAR_WIDTH  # noqa: E402
from src.gui.widgets.spinner import StudioSpinner  # noqa: E402
from src.gui.widgets.toast import LEVEL_TITLES, TOAST_ICONS  # noqa: E402
from src.gui.windows.main_window import MainWindow  # noqa: E402
from src.gui.windows.preferences_window import PreferencesWindow  # noqa: E402
from src.models import PlayerInstanceConfig, Profile  # noqa: E402


@pytest.fixture(scope="module")
def application(tmp_path_factory):
    """Compile current resources and use real GTK without starting any Steam clients."""
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
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

    window.show_idle_state()
    assert page.screen_mode_row.is_sensitive()
    assert page.placement_mode_row.is_sensitive()
    assert page.add_player_button.is_sensitive()
    assert all(btn.is_sensitive() for btn in page._roster_remove_buttons)
    assert page.layout_preview._allow_reposition
    assert page.layout_preview.assign_player(0, 1)


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
        assert isinstance(prefs.network_isolation_row, Gtk.Switch)
        assert prefs.network_isolation_row.get_active() is True
        prefs.gamescope_row.set_active(False)
        changed.assert_called_with("use_gamescope", False)
        prefs.network_isolation_row.set_active(False)
        changed.assert_called_with("isolate_network", False)
        assert prefs._profile.isolate_network is False
        prefs._on_reset_clicked(None)
        assert prefs._profile.isolate_network is True
        assert prefs.network_isolation_row.get_active() is True
        assert prefs._instance_list_box.get_row_at_index(0) is None
        (tmp_path / "0").mkdir()
        prefs._populate_player_list()
        assert prefs._instance_list_box.get_row_at_index(0) is not None
        assert prefs._instance_list_box.get_row_at_index(1) is None
    finally:
        prefs.destroy()


def test_disabling_network_isolation_disables_guest_ip_but_preserves_value(window):
    """Turning off network isolation grays out Guest IP without discarding saved addresses."""
    page = window.get_layout_page()
    row = page.player_rows[0]
    row.guest_ip_row.set_text("192.168.1.55")
    assert row.guest_ip_row.get_sensitive() is True

    page.set_network_isolation_enabled(False)
    assert row.guest_ip_row.get_sensitive() is False
    assert row.get_config().guest_ip == "192.168.1.55"

    page.set_network_isolation_enabled(True)
    assert row.guest_ip_row.get_sensitive() is True
    assert row.get_config().guest_ip == "192.168.1.55"


def test_roster_numbers_are_centered_in_fixed_size_badges(window):
    """Numeric labels must not inherit the left alignment used by general UI text."""
    for item in window.get_layout_page()._roster_rows:
        badge = item.get_child().get_first_child()
        assert badge.get_xalign() == 0.5
        assert badge.get_yalign() == 0.5
        assert badge.get_valign() == Gtk.Align.CENTER
        assert badge.get_size_request() == (36, 36)


def test_inspector_starts_hidden_by_default_and_toggle_follows_visibility(window):
    """Player Setup starts hidden without resizing the window, while the roster stays open."""
    page = window.get_layout_page()
    assert not hasattr(window, "roster_toggle")
    assert not hasattr(page, "roster_split")
    assert page.roster_sidebar.get_visible()
    assert tuple(window.get_default_size()) == (1080, 720)
    split, button = page.inspector_split, window.inspector_toggle
    assert not split.get_show_sidebar()
    assert not button.get_active()
    assert button.get_tooltip_text().startswith("Show ")
    button.set_active(True)
    assert split.get_show_sidebar()
    assert button.get_tooltip_text().startswith("Hide ")
    split.set_show_sidebar(False)
    assert not button.get_active()


def test_roster_sidebar_width_never_grows_across_player_counts_and_states(window):
    """The left party sidebar must remain locked at its fixed width regardless of party size or status text."""
    page = window.get_layout_page()
    displays = {"displays": [{"name": "HDMI-A-1", "width": 1920, "height": 1080}]}
    expected = (ROSTER_SIDEBAR_WIDTH, ROSTER_SIDEBAR_WIDTH)

    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected

    # A long custom player name must ellipsize rather than widening the roster.
    page.player_rows[0].start_name_edit()
    page.player_rows[0].name_entry.set_text("VeryLongCustomPlayerDisplayName32")
    page.player_rows[0].commit_name_edit()
    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected

    # Adding a 3rd player (unverified) triggers the longer setup summary string.
    page.add_player_button.emit("clicked")
    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected

    page.load_data(Profile(num_players=3), displays, {0: True, 1: True, 2: True})
    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected

    page.load_data(Profile(num_players=8), displays, {index: index < 4 for index in range(8)})
    page.player_rows[0].set_update_progress("Updating Steam...", 100)
    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected

    window.show_launching_state()
    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected

    window.show_running_state()
    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected

    window.show_stopping_state()
    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected

    window.show_idle_state()
    for row in page.player_rows:
        row.checkbox.set_active(False)
    assert page.roster_sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[:2] == expected


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
    """Shortcuts must toggle the inspector in both directions; no roster hide action exists."""
    page = window.get_layout_page()
    assert window.lookup_action("players") is None
    split = page.inspector_split
    split.set_show_sidebar(False)
    action = window.lookup_action("inspector")
    action.activate(None)
    assert split.get_show_sidebar()
    action.activate(None)
    assert not split.get_show_sidebar()


def test_header_has_only_left_aligned_tools_and_inspector_toggle_sits_on_stage_header(application, monkeypatch):
    """The header bar keeps theme/menu on the left; Player Setup toggle aligns with SESSION LAYOUT."""
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
        page = win.get_layout_page()
        assert packed == [(header, "start", win.header_tools)]
        assert isinstance(header.get_title_widget(), Gtk.Box)
        assert header.get_title_widget().get_first_child() is None
        assert not hasattr(win, "roster_toggle")
        assert win.header_tools.get_first_child() is win.theme_toggle_button
        assert win.theme_toggle_button.get_next_sibling() is win.menu_button
        assert win.header_tools.get_last_child() is win.menu_button
        assert win.inspector_toggle.get_parent() is page.stage_header
        assert page.stage_header.get_last_child() is win.inspector_toggle
        title_box = page.stage_header.get_first_child()
        assert title_box.get_first_child().get_label() == "SESSION LAYOUT"
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
    assert window.inspector_toggle.get_parent() is page.stage_header
    assert page.stage_header.get_last_child() is window.inspector_toggle
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


def test_controls_section_has_right_aligned_icon_only_refresh_button(window):
    """The Controls header appears once and exposes a compact icon-only refresh button on the right side."""
    row = window.get_layout_page().player_rows[0]
    button = row.refresh_controllers_button
    heading = button.get_parent()
    title = button.get_prev_sibling()

    labels = []

    def collect_labels(widget):
        if isinstance(widget, Gtk.Label):
            labels.append(widget.get_text())
        child = widget.get_first_child()
        while child is not None:
            collect_labels(child)
            child = child.get_next_sibling()

    collect_labels(row)
    assert labels.count("Controls") == 1

    assert button.get_icon_name() == "twinverse-refresh-symbolic"
    assert button.get_label() is None
    assert button.has_css_class("inspector-refresh-button")
    assert heading.has_css_class("inspector-section-heading")
    assert heading.get_last_child() is button
    assert isinstance(title, Gtk.Label)
    assert title.get_text() == "Controls"
    assert title.get_hexpand() is True

    button.emit("clicked")
    window._presenter.on_devices_refresh_requested.assert_called_once_with()


def test_toast_levels_replace_previous_styles_and_preserve_base_classes(window):
    """Remodeled studio toast preserves classes, shows custom icons/titles and supports dismiss."""
    overlay = window.toast_overlay
    level_classes = {"toast-info", "toast-error", "toast-busy"}
    for level, css_class in (
        (ERROR, "toast-error"),
        (BUSY, "toast-busy"),
        (INFO, "toast-info"),
        ("unknown", "toast-info"),
    ):
        overlay.show_toast("Session update", level, timeout=0)
        assert overlay._badge.has_css_class("toast-badge")
        assert overlay._icon.has_css_class("toast-icon")
        assert overlay._title.has_css_class("toast-title")
        assert overlay._card.has_css_class("toast-card")
        assert overlay._dismiss_button.has_css_class("toast-dismiss")
        assert overlay._dismiss_button.get_icon_name() == "twinverse-close-symbolic"
        assert set(overlay._card.get_css_classes()) & level_classes == {css_class}
        assert overlay._icon.get_icon_name() == TOAST_ICONS.get(level, TOAST_ICONS[INFO])
        assert overlay._title.get_text() == LEVEL_TITLES.get(level, LEVEL_TITLES[INFO])
        assert overlay._label.get_text() == "Session update"
        assert overlay._revealer.get_reveal_child()
    overlay._dismiss_button.emit("clicked")
    assert not overlay._revealer.get_reveal_child()


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


def test_light_theme_tokens_and_player_cards_meet_wcag_aa_contrast():
    """Light mode text, semantic statuses, controls and all 8 player cards meet WCAG AA contrast."""
    stylesheet = (Path(__file__).resolve().parents[1] / "res/styles/style.css").read_text()
    tokens = dict(re.findall(r"@define-color\s+([\w-]+)\s+(#[0-9a-fA-F]{6});", stylesheet))

    def luminance(hex_color: str) -> float:
        rgb = [int(hex_color[i : i + 2], 16) / 255.0 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def contrast(first: str, second: str) -> float:
        l1, l2 = luminance(first), luminance(second)
        return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

    for fg_key in ("studio_fg_light", "studio_secondary_light", "studio_muted_light", "layout_accent_light"):
        for bg_key in ("studio_bg_light", "studio_surface_light", "studio_canvas_light"):
            assert contrast(tokens[fg_key], tokens[bg_key]) >= 4.5, f"{fg_key} on {bg_key}"

    for semantic_key in ("studio_success_light", "studio_warning_light", "studio_danger_light"):
        assert contrast(tokens[semantic_key], tokens["studio_surface_light"]) >= 4.5, semantic_key
        assert contrast(tokens[semantic_key], tokens["studio_bg_light"]) >= 4.5, semantic_key

    assert contrast(tokens["studio_control_border_light"], tokens["studio_surface_light"]) >= 3.0

    for index in range(8):
        card_match = re.search(
            rf"\.light \.slot-button\.player-color-{index}\s*\{{[^}}]*background:\s*(#[0-9a-fA-F]{{6}});[^}}]*(?<!-)color:\s*(#[0-9a-fA-F]{{6}});",
            stylesheet,
        )
        assert card_match is not None, f"Missing light slot-button player-color-{index}"
        card_bg, card_fg = card_match.groups()
        assert contrast(card_fg, card_bg) >= 7.0, f"player-color-{index} slot text"

        num_match = re.search(
            rf"\.light \.slot-button\.player-color-{index}\s+\.slot-number\s*\{{[^}}]*(?<!-)color:\s*(#[0-9a-fA-F]{{6}});",
            stylesheet,
        )
        assert num_match is not None, f"Missing light slot-number player-color-{index}"
        assert contrast(num_match.group(1), card_bg) >= 4.5, f"player-color-{index} slot number"

        avatar_match = re.search(
            rf"\.light \.party-avatar\.player-color-{index}\s*\{{[^}}]*background:\s*(#[0-9a-fA-F]{{6}});[^}}]*(?<!-)color:\s*(#[0-9a-fA-F]{{6}});",
            stylesheet,
        )
        assert avatar_match is not None, f"Missing light party-avatar player-color-{index}"
        assert contrast(avatar_match.group(2), avatar_match.group(1)) >= 4.5, f"player-color-{index} avatar"


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


def test_spinners_use_studio_spinner_and_survive_hiding_player_setup(window):
    """Spinners use StudioSpinner so hiding Player Setup never freezes animation."""
    page = window.get_layout_page()
    row = page.player_rows[0]
    assert isinstance(row.status_spinner, StudioSpinner)
    assert isinstance(window.launch_spinner, StudioSpinner)

    page.select_player(0, open_inspector=True)
    row.set_instance_state("starting")
    row.set_update_progress("Downloading Steam...", 30)
    assert row.status_spinner.get_spinning()
    assert row.status_spinner.get_visible()
    assert row.status_spinner._inner.get_visible()

    page.inspector_split.set_show_sidebar(False)
    row.set_update_progress("Downloading Steam...", 60)
    page.inspector_split.set_show_sidebar(True)
    assert row.status_spinner.get_spinning()
    assert row.status_spinner.get_visible()
    assert row.status_spinner._inner.get_visible()

    row.clear_update_progress()
    row.set_instance_state("idle")
    assert not row.status_spinner.get_spinning()
    assert not row.status_spinner._inner.get_visible()


def test_all_studio_icons_are_bundled_symbolic_assets(window):
    """Every symbolic icon referenced in src/gui resolves from Twinverse's GResource bundle."""
    display_theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    assert "/io/github/mall0r/Twinverse/icons" in display_theme.get_resource_path()
    theme = Gtk.IconTheme.new()
    theme.set_search_path([])
    theme.set_resource_path(["/io/github/mall0r/Twinverse/icons"])
    gui_root = Path(__file__).resolve().parents[1] / "src/gui"
    pattern = re.compile(r'"([a-z0-9-]+-symbolic)"')
    icon_names = {
        match.group(1)
        for path in gui_root.rglob("*.py")
        if path.name != "notifications.py"
        for match in pattern.finditer(path.read_text())
    }
    assert icon_names
    for name in sorted(icon_names):
        assert theme.has_icon(name), name
        paintable = theme.lookup_icon(name, None, 16, 1, Gtk.TextDirection.LTR, 0)
        uri = paintable.get_file().get_uri() if paintable.get_file() else ""
        assert uri.startswith("resource:///io/github/mall0r/Twinverse/icons/"), f"{name}: {uri}"
        assert uri.endswith("-symbolic.svg"), f"{name} must resolve to a symbolic SVG ({uri})"


def test_opening_player_setup_in_light_mode_does_not_shift_session_layout(window):
    """Toggling Player Setup in light mode must not change header or stage dimensions."""
    page = window.get_layout_page()
    style = Adw.StyleManager.get_default()
    previous_scheme = style.get_color_scheme()
    try:
        style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        page.inspector_split.set_show_sidebar(False)
        closed_toggle = (
            window.inspector_toggle.measure(Gtk.Orientation.HORIZONTAL, -1)[:2],
            window.inspector_toggle.measure(Gtk.Orientation.VERTICAL, -1)[:2],
        )
        closed_header = page.stage_header.measure(Gtk.Orientation.VERTICAL, -1)[:2]

        page.inspector_split.set_show_sidebar(True)
        open_toggle = (
            window.inspector_toggle.measure(Gtk.Orientation.HORIZONTAL, -1)[:2],
            window.inspector_toggle.measure(Gtk.Orientation.VERTICAL, -1)[:2],
        )
        open_header = page.stage_header.measure(Gtk.Orientation.VERTICAL, -1)[:2]

        assert open_toggle == closed_toggle
        assert open_header == closed_header
    finally:
        style.set_color_scheme(previous_scheme)


def test_disconnected_controllers_are_remembered_across_refresh_reconnect_and_clear(window):
    """Remembered controllers persist while unplugged, reconnect cleanly, and clear only on explicit change."""
    page = window.get_layout_page()
    displays = [{"name": "HDMI-A-1", "width": 1920, "height": 1080}]
    pad_id = "/dev/input/by-id/usb-xbox_pad-event-joystick"
    other_pad_id = "/dev/input/by-id/usb-dualsense_pad-event-joystick"

    # Legacy profile with only PHYSICAL_DEVICE_ID derives a clean readable name (never raw path).
    profile = Profile(
        num_players=2,
        PLAYERS=[
            PlayerInstanceConfig(PHYSICAL_DEVICE_ID=pad_id),
            PlayerInstanceConfig(),
        ],
    )
    page.load_data(profile, {"displays": displays, "joystick": [], "audio": []}, {0: True, 1: True})
    row = page.player_rows[0]
    icon = page.layout_preview._slots[0].controller_icon
    model = row.joystick_row.get_model()
    labels = [model.get_string(i) for i in range(model.get_n_items())]
    assert labels == ["None", "Xbox Pad (Disconnected)"]
    assert row.joystick_row.get_selected() == 1
    assert row.has_controller_selected()
    assert not row.is_controller_connected()
    assert row.joystick_row.has_css_class("controller-disconnected")
    assert row.get_config().physical_device_id == pad_id
    assert icon.get_visible()
    assert icon.has_css_class("slot-controller-disconnected")
    assert icon.get_tooltip_text() == "Xbox Pad (Disconnected)"

    # Refreshing while still unplugged keeps the remembered entry without duplicating suffixes.
    page.update_devices_info({"displays": displays, "joystick": [], "audio": []})
    model = row.joystick_row.get_model()
    assert [model.get_string(i) for i in range(model.get_n_items())] == ["None", "Xbox Pad (Disconnected)"]
    assert row.joystick_row.get_selected() == 1
    assert row.get_config().physical_device_id == pad_id

    # Reconnecting the same controller resolves to the live connected entry without duplicates.
    connected = [{"id": pad_id, "name": "Xbox Wireless Controller"}]
    page.update_devices_info({"displays": displays, "joystick": connected, "audio": []})
    model = row.joystick_row.get_model()
    assert [model.get_string(i) for i in range(model.get_n_items())] == ["None", "Xbox Wireless Controller"]
    assert row.joystick_row.get_selected() == 1
    assert row.has_controller_selected()
    assert row.is_controller_connected()
    assert not row.joystick_row.has_css_class("controller-disconnected")
    assert icon.get_visible()
    assert not icon.has_css_class("slot-controller-disconnected")
    assert icon.get_tooltip_text() == "Xbox Wireless Controller"

    # Turning the controller off remembers its friendly name and dims the badge.
    page.update_devices_info({"displays": displays, "joystick": [], "audio": []})
    model = row.joystick_row.get_model()
    assert [model.get_string(i) for i in range(model.get_n_items())] == [
        "None",
        "Xbox Wireless Controller (Disconnected)",
    ]
    assert row.joystick_row.get_selected() == 1
    assert row.has_controller_selected()
    assert not row.is_controller_connected()
    assert row.joystick_row.has_css_class("controller-disconnected")
    saved_cfg = row.get_config()
    assert saved_cfg.physical_device_id == pad_id
    assert saved_cfg.physical_device_name == "Xbox Wireless Controller"
    assert page.get_data()["player_configs"][0].physical_device_id == pad_id
    assert icon.get_visible()
    assert icon.has_css_class("slot-controller-disconnected")
    assert icon.get_tooltip_text() == "Xbox Wireless Controller (Disconnected)"

    # Selecting a different connected controller replaces the remembered entry and prunes the stale one.
    other_connected = [{"id": other_pad_id, "name": "DualSense Controller"}]
    page.update_devices_info({"displays": displays, "joystick": other_connected, "audio": []})
    model = row.joystick_row.get_model()
    assert [model.get_string(i) for i in range(model.get_n_items())] == [
        "None",
        "DualSense Controller",
        "Xbox Wireless Controller (Disconnected)",
    ]
    assert row.joystick_row.get_selected() == 2
    row.joystick_row.set_selected(1)
    model = row.joystick_row.get_model()
    assert [model.get_string(i) for i in range(model.get_n_items())] == ["None", "DualSense Controller"]
    assert row.is_controller_connected()
    assert row.get_config().physical_device_id == other_pad_id
    assert row.get_config().physical_device_name == "DualSense Controller"

    # Unplugging again and explicitly choosing None clears the assignment permanently.
    page.update_devices_info({"displays": displays, "joystick": [], "audio": []})
    assert row.joystick_row.get_selected() == 1
    row.joystick_row.set_selected(0)
    model = row.joystick_row.get_model()
    assert [model.get_string(i) for i in range(model.get_n_items())] == ["None"]
    assert not row.has_controller_selected()
    assert not row.is_controller_connected()
    assert not row.joystick_row.has_css_class("controller-disconnected")
    assert row.get_config().physical_device_id is None
    assert row.get_config().physical_device_name is None
    assert not icon.get_visible()
