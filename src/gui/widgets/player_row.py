"""Standalone selected-player inspector."""

# flake8: noqa: E402

import os
import weakref
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GObject, Gtk, Pango

from src.core.i18n import TRANSLATIONS, t
from src.core.utils import format_input_device_name
from src.gui.widgets.env_variable_row import EnvVariableRow
from src.gui.widgets.marquee_label import MarqueeLabel
from src.gui.widgets.spinner import StudioSpinner
from src.models import DEFAULT_PLAYER_NAME, PlayerInstanceConfig

# Only a confirmed Steam client is running; a pending launch can be cancelled.
INSTANCE_IDLE = "idle"
INSTANCE_STARTING = "starting"
INSTANCE_RUNNING = "running"
INSTANCE_STOPPING = "stopping"

_DEFAULT_PLAYER_NAMES = frozenset({DEFAULT_PLAYER_NAME, *(cat["player.default_name"] for cat in TRANSLATIONS.values())})


class _ControllerOptionRow(Gtk.Box):
    """Dropdown list row with marquee scrolling for long controller names and a selection dot."""

    def __init__(self, max_width: int = 220):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, hexpand=True)
        self.add_css_class("inspector-controller-option")
        self.label = MarqueeLabel(max_width=max_width)
        self.label.add_css_class("inspector-controller-option-label")
        self.dot = Gtk.Image.new_from_icon_name("twinverse-dot-symbolic")
        self.dot.set_pixel_size(14)
        self.dot.set_valign(Gtk.Align.CENTER)
        self.dot.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        self.dot.add_css_class("inspector-controller-selected-dot")
        self.dot.set_opacity(0.0)
        self.append(self.label)
        self.append(self.dot)
        self._selection_handler = 0
        self._bound_item: Optional[GObject.Object] = None
        self._selected = False

    def is_selected_option(self) -> bool:
        """Return whether this row currently shows the selected dot indicator."""
        return self._selected

    def set_selected(self, selected: bool) -> None:
        """Show or hide the selection dot without shifting option text alignment."""
        self._selected = bool(selected)
        self.dot.set_opacity(1.0 if self._selected else 0.0)
        if self._selected:
            self.add_css_class("is-selected")
        else:
            self.remove_css_class("is-selected")

    def sync_selected(self, dropdown: Gtk.DropDown, _pspec=None) -> None:
        """Sync the selection dot against the dropdown's currently selected item."""
        self.set_selected(self._bound_item is not None and dropdown.get_selected_item() == self._bound_item)


