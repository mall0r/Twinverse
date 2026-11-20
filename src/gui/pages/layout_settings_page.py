"""Session studio: a party roster, an interactive stage and a focused inspector."""

# flake8: noqa: E402

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, GObject, Gtk, Pango  # noqa: E402

from src.core.layout import LayoutCalculator
from src.core.tiling import TEMPLATES, build_tiling_plan
from src.gui.widgets import LayoutPreview, PlayerRow
from src.gui.widgets.player_row import INSTANCE_IDLE


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
        self._last_user_selected_mode = None
        self._layout_order = []
        self._monitor_layouts = {}
        self._tiling_plan = None
        self._known_instance_count = 0
        self._displays = []
        self._active_player = 0
        self._screen_settings_sensitive = True
        self._gamescope_enabled = True
        self._preview_signature = None
        self._preview_geometry = None
        self._drag_scroll_id = 0
        self._drag_scroll_drop = None
        self._drag_scroll_step = 0
        self.player_rows = []
        self._roster_rows = []
        self._roster_status = []
        self.add_css_class("studio-workspace")
        self._build_ui()
        self.connect("unmap", lambda *_: self._stop_drag_scrolling())

    @staticmethod
    def _label(text, style, **kwargs):
        label = Gtk.Label(label=text, xalign=0, **kwargs)
        label.add_css_class(style)
        return label

    def _build_ui(self):
        self.roster_split = Adw.OverlaySplitView(
            min_sidebar_width=220,
            max_sidebar_width=220,
            sidebar_width_fraction=0.18,
            hexpand=True,
            vexpand=True,
        )
        self.append(self.roster_split)
        self.roster_split.set_sidebar(self._build_roster())

        self.inspector_split = Adw.OverlaySplitView(
            sidebar_position=Gtk.PackType.END,
            min_sidebar_width=324,
            max_sidebar_width=344,
            sidebar_width_fraction=0.3,
            hexpand=True,
            vexpand=True,
        )
        self.roster_split.set_content(self.inspector_split)
        self.inspector_split.set_content(self._build_stage())
        self.inspector_split.set_sidebar(self._build_inspector())

    def _build_roster(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        sidebar.add_css_class("party-sidebar")
        heading = Gtk.Box(spacing=8)
        heading.append(self._label("Your party", "party-heading", hexpand=True))

        sidebar.append(heading)

        self.roster = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.roster.add_css_class("party-list")
        self.roster.connect("row-selected", self._on_roster_selection_changed)
        self.roster.connect("row-activated", self._on_roster_selected)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(self.roster)
        sidebar.append(scroll)

        count_box = Gtk.Box(spacing=8)
        count_label = Gtk.Label(label="_Party size", use_underline=True, xalign=0, hexpand=True)
        count_label.add_css_class("muted")
        count_box.append(count_label)
        adjustment = Gtk.Adjustment(value=2, lower=1, upper=8, step_increment=1, page_increment=1)
        self.num_players_row = Gtk.SpinButton(adjustment=adjustment, numeric=True, width_chars=1)
        self.num_players_row.set_tooltip_text(
            "Add or remove players. Settings for players removed from the party are kept."
        )
        self.num_players_row.set_alignment(1)
        count_label.set_mnemonic_widget(self.num_players_row)
        self.num_players_row.update_property([Gtk.AccessibleProperty.LABEL], ["Party size"])
        self.num_players_row.add_css_class("party-stepper")
        adjustment.connect("value-changed", self._on_num_players_changed)
        count_box.append(self.num_players_row)
        sidebar.append(count_box)
        sidebar.append(Gtk.Separator())

        self.session_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.session_controls.add_css_class("party-session-status")
        sidebar.append(self.session_controls)
        return sidebar

    def _build_stage(self):
        studio = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        studio.add_css_class("studio-stage")
        top = Gtk.Box(spacing=16)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        titles.append(self._label("SESSION STUDIO", "eyebrow"))
        top.append(titles)

        studio.append(top)

        canvas_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, vexpand=True)
        canvas_box.add_css_class("stage-surface")
        canvas_heading = Gtk.Box(spacing=8)
        canvas_heading.append(self._label("LIVE LAYOUT", "canvas-kicker", hexpand=True))
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
            icon_name="application-x-executable-symbolic",
            description="Players run in independent windows. Enable Gamescope in Preferences to arrange a split-screen session.",
            vexpand=True,
        )
        self.displays_disabled_group.set_visible(False)
        canvas_box.append(self.displays_disabled_group)
        hint = Gtk.Box(spacing=8)
        hint.append(Gtk.Image(icon_name="input-mouse-symbolic"))
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

    def select_player(self, index, open_inspector=True):
        """Inspect a player without changing their participation in the session."""
        if not 0 <= index < len(self.player_rows):
            return
        self._active_player = index
        self.inspector_stack.set_visible_child_name(str(index))
        row = self._roster_rows[index]
        if self.roster.get_selected_row() != row:
            self._syncing_roster_selection = True
            try:
                self.roster.select_row(row)
            finally:
                self._syncing_roster_selection = False
        self.layout_preview.set_active_player(index)
        if open_inspector:
            self.inspector_split.set_show_sidebar(True)
            if self.roster_split.get_collapsed():
                self.roster_split.set_show_sidebar(False)

    def _on_roster_selection_changed(self, _list, row):
        if row is not None and not self._is_loading and not self._syncing_roster_selection:
            self.select_player(row.get_index(), open_inspector=False)

    def _on_roster_selected(self, _list, row):
        if (
            row is not None
            and not self._is_loading
            and not self._syncing_roster_selection
            and not self.layout_preview._suppress_activation
        ):
            self.select_player(row.get_index())

    def load_data(self, profile, devices_info, verification_statuses):
        """Restore saved assignments without emitting edits or resetting the active player."""
        self._is_loading = True
        self._displays = sorted(devices_info.get("displays", []), key=lambda display: display.get("id", 0))
        self._num_monitors = max(1, len(self._displays))
        self._monitor_layouts = {key: config.model_dump() for key, config in profile.monitor_layouts.items()}
        saved_instances = [index + 1 for index in profile.layout_order or []]
        self._known_instance_count = max(profile.num_players, len(profile.player_configs), *saved_instances, 0)
        self._layout_order = LayoutCalculator.order_instances(
            list(range(self._known_instance_count)), profile.layout_order
        )
        self.placement_mode_row.set_selected(0 if profile.layout_order is None else 1)
        self.num_players_row.get_adjustment().set_value(profile.num_players)
        is_split = (self._last_user_selected_mode or profile.mode) == "splitscreen"
        self.screen_mode_row.set_selected(1 if is_split else 0)
        self._update_num_players_limits(is_split)
        self.orientation_field.set_visible(is_split)
        self.orientation_row.set_visible(is_split)
        self.set_gamescope_enabled(profile.use_gamescope)
        if is_split and profile.splitscreen:
            self.orientation_row.set_selected(self.orientations.index(profile.splitscreen.orientation.capitalize()))
        self.rebuild_player_rows(profile.num_players, devices_info)
        selected = set(profile.selected_players) if profile.selected_players else set(range(len(self.player_rows)))
        for i, row in enumerate(self.player_rows):
            if i < len(profile.player_configs):
                row.load_config(profile.player_configs[i])
            row.set_selected(i in selected)
            row.set_verification_status(verification_statuses.get(i, False))
        self._apply_grab_input_exclusivity()
        self._is_loading = False
        self.select_player(min(self._active_player, len(self.player_rows) - 1), open_inspector=False)
        self._preview_signature = None
        self._update_layout_preview()
        self._sync_roster()

    def rebuild_player_rows(self, num_players, devices_info):
        """Replace roster entries and inspectors, releasing old progress timers."""
        for row in self.player_rows:
            row.clear_update_progress()
            self.inspector_stack.remove(row)
        while child := self.roster.get_first_child():
            self.roster.remove(child)
        self.player_rows = []
        self._roster_rows = []
        self._roster_status = []
        for index in range(num_players):
            player = PlayerRow(index, devices_info)
            player.set_parent_page(self)
            player.connect("settings-changed", self._on_setting_changed)
            player.connect("launch-clicked", lambda _w, number: self.emit("instance-launch-requested", number))
            player.connect("refresh-devices-requested", lambda *_: self.emit("devices-refresh-requested"))
            player.connect("status-changed", lambda *_: self._sync_roster())
            self.inspector_stack.add_named(player, str(index))
            self.player_rows.append(player)
            item = Gtk.ListBoxRow()
            item.add_css_class("party-player")
            item.update_property([Gtk.AccessibleProperty.LABEL], [f"Configure Player {index + 1}"])
            body = Gtk.Box(spacing=10)
            number = Gtk.Label(label=f"{index + 1:02d}", xalign=0.5, yalign=0.5, valign=Gtk.Align.CENTER)
            number.set_size_request(36, 36)
            number.add_css_class("party-avatar")
            number.add_css_class(f"player-color-{index % 8}")
            body.append(number)
            text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
            text.append(self._label(f"Player {index + 1}", "party-player-name"))
            status = self._label("Not installed", "party-player-status")
            status.set_ellipsize(Pango.EllipsizeMode.END)
            status.set_max_width_chars(17)
            text.append(status)
            body.append(text)
            player.checkbox.set_valign(Gtk.Align.CENTER)
            body.append(player.checkbox)
            item.set_child(body)
            self.layout_preview.add_player_drag_source(item, index)
            self.roster.append(item)
            self._roster_rows.append(item)
            self._roster_status.append(status)

    def _sync_roster(self):
        if self._is_loading:
            return
        statuses = {}
        for index, player in enumerate(self.player_rows):
            status = player.get_status_text()
            statuses[index] = status
            self._roster_status[index].set_label(status)
            self._roster_status[index].set_tooltip_text(status)
            item = self._roster_rows[index]
            for state in ("running", "starting", "stopping", "idle"):
                item.remove_css_class(f"party-{state}")
            item.add_css_class(f"party-{player.get_instance_state()}")
            if player.is_selected():
                item.remove_css_class("party-excluded")
            else:
                item.add_css_class("party-excluded")
        self.layout_preview.set_player_statuses(statuses)

        count = len(self._displays)
        self.display_summary.set_label(
            f"{count} display{'s' if count != 1 else ''}" if count else "No display detected"
        )

        self._sync_placement_controls()
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
        active = next((i for i, row in enumerate(self.player_rows) if row.grab_input_switch.get_active()), None)
        if active is None:
            return
        for i, row in enumerate(self.player_rows):
            if i != active:
                row.set_grab_input_active(False)
                row.set_grab_input_sensitive(False)

    def _handle_grab_input_exclusivity(self, active_index):
        if self._is_loading or self._applying_exclusivity:
            return
        active = self.player_rows[active_index].grab_input_switch.get_active()
        self._applying_exclusivity = True
        try:
            for i, row in enumerate(self.player_rows):
                if i != active_index:
                    if active:
                        row.set_grab_input_active(False)
                    row.set_grab_input_sensitive(not active)
        finally:
            self._applying_exclusivity = False

    def get_data(self):
        """Return the existing profile/controller data contract from the new controls."""
        mode = self.screen_mode_row.get_selected_item().get_string().lower()
        return {
            "num_players": int(self.num_players_row.get_value()),
            "mode": mode,
            "orientation": (
                self.orientation_row.get_selected_item().get_string().lower() if mode == "splitscreen" else None
            ),
            "player_configs": [row.get_config() for row in self.player_rows],
            "selected_players": self.get_selected_players(),
            "layout_order": list(self._layout_order) if self.placement_mode_row.get_selected() == 1 else None,
            "monitor_layouts": {
                key: {"template": config["template"], "players": list(config["players"])}
                for key, config in self._monitor_layouts.items()
            },
        }

    def get_selected_players(self):
        """Return participating players independently of the active inspector."""
        return [i for i, row in enumerate(self.player_rows) if row.is_selected()]

    def set_running_state(self, is_running):
        """Synchronize all inspectors when a bulk operation completes."""
        for row in self.player_rows:
            row.set_running_state(is_running)

    def update_verification_status(self, instance_num, is_verified):
        """Propagate installation readiness to the inspector, roster and stage."""
        if 0 <= instance_num < len(self.player_rows):
            self.player_rows[instance_num].set_verification_status(is_verified)

    def _on_num_players_changed(self, adjustment):
        if not self._is_loading:
            self._on_setting_changed()

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
            for row in self.player_rows:
                row.update_devices(devices_info)
            self._displays = sorted(devices_info.get("displays", []), key=lambda display: display.get("id", 0))
            self._num_monitors = max(1, len(self._displays))
        finally:
            self._is_loading = loading
        self._update_layout_preview()
        self._sync_roster()

    def _update_layout_preview(self):
        self._known_instance_count = max(self._known_instance_count, len(self.player_rows))
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
        self.num_players_row.get_adjustment().set_upper(min(8, self._num_monitors * 4) if is_splitscreen else 8)

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
        """Lock the single party-size control while instances are active."""
        self.num_players_row.set_sensitive(sensitive)

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
