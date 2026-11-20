"""An interactive, expanding session canvas using the launcher's real split geometry."""

# flake8: noqa: E402

from dataclasses import dataclass
from math import ceil

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GLib, GObject, Graphene, Gsk, Gtk, Pango

from src.core.layout import LayoutCalculator
from src.core.tiling import TilingPlan, monitor_key
from src.gui.widgets.card_motion import CardMotion, CardRect, MovingCard
from src.gui.widgets.tiling_picker import TilingPicker


class _MonitorLayout(Gtk.LayoutManager):
    """Scale an interactive monitor without imposing its cards' text size on the window."""

    def do_get_request_mode(self, widget):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, widget, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 80, 320, -1, -1
        natural = ceil(max(1, for_size if for_size >= 0 else 320) / widget.get_ratio())
        return min(80, natural), natural, -1, -1

    def do_allocate(self, widget, width, height, baseline):
        child = widget.get_child()
        if child is None or width <= 0 or height <= 0:
            return
        ratio = widget.get_ratio()
        visual_width = min(width, height * ratio)
        visual_height = visual_width / ratio
        minimum_width = max(1, child.measure(Gtk.Orientation.HORIZONTAL, -1)[0])
        minimum_height = child.measure(Gtk.Orientation.VERTICAL, minimum_width)[0]
        logical_width = max(minimum_width, ceil(minimum_height * ratio), ceil(visual_width))
        logical_height = max(1, ceil(logical_width / ratio))
        transform = (
            Gsk.Transform.new()
            .translate(Graphene.Point().init((width - visual_width) / 2, (height - visual_height) / 2))
            .scale(visual_width / logical_width, visual_height / logical_height)
        )
        child.allocate(logical_width, logical_height, -1, transform)


