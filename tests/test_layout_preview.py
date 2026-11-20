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
from src.models import PlayerInstanceConfig, Profile


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


def _walk_widgets(root):
    stack = [root]
    while stack:
        widget = stack.pop()
        yield widget
        child = widget.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()


def test_loading_preview_does_not_emit_a_profile_change(page, devices):
    """Loading a saved custom layout must not trigger autosave or change the selection."""
    changes = []
    page.connect("settings-changed", lambda _page: changes.append(True))
    page.load_data(Profile(num_players=4, layout_order=[2, 0, 3, 1]), devices, {})
    assert changes == []
    assert page.placement_mode_row.get_selected() == 1
    assert page.layout_preview.instances == [2, 0, 3, 1]
    assert page.get_data()["layout_order"] == [2, 0, 3, 1]


def test_automatic_is_the_default_and_repositioning_is_available_on_canvas(page, devices):
    """Profiles stay automatic until a player is actually moved on the canvas."""
    page.load_data(Profile(num_players=4), devices, {})
    assert page.get_data()["layout_order"] is None
    assert page.layout_preview.instances == [0, 1, 2, 3]
    assert page.layout_preview._allow_reposition
    assert all(not hasattr(row, "position_row") for row in page.player_rows)


def test_assigning_an_instance_swaps_both_slots_and_emits_once(page, devices):
    """A canvas swap updates both slots atomically without duplicate assignments."""
    page.load_data(Profile(num_players=4), devices, {})
    page.placement_mode_row.set_selected(1)
    changes = []
    page.connect("settings-changed", lambda _page: changes.append(True))
    assert page.layout_preview.assign_player(2, 0)
    assert page.get_data()["layout_order"] == [2, 1, 0, 3]
    assert page.layout_preview.instances == [2, 1, 0, 3]
    assert changes == [True]


def test_swapping_between_monitors_keeps_monitor_labels_and_unique_assignments(page, devices):
    """All visible slots share one assignment set, including slots on another monitor."""
    page.load_data(Profile(num_players=6), devices, {})
    page.placement_mode_row.set_selected(1)
    assert page.layout_preview.assign_player(5, 0)
    assert page.get_data()["layout_order"] == [5, 1, 2, 3, 4, 0]
    assert page.layout_preview.monitor_names == ["HDMI-A-1", "DP-1"]
    assert len(set(page.layout_preview.instances)) == 6


def test_unchecking_players_keeps_their_saved_order_but_removes_their_slots(page, devices):
    """A partial selection can be rearranged without losing hidden instance assignments."""
    page.load_data(Profile(num_players=4), devices, {})
    page.placement_mode_row.set_selected(1)
    page.player_rows[1].checkbox.set_active(False)
    page.player_rows[3].checkbox.set_active(False)
    assert page.layout_preview.instances == [0, 2]
    assert not page.layout_preview.assign_player(1, 0)
    assert page.layout_preview.assign_player(2, 0)
    assert page.get_data()["layout_order"] == [2, 1, 0, 3]
    page.player_rows[1].checkbox.set_active(True)
    page.player_rows[3].checkbox.set_active(True)
    assert page.layout_preview.instances == [2, 1, 0, 3]


def test_no_selected_players_shows_empty_canvas(page, devices):
    """An empty selection shows a helpful message and leaves no assignable slots."""
    page.load_data(Profile(), devices, {})
    for row in page.player_rows:
        row.checkbox.set_active(False)
    assert page.layout_preview.instances == []
    assert page.layout_preview.slot_labels == []
    assert not page.layout_preview.assign_player(0, 0)
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
    assert page.layout_preview.monitor_names == ["HDMI-A-1", "DP-1", "HDMI-A-1"]
    fallback = page.layout_preview.monitor_cards[-1]
    warning = fallback.get_first_child().get_next_sibling().get_label()
    assert "No dedicated display" in warning
    assert "HDMI-A-1" in warning


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
    assert not page.layout_preview._allow_reposition
    assert not page.layout_preview.assign_player(0, 0)
    page.set_screen_settings_sensitive(True)
    assert page.layout_preview._allow_reposition


