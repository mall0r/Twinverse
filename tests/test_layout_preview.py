"""Exercise the real GTK placement controls, their preview geometry and persistence."""

# flake8: noqa: E402

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from src.core.config import Config
from src.core.layout import LayoutCalculator
from src.gui.controllers.settings_controller import SettingsController
from src.gui.pages.layout_settings_page import LayoutSettingsPage
from src.models import Profile


@pytest.fixture
def page():
    """Build real controls when a display is available, including an Xvfb display."""
    if not Gtk.init_check():
        pytest.skip("A GTK display is required; run these tests under xvfb-run on headless systems")
    Adw.init()
    return LayoutSettingsPage()


@pytest.fixture
def devices():
    """Describe two named monitors with different aspect ratios."""
    return {
        "displays": [
            {"id": 0, "name": "HDMI-A-1", "width": 1920, "height": 1080},
            {"id": 1, "name": "DP-1", "width": 2560, "height": 1440},
        ]
    }


def test_loading_preview_does_not_emit_a_profile_change(page, devices):
    """Loading a saved custom layout must not trigger autosave or change the selection."""
    changes = []
    page.connect("settings-changed", lambda _page: changes.append(True))
    page.load_data(Profile(num_players=4, layout_order=[2, 0, 3, 1]), devices, {})
    assert changes == []
    assert page.placement_mode_row.get_selected() == 1
    assert page.layout_preview.instances == [2, 0, 3, 1]
    assert page.get_data()["layout_order"] == [2, 0, 3, 1]


def test_automatic_is_the_default_and_destinations_are_available_in_player_setup(page, devices):
    """Profiles stay automatic until a player is actually moved by dragging or selection."""
    page.load_data(Profile(num_players=4), devices, {})
    assert page.get_data()["layout_order"] is None
    assert page.layout_preview.instances == [0, 1, 2, 3]
    assert all(row.position_row.is_sensitive() for row in page.player_rows)


def test_selecting_an_instance_swaps_both_slots_and_emits_once(page, devices):
    """A user swap updates both selectors atomically without duplicate assignments."""
    page.load_data(Profile(num_players=4), devices, {})
    page.placement_mode_row.set_selected(1)
    changes = []
    page.connect("settings-changed", lambda _page: changes.append(True))
    page.player_rows[2].position_row.set_selected(0)
    assert page.get_data()["layout_order"] == [2, 1, 0, 3]
    assert [row.position_row.get_selected() for row in page.player_rows] == [2, 1, 0, 3]
    assert changes == [True]


def test_swapping_between_monitors_keeps_monitor_labels_and_unique_assignments(page, devices):
    """All visible slots share one assignment set, including slots on another monitor."""
    page.load_data(Profile(num_players=6), devices, {})
    page.placement_mode_row.set_selected(1)
    page.player_rows[5].position_row.set_selected(0)
    assert page.get_data()["layout_order"] == [5, 1, 2, 3, 4, 0]
    assert page.layout_preview.monitor_names == ["Monitor 1 · HDMI-A-1", "Monitor 2 · DP-1"]
    assert len(set(page.layout_preview.instances)) == 6


def test_unchecking_players_keeps_their_saved_order_but_removes_their_slots(page, devices):
    """A partial selection can be rearranged without losing hidden instance assignments."""
    page.load_data(Profile(num_players=4), devices, {})
    page.placement_mode_row.set_selected(1)
    page.player_rows[1].checkbox.set_active(False)
    page.player_rows[3].checkbox.set_active(False)
    assert page.layout_preview.instances == [0, 2]
    assert all(page.player_rows[index].position_row.get_model().get_n_items() == 2 for index in (0, 2))
    assert all(not page.player_rows[index].position_row.is_sensitive() for index in (1, 3))
    page.player_rows[2].position_row.set_selected(0)
    assert page.get_data()["layout_order"] == [2, 1, 0, 3]
    page.player_rows[1].checkbox.set_active(True)
    page.player_rows[3].checkbox.set_active(True)
    assert page.layout_preview.instances == [2, 1, 0, 3]


def test_no_selected_players_has_no_assignment_controls(page, devices):
    """An empty selection shows a helpful message instead of invalid dropdowns."""
    page.load_data(Profile(), devices, {})
    for row in page.player_rows:
        row.checkbox.set_active(False)
    assert page.layout_preview.instances == []
    assert page.layout_preview.slot_labels == []
    assert all(not row.position_row.is_sensitive() for row in page.player_rows)
    assert "Select at least one instance" in page.layout_preview.get_first_child().get_label()