class _MonitorFrame(Gtk.AspectFrame):
    """Keep the real display ratio while scaling both rendering and input coordinates."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_layout_manager(_MonitorLayout())


class _PlayerDragPayload(GObject.Object):
    """An in-process player identity that cannot be confused with external drag data."""

    def __init__(self, owner: "LayoutPreview", instance: int):
        super().__init__()
        self.owner = owner
        self.instance = instance


@dataclass
class _PlayerSlot:
    cell: Gtk.Overlay
    button: Gtk.Button
    number: Gtk.Label
    name: Gtk.Label
    status: Gtk.Label
    instance: int | None
    location: str


class LayoutPreview(Gtk.Box):
    """Fit monitors in a two-column canvas, keeping activation separate from assignment.

    Additional rows can scroll within the session's canvas. Player
    indices are zero-based, as are the eight repeating ``player-color-N`` classes.
    """

    __gsignals__ = {
        "template-selected": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
        "order-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "player-activated": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        """Keep live selection and status independent of the placement configuration."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24, hexpand=True, vexpand=True)
        self.add_css_class("canvas-root")
        self.instances: list[int | None] = []
        self.monitor_slot_ranges: dict[str, tuple[int, int]] = {}
        self.tiling_pickers: dict[str, TilingPicker] = {}
        self.slot_labels: list[str] = []
        self.monitor_grids: list[Gtk.Grid] = []
        self.monitor_names: list[str] = []
        self.monitor_wall: Gtk.Grid | None = None
        self.monitor_cards: list[Gtk.Widget] = []
        self._slots: list[_PlayerSlot] = []
        self._active_player: int | None = None
        self._player_statuses: dict[int, str] = {}
        self._updating = False
        self._allow_reposition = False
        self._using_tiling = False
        self._drag_source: Gtk.DragSource | None = None
        self._drag_payload: _PlayerDragPayload | None = None
        self._suppress_activation = False
        self._activation_reset_id = 0
        self._drag_image: Gdk.Paintable | None = None
        self._drag_hotspot = (0, 0)
        self._drag_size = (0, 0)
        self._motion = CardMotion(self)
        self._motion_size = (0, 0)
        self._pending_card_images: dict[Gtk.Widget, Gdk.Paintable] = {}
        self.connect("unmap", lambda *_: self._motion.finish())

    @staticmethod
    def _monitor_display_name(monitor: dict) -> str:
        """Return only the display connector name without a numeric monitor prefix."""
        return monitor.get("name") or "Unknown connector"

    def do_snapshot(self, snapshot):
        """Draw floating cards above all monitor grids, in canvas coordinates."""
        if self._motion.active and self._motion_size != (self.get_width(), self.get_height()):
            self._motion.finish()
        Gtk.Box.do_snapshot(self, snapshot)
        if not self._motion.active:
            self._pending_card_images.clear()
        self._motion.snapshot(snapshot)

    def configure(self, instances, mode, orientation, displays, editable, *, allow_reposition=None):
        """Rebuild geometry without emitting changes or losing live player state.

        Interaction defaults to ``editable``. A parent may allow repositioning in
        automatic mode and use ``order-changed`` to opt into custom placement.
        """
        self._motion.finish()
        self._pending_card_images.clear()
        self._updating = True
        try:
            if self._drag_source is not None and self._drag_source.get_drag() is not None:
                self._drag_source.drag_cancel()
            self._clear_drag_state()
            self._allow_reposition = bool(editable if allow_reposition is None else allow_reposition)
            self._using_tiling = False
            while child := self.get_first_child():
                self.remove(child)
            self.instances = list(instances)
            self.slot_labels = []
            self.monitor_grids = []
            self.monitor_names = []
            self.monitor_wall = None
            self.monitor_cards = []
            self._slots = []
            self.monitor_slot_ranges = {}
            self.tiling_pickers = {}
            if not self.instances:
                label = Gtk.Label(
                    label="Your session canvas is empty.\nSelect at least one instance from the roster to begin.",
                    wrap=True,
                    justify=Gtk.Justification.CENTER,
                    hexpand=True,
                    vexpand=True,
                    valign=Gtk.Align.CENTER,
                )
                label.add_css_class("canvas-empty")
                self.append(label)
                for index, monitor in enumerate(displays or []):
                    self._append_unused_monitor(monitor, index)
                return

            monitors = list(displays or [])
            has_displays = bool(monitors)
            if not has_displays:
                monitors = [{"name": "Not detected", "width": 1920, "height": 1080}]
            group_size = 4 if mode == "splitscreen" else 1

            for start in range(0, len(self.instances), group_size):
                group = self.instances[start : start + group_size]
                requested_monitor = start // group_size
                monitor_index = requested_monitor if requested_monitor < len(monitors) else 0
                monitor = monitors[monitor_index]
                width = max(1, int(monitor.get("width") or 1920))
                height = max(1, int(monitor.get("height") or 1080))
                name = self._monitor_display_name(monitor)
                self.monitor_names.append(name)

                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True, vexpand=True)
                box.add_css_class("canvas-monitor")
                header = self._make_monitor_header(name, width, height, len(group), mode, orientation)
                box.append(header)
                key = monitor_key(monitor, monitor_index)
                if has_displays and key not in self.tiling_pickers:
                    template = self._legacy_template(len(group), orientation)
                    self.monitor_slot_ranges[key] = (start, start + len(group))
                    self._add_picker(header, key, template)
                if requested_monitor >= len(monitors):
                    self._append_warning(box, f"No dedicated display for this group; it shares {name}.")
                elif not has_displays:
                    self._append_warning(
                        box, "No display detected. Using a 1920 × 1080 preview until one is available."
                    )

                grid = Gtk.Grid(
                    column_homogeneous=True,
                    row_homogeneous=True,
                    column_spacing=6,
                    row_spacing=6,
                    hexpand=True,
                    vexpand=True,
                )
                grid.add_css_class("canvas-monitor-grid")
                self.monitor_grids.append(grid)
                xs, ys, widths, heights = LayoutCalculator.get_layout_coordinates(len(group), orientation)
                for local_slot, instance in enumerate(group):
                    slot = start + local_slot
                    geometry = LayoutCalculator.calculate_position(width, height, len(group), local_slot, orientation)
                    self.slot_labels.append(f"{name} · Space {slot + 1}")
                    cell = self._make_slot(slot, instance, name, geometry)
                    grid.attach(
                        cell,
                        round(xs[local_slot] * 2),
                        round(ys[local_slot] * 2),
                        round(widths[local_slot] * 2),
                        round(heights[local_slot] * 2),
                    )

                frame = _MonitorFrame(
                    ratio=width / height,
                    obey_child=False,
                    hexpand=True,
                    vexpand=True,
                    halign=Gtk.Align.FILL,
                    valign=Gtk.Align.FILL,
                )
                frame.add_css_class("canvas-monitor-frame")
                frame.set_child(grid)
                box.append(frame)
                self._append_monitor(box)
            for index, monitor in enumerate(displays or []):
                if monitor_key(monitor, index) not in self.tiling_pickers:
                    self._append_unused_monitor(monitor, index)
        finally:
            self._updating = False

    def _append_monitor(self, card):
        if self.monitor_wall is None:
            self.monitor_wall = Gtk.Grid(
                column_homogeneous=True,
                column_spacing=20,
                row_spacing=24,
                hexpand=True,
                vexpand=True,
            )
            self.monitor_wall.add_css_class("monitor-wall")
            self.append(self.monitor_wall)
        index = len(self.monitor_cards)
        self.monitor_wall.attach(card, index % 2, index // 2, 1, 1)
        self.monitor_cards.append(card)

    @staticmethod
    def _legacy_template(count, orientation):
        if count <= 1:
            return "fullscreen"
        if count == 4:
            return "grid"
        horizontal = orientation.lower() == "horizontal"
        if count == 2:
            return "rows" if horizontal else "columns"
        return "main-top" if horizontal else "main-left"

    def _add_picker(self, header, key, template_id):
        picker = TilingPicker()
        picker.set_selected(template_id)
        picker.set_editable(self._allow_reposition)
        picker.connect("template-selected", self._on_template_selected, key)
        # Keep the responsive option row inside the heading's details column.
        header.get_first_child().get_next_sibling().append(picker)
        self.tiling_pickers[key] = picker

    def _on_template_selected(self, _picker, template_id, key):
        if not self._updating and self._allow_reposition and self.is_sensitive():
            self.emit("template-selected", key, template_id)

    def _append_unused_monitor(self, monitor, index):
        key = monitor_key(monitor, index)
        width = max(1, int(monitor.get("width") or 1920))
        height = max(1, int(monitor.get("height") or 1080))
        header = self._make_monitor_header(
            self._monitor_display_name(monitor),
            width,
            height,
            0,
            "fullscreen",
            "horizontal",
        )
        self._add_picker(header, key, None)
        self.monitor_slot_ranges[key] = (len(self.instances), len(self.instances))
        self._append_monitor(header)

    def get_monitor_layouts(self):
        """Export connected monitor assignments, never overflow/tray players."""
        return {
            key: {
                "template": self.tiling_pickers[key]._selected or "fullscreen",
                "players": list(self.instances[start:end]),
            }
            for key, (start, end) in self.monitor_slot_ranges.items()
        }

    def configure_tiling(self, plan: TilingPlan, editable: bool):
        """Render exact monitor capacities, preserving holes and unassigned players."""
        self._motion.finish()
        self._pending_card_images.clear()
        self._updating = True
        try:
            if self._drag_source is not None and self._drag_source.get_drag() is not None:
                self._drag_source.drag_cancel()
            self._clear_drag_state()
            self._allow_reposition = bool(editable)
            self._using_tiling = True
            while child := self.get_first_child():
                self.remove(child)
            self.instances = []
            self.slot_labels = []
            self.monitor_grids = []
            self.monitor_names = []
            self.monitor_wall = None
            self.monitor_cards = []
            self.monitor_slot_ranges = {}
            self.tiling_pickers = {}
            self._slots = []
            for monitor in plan.monitors:
                start = len(self.instances)
                self.instances.extend(monitor.players)
                self.monitor_slot_ranges[monitor.key] = (start, len(self.instances))
                width = max(1, int(monitor.display.get("width") or 1920))
                height = max(1, int(monitor.display.get("height") or 1080))
                name = self._monitor_display_name(monitor.display)
                self.monitor_names.append(name)
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True, vexpand=True)
                box.add_css_class("canvas-monitor")
                header = self._make_monitor_header(name, width, height, 0, "fullscreen", "horizontal")
                details = header.get_first_child().get_next_sibling()
                details.get_first_child().get_next_sibling().set_label(f"{width} × {height} · {monitor.template.title}")
                header.get_last_child().set_label(
                    f"{sum(player is not None for player in monitor.players)} / {monitor.template.capacity} PLAYERS"
                )
                self._add_picker(header, monitor.key, monitor.template.id)
                box.append(header)
                grid = Gtk.Grid(
                    column_homogeneous=True,
                    row_homogeneous=True,
                    column_spacing=6,
                    row_spacing=6,
                    hexpand=True,
                    vexpand=True,
                )
                grid.add_css_class("canvas-monitor-grid")
                self.monitor_grids.append(grid)
                for local, (x, y, w, h) in enumerate(monitor.template.rectangles):
                    slot = start + local
                    self.slot_labels.append(f"{name} · Space {local + 1}")
                    geometry = (int(x * width), int(y * height), int(w * width), int(h * height))
                    cell = self._make_slot(slot, self.instances[slot], name, geometry)
                    grid.attach(cell, round(x * 2), round(y * 2), round(w * 2), round(h * 2))
                frame = _MonitorFrame(ratio=width / height, obey_child=False, hexpand=True, vexpand=True)
                frame.add_css_class("canvas-monitor-frame")
                frame.set_child(grid)
                box.append(frame)
                self._append_monitor(box)
            if plan.unassigned:
                tray = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, hexpand=True)
                title = Gtk.Label(label="Players without a space", xalign=0)
                title.add_css_class("heading")
                tray.append(title)
                self._append_warning(
                    tray,
                    "These players have no monitor assignment. Choose a larger layout or drop them into an empty space.",
                )
                primary = plan.monitors[0].display if plan.monitors else {}
                width = max(1, int(primary.get("width") or 1920))
                height = max(1, int(primary.get("height") or 1080))
                for player in plan.unassigned:
                    slot = len(self.instances)
                    self.instances.append(player)
                    self.slot_labels.append("Unassigned · Players without a space")
                    cell = self._make_slot(slot, player, "Unassigned (preview geometry only)", (0, 0, width, height))
                    tray.append(cell)
                self.append(tray)
        finally:
            self._updating = False

    def set_active_player(self, index: int | None):
        """Highlight a player's current space without emitting activation; None clears it."""
        self._active_player = index
        for slot in range(len(self._slots)):
            self._refresh_slot(slot)

    def set_player_statuses(self, statuses: dict[int, str]):
        """Replace status text by player index in place, preserving widgets and keyboard focus.

        Players absent from the mapping display "Ready to configure". Statuses and
        selection survive subsequent calls to configure, including temporary removal.
        """
        self._player_statuses = dict(statuses)
        for slot in range(len(self._slots)):
            self._refresh_slot(slot)

    def assign_player(self, instance: int, target_slot: int) -> bool:
        """Swap a participating player into a global slot, emitting one complete order.

        Invalid, excluded, unchanged or locked assignments return False without
        changing selection. Successful moves select the moved player, but do not
        activate the inspector. Slot labels and cell geometry remain unchanged.
        """
        return self._swap_players(instance, target_slot)

    def _capture_card(self, widget):
        if not widget.get_mapped() or widget.get_width() <= 0 or widget.get_height() <= 0:
            return None
        # A second move can begin before GTK redraws restored cells. Keep their
        # new identities available without snapshotting a pending allocation.
        image = self._pending_card_images.get(widget)
        if image is None:
            image = Gtk.WidgetPaintable.new(widget).get_current_image()
        snapshot = Gtk.Snapshot()
        image.snapshot(snapshot, widget.get_width(), widget.get_height())
        if image.get_intrinsic_width() != widget.get_width() or image.get_intrinsic_height() != widget.get_height():
            return snapshot.to_paintable(Graphene.Size().init(widget.get_width(), widget.get_height()))
        return image if snapshot.to_node() is not None else None

    def _card_rect(self, widget):
        found, bounds = widget.compute_bounds(self)
        if not found or bounds.get_width() <= 0 or bounds.get_height() <= 0:
            return None
        return CardRect(bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height())

    def _swap_players(self, instance, target_slot, landing_origin=None):
        if not self._can_assign_player(instance, target_slot):
            return False
        self._motion.finish()
        other_slot = self.instances.index(instance)
        source, destination = self._slots[other_slot].cell, self._slots[target_slot].cell
        source_rect, destination_rect = self._card_rect(source), self._card_rect(destination)
        source_image = self._capture_card(source)
        image = source_image
        if self._drag_payload is not None and self._drag_payload.instance == instance and self._drag_image is not None:
            image = self._drag_image
        displaced_image = self._capture_card(destination) if self.instances[target_slot] is not None else None
        self._pending_card_images.pop(source, None)
        self._pending_card_images.pop(destination, None)
        if displaced_image is not None:
            self._pending_card_images[source] = displaced_image
        if source_image is not None:
            self._pending_card_images[destination] = source_image
        cards = []
        if source_rect is not None and destination_rect is not None and image is not None:
            if displaced_image is not None:
                cards.append(MovingCard(displaced_image, destination_rect, source_rect))
            cards.append(MovingCard(image, landing_origin or source_rect, destination_rect))
        self._updating = True
        try:
            self.instances[target_slot], self.instances[other_slot] = instance, self.instances[target_slot]
            self.set_active_player(instance)
            for key, (start, end) in self.monitor_slot_ranges.items():
                picker = self.tiling_pickers[key]
                badge = picker.get_parent().get_parent().get_last_child()
                # Legacy badges retain their original count-only presentation.
                if " / " in badge.get_label():
                    occupied = sum(player is not None for player in self.instances[start:end])
                    badge.set_label(f"{occupied} / {end - start} PLAYERS")
            self._clear_drop_highlights()
        finally:
            self._updating = False
        if cards:
            self._motion_size = (self.get_width(), self.get_height())
            self._motion.play(cards, [source, destination])
        self.emit("order-changed", list(self.instances))
        return True

    def set_reposition_enabled(self, enabled: bool):
        """Apply runtime locks without rebuilding cells or losing canvas focus."""
        enabled = bool(enabled)
        for picker in self.tiling_pickers.values():
            picker.set_editable(enabled)
        if enabled == self._allow_reposition:
            return
        self._allow_reposition = enabled
        if not enabled:
            self._motion.finish()
            if self._drag_source is not None and self._drag_source.get_drag() is not None:
                self._drag_source.drag_cancel()
            self._clear_drag_state()
        for slot, widgets in enumerate(self._slots):
            if enabled:
                widgets.cell.add_css_class("slot-editable")
            else:
                widgets.cell.remove_css_class("slot-editable")
            widgets.button.set_cursor_from_name("grab" if enabled else "default")
            self._refresh_slot(slot)

    def add_player_drag_source(self, widget: Gtk.Widget, instance: int) -> Gtk.DragSource:
        """Attach a roster source that checks current participation and locks at prepare time."""
        source = self._make_drag_source(widget)
        source.connect("prepare", self._on_player_drag_prepare, instance)
        return source

    def _can_drag_player(self, instance):
        return (
            not self._updating
            and self._allow_reposition
            and self.is_sensitive()
            and type(instance) is int
            and instance >= 0
            and instance in self.instances
        )

    def _can_assign_player(self, instance, target_slot):
        return (
            self._can_drag_player(instance)
            and type(target_slot) is int
            and 0 <= target_slot < len(self._slots)
            and target_slot < len(self.instances)
            and (
                not self._using_tiling
                or target_slot < sum(end - start for start, end in self.monitor_slot_ranges.values())
            )
            and self._slots[target_slot].cell.is_sensitive()
            and self._slots[target_slot].button.is_sensitive()
            and self.instances[target_slot] != instance
        )

    def _is_current_slot(self, widget, slot):
        return 0 <= slot < len(self._slots) and self._slots[slot].cell is widget

    def _make_drag_source(self, widget):
        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        source.connect("drag-begin", self._on_drag_begin)
        source.connect("drag-end", self._on_drag_end)
        source.connect("drag-cancel", self._on_drag_cancel)
        widget.add_controller(source)
        return source

    def _on_player_drag_prepare(self, source, x, y, instance):
        widget = source.get_widget()
        if widget is None or not widget.is_sensitive() or not self._can_drag_player(instance):
            return None
        self._motion.finish()
        self._clear_drag_state()
        self._drag_source = source
        self._drag_payload = _PlayerDragPayload(self, instance)
        # Freeze before dimming the source: a live paintable would fade or change
        # identity along with the original cell during a successful swap.
        self._drag_image = self._capture_card(widget) or Gtk.WidgetPaintable.new(widget)
        logical_width, logical_height = max(1, widget.get_width()), max(1, widget.get_height())
        bounds = self._card_rect(widget)
        width = max(1, round(bounds.width)) if bounds is not None else logical_width
        height = max(1, round(bounds.height)) if bounds is not None else logical_height
        if (self._drag_image.get_intrinsic_width(), self._drag_image.get_intrinsic_height()) != (width, height):
            snapshot = Gtk.Snapshot()
            self._drag_image.snapshot(snapshot, width, height)
            self._drag_image = snapshot.to_paintable(Graphene.Size().init(width, height))
        self._drag_size = (width, height)
        self._drag_hotspot = (
            round(max(0, min(width - 1, x * width / logical_width))),
            round(max(0, min(height - 1, y * height / logical_height))),
        )
        source.set_icon(self._drag_image, *self._drag_hotspot)
        return Gdk.ContentProvider.new_for_value(self._drag_payload)

    def _on_slot_drag_prepare(self, source, x, y, slot):
        if not self._is_current_slot(source.get_widget(), slot):
            return None
        if not self._slots[slot].button.is_sensitive():
            return None
        return self._on_player_drag_prepare(source, x, y, self.instances[slot])

    def _on_drag_begin(self, source, _drag):
        payload = self._drag_payload
        if source is not self._drag_source or payload is None or not self._can_drag_player(payload.instance):
            source.drag_cancel()
            return
        if self._activation_reset_id:
            GLib.source_remove(self._activation_reset_id)
            self._activation_reset_id = 0
        self._suppress_activation = True
        source.set_state(Gtk.EventSequenceState.CLAIMED)
        source.get_widget().add_css_class("player-dragging")

    def _on_drag_end(self, source, _drag, _delete_data):
        if source is self._drag_source:
            self._clear_drag_state()

    def _on_drag_cancel(self, source, _drag, _reason):
        if source is self._drag_source:
            self._clear_drag_state()
        return False

    def _clear_drag_state(self):
        if self._drag_source is not None:
            widget = self._drag_source.get_widget()
            if widget is not None:
                widget.remove_css_class("player-dragging")
        self._drag_source = None
        self._drag_payload = None
        self._drag_image = None
        self._drag_hotspot = (0, 0)
        self._drag_size = (0, 0)
        self._clear_drop_highlights()
        if self._suppress_activation and not self._activation_reset_id:
            # Release may finish the native drag before the button processes it.
            self._activation_reset_id = GLib.idle_add(self._restore_player_activation)

    def _restore_player_activation(self):
        self._suppress_activation = False
        self._activation_reset_id = 0
        return GLib.SOURCE_REMOVE

    def _clear_drop_highlights(self):
        for widgets in self._slots:
            widgets.cell.remove_css_class("slot-drop-target")

    def _payload_for_drop(self, drop):
        """Authenticate local hover before GTK loads the typed value for the drop."""
        if drop is None or self._drag_source is None:
            return None
        drag = drop.get_drag()
        if (
            drag is None
            or drag != self._drag_source.get_drag()
            or not drop.get_actions() & Gdk.DragAction.MOVE
            or not drop.get_formats().contain_gtype(_PlayerDragPayload)
        ):
            return None
        return self._drag_payload

    def is_player_drag(self, drop: Gdk.Drop | None) -> bool:
        """Authenticate an ongoing local drag for canvas edge scrolling."""
        payload = self._payload_for_drop(drop)
        return (
            isinstance(payload, _PlayerDragPayload)
            and payload.owner is self
            and self._can_drag_player(payload.instance)
        )

    def _can_drop_player(self, target, payload, slot):
        return (
            isinstance(payload, _PlayerDragPayload)
            and payload.owner is self
            and payload is self._drag_payload
            and self._drag_source is not None
            and self._is_current_slot(target.get_widget(), slot)
            and self._can_assign_player(payload.instance, slot)
        )

    def _on_drop_accept(self, target, drop, slot):
        return self._can_drop_player(target, self._payload_for_drop(drop), slot)

    def _on_drop_motion(self, target, _x, _y, slot):
        self._clear_drop_highlights()
        payload = self._payload_for_drop(target.get_current_drop())
        if not self._can_drop_player(target, payload, slot):
            return Gdk.DragAction(0)
        target.get_widget().add_css_class("slot-drop-target")
        return Gdk.DragAction.MOVE

    def _on_drop_leave(self, target):
        widget = target.get_widget()
        if widget is not None:
            widget.remove_css_class("slot-drop-target")

    def _on_player_drop(self, target, payload, x, y, slot):
        self._clear_drop_highlights()
        if not self._can_drop_player(target, payload, slot):
            return False
        found, point = target.get_widget().compute_point(self, Graphene.Point().init(x, y))
        origin = None
        if found and self._drag_image is not None and all(size > 0 for size in self._drag_size):
            origin = CardRect(
                point.x - self._drag_hotspot[0],
                point.y - self._drag_hotspot[1],
                *self._drag_size,
            )
        widget = self._drag_source.get_widget()
        if widget is not None:
            widget.remove_css_class("player-dragging")
        return self._swap_players(payload.instance, slot, origin)

    @staticmethod
    def _make_monitor_header(name, width, height, player_count, mode, orientation):
        header = Gtk.Box(spacing=12, hexpand=True)
        header.add_css_class("canvas-monitor-header")
        icon = Gtk.Image.new_from_icon_name("video-display-symbolic")
        icon.add_css_class("canvas-monitor-icon")
        header.append(icon)
        details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        title = Gtk.Label(label=name, xalign=0, wrap=True)
        title.add_css_class("canvas-monitor-title")
        title.add_css_class("heading")
        details.append(title)
        layout = f"Split screen · {orientation.capitalize()}" if mode == "splitscreen" else "Fullscreen"
        metadata = Gtk.Label(label=f"{width} × {height} · {layout}", xalign=0, wrap=True)
        metadata.add_css_class("canvas-monitor-meta")
        metadata.add_css_class("dim-label")
        details.append(metadata)
        header.append(details)
        count = Gtk.Label(
            label=f"{player_count} {'PLAYER' if player_count == 1 else 'PLAYERS'}", valign=Gtk.Align.START
        )
        count.add_css_class("canvas-monitor-badge")
        header.append(count)
        return header

    @staticmethod
    def _append_warning(box, message):
        warning = Gtk.Label(label=message, xalign=0, wrap=True)
        warning.add_css_class("canvas-warning")
        warning.add_css_class("warning")
        box.append(warning)

    def _make_slot(self, slot, instance, monitor_name, geometry):
        """Keep activation inside a reusable, draggable cell without changing its size request."""
        cell = Gtk.Overlay(hexpand=True, vexpand=True)
        cell.add_css_class("slot-cell")
        if self._allow_reposition:
            cell.add_css_class("slot-editable")

        button = Gtk.Button(hexpand=True, vexpand=True)
        button.add_css_class("slot-button")
        button.set_cursor_from_name("grab" if self._allow_reposition else "default")
        button.connect("clicked", self._on_player_activated, slot)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True, vexpand=True)
        content.add_css_class("slot-content")
        caption = Gtk.Box(spacing=6)
        caption.add_css_class("slot-caption")
        space = Gtk.Label(label=f"SPACE {slot + 1:02d}", xalign=0, hexpand=True)
        space.add_css_class("slot-space")
        caption.append(space)
        action = Gtk.Image.new_from_icon_name("go-next-symbolic")
        action.add_css_class("slot-action")
        caption.append(action)
        content.append(caption)

        identity = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            hexpand=True,
            vexpand=True,
            valign=Gtk.Align.CENTER,
        )
        identity.add_css_class("slot-identity")
        number = Gtk.Label()
        number.add_css_class("slot-number")
        number.add_css_class("title-1")
        identity.append(number)
        name = Gtk.Label(ellipsize=Pango.EllipsizeMode.END)
        name.add_css_class("slot-name")
        name.add_css_class("heading")
        identity.append(name)
        status_row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        status_row.add_css_class("slot-status-row")
        dot = Gtk.Image.new_from_icon_name("media-record-symbolic")
        dot.set_pixel_size(8)
        dot.add_css_class("slot-status-dot")
        status_row.append(dot)
        status = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, max_width_chars=28)
        status.add_css_class("slot-status")
        status_row.append(status)
        identity.append(status_row)
        content.append(identity)

        x, y, width, height = geometry
        dimensions = Gtk.Label(label=f"{width} × {height} · ({x}, {y})", ellipsize=Pango.EllipsizeMode.END)
        dimensions.add_css_class("slot-geometry")
        dimensions.add_css_class("dim-label")
        content.append(dimensions)
        button.set_child(content)
        cell.set_child(button)

        source = self._make_drag_source(cell)
        source.connect("prepare", self._on_slot_drag_prepare, slot)
        target = Gtk.DropTarget.new(_PlayerDragPayload, Gdk.DragAction.MOVE)
        target.connect("accept", self._on_drop_accept, slot)
        target.connect("enter", self._on_drop_motion, slot)
        target.connect("motion", self._on_drop_motion, slot)
        target.connect("leave", self._on_drop_leave)
        target.connect("drop", self._on_player_drop, slot)
        cell.add_controller(target)
        location = f"Space {slot + 1} on {monitor_name}. {width} by {height} pixels at x {x}, y {y}."
        self._slots.append(_PlayerSlot(cell, button, number, name, status, instance, location))
        self._refresh_slot(slot)
        return cell

    def _refresh_slot(self, slot):
        """Refresh identity, live text and selection after either a swap or a status update."""
        widgets = self._slots[slot]
        instance = self.instances[slot]
        old_color = f"player-color-{widgets.instance % 8}" if widgets.instance is not None else None
        color = f"player-color-{instance % 8}" if instance is not None else None
        active = instance is not None and instance == self._active_player
        for widget in (widgets.cell, widgets.button):
            if old_color is not None and old_color != color:
                widget.remove_css_class(old_color)
            if color is not None:
                widget.add_css_class(color)
            if active:
                widget.add_css_class("slot-active")
            else:
                widget.remove_css_class("slot-active")
        widgets.instance = instance
        if instance is None:
            widgets.number.set_label("—")
            widgets.name.set_label("Empty space")
            widgets.status.set_label("Drop a player here")
            widgets.status.set_tooltip_text("Drop a player here")
            widgets.button.set_tooltip_text(f"Empty space · Drop a player here\n{widgets.location}")
            widgets.button.update_property(
                [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
                ["Empty space", f"{widgets.location} Drop a player here."],
            )
            return
        widgets.number.set_label(f"{instance + 1:02d}")
        widgets.name.set_label(f"Player {instance + 1}")
        status = self._player_statuses.get(instance, "Ready to configure")
        widgets.status.set_label(status)
        widgets.status.set_tooltip_text(status)
        interaction = " Drag to another space to swap players." if self._allow_reposition else ""
        description = (
            f"{'Selected player. ' if active else ''}{widgets.location} Activate to configure this player.{interaction}"
        )
        widgets.button.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [f"Player {instance + 1}, {status}", description],
        )
        widgets.button.set_tooltip_text(f"Configure Player {instance + 1} · {status}\n{widgets.location}{interaction}")

    def _on_player_activated(self, button, slot):
        """Resolve the current assignment, not the player present when the button was built."""
        if (
            self._updating
            or self._suppress_activation
            or not 0 <= slot < len(self._slots)
            or self._slots[slot].button is not button
        ):
            return
        instance = self.instances[slot]
        if instance is None:
            return
        self.set_active_player(instance)
        self.emit("player-activated", instance)