def test_ui_order_round_trips_through_the_controller_and_profile(page, devices, monkeypatch, tmp_path):
    """Reopening the page restores the same assignments after saving the real UI data."""
    monkeypatch.setattr(Config, "get_profile_path", lambda: tmp_path / "profile.json")
    page.load_data(Profile(num_players=4), devices, {})
    page.placement_mode_row.set_selected(1)
    assert page.layout_preview.assign_player(3, 0)
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


def test_studio_header_and_roster_copy_are_minimal(page, devices):
    """Removed titles, subtitles, descriptions and the Live Layout icon stay absent."""
    page.load_data(Profile(), devices, {})
    labels = [w.get_label() for w in _walk_widgets(page) if isinstance(w, Gtk.Label)]
    assert "SESSION STUDIO" in labels
    assert "LIVE LAYOUT" in labels
    assert "A space for everyone." not in labels
    assert "Arrange your screens. Connect your players. Play together." not in labels
    assert "Choose who joins this session." not in labels
    assert "Display position" not in labels
    live_layout = next(w for w in _walk_widgets(page) if isinstance(w, Gtk.Label) and w.get_label() == "LIVE LAYOUT")
    assert live_layout.get_prev_sibling() is None


def test_direct_add_and_middle_player_removal_preserve_identities_and_roundtrip(page, devices, monkeypatch, tmp_path):
    """Removing a player from the middle keeps other players' homes, configs and order intact."""
    monkeypatch.setattr(Config, "get_profile_path", lambda: tmp_path / "profile.json")
    profile = Profile(
        num_players=3,
        player_configs=[
            PlayerInstanceConfig(GUEST_IP="192.168.1.10"),
            PlayerInstanceConfig(GUEST_IP="192.168.1.20"),
            PlayerInstanceConfig(GUEST_IP="192.168.1.30"),
        ],
    )
    page.load_data(profile, devices, {0: True, 1: False, 2: True})
    assert [row._player_num for row in page.player_rows] == [0, 1, 2]

    # Remove Player 2 (index 1) directly from the middle of the party.
    page._roster_remove_buttons[1].emit("clicked")
    assert [row._player_num for row in page.player_rows] == [0, 2]
    assert page.get_selected_players() == [0, 2]
    assert page.layout_preview.instances == [0, 2]
    data = page.get_data()
    assert data["num_players"] == 2
    assert data["party_players"] == [0, 2]
    assert data["player_configs"][0].guest_ip == "192.168.1.10"
    assert data["player_configs"][1].guest_ip == "192.168.1.20"
    assert data["player_configs"][2].guest_ip == "192.168.1.30"

    # Persist and reload from disk.
    controller = SettingsController.__new__(SettingsController)
    controller._profile = Profile()
    controller.update_from_ui_data(data)
    controller.get_profile().save()
    reloaded = Profile.load()
    assert reloaded.party_indices() == [0, 2]
    assert reloaded.launch_indices() == [0, 2]

    page.load_data(reloaded, devices, {0: True, 2: True})
    assert [row._player_num for row in page.player_rows] == [0, 2]
    assert page.get_player_row(2).get_config().guest_ip == "192.168.1.30"

    # Remove Player 1 -> only Player 3 remains, and its remove button becomes disabled.
    page._roster_remove_buttons[0].emit("clicked")
    assert [row._player_num for row in page.player_rows] == [2]
    assert not page._roster_remove_buttons[0].is_sensitive()
    assert not page.remove_player(2)

    # Add player brings back the first free slot with its saved settings intact.
    page.add_player_button.emit("clicked")
    assert [row._player_num for row in page.player_rows] == [0, 2]
    assert page.get_player_row(0).get_config().guest_ip == "192.168.1.10"
