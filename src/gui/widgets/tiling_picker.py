"""Compact, native per-monitor tiling selection with vector thumbnails."""

# flake8: noqa: E402

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")

from gi.repository import GObject, Graphene, Gsk, Gtk

from src.core.i18n import ngettext, subscribe, t, translate_template_title
from src.core.tiling import TEMPLATES

_THUMB_WIDTH = 26
_THUMB_HEIGHT = 18
_THUMB_INSET = 2
_BUTTON_WIDTH = 34
_BUTTON_HEIGHT = 26


def _rect(x, y, width, height):
    rect = Graphene.Rect()
    rect.init(x, y, width, height)
    return rect


class _Thumbnail(Gtk.Widget):
    def __init__(self, template):
        super().__init__()
        self.template = template
        self.set_size_request(_THUMB_WIDTH, _THUMB_HEIGHT)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_can_target(False)
        self.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.add_css_class("tiling-thumbnail")

    def do_snapshot(self, snapshot):
        color = self.get_color()
        outline = Gsk.RoundedRect()
        outline.init_from_rect(_rect(0, 0, _THUMB_WIDTH, _THUMB_HEIGHT), 2.5)
        snapshot.append_border(outline, [1.0] * 4, [color] * 4)
        inner_width = _THUMB_WIDTH - 2 * _THUMB_INSET
        inner_height = _THUMB_HEIGHT - 2 * _THUMB_INSET
        # A shared inset and half-pixel gutters preserve the template proportions.
        for x, y, width, height in self.template.rectangles:
            cell = Gsk.RoundedRect()
            cell.init_from_rect(
                _rect(
                    _THUMB_INSET + x * inner_width + 0.5,
                    _THUMB_INSET + y * inner_height + 0.5,
                    width * inner_width - 1,
                    height * inner_height - 1,
                ),
                1,
            )
            snapshot.push_rounded_clip(cell)
            snapshot.append_color(color, cell.bounds)
            snapshot.pop()


class _Option(Gtk.ToggleButton):
    def __init__(self, picker, template_id):
        super().__init__()
        self._picker = picker
        self._template_id = template_id

    def do_clicked(self):
        # Sensitivity alone does not protect against explicitly emitted clicks.
        if not self._picker._editable or self._picker._selected == self._template_id:
            return
        Gtk.ToggleButton.do_clicked(self)


class TilingPicker(Gtk.Box):
    """Choose one template; only user selection emits ``template-selected``.

    Unknown template IDs raise KeyError. Programmatic selection remains available
    while read-only, so loading saved monitor settings never requires unlocking.
    """

    __gsignals__ = {
        "template-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, selected: str = "fullscreen"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.add_css_class("tiling-picker")
        self._editable = True
        self._updating = False
        self._selected = selected
        self.buttons: dict[str, Gtk.ToggleButton] = {}
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_min_children_per_line(1)
        flow.set_max_children_per_line(len(TEMPLATES))
        flow.set_column_spacing(4)
        flow.set_row_spacing(4)
        flow.set_homogeneous(True)
        flow.set_halign(Gtk.Align.START)
        flow.set_hexpand(True)
        self.append(flow)
        first = None
        for template in TEMPLATES.values():
            button = _Option(self, template.id)
            button.add_css_class("tiling-option")
            button.set_size_request(_BUTTON_WIDTH, _BUTTON_HEIGHT)
            button.set_halign(Gtk.Align.START)
            button.set_valign(Gtk.Align.CENTER)
            button.set_child(_Thumbnail(template))
            description = self._format_template_description(template)
            button.set_tooltip_text(description)
            button.update_property([Gtk.AccessibleProperty.LABEL], [description])
            if first is None:
                first = button
            else:
                button.set_group(first)
            self.buttons[template.id] = button
            button.connect("toggled", self._on_toggled, template.id)
            flow.insert(button, -1)
            button.get_parent().set_focusable(False)
        self.set_selected(selected)
        subscribe(self.retranslate)

    def _format_template_description(self, template) -> str:
        capacity = ngettext("tiling.capacity_one", "tiling.capacity_many", template.capacity)
        title = translate_template_title(template.id, template.title)
        return t("tiling.tooltip", title=title, capacity=capacity)

    def retranslate(self, *_args):
        """Update template tooltips and accessible labels for the active language."""
        for template_id, button in self.buttons.items():
            template = TEMPLATES.get(template_id)
            if template is not None:
                description = self._format_template_description(template)
                button.set_tooltip_text(description)
                button.update_property([Gtk.AccessibleProperty.LABEL], [description])

    def set_selected(self, template_id):
        """Synchronize selection without notifying profile-change listeners."""
        button = self.buttons[template_id] if template_id is not None else None
        self._updating = True
        try:
            self._selected = template_id
            if button is not None:
                button.set_active(True)
            else:
                for option in self.buttons.values():
                    option.set_active(False)
        finally:
            self._updating = False

    def set_editable(self, editable):
        """Disable interaction while retaining the selected template."""
        self._editable = bool(editable)
        for button in self.buttons.values():
            button.set_sensitive(self._editable)

    def _on_toggled(self, button, template_id):
        if self._updating:
            return
        if not self._editable:
            self.set_selected(self._selected)
            return
        if button.get_active() and template_id != self._selected:
            self._selected = template_id
            self.emit("template-selected", template_id)
