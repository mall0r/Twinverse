"""Session Layout: a party roster, an interactive stage and a focused inspector."""

# flake8: noqa: E402

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk, Pango  # noqa: E402

from src.core.layout import LayoutCalculator
from src.core.tiling import TEMPLATES, build_tiling_plan
from src.gui.widgets import LayoutPreview, PlayerRow
from src.gui.widgets.player_row import INSTANCE_IDLE
from src.models import DEFAULT_PLAYER_NAME, PlayerInstanceConfig

ROSTER_SIDEBAR_WIDTH = 244


class LayoutSettingsPage(Gtk.Box):
    """Coordinate the studio widgets while retaining the launcher's data contract."""

    __gsignals__ = {
        "settings-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "verification-completed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "instance-launch-requested": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "devices-refresh-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "summary-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, **kwargs):
        """Build a new studio, not a preferences page."""
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, **kwargs)
        self._is_loading = False
        self._applying_exclusivity = False
        self._syncing_roster_selection = False
        self._num_monitors = 1
        self._max_players = 8
        self._party_controls_sensitive = True
        self._last_user_selected_mode = None
        self._layout_order = []
        self._monitor_layouts = {}
        self._tiling_plan = None
        self._known_instance_count = 0
        self._devices_info = {}
        self._displays = []
        self._active_player = 0
        self._screen_settings_sensitive = True
        self._gamescope_enabled = True
        self._preview_signature = None
        self._preview_geometry = None
        self._drag_scroll_id = 0
        self._drag_scroll_drop = None
        self._drag_scroll_step = 0
        self._party_players = []
        self._saved_player_configs = {}
        self._verification_statuses = {}
        self.player_rows = []
        self._roster_rows = []
        self._roster_names = []
        self._roster_status = []
        self._roster_remove_buttons = []
        self.add_css_class("studio-workspace")
        self._build_ui()
        self.connect("unmap", lambda *_: self._stop_drag_scrolling())

    @staticmethod
    def _label(text, style, **kwargs):
        label = Gtk.Label(label=text, xalign=0, **kwargs)
        label.add_css_class(style)
        return label

    def _build_ui(self):
        self.roster_sidebar = Adw.Clamp(
            maximum_size=ROSTER_SIDEBAR_WIDTH,
            tightening_threshold=ROSTER_SIDEBAR_WIDTH,
            hexpand=False,
            vexpand=True,
        )
        self.roster_sidebar.set_size_request(ROSTER_SIDEBAR_WIDTH, -1)
        self.roster_sidebar.set_child(self._build_roster())
        self.append(self.roster_sidebar)

        self.inspector_split = Adw.OverlaySplitView(
            sidebar_position=Gtk.PackType.END,
            show_sidebar=False,
            min_sidebar_width=324,
            max_sidebar_width=344,
            sidebar_width_fraction=0.3,
            hexpand=True,
            vexpand=True,
        )
        self.append(self.inspector_split)
        self.inspector_split.set_content(self._build_stage())
        self.inspector_split.set_sidebar(self._build_inspector())

    def _build_roster(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20, hexpand=False, vexpand=True)
        sidebar.add_css_class("party-sidebar")
        heading = Gtk.Box(spacing=8)
        heading.append(self._label("Your party", "party-heading", hexpand=True))

        sidebar.append(heading)

        self.roster = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.roster.add_css_class("party-list")
        self.roster.connect("row-selected", self._on_roster_selection_changed)
        self.roster.connect("row-activated", self._on_roster_selected)
        scroll = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_width=False,
            vexpand=True,
        )
        scroll.set_child(self.roster)
        sidebar.append(scroll)

        self.add_player_button = Gtk.Button(hexpand=True)
        self.add_player_button.set_child(Adw.ButtonContent(icon_name="twinverse-add-symbolic", label="Add player"))
        self.add_player_button.set_tooltip_text("Add a player to the party")
        self.add_player_button.update_property([Gtk.AccessibleProperty.LABEL], ["Add player"])
        self.add_player_button.add_css_class("party-add-button")
        self.add_player_button.connect("clicked", self._on_add_player_clicked)
        sidebar.append(self.add_player_button)
        sidebar.append(Gtk.Separator())

        self.session_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.session_controls.add_css_class("party-session-status")
        sidebar.append(self.session_controls)
        return sidebar

    def _build_stage(self):
        studio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        studio.add_css_class("studio-stage")
        self.stage_header = Gtk.Box(spacing=16)
        self.stage_header.add_css_class("stage-header")
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True, valign=Gtk.Align.CENTER)
        titles.append(self._label("SESSION LAYOUT", "eyebrow"))
        self.stage_header.append(titles)

        studio.append(self.stage_header)

        canvas_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, vexpand=True)
        canvas_box.add_css_class("stage-surface")
        canvas_heading = Gtk.Box(spacing=8)
        self.display_summary = self._label("Detecting displays", "canvas-display-count")
        canvas_heading.append(self.display_summary)
        canvas_box.append(canvas_heading)
        self.layout_preview = LayoutPreview()
        self.layout_preview.connect("order-changed", self._on_layout_order_changed)
        self.layout_preview.connect("template-selected", self._on_monitor_template_selected)
        self.layout_preview.connect("player-activated", lambda _w, index: self.select_player(index))
        self.layout_preview_group = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.layout_preview_group.set_child(self.layout_preview)
        drag_motion = Gtk.DropControllerMotion()
        drag_motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        drag_motion.connect("enter", self._on_canvas_drag_motion)
        drag_motion.connect("motion", self._on_canvas_drag_motion)
        drag_motion.connect("leave", lambda *_: self._stop_drag_scrolling())
        self.layout_preview_group.add_controller(drag_motion)
        canvas_box.append(self.layout_preview_group)

        self.displays_disabled_group = Adw.StatusPage(
            title="Direct Steam mode",
            icon_name="twinverse-window-symbolic",
            description="Players run in independent windows. Enable Gamescope in Preferences to arrange a split-screen session.",
            vexpand=True,
        )
        self.displays_disabled_group.set_visible(False)
        canvas_box.append(self.displays_disabled_group)
        hint = Gtk.Box(spacing=8)
        hint.append(Gtk.Image(icon_name="mouse-wireless-symbolic"))
        hint.append(
            self._label(
                "Drag players between spaces to swap them.",
                "canvas-hint",
                wrap=True,
            )
        )
        canvas_box.append(hint)
        studio.append(canvas_box)

        self.gamescope_settings_group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16, homogeneous=True)
        self.gamescope_settings_group.add_css_class("layout-dock")
        self.screen_modes = ["Fullscreen", "Splitscreen"]
        self.orientations = ["Horizontal", "Vertical"]
        self.screen_mode_row = Gtk.DropDown(model=Gtk.StringList.new(self.screen_modes))
        self.orientation_row = Gtk.DropDown(model=Gtk.StringList.new(self.orientations))
        self.placement_mode_row = Gtk.DropDown(model=Gtk.StringList.new(["Automatic", "Custom"]))
        # Retain legacy values for profile migration; templates are chosen on each monitor.
        self.orientation_field = self._field("SPLIT DIRECTION", self.orientation_row)
        self.gamescope_settings_group.append(self._field("PLACEMENT", self.placement_mode_row))
        self.screen_mode_row.connect("notify::selected", self._on_screen_mode_changed)
        self.orientation_row.connect("notify::selected", self._on_setting_changed)
        self.placement_mode_row.connect("notify::selected", self._on_setting_changed)
        studio.append(self.gamescope_settings_group)
        return studio

    @staticmethod
    def _drag_scroll_delta(y, height):
        if height <= 0 or y < 0 or y > height:
            return 0
        edge = min(56, height / 4)
        if y < edge:
            return -max(3, 16 * (edge - y) / edge)
        if y > height - edge:
            return max(3, 16 * (y - height + edge) / edge)
        return 0

    def _on_canvas_drag_motion(self, controller, _x, y):
        drop = controller.get_drop()
        step = self._drag_scroll_delta(y, self.layout_preview_group.get_height())
        if not step or not self.layout_preview.is_player_drag(drop):
            self._stop_drag_scrolling()
            return
        self._drag_scroll_drop = drop
        self._drag_scroll_step = step
        if not self._drag_scroll_id:
            self._drag_scroll_id = GLib.timeout_add(30, self._scroll_canvas_for_drag)

    def _scroll_canvas_for_drag(self):
        if not self.layout_preview_group.get_mapped() or not self.layout_preview.is_player_drag(self._drag_scroll_drop):
            self._drag_scroll_id = 0
            self._drag_scroll_drop = None
            self._drag_scroll_step = 0
            return GLib.SOURCE_REMOVE
        adjustment = self.layout_preview_group.get_vadjustment()
        upper = max(adjustment.get_lower(), adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(max(adjustment.get_lower(), min(upper, adjustment.get_value() + self._drag_scroll_step)))
        return GLib.SOURCE_CONTINUE

    def _stop_drag_scrolling(self):
        if self._drag_scroll_id:
            GLib.source_remove(self._drag_scroll_id)
        self._drag_scroll_id = 0
        self._drag_scroll_drop = None
        self._drag_scroll_step = 0

    def _field(self, title, control):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._label(title, "dock-label"))
        control.add_css_class("dock-select")
        control.set_hexpand(True)
        control.update_property([Gtk.AccessibleProperty.LABEL], [title.capitalize()])
        box.append(control)
        return box

    def _build_inspector(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        panel.add_css_class("player-panel")
        heading = Gtk.Box(spacing=8)
        heading.add_css_class("panel-heading")
        heading.append(self._label("PLAYER SETUP", "eyebrow", hexpand=True))

        panel.append(heading)
        self.inspector_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroller.set_child(self.inspector_stack)
        panel.append(scroller)
        return panel

    def _player_position(self, instance_num):
        try:
            return self._party_players.index(instance_num)
        except ValueError:
            return None

    def get_player_row(self, instance_num):
        """Return the inspector row for a zero-based instance ID, or None."""
        pos = self._player_position(instance_num)
        if pos is None:
            return None
        return self.player_rows[pos]

    def select_player(self, index, open_inspector=True):
        """Inspect a player without changing their participation in the session."""
        pos = self._player_position(index)
        if pos is None:
            return
        self._active_player = index
        self.inspector_stack.set_visible_child_name(str(index))
        row = self._roster_rows[pos]
        if self.roster.get_selected_row() != row:
            self._syncing_roster_selection = True
            try:
                self.roster.select_row(row)
            finally:
                self._syncing_roster_selection = False
        self.layout_preview.set_active_player(index)
        if open_inspector:
            self.inspector_split.set_show_sidebar(True)

    def _on_roster_selection_changed(self, _list, row):
        if row is not None and not self._is_loading and not self._syncing_roster_selection:
            pos = row.get_index()
            if 0 <= pos < len(self._party_players):
                self.select_player(self._party_players[pos], open_inspector=False)

    def _on_roster_selected(self, _list, row):
        if (
            row is not None
            and not self._is_loading
            and not self._syncing_roster_selection
            and not self.layout_preview._suppress_activation
        ):
            pos = row.get_index()
            if 0 <= pos < len(self._party_players):
                self.select_player(self._party_players[pos])

    def load_data(self, profile, devices_info, verification_statuses):
        """Restore saved assignments without emitting edits or resetting the active player."""
        self._is_loading = True
        self._devices_info = {kind: list(items) for kind, items in devices_info.items()}
        self._displays = sorted(devices_info.get("displays", []), key=lambda display: display.get("id", 0))
        self._num_monitors = max(1, len(self._displays))
        self._monitor_layouts = {key: config.model_dump() for key, config in profile.monitor_layouts.items()}
        party = profile.party_indices() or [0]
        self._saved_player_configs = {
            index: config.model_copy(deep=True) for index, config in enumerate(profile.player_configs)
        }
        self._verification_statuses = dict(verification_statuses)
        saved_instances = [index + 1 for index in profile.layout_order or []]
        self._known_instance_count = max(
            profile.num_players, len(profile.player_configs), *(index + 1 for index in party), *saved_instances, 0
        )
        self._layout_order = LayoutCalculator.order_instances(
            list(range(self._known_instance_count)), profile.layout_order
        )
        self.placement_mode_row.set_selected(0 if profile.layout_order is None else 1)
        is_split = (self._last_user_selected_mode or profile.mode) == "splitscreen"
        self.screen_mode_row.set_selected(1 if is_split else 0)
        self._update_num_players_limits(is_split)
        self.orientation_field.set_visible(is_split)
        self.orientation_row.set_visible(is_split)
        self.set_gamescope_enabled(profile.use_gamescope)
        if is_split and profile.splitscreen:
            self.orientation_row.set_selected(self.orientations.index(profile.splitscreen.orientation.capitalize()))
        self.rebuild_player_rows(party, devices_info)
        selected = set(profile.selected_players) if profile.selected_players else set(self._party_players)
        for row in self.player_rows:
            instance_num = row._player_num
            if instance_num < len(profile.player_configs):
                row.load_config(profile.player_configs[instance_num])
            row.set_selected(instance_num in selected)
            row.set_verification_status(self._verification_statuses.get(instance_num, False))
        self._apply_grab_input_exclusivity()
        self._is_loading = False
        active = self._active_player if self._active_player in self._party_players else self._party_players[0]
        self.select_player(active, open_inspector=False)
        self._preview_signature = None
        self._update_layout_preview()
        self._sync_roster()

    def _create_player_entry(self, instance_num, devices_info):
        """Build an inspector row and its paired roster entry for one instance ID."""
        player = PlayerRow(instance_num, devices_info)
        player.set_parent_page(self)
        player.connect("settings-changed", self._on_setting_changed)
        player.connect("launch-clicked", lambda _w, number: self.emit("instance-launch-requested", number))
        player.connect("refresh-devices-requested", lambda *_: self.emit("devices-refresh-requested"))
        player.connect("status-changed", lambda *_: self._sync_roster())

        item = Gtk.ListBoxRow()
        item.add_css_class("party-player")
        item.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"Configure {player.get_player_name()} {instance_num + 1:02d}"]
        )
        body = Gtk.Box(spacing=8)
        number = Gtk.Label(label=f"{instance_num + 1:02d}", xalign=0.5, yalign=0.5, valign=Gtk.Align.CENTER)
        number.set_size_request(36, 36)
        number.add_css_class("party-avatar")
        number.add_css_class(f"player-color-{instance_num % 8}")
        body.append(number)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        name_label = self._label(player.get_player_name(), "party-player-name")
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.set_max_width_chars(14)
        text.append(name_label)
        status = self._label("Not installed", "party-player-status")
        status.set_ellipsize(Pango.EllipsizeMode.END)
        status.set_max_width_chars(17)
        text.append(status)
        body.append(text)

        actions = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        player.checkbox.set_valign(Gtk.Align.CENTER)
        actions.append(player.checkbox)
        remove_button = Gtk.Button(icon_name="twinverse-close-symbolic", valign=Gtk.Align.CENTER)
        remove_button.add_css_class("flat")
        remove_button.add_css_class("party-remove-button")
        remove_button.set_tooltip_text(f"Remove {player.get_player_name()} ({instance_num + 1:02d}) from party")
        remove_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [f"Remove {player.get_player_name()} {instance_num + 1:02d}"]
        )
        remove_button.connect("clicked", lambda _btn, num=instance_num: self.remove_player(num))
        actions.append(remove_button)
        body.append(actions)

        item.set_child(body)
        self.layout_preview.add_player_drag_source(item, instance_num)
        return player, item, name_label, status, remove_button

    def rebuild_player_rows(self, players, devices_info):
        """Replace roster entries and inspectors, releasing old progress timers."""
        party = list(range(players)) if isinstance(players, int) else list(players)
        for row in self.player_rows:
            row.clear_update_progress()
            self.inspector_stack.remove(row)
        while child := self.roster.get_first_child():
            self.roster.remove(child)
        self._party_players = []
        self.player_rows = []
        self._roster_rows = []
        self._roster_names = []
        self._roster_status = []
        self._roster_remove_buttons = []
        for instance_num in party:
            player, item, name_label, status, remove_button = self._create_player_entry(instance_num, devices_info)
            self.inspector_stack.add_named(player, str(instance_num))
            self.roster.append(item)
            self._party_players.append(instance_num)
            self.player_rows.append(player)
            self._roster_rows.append(item)
            self._roster_names.append(name_label)
            self._roster_status.append(status)
            self._roster_remove_buttons.append(remove_button)
        self._sync_party_controls()

    def _can_modify_party(self):
        return self._party_controls_sensitive and all(
            row.get_instance_state() == INSTANCE_IDLE for row in self.player_rows
        )

    def _sync_party_controls(self):
        if not hasattr(self, "add_player_button"):
            return
        can_modify = self._can_modify_party()
        self.add_player_button.set_sensitive(can_modify and len(self._party_players) < self._max_players)
        can_remove = can_modify and len(self._party_players) > 1
        for button in self._roster_remove_buttons:
            button.set_sensitive(can_remove)

    def _on_add_player_clicked(self, _button):
        self.add_player()

    def add_player(self):
        """Append the next available player slot (up to the current limit) to the party."""
        if not self._can_modify_party() or len(self._party_players) >= self._max_players:
            return None
        new_index = next((index for index in range(8) if index not in self._party_players), None)
        if new_index is None:
            return None

        pos = sum(1 for existing in self._party_players if existing < new_index)
        was_loading = self._is_loading
        self._is_loading = True
        try:
            player, item, name_label, status, remove_button = self._create_player_entry(new_index, self._devices_info)
            if new_index in self._saved_player_configs:
                player.load_config(self._saved_player_configs[new_index])
            player.set_selected(True)
            player.set_verification_status(self._verification_statuses.get(new_index, False))
            self.inspector_stack.add_named(player, str(new_index))
            self.roster.insert(item, pos)
            self._party_players.insert(pos, new_index)
            self.player_rows.insert(pos, player)
            self._roster_rows.insert(pos, item)
            self._roster_names.insert(pos, name_label)
            self._roster_status.insert(pos, status)
            self._roster_remove_buttons.insert(pos, remove_button)
            self._known_instance_count = max(self._known_instance_count, new_index + 1)
            if any(row is not player and row.grab_input_switch.get_active() for row in self.player_rows):
                player.set_grab_input_active(False)
                player.set_grab_input_sensitive(False)
            elif player.grab_input_switch.get_active():
                self._apply_grab_input_exclusivity()
        finally:
            self._is_loading = was_loading

        self._sync_party_controls()
        self._on_setting_changed()
        return new_index

    def remove_player(self, instance_num):
        """Remove a specific player directly from the party while keeping their saved settings."""
        if not self._can_modify_party() or len(self._party_players) <= 1:
            return False
        pos = self._player_position(instance_num)
        if pos is None:
            return False

        row = self.player_rows[pos]
        had_grab = row.grab_input_switch.get_active()
        self._saved_player_configs[instance_num] = row.get_config()
        row.clear_update_progress()

        was_loading = self._is_loading
        self._is_loading = True
        try:
            self.inspector_stack.remove(row)
            self.roster.remove(self._roster_rows[pos])
            self._party_players.pop(pos)
            self.player_rows.pop(pos)
            self._roster_rows.pop(pos)
            self._roster_names.pop(pos)
            self._roster_status.pop(pos)
            self._roster_remove_buttons.pop(pos)
            if had_grab:
                for remaining in self.player_rows:
                    remaining.set_grab_input_sensitive(True)
        finally:
            self._is_loading = was_loading

        if self._active_player == instance_num:
            next_pos = min(pos, len(self._party_players) - 1)
            self.select_player(self._party_players[next_pos], open_inspector=False)
        self._sync_party_controls()
        self._on_setting_changed()
        return True

    def _sync_roster(self):
        if self._is_loading:
            return
        statuses = {}
        controllers = {}
        mouse_grabs = {}
        names = {}
        for pos, player in enumerate(self.player_rows):
            instance_num = player._player_num
            player_name = player.get_player_name()
            status = player.get_status_text()
            names[instance_num] = player_name
            statuses[instance_num] = status
            controllers[instance_num] = player.has_controller_selected()
            mouse_grabs[instance_num] = player.has_grab_mouse()
            self._roster_names[pos].set_label(player_name)
            self._roster_names[pos].set_tooltip_text(player_name if player_name != DEFAULT_PLAYER_NAME else None)
            self._roster_status[pos].set_label(status)
            self._roster_status[pos].set_tooltip_text(status)
            item = self._roster_rows[pos]
            item.update_property([Gtk.AccessibleProperty.LABEL], [f"Configure {player_name} {instance_num + 1:02d}"])
            remove_button = self._roster_remove_buttons[pos]
            remove_button.set_tooltip_text(f"Remove {player_name} ({instance_num + 1:02d}) from party")
            remove_button.update_property(
                [Gtk.AccessibleProperty.LABEL], [f"Remove {player_name} {instance_num + 1:02d}"]
            )
            for state in ("running", "starting", "stopping", "idle"):
                item.remove_css_class(f"party-{state}")
            item.add_css_class(f"party-{player.get_instance_state()}")
            if player.is_selected():
                item.remove_css_class("party-excluded")
            else:
                item.add_css_class("party-excluded")
        self.layout_preview.set_player_names(names)
        self.layout_preview.set_player_statuses(statuses)
        self.layout_preview.set_player_controllers(controllers)
        self.layout_preview.set_player_mouse_grabs(mouse_grabs)

        count = len(self._displays)
        self.display_summary.set_label(
            f"{count} display{'s' if count != 1 else ''}" if count else "No display detected"
        )

        self._sync_placement_controls()
        self._sync_party_controls()
        self.emit("summary-changed")

    def _can_reposition_players(self):
        return (
            self._screen_settings_sensitive
            and self._gamescope_enabled
            and all(row.get_instance_state() == INSTANCE_IDLE for row in self.player_rows)
        )

    def _sync_placement_controls(self):
        self.layout_preview.set_reposition_enabled(self._can_reposition_players())

    def _apply_grab_input_exclusivity(self):
        active = next((row._player_num for row in self.player_rows if row.grab_input_switch.get_active()), None)
        if active is None:
            return
        for row in self.player_rows:
            if row._player_num != active:
                row.set_grab_input_active(False)
                row.set_grab_input_sensitive(False)

    def _handle_grab_input_exclusivity(self, active_instance):
        if self._is_loading or self._applying_exclusivity:
            return
        active_row = self.get_player_row(active_instance)
        if active_row is None:
            return
        active = active_row.grab_input_switch.get_active()
        self._applying_exclusivity = True
        try:
            for row in self.player_rows:
                if row._player_num != active_instance:
                    if active:
                        row.set_grab_input_active(False)
                    row.set_grab_input_sensitive(not active)
        finally:
            self._applying_exclusivity = False

    def get_data(self):
        """Return the existing profile/controller data contract from the studio controls."""
        mode = self.screen_mode_row.get_selected_item().get_string().lower()
        live_configs = {row._player_num: row.get_config() for row in self.player_rows}
        max_index = max(
            max(self._party_players, default=-1),
            max(self._saved_player_configs, default=-1),
        )
        player_configs = [
            live_configs.get(index, self._saved_player_configs.get(index, PlayerInstanceConfig()))
            for index in range(max_index + 1)
        ]
        return {
            "num_players": len(self._party_players),
            "party_players": list(self._party_players),
            "mode": mode,
            "orientation": (
                self.orientation_row.get_selected_item().get_string().lower() if mode == "splitscreen" else None
            ),
            "player_configs": player_configs,
            "selected_players": self.get_selected_players(),
            "layout_order": list(self._layout_order) if self.placement_mode_row.get_selected() == 1 else None,
            "monitor_layouts": {
                key: {"template": config["template"], "players": list(config["players"])}
                for key, config in self._monitor_layouts.items()
            },
        }

    def get_selected_players(self):
        """Return participating player instance IDs independently of the active inspector."""
        return [row._player_num for row in self.player_rows if row.is_selected()]

    def set_running_state(self, is_running):
        """Synchronize all inspectors when a bulk operation completes."""
        for row in self.player_rows:
            row.set_running_state(is_running)

    def update_verification_status(self, instance_num, is_verified):
        """Propagate installation readiness to the inspector, roster and stage."""
        self._verification_statuses[instance_num] = is_verified
        row = self.get_player_row(instance_num)
        if row is not None:
            row.set_verification_status(is_verified)

    def _on_screen_mode_changed(self, dropdown, *_args):
        mode = dropdown.get_selected_item().get_string().lower()
        split = mode == "splitscreen"
        self.orientation_field.set_visible(split)
        self.orientation_row.set_visible(split)
        if not self._is_loading:
            self._last_user_selected_mode = mode
        self._update_num_players_limits(split)
        self._on_setting_changed()

    def update_devices_info(self, devices_info):
        """Refresh discovery results without treating model replacement as user edits."""
        loading = self._is_loading
        self._is_loading = True
        try:
            self._devices_info = {kind: list(items) for kind, items in devices_info.items()}
            for row in self.player_rows:
                row.update_devices(devices_info)
            self._displays = sorted(devices_info.get("displays", []), key=lambda display: display.get("id", 0))
            self._num_monitors = max(1, len(self._displays))
            self._update_num_players_limits(self.screen_mode_row.get_selected() == 1)
        finally:
            self._is_loading = loading
        self._update_layout_preview()
        self._sync_roster()

    def _update_layout_preview(self):
        self._known_instance_count = max(
            self._known_instance_count,
            max(self._party_players, default=-1) + 1,
        )
        self._layout_order = LayoutCalculator.order_instances(
            list(range(self._known_instance_count)), self._layout_order
        )
        custom = self.placement_mode_row.get_selected() == 1
        instances = LayoutCalculator.order_instances(
            self.get_selected_players(), self._layout_order if custom else None
        )
        mode = self.screen_mode_row.get_selected_item().get_string().lower()
        orientation = self.orientation_row.get_selected_item().get_string().lower()
        allowed = self._can_reposition_players()
        self._tiling_plan = None
        if self._monitor_layouts:
            self._tiling_plan = build_tiling_plan(instances, self._displays, self._monitor_layouts)
            instances = [player for monitor in self._tiling_plan.monitors for player in monitor.players]
            instances.extend(self._tiling_plan.unassigned)
        templates = (
            tuple((monitor.key, monitor.template.id) for monitor in self._tiling_plan.monitors)
            if self._tiling_plan is not None
            else ()
        )
        geometry = (mode, orientation, repr(self._displays), templates)
        signature = (tuple(instances), geometry, custom)
        if (
            self._preview_signature is None
            or geometry != self._preview_geometry
            or self.layout_preview.instances != instances
        ):
            if self._tiling_plan is not None:
                self.layout_preview.configure_tiling(self._tiling_plan, allowed)
            else:
                self.layout_preview.configure(
                    instances, mode, orientation, self._displays, custom and allowed, allow_reposition=allowed
                )
        # A swap already updates the preview in place. Rebuilding here would cancel
        # the native drag before GTK can finish the successful drop.
        self._preview_signature = signature
        self._preview_geometry = geometry
        self.layout_preview.set_active_player(self._active_player)
        self._sync_roster()

    def _on_layout_order_changed(self, preview, visible_order):
        self._stop_drag_scrolling()
        if self._is_loading or not self._can_reposition_players():
            return
        was_loading = self._is_loading
        self._is_loading = True
        try:
            self.placement_mode_row.set_selected(1)
        finally:
            self._is_loading = was_loading
        if self._monitor_layouts:
            self._monitor_layouts.update(preview.get_monitor_layouts())
        selected = set(self.get_selected_players())
        positions = [i for i, instance in enumerate(self._layout_order) if instance in selected]
        for position, instance in zip(positions, (player for player in visible_order if player is not None)):
            self._layout_order[position] = instance
        self.select_player(preview._active_player, open_inspector=False)
        self._on_setting_changed()

    def _on_monitor_template_selected(self, preview, key, template_id):
        if not self._can_reposition_players() or template_id not in TEMPLATES:
            return
        layouts = preview.get_monitor_layouts()
        if key not in layouts:
            return
        if self.placement_mode_row.get_selected() == 1:
            self._monitor_layouts.update(layouts)
            config = self._monitor_layouts[key]
            config["template"] = template_id
            config["players"] = config["players"][: TEMPLATES[template_id].capacity]
        else:
            for monitor_name, layout in layouts.items():
                self._monitor_layouts[monitor_name] = {
                    "template": layout["template"],
                    "players": [],
                }
            self._monitor_layouts[key]["template"] = template_id
        self._on_setting_changed()

    def get_layout_error(self, instance=None):
        """Explain insufficient monitor capacity before starting any instances."""
        unassigned = self._tiling_plan.unassigned if self._tiling_plan is not None else []
        if instance is not None:
            unassigned = [player for player in unassigned if player == instance]
        if self._gamescope_enabled and unassigned:
            players = ", ".join(str(player + 1) for player in unassigned)
            return f"Players {players} have no display space. Choose a larger template or exclude them from the party."
        return None

    def _update_num_players_limits(self, is_splitscreen):
        self._max_players = min(8, self._num_monitors * 4) if is_splitscreen else 8
        self._sync_party_controls()

    def _on_setting_changed(self, *_args):
        if not self._is_loading:
            if _args and _args[0] is self.placement_mode_row and self.placement_mode_row.get_selected() == 0:
                for config in self._monitor_layouts.values():
                    config["players"] = []
            self._update_layout_preview()
            self.emit("settings-changed")

    def set_gamescope_enabled(self, enabled):
        """Replace Gamescope-only controls with the direct-mode explanation."""
        self._gamescope_enabled = enabled
        self.gamescope_settings_group.set_visible(enabled)
        self.layout_preview_group.set_visible(enabled)
        self.displays_disabled_group.set_visible(not enabled)
        if not self._is_loading:
            self._sync_placement_controls()

    def set_number_of_instances_sensitive(self, sensitive):
        """Lock party add and remove controls while instances are active."""
        self._party_controls_sensitive = bool(sensitive)
        self._sync_party_controls()

    def set_screen_settings_sensitive(self, sensitive):
        """Lock placement while leaving canvas navigation available."""
        self._screen_settings_sensitive = sensitive
        self.gamescope_settings_group.set_sensitive(sensitive)
        self.screen_mode_row.set_sensitive(sensitive)
        self.orientation_row.set_sensitive(sensitive)
        self.placement_mode_row.set_sensitive(sensitive)
        self._update_layout_preview()

    def set_checkboxes_sensitive(self, sensitive):
        """Lock participation without blocking player inspection or stop actions."""
        for row in self.player_rows:
            row.set_checkbox_sensitive(sensitive)