class PlayerRow(Gtk.Box):
    """Configure and control one player independently of the player roster."""

    __gsignals__ = {
        "settings-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "status-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "launch-clicked": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        "refresh-devices-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, player_num: int, devices_info: dict, **kwargs):
        """Create an inspector; its unparented checkbox belongs in the roster."""
        super().__init__(**kwargs)
        self.set_orientation(Gtk.Orientation.VERTICAL)
        self.set_size_request(300, -1)
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.START)
        self.add_css_class("inspector-player")

        self._player_num = player_num
        self._custom_name: Optional[str] = None
        self._player_name = t("player.default_name")
        self._editing_name = False
        self._devices_info = {kind: list(devices_info.get(kind, [])) for kind in ("joystick", "audio")}
        self._joystick_options, _ = self._build_joystick_options(self._devices_info["joystick"])
        self._parent_page = None
        self._is_loading = False
        self._is_verified = False
        self._is_running = False
        self._network_isolation_enabled = True
        self._state = INSTANCE_IDLE
        self._status_detail = ""
        self._update_progress: Optional[tuple[str, Optional[int]]] = None
        self._env_rows: list[EnvVariableRow] = []
        self._build_ui()
        self._update_button_state()
        self._update_status_icon()

    def _build_ui(self):
        self.checkbox = Gtk.CheckButton(active=True)
        self.checkbox.add_css_class("player-checkbox")
        self._sync_checkbox_accessibility()
        self.checkbox.connect("toggled", self._on_checkbox_toggled)

        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        self._content.add_css_class("inspector-content")
        self._content.set_margin_start(16)
        self._content.set_margin_end(16)
        self._content.set_margin_top(20)
        self._content.set_margin_bottom(20)
        self.append(self._content)

        self._create_header()
        self._content.append(Gtk.Separator())
        self._create_device_rows()
        self._content.append(Gtk.Separator())
        self._create_env_section()

    def _create_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        header.add_css_class("inspector-header")
        identity = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        avatar = Gtk.Label(label=f"{self._player_num + 1:02d}", valign=Gtk.Align.START)
        avatar.set_size_request(44, 44)
        avatar.add_css_class("inspector-avatar")
        avatar.add_css_class("party-avatar")
        avatar.add_css_class(f"player-color-{self._player_num % 8}")
        identity.append(avatar)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self._name_stack = Gtk.Stack(vhomogeneous=False, hhomogeneous=False, hexpand=True)
        self._name_display_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, hexpand=True)
        self.title_label = Gtk.Label(
            label=self._player_name,
            xalign=0,
            ellipsize=Pango.EllipsizeMode.END,
        )
        self.title_label.add_css_class("inspector-title")
        self._name_display_box.append(self.title_label)

        self.edit_name_button = Gtk.Button(icon_name="twinverse-edit-symbolic", valign=Gtk.Align.CENTER)
        self.edit_name_button.add_css_class("flat")
        self.edit_name_button.add_css_class("inspector-edit-name-button")
        self.edit_name_button.set_tooltip_text(t("player.edit_name_tooltip"))
        self.edit_name_button.update_property([Gtk.AccessibleProperty.LABEL], [t("player.edit_name_tooltip")])
        self.edit_name_button.connect("clicked", lambda *_: self.start_name_edit())
        self._name_display_box.append(self.edit_name_button)

        self.name_entry = Gtk.Entry(placeholder_text=t("player.default_name"), max_length=32, hexpand=True)
        self.name_entry.set_width_chars(1)
        self.name_entry.add_css_class("inspector-entry")
        self.name_entry.add_css_class("inspector-name-entry")
        self.name_entry.connect("activate", lambda *_: self.commit_name_edit())
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_name_entry_key_pressed)
        self.name_entry.add_controller(key_controller)
        focus_controller = Gtk.EventControllerFocus()
        focus_controller.connect("leave", lambda *_: self.commit_name_edit())
        self.name_entry.add_controller(focus_controller)

        self._name_stack.add_named(self._name_display_box, "display")
        self._name_stack.add_named(self.name_entry, "edit")
        self._name_stack.set_visible_child_name("display")
        titles.append(self._name_stack)

        self._status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._status_box.add_css_class("inspector-status-line")
        self.status_icon = Gtk.Image()
        self.status_icon.add_css_class("inspector-status-icon")
        self.status_spinner = StudioSpinner(size=14)
        self.status_spinner.add_css_class("inspector-status-icon")
        self.status_label = Gtk.Label(xalign=0, wrap=True)
        self.status_label.add_css_class("inspector-status")
        self._status_box.append(self.status_icon)
        self._status_box.append(self.status_spinner)
        self._status_box.append(self.status_label)
        titles.append(self._status_box)
        identity.append(titles)
        header.append(identity)

        self.status_detail_label = Gtk.Label(
            label="",
            xalign=0,
            wrap=False,
            single_line_mode=True,
            ellipsize=Pango.EllipsizeMode.END,
            hexpand=True,
            visible=False,
        )
        self.status_detail_label.add_css_class("inspector-detail")
        self.status_detail_label.add_css_class("inspector-console-log")
        header.append(self.status_detail_label)

        self.launch_button = Gtk.Button(label=t("player.action.install"))
        self.launch_button.set_size_request(-1, 40)
        self.launch_button.add_css_class("inspector-action")
        self.launch_button.connect("clicked", self._on_launch_clicked)
        header.append(self.launch_button)
        self._content.append(header)

    def _sync_checkbox_accessibility(self):
        label = f"{self._player_name} {self._player_num + 1:02d}"
        self.checkbox.set_tooltip_text(t("player.include_tooltip", label=label))
        self.checkbox.update_property([Gtk.AccessibleProperty.LABEL], [t("player.include_a11y", label=label)])

    def get_player_name(self) -> str:
        """Return the display name for this player (defaults to localized 'Player')."""
        return self._player_name

    def set_player_name(self, name: Optional[str]):
        """Update the player's display name without reporting a configuration edit."""
        cleaned = (name or "").strip()
        if not cleaned or cleaned in _DEFAULT_PLAYER_NAMES:
            self._custom_name = None
            normalized = t("player.default_name")
        else:
            self._custom_name = cleaned
            normalized = cleaned
        self._editing_name = False
        self._player_name = normalized
        self.title_label.set_label(normalized)
        self.title_label.set_tooltip_text(self._custom_name)
        self._name_stack.set_visible_child_name("display")
        self._sync_checkbox_accessibility()

    def start_name_edit(self):
        """Switch the player title into inline edit mode."""
        self._editing_name = True
        self.name_entry.set_text(self._player_name)
        self._name_stack.set_visible_child_name("edit")
        self.name_entry.grab_focus()
        self.name_entry.select_region(0, -1)

    def commit_name_edit(self):
        """Save the edited player name and return to display mode."""
        if not self._editing_name:
            return
        self._editing_name = False
        cleaned = self.name_entry.get_text().strip()
        if not cleaned or cleaned in _DEFAULT_PLAYER_NAMES:
            new_custom = None
            normalized = t("player.default_name")
        else:
            new_custom = cleaned
            normalized = cleaned
        changed = new_custom != self._custom_name or normalized != self._player_name
        self._custom_name = new_custom
        self._player_name = normalized
        self.title_label.set_label(normalized)
        self.title_label.set_tooltip_text(self._custom_name)
        self._name_stack.set_visible_child_name("display")
        self._sync_checkbox_accessibility()
        if changed:
            self._on_setting_changed()

    def cancel_name_edit(self):
        """Discard in-progress name edits and return to display mode."""
        if not self._editing_name:
            return
        self._editing_name = False
        self._name_stack.set_visible_child_name("display")

    def _on_name_entry_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.cancel_name_edit()
            return True
        return False

    def _create_device_rows(self):
        self.refresh_controllers_button = Gtk.Button(icon_name="twinverse-refresh-symbolic", valign=Gtk.Align.CENTER)
        self.refresh_controllers_button.add_css_class("flat")
        self.refresh_controllers_button.add_css_class("inspector-refresh-button")
        self.refresh_controllers_button.set_tooltip_text(t("player.refresh_controllers"))
        self.refresh_controllers_button.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("player.refresh_controllers")]
        )
        self.refresh_controllers_button.connect("clicked", self._on_refresh_joysticks_clicked)

        controls, self._controls_heading_label = self._create_section(
            t("player.controls_section"), "twinverse-gamepad-symbolic", action=self.refresh_controllers_button
        )
        self.joystick_row = self._create_dropdown(
            self._joystick_dropdown_labels(), on_selected=self._on_joystick_selected
        )
        self.joystick_row.set_list_factory(self._create_controller_list_factory(self.joystick_row))
        self._controller_field, self._controller_label = self._create_field(
            t("player.controller_label"), self.joystick_row
        )
        self._controller_field.set_tooltip_text(t("player.controller_tooltip"))
        controls.append(self._controller_field)

        grab_line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        grab_line.add_css_class("inspector-toggle")
        grab_labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        self._grab_label = Gtk.Label(label=t("player.grab_mouse_label"), use_underline=True, xalign=0)
        self._grab_label.add_css_class("inspector-field-label")
        grab_labels.append(self._grab_label)
        self._grab_help = self._help_label(t("player.grab_mouse_help"))
        grab_labels.append(self._grab_help)
        grab_line.append(grab_labels)
        self.grab_input_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.grab_input_switch.add_css_class("inspector-switch")
        self._grab_label.set_mnemonic_widget(self.grab_input_switch)
        self.grab_input_switch.connect("notify::active", self._on_grab_input_toggled)
        grab_line.append(self.grab_input_switch)
        controls.append(grab_line)

        self._content.append(Gtk.Separator())
        audio_section, self._audio_heading_label = self._create_section(
            t("player.audio_section"), "twinverse-audio-symbolic"
        )
        audio = self._devices_info["audio"]
        self.audio_row = self._create_dropdown([t("player.audio_default")] + [device["name"] for device in audio])
        audio_field, self._audio_label = self._create_field(t("player.output_device_label"), self.audio_row)
        audio_section.append(audio_field)

        self._content.append(Gtk.Separator())
        network_section, self._network_heading_label = self._create_section(
            t("player.network_section"), "twinverse-network-symbolic"
        )
        self.guest_ip_row = Gtk.Entry(placeholder_text=t("player.guest_ip_placeholder"), hexpand=True)
        self.guest_ip_row.set_width_chars(1)
        self.guest_ip_row.set_max_width_chars(24)
        self.guest_ip_row.add_css_class("inspector-entry")
        self.guest_ip_row.set_tooltip_text(t("player.guest_ip_tooltip"))
        self.guest_ip_row.connect("changed", self._on_setting_changed)
        guest_field, self._guest_ip_label = self._create_field(t("player.guest_ip_label"), self.guest_ip_row)
        self._guest_ip_help = self._help_label(t("player.guest_ip_help"))
        guest_field.append(self._guest_ip_help)
        network_section.append(guest_field)

    def _create_section(self, title: str, icon_name: str, action: Optional[Gtk.Widget] = None):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        section.add_css_class("inspector-section")
        heading, heading_label = self._section_heading(title, icon_name, action=action)
        section.append(heading)
        self._content.append(section)
        return section, heading_label

    @staticmethod
    def _section_heading(title: str, icon_name: str, action: Optional[Gtk.Widget] = None):
        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        heading.add_css_class("inspector-section-heading")
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.add_css_class("inspector-section-icon")
        label = Gtk.Label(label=title, xalign=0, hexpand=True)
        label.add_css_class("inspector-section-title")
        heading.append(icon)
        heading.append(label)
        if action is not None:
            heading.append(action)
        return heading, label

    @staticmethod
    def _help_label(text: str):
        label = Gtk.Label(label=text, xalign=0, wrap=True, hexpand=True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_max_width_chars(28)
        label.add_css_class("inspector-help")
        return label

    @staticmethod
    def _create_field(title: str, control, mnemonic_widget=None):
        field = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        field.add_css_class("inspector-field")
        label = Gtk.Label(label=title, use_underline=True, xalign=0)
        label.add_css_class("inspector-field-label")
        label.set_mnemonic_widget(mnemonic_widget if mnemonic_widget is not None else control)
        field.append(label)
        field.append(control)
        return field, label

    def _create_dropdown(self, labels: list[str], on_selected=None):
        dropdown = Gtk.DropDown(model=Gtk.StringList.new(labels), hexpand=True, enable_search=True)
        dropdown.add_css_class("inspector-dropdown")
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_dropdown_item)
        factory.connect("bind", self._bind_dropdown_item)
        dropdown.set_factory(factory)
        dropdown.connect("notify::selected", on_selected if on_selected is not None else self._on_setting_changed)
        return dropdown

    def _create_controller_list_factory(self, dropdown: Gtk.DropDown) -> Gtk.SignalListItemFactory:
        # Use a weak reference so the factory closure never forms a reference cycle with the dropdown.
        dropdown_ref = weakref.ref(dropdown)
        list_factory = Gtk.SignalListItemFactory()
        list_factory.connect("setup", self._setup_controller_list_item)
        list_factory.connect("bind", self._bind_controller_list_item, dropdown_ref)
        list_factory.connect("unbind", self._unbind_controller_list_item, dropdown_ref)
        return list_factory

    @staticmethod
    def _setup_controller_list_item(_factory, item):
        item.set_child(_ControllerOptionRow())

    @staticmethod
    def _bind_controller_list_item(_factory, item, dropdown_ref):
        dropdown = dropdown_ref()
        row = item.get_child()
        if dropdown is None or not isinstance(row, _ControllerOptionRow):
            return
        if row._selection_handler:
            dropdown.disconnect(row._selection_handler)
            row._selection_handler = 0
        list_obj = item.get_item()
        text = list_obj.get_string() if list_obj is not None else ""
        row._bound_item = list_obj
        row.label.set_text(text)
        row.set_tooltip_text(text)
        row.sync_selected(dropdown)
        row._selection_handler = dropdown.connect("notify::selected-item", row.sync_selected)

    @staticmethod
    def _unbind_controller_list_item(_factory, item, dropdown_ref):
        dropdown = dropdown_ref()
        row = item.get_child()
        if not isinstance(row, _ControllerOptionRow):
            return
        if dropdown is not None and row._selection_handler:
            dropdown.disconnect(row._selection_handler)
        row._selection_handler = 0
        row._bound_item = None
        row.set_selected(False)
        row.label.stop()

    @staticmethod
    def _setup_dropdown_item(_factory, item):
        # Long option labels must not force the entire inspector wider.
        label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=20)
        item.set_child(label)

    @staticmethod
    def _bind_dropdown_item(_factory, item):
        text = item.get_item().get_string()
        item.get_child().set_text(text)
        item.get_child().set_tooltip_text(text)

    @staticmethod
    def _format_joystick_label(option: dict) -> str:
        name = (option.get("name") or "").strip() or format_input_device_name(option.get("id") or "")
        if option.get("disconnected"):
            return t("player.controller_disconnected_label", name=name)
        return name

    def _joystick_dropdown_labels(self) -> list[str]:
        return [t("player.controller_none")] + [self._format_joystick_label(opt) for opt in self._joystick_options]

    @staticmethod
    def _find_connected_device_index(device_list: list[dict], device_id: str) -> Optional[int]:
        canonical_id = os.path.realpath(device_id) if os.path.isabs(device_id) else None
        for index, device in enumerate(device_list):
            if device["id"] == device_id or (
                canonical_id is not None and os.path.realpath(device["id"]) == canonical_id
            ):
                return index
        return None

    @classmethod
    def _build_joystick_options(
        cls,
        connected_devices: list[dict],
        remembered_id: Optional[str] = None,
        remembered_name: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        options = [
            {
                "id": device["id"],
                "name": (device.get("name") or "").strip() or format_input_device_name(device["id"]),
                "disconnected": False,
            }
            for device in connected_devices
        ]
        cleaned_id = (remembered_id or "").strip()
        if not cleaned_id:
            return options, 0

        connected_idx = cls._find_connected_device_index(connected_devices, cleaned_id)
        if connected_idx is not None:
            return options, connected_idx + 1

        display_name = (remembered_name or "").strip() or format_input_device_name(cleaned_id) or cleaned_id
        options.append({"id": cleaned_id, "name": display_name, "disconnected": True})
        return options, len(options)

    def _rebuild_joystick_model(self, device_id: Optional[str], device_name: Optional[str] = None) -> None:
        self._joystick_options, selected_idx = self._build_joystick_options(
            self._devices_info["joystick"], device_id, device_name
        )
        self.joystick_row.set_model(Gtk.StringList.new(self._joystick_dropdown_labels()))
        self.joystick_row.set_selected(selected_idx)
        self._sync_joystick_disconnected_style()

    def _selected_joystick_option(self) -> Optional[dict]:
        selected_idx = self.joystick_row.get_selected()
        if 0 < selected_idx <= len(self._joystick_options):
            return self._joystick_options[selected_idx - 1]
        return None

    def _prune_unselected_disconnected_joystick(self) -> None:
        if not self._joystick_options or not self._joystick_options[-1].get("disconnected"):
            return
        if self.joystick_row.get_selected() == len(self._joystick_options):
            return
        self._joystick_options.pop()
        model = self.joystick_row.get_model()
        if isinstance(model, Gtk.StringList) and model.get_n_items() == len(self._joystick_options) + 2:
            was_loading = self._is_loading
            self._is_loading = True
            try:
                model.remove(model.get_n_items() - 1)
            finally:
                self._is_loading = was_loading

    def _sync_joystick_disconnected_style(self) -> None:
        opt = self._selected_joystick_option()
        if opt is not None and opt.get("disconnected"):
            self.joystick_row.add_css_class("controller-disconnected")
        else:
            self.joystick_row.remove_css_class("controller-disconnected")

    def _on_joystick_selected(self, *_args):
        if self._is_loading:
            return
        self._prune_unselected_disconnected_joystick()
        self._sync_joystick_disconnected_style()
        self._on_setting_changed()

    def _create_env_section(self):
        self.env_expander = Gtk.Expander()
        self.env_expander.add_css_class("inspector-env-expander")
        env_heading, self._env_heading_label = self._section_heading(
            t("player.env_section"), "twinverse-terminal-symbolic"
        )
        self.env_expander.set_label_widget(env_heading)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(12)
        self._env_help = self._help_label(t("player.env_help"))
        body.append(self._env_help)
        self._env_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._env_box.add_css_class("inspector-env-list")
        body.append(self._env_box)
        self._env_add_button = Gtk.Button(label=t("player.env_add"), halign=Gtk.Align.START)
        self._env_add_button.add_css_class("inspector-env-add")
        self._env_add_button.connect("clicked", self._on_add_env_clicked)
        body.append(self._env_add_button)
        self.env_expander.set_child(body)
        self._content.append(self.env_expander)

    def retranslate(self):
        """Update all inspector text, placeholders, tooltips, and default options in place."""
        was_loading = self._is_loading
        self._is_loading = True
        try:
            if self._custom_name is None:
                self._player_name = t("player.default_name")
                self.title_label.set_label(self._player_name)
                self.title_label.set_tooltip_text(None)
            self.name_entry.set_placeholder_text(t("player.default_name"))
            self.edit_name_button.set_tooltip_text(t("player.edit_name_tooltip"))
            self.edit_name_button.update_property([Gtk.AccessibleProperty.LABEL], [t("player.edit_name_tooltip")])
            self._sync_checkbox_accessibility()

            self.refresh_controllers_button.set_tooltip_text(t("player.refresh_controllers"))
            self.refresh_controllers_button.update_property(
                [Gtk.AccessibleProperty.LABEL], [t("player.refresh_controllers")]
            )
            self._controls_heading_label.set_label(t("player.controls_section"))
            self._controller_label.set_label(t("player.controller_label"))
            self._controller_field.set_tooltip_text(t("player.controller_tooltip"))
            self._grab_label.set_label(t("player.grab_mouse_label"))
            self._grab_help.set_text(t("player.grab_mouse_help"))

            self._audio_heading_label.set_label(t("player.audio_section"))
            self._audio_label.set_label(t("player.output_device_label"))

            self._network_heading_label.set_label(t("player.network_section"))
            self.guest_ip_row.set_placeholder_text(t("player.guest_ip_placeholder"))
            self.guest_ip_row.set_tooltip_text(t("player.guest_ip_tooltip"))
            self._guest_ip_label.set_label(t("player.guest_ip_label"))
            self.set_network_isolation_enabled(self._network_isolation_enabled)

            self._env_heading_label.set_label(t("player.env_section"))
            self._env_help.set_text(t("player.env_help"))
            self._env_add_button.set_label(t("player.env_add"))
            for env_row in self._env_rows:
                env_row.retranslate()

            joystick_model = self.joystick_row.get_model()
            expected_joystick_labels = self._joystick_dropdown_labels()
            if isinstance(joystick_model, Gtk.StringList) and joystick_model.get_n_items() == len(
                expected_joystick_labels
            ):
                selected_idx = self.joystick_row.get_selected()
                for idx, label in enumerate(expected_joystick_labels):
                    if joystick_model.get_string(idx) != label:
                        joystick_model.splice(idx, 1, [label])
                if self.joystick_row.get_selected() != selected_idx:
                    self.joystick_row.set_selected(selected_idx)
            else:
                selected_joystick = self._selected_joystick_option()
                self._rebuild_joystick_model(
                    selected_joystick["id"] if selected_joystick is not None else None,
                    selected_joystick.get("name") if selected_joystick is not None else None,
                )

            audio_model = self.audio_row.get_model()
            audio_default = t("player.audio_default")
            if isinstance(audio_model, Gtk.StringList) and audio_model.get_n_items() >= 1:
                selected_idx = self.audio_row.get_selected()
                if audio_model.get_string(0) != audio_default:
                    audio_model.splice(0, 1, [audio_default])
                    if self.audio_row.get_selected() != selected_idx:
                        self.audio_row.set_selected(selected_idx)
            else:
                self.update_devices(self._devices_info)

            self._update_button_state()
            self._update_status_icon()
        finally:
            self._is_loading = was_loading

    def _on_add_env_clicked(self, _button):
        self._add_env_row().key_entry.grab_focus()

    def _add_env_row(self, key: str = "", value: str = ""):
        env_row = EnvVariableRow(key, value)
        env_row.connect("remove-requested", self._on_env_row_remove_requested)
        env_row.connect("changed", self._on_setting_changed)
        self._env_box.append(env_row)
        self._env_rows.append(env_row)
        self._on_setting_changed()
        return env_row

    def _on_env_row_remove_requested(self, env_row):
        if env_row in self._env_rows:
            self._env_box.remove(env_row)
            self._env_rows.remove(env_row)
            self._on_setting_changed()

    def _on_setting_changed(self, *_args):
        if not self._is_loading:
            self.emit("settings-changed")

    def _on_refresh_joysticks_clicked(self, _button):
        self.emit("refresh-devices-requested")

    def _on_launch_clicked(self, _button):
        self.emit("launch-clicked", self._player_num)

    def _on_checkbox_toggled(self, *_args):
        self._on_setting_changed()

    def set_selected(self, selected: bool):
        """Set roster participation without reporting a configuration edit."""
        was_loading = self._is_loading
        self._is_loading = True
        try:
            self.checkbox.set_active(selected)
        finally:
            self._is_loading = was_loading

    def is_selected(self) -> bool:
        """Return whether this player participates in the session."""
        return self.checkbox.get_active()

    def has_controller_selected(self) -> bool:
        """Return whether this player currently has a controller assigned (connected or remembered)."""
        return self._selected_joystick_option() is not None

    def is_controller_connected(self) -> bool:
        """Return whether this player's assigned controller is currently connected."""
        opt = self._selected_joystick_option()
        return opt is not None and not opt.get("disconnected", False)

    def get_selected_controller_name(self) -> Optional[str]:
        """Return the display label of the controller currently assigned to this player."""
        opt = self._selected_joystick_option()
        if opt is None:
            return None
        return self._format_joystick_label(opt) or opt.get("id") or None

    def has_grab_mouse(self) -> bool:
        """Return whether this player currently has mouse capture enabled."""
        return bool(self.grab_input_switch.get_active())

    def _on_grab_input_toggled(self, _switch, _gparam):
        if self._is_loading:
            return
        if self._parent_page is not None:
            self._parent_page._handle_grab_input_exclusivity(self._player_num)
        self._on_setting_changed()

    def set_parent_page(self, parent_page):
        """Delegate mouse-grab exclusivity to the page that owns all players."""
        self._parent_page = parent_page

    def update_devices(self, devices_info: dict):
        """Replace device models while retaining assignments by ID, even when disconnected."""
        selected_joystick = self._selected_joystick_option()
        current_joystick_id = selected_joystick["id"] if selected_joystick is not None else None
        current_joystick_name = selected_joystick.get("name") if selected_joystick is not None else None
        current_audio = self._get_combo_device_id(self.audio_row, self._devices_info["audio"])
        was_loading = self._is_loading
        self._is_loading = True
        try:
            self._devices_info = {kind: list(devices_info.get(kind, [])) for kind in ("joystick", "audio")}
            self._rebuild_joystick_model(current_joystick_id, current_joystick_name)
            audio_devices = self._devices_info["audio"]
            self.audio_row.set_model(
                Gtk.StringList.new([t("player.audio_default")] + [device["name"] for device in audio_devices])
            )
            self._set_combo_selection(self.audio_row, audio_devices, current_audio)
        finally:
            self._is_loading = was_loading

    def load_config(self, config: PlayerInstanceConfig):
        """Restore settings silently, retaining remembered controllers even when disconnected."""
        was_loading = self._is_loading
        self._is_loading = True
        try:
            self.set_player_name(config.name)
            self.grab_input_switch.set_active(config.grab_input_devices)
            self._rebuild_joystick_model(config.physical_device_id, config.physical_device_name)
            self._set_combo_selection(self.audio_row, self._devices_info["audio"], config.audio_device_id)
            self.guest_ip_row.set_text(config.guest_ip or "")
            for env_row in self._env_rows:
                self._env_box.remove(env_row)
            self._env_rows.clear()
            for key, value in (config.env or {}).items():
                self._add_env_row(key, value)
            self.env_expander.set_expanded(bool(self._env_rows))
        finally:
            self._is_loading = was_loading

    def get_config(self) -> PlayerInstanceConfig:
        """Read settings; environment values are deliberately not stripped."""
        selected_joystick = self._selected_joystick_option()
        joystick_id = selected_joystick["id"] if selected_joystick is not None else None
        joystick_name = (selected_joystick.get("name") or "").strip() or None if selected_joystick is not None else None
        return PlayerInstanceConfig(
            NAME=self._custom_name,
            PHYSICAL_DEVICE_ID=joystick_id,
            PHYSICAL_DEVICE_NAME=joystick_name,
            GRAB_INPUT_DEVICES=self.grab_input_switch.get_active(),
            AUDIO_DEVICE_ID=self._get_combo_device_id(self.audio_row, self._devices_info["audio"]),
            ENV=self._collect_env_vars(),
            GUEST_IP=self.guest_ip_row.get_text().strip() or None,
        )

    def set_network_isolation_enabled(self, enabled: bool):
        """Enable or disable the Guest IP field to match the network isolation setting."""
        self._network_isolation_enabled = bool(enabled)
        self.guest_ip_row.set_sensitive(enabled)
        if enabled:
            self._guest_ip_help.set_text(t("player.guest_ip_help"))
        else:
            self._guest_ip_help.set_text(t("player.guest_ip_help_disabled"))

    def set_running_state(self, is_running: bool):
        """Keep the legacy running flag and the instance state in sync."""
        self.set_instance_state(INSTANCE_RUNNING if is_running else INSTANCE_IDLE)

    def set_instance_state(self, state: str):
        """Update runtime presentation without dirtying the profile."""
        changed = self._state != state
        self._state = state
        self._is_running = state == INSTANCE_RUNNING
        self._update_button_state()
        self._update_status_icon()
        if changed:
            self.emit("status-changed")

    def get_instance_state(self) -> str:
        """Return the current instance state."""
        return self._state

    def set_status_detail(self, detail: str):
        """Show launch or failure details as readable text, not just a tooltip."""
        detail = detail or ""
        if detail != self._status_detail:
            self._status_detail = detail
            self._update_status_icon()
            self.emit("status-changed")

    def get_status_detail(self) -> str:
        """Return the latest launch detail supplied by the presenter."""
        return self._status_detail

    def get_status_text(self) -> str:
        """Return a short, human-readable status suitable for the roster."""
        if self._state == INSTANCE_STOPPING:
            return t("status.stopping")
        if self._update_progress is not None:
            percent = self._update_progress[1]
            return t("status.updating") if percent is None else t("status.updating_percent", percent=percent)
        if self._state == INSTANCE_STARTING:
            return t("status.starting")
        if self._state == INSTANCE_RUNNING:
            return t("status.running")
        return t("status.ready") if self._is_verified else t("status.not_installed")

    def set_update_progress(self, detail: str, percent: Optional[int] = None):
        """Record Steam update progress for the status text and observers."""
        percent = None if percent is None else max(0, min(100, percent))
        progress = (detail or "", percent)
        changed = self._update_progress != progress
        self._update_progress = progress
        self._update_status_icon()
        if changed:
            self.emit("status-changed")

    def clear_update_progress(self):
        """Clear Steam update progress when the update finishes."""
        changed = self._update_progress is not None
        self._update_progress = None
        self._update_status_icon()
        if changed:
            self.emit("status-changed")

    def set_verification_status(self, is_verified: bool):
        """Update installation readiness and notify roster status observers."""
        changed = self._is_verified != is_verified
        self._is_verified = is_verified
        self._update_button_state()
        self._update_status_icon()
        if changed:
            self.emit("status-changed")

    def _update_button_state(self):
        self.launch_button.remove_css_class("suggested-action")
        self.launch_button.remove_css_class("destructive-action")
        if self._state == INSTANCE_RUNNING:
            label = t("player.action.stop")
            tooltip = t("player.action.stop_tooltip")
            style = "destructive-action"
        elif self._state == INSTANCE_STARTING:
            label = t("player.action.cancel")
            tooltip = t("player.action.cancel_tooltip")
            style = None
        elif self._state == INSTANCE_STOPPING:
            label = t("player.action.stopping")
            tooltip = t("player.action.stopping_tooltip")
            style = None
        elif self._is_verified:
            label = t("player.action.start")
            tooltip = t("player.action.start_tooltip")
            style = "suggested-action"
        else:
            label = t("player.action.install")
            tooltip = t("player.action.install_tooltip")
            style = "suggested-action"
        self.launch_button.set_label(label)
        self.launch_button.set_tooltip_text(tooltip)
        self.launch_button.set_sensitive(self._state != INSTANCE_STOPPING)
        if style:
            self.launch_button.add_css_class(style)

    def _update_status_icon(self):
        busy = self._state in (INSTANCE_STARTING, INSTANCE_STOPPING) or self._update_progress is not None
        self.status_spinner.set_spinning(busy)
        self.status_spinner.set_visible(busy)
        self.status_icon.set_visible(not busy)
        if self._state in (INSTANCE_STARTING, INSTANCE_STOPPING):
            style = self._state
        elif self._update_progress is not None:
            style = "starting"
        elif self._state == INSTANCE_RUNNING:
            style = "running"
        else:
            style = "ready" if self._is_verified else "unverified"
        for state in ("starting", "running", "stopping", "ready", "unverified"):
            self._status_box.remove_css_class(f"inspector-{state}")
        self._status_box.add_css_class(f"inspector-{style}")
        icon = "twinverse-play-symbolic" if self._is_running else "twinverse-check-symbolic"
        self.status_icon.set_from_icon_name(
            icon if self._is_verified or self._is_running else "twinverse-download-symbolic"
        )
        self.status_label.set_text(self.get_status_text())
        detail = self._status_detail or (self._update_progress[0] if self._update_progress is not None else "")
        self.status_detail_label.set_text(detail)
        self.status_detail_label.set_tooltip_text(detail)
        self.status_detail_label.set_visible(bool(detail))
        self._status_box.set_tooltip_text(detail or self.get_status_text())

    def _set_combo_selection(self, combo_row, device_list, device_id):
        """Restore a connected device selection, or fall back to the default option."""
        if not device_id:
            combo_row.set_selected(0)
            return
        index = self._find_connected_device_index(device_list, device_id)
        combo_row.set_selected(index + 1 if index is not None else 0)

    def _get_combo_device_id(self, combo_row, device_list):
        selected_idx = combo_row.get_selected()
        if 0 < selected_idx <= len(device_list):
            return device_list[selected_idx - 1]["id"]
        return None

    def set_grab_input_sensitive(self, sensitive: bool):
        """Allow the owning page to enforce exclusive mouse capture."""
        self.grab_input_switch.set_sensitive(sensitive)

    def set_grab_input_active(self, active: bool):
        """Apply exclusivity without recursively reporting a settings edit."""
        was_loading = self._is_loading
        self._is_loading = True
        try:
            self.grab_input_switch.set_active(active)
        finally:
            self._is_loading = was_loading

    def set_checkbox_sensitive(self, sensitive: bool):
        """Allow the page to lock roster participation during a session."""
        self.checkbox.set_sensitive(sensitive)

    def _collect_env_vars(self) -> dict:
        env = {}
        for env_row in self._env_rows:
            key, value = env_row.get_values()
            if key:
                env[key] = value
        return env
