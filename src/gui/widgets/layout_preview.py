"""Monitor previews with accessible instance selectors for each display slot."""

# flake8: noqa: E402

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GObject, Gtk

from src.core.layout import LayoutCalculator


class LayoutPreview(Gtk.Box):
    """Show the actual split geometry and swap instance assignments without duplicates."""

    __gsignals__ = {
        "order-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        """Initialize a preview that can be rebuilt without emitting user changes."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.instances: list[int] = []
        self.slot_selectors: list[Gtk.DropDown] = []
        self.monitor_grids: list[Gtk.Grid] = []
        self.monitor_names: list[str] = []
        self._choices: list[int] = []
        self._updating = False

    def configure(self, instances, mode, orientation, displays, editable):
        """Render selected instances in slot order, using the current monitor aspect ratios."""
        self._updating = True
        try:
            while child := self.get_first_child():
                self.remove(child)
            self.instances = list(instances)
            self._choices = sorted(instances)
            self.slot_selectors = []
            self.monitor_grids = []
            self.monitor_names = []
            if not instances:
                label = Gtk.Label(label="Select at least one instance to preview the layout.", wrap=True)
                label.add_css_class("dim-label")
                self.append(label)
                return

            monitors = displays or [{"name": "Not detected", "width": 1920, "height": 1080}]
            group_size = 4 if mode == "splitscreen" else 1
            for start in range(0, len(instances), group_size):
                group = instances[start : start + group_size]
                requested_monitor = start // group_size
                monitor_index = requested_monitor if requested_monitor < len(monitors) else 0
                monitor = monitors[monitor_index]
                name = f"Monitor {monitor_index + 1} · {monitor.get('name', 'Unknown connector')}"
                self.monitor_names.append(name)
                box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                title = Gtk.Label(label=name, xalign=0, wrap=True)
                title.add_css_class("heading")
                box.append(title)
                if requested_monitor >= len(monitors):
                    warning = Gtk.Label(
                        label="No dedicated display for this group; it shares Monitor 1.", xalign=0, wrap=True
                    )
                    warning.add_css_class("dim-label")
                    box.append(warning)

                grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True, column_spacing=6, row_spacing=6)
                grid.add_css_class("layout-monitor")
                self.monitor_grids.append(grid)
                xs, ys, widths, heights = LayoutCalculator.get_layout_coordinates(len(group), orientation)
                for local_slot, instance in enumerate(group):
                    slot = start + local_slot
                    cell = self._make_slot(slot, instance, name, editable)
                    grid.attach(
                        cell,
                        round(xs[local_slot] * 2),
                        round(ys[local_slot] * 2),
                        round(widths[local_slot] * 2),
                        round(heights[local_slot] * 2),
                    )

                width = max(1, int(monitor.get("width") or 1920))
                height = max(1, int(monitor.get("height") or 1080))
                frame = Gtk.AspectFrame(ratio=width / height, obey_child=False, halign=Gtk.Align.CENTER)
                frame.set_size_request(300, -1)
                frame.set_child(grid)
                box.append(frame)
                self.append(box)
        finally:
            self._updating = False

    def _make_slot(self, slot, instance, monitor_name, editable):
        """Build a labelled selector whose choices are limited to selected instances."""
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True, vexpand=True)
        cell.add_css_class("layout-slot")
        label = Gtk.Label(label=f"Space {slot + 1}", valign=Gtk.Align.END, vexpand=True)
        label.add_css_class("caption-heading")
        cell.append(label)
        selector = Gtk.DropDown(model=Gtk.StringList.new([f"Instance {index + 1}" for index in self._choices]))
        selector.set_selected(self._choices.index(instance))
        selector.set_sensitive(editable)
        selector.set_tooltip_text(
            "Choose an instance; the previous assignments are swapped."
            if editable
            else "Select Custom placement to change this assignment."
        )
        selector.update_property([Gtk.AccessibleProperty.LABEL], [f"Instance for space {slot + 1} on {monitor_name}"])
        label.set_mnemonic_widget(selector)
        selector.connect("notify::selected", self._on_slot_changed, slot)
        self.slot_selectors.append(selector)
        cell.append(selector)
        cell.append(Gtk.Box(vexpand=True))
        return cell

    def _on_slot_changed(self, selector, _pspec, slot):
        """Swap two slots atomically rather than assigning one instance twice."""
        if self._updating or selector not in self.slot_selectors:
            return
        choice = selector.get_selected()
        if not 0 <= choice < len(self._choices):
            return
        instance = self._choices[choice]
        other_slot = self.instances.index(instance)
        if other_slot == slot:
            return
        self.instances[slot], self.instances[other_slot] = self.instances[other_slot], self.instances[slot]
        self._updating = True
        try:
            for index in (slot, other_slot):
                self.slot_selectors[index].set_selected(self._choices.index(self.instances[index]))
        finally:
            self._updating = False
        self.emit("order-changed", list(self.instances))