def test_switching_back_to_automatic_restores_natural_placement(page, devices):
    """Automatic mode clears the saved custom override and updates the preview immediately."""
    page.load_data(Profile(num_players=4, layout_order=[2, 0, 3, 1]), devices, {})
    page.placement_mode_row.set_selected(0)
    assert page.get_data()["layout_order"] is None
    assert page.layout_preview.instances == [0, 1, 2, 3]


@pytest.mark.parametrize("count", [1, 2, 3, 4])
@pytest.mark.parametrize("orientation", ["horizontal", "vertical"])
def test_preview_spans_match_the_launcher_split_tables(page, devices, count, orientation):
    """The large three-player slot and all other previews must match actual layout geometry."""
    profile = Profile(num_players=count)
    profile.splitscreen.orientation = orientation
    page.load_data(profile, devices, {})
    xs, ys, widths, heights = LayoutCalculator.get_layout_coordinates(count, orientation)
    for slot, widgets in enumerate(page.layout_preview._slots):
        cell = widgets.cell
        grid = cell.get_parent()
        assert tuple(grid.query_child(cell)) == (
            round(xs[slot] * 2),
            round(ys[slot] * 2),
            round(widths[slot] * 2),
            round(heights[slot] * 2),
        )


def test_fullscreen_previews_one_slot_per_monitor_with_a_fallback_warning(page, devices):
    """Fullscreen slots identify their actual output, including the existing monitor fallback."""
    page.load_data(Profile(mode="fullscreen", num_players=3), devices, {})
    assert page.layout_preview.monitor_names == ["Monitor 1 · HDMI-A-1", "Monitor 2 · DP-1", "Monitor 1 · HDMI-A-1"]
    fallback = page.layout_preview.monitor_cards[-1]
    assert "No dedicated display" in fallback.get_first_child().get_next_sibling().get_label()


def test_monitor_rotation_is_reflected_in_the_preview_aspect_ratio(page, devices):
    """A portrait display must not be presented as a landscape monitor."""
    devices["displays"][0].update(width=1080, height=1920)
    page.load_data(Profile(), devices, {})
    frame = page.layout_preview.monitor_cards[0].get_last_child()
    assert frame.get_ratio() == pytest.approx(1080 / 1920)


def test_running_state_disables_placement_changes(page, devices):
    """Stop instances before allowing assignments and launch dimensions to change."""
    page.load_data(Profile(layout_order=[1, 0]), devices, {})
    page.set_screen_settings_sensitive(False)
    assert not page.placement_mode_row.is_sensitive()
    assert all(not row.position_row.is_sensitive() for row in page.player_rows)
    page.set_screen_settings_sensitive(True)
    assert all(row.position_row.is_sensitive() for row in page.player_rows)


def test_ui_order_round_trips_through_the_controller_and_profile(page, devices, monkeypatch, tmp_path):
    """Reopening the page restores the same assignments after saving the real UI data."""
    monkeypatch.setattr(Config, "get_profile_path", lambda: tmp_path / "profile.json")
    page.load_data(Profile(num_players=4), devices, {})
    page.placement_mode_row.set_selected(1)
    page.player_rows[3].position_row.set_selected(0)
    controller = SettingsController.__new__(SettingsController)
    controller._profile = Profile()
    controller.update_from_ui_data(page.get_data())
    controller.get_profile().save()
    page.load_data(Profile.load(), devices, {})
    assert page.layout_preview.instances == [3, 1, 2, 0]
    assert page.get_data()["layout_order"] == [3, 1, 2, 0]


def test_hidden_instance_assignments_survive_a_smaller_page(page, devices):
    """The UI retains off-page positions so increasing the count restores their custom order."""
    profile = Profile(num_players=2, layout_order=[3, 1, 2, 0])
    profile.player_configs = [*profile.player_configs, *Profile().player_configs]
    page.load_data(profile, devices, {})
    assert page.layout_preview.instances == [1, 0]
    assert page.get_data()["layout_order"] == [3, 1, 2, 0]


def test_saved_order_above_the_current_count_is_not_discarded(page, devices):
    """A saved position is preserved even when the hidden instance has no configuration row left."""
    page.load_data(Profile(num_players=2, layout_order=[3, 1, 2, 0]), devices, {})
    assert page.layout_preview.instances == [1, 0]
    assert page.get_data()["layout_order"] == [3, 1, 2, 0]
