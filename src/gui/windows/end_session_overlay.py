"""Floating confirmation overlay shown when ending a running session via controller shortcut."""

# flake8: noqa: E402

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk, Pango  # noqa: E402

from src.core.i18n import TRANSLATIONS, subscribe, t, unsubscribe

OVERLAY_WINDOW_TITLES: tuple[str, ...] = tuple(
    dict.fromkeys(
        catalog["exit_confirm.window_title"]
        for catalog in TRANSLATIONS.values()
        if "exit_confirm.window_title" in catalog
    )
)


class EndSessionOverlay(Gtk.Window):
    """Centered floating confirmation dialog controllable by gamepad, keyboard, and mouse."""

    def __init__(
        self,
        application,
        *,
        on_confirm: Callable[[], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        """Build the end-session confirmation overlay window."""
        super().__init__(
            application=application,
            decorated=False,
            resizable=False,
        )
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._selected = "cancel"
        self._resolved = False

        self.set_title(t("exit_confirm.window_title"))
        self.set_default_size(440, -1)
        self.add_css_class("exit-confirm-window")

        self._style_manager = Adw.StyleManager.get_default()
        self._style_handler_id = self._style_manager.connect("notify::dark", self._on_theme_changed)
        self._on_theme_changed(self._style_manager, None)

        self._build_ui()
        self._install_key_controller()
        self._sync_selection()

        subscribe(self.retranslate)
        self.connect("close-request", self._on_close_request)
        self.connect("destroy", self._on_destroy)

    @property
    def selected_option(self) -> str:
        """Return the currently highlighted option ('cancel' or 'confirm')."""
        return self._selected

    def _build_ui(self) -> None:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        card.add_css_class("exit-confirm-card")
        card.set_halign(Gtk.Align.FILL)
        card.set_valign(Gtk.Align.CENTER)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.title_label = Gtk.Label(
            label=t("exit_confirm.heading"),
            halign=Gtk.Align.CENTER,
            justify=Gtk.Justification.CENTER,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
        )
        self.title_label.add_css_class("exit-confirm-title")
        text_box.append(self.title_label)

        self.body_label = Gtk.Label(
            label=t("exit_confirm.body"),
            halign=Gtk.Align.CENTER,
            justify=Gtk.Justification.CENTER,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
            max_width_chars=42,
        )
        self.body_label.add_css_class("exit-confirm-body")
        text_box.append(self.body_label)
        card.append(text_box)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, homogeneous=True)
        buttons.add_css_class("exit-confirm-actions")

        self.cancel_button = Gtk.Button(label=t("exit_confirm.cancel"), hexpand=True)
        self.cancel_button.add_css_class("exit-confirm-button")
        self.cancel_button.add_css_class("exit-confirm-cancel")
        self.cancel_button.connect("clicked", lambda *_: self._resolve(confirmed=False))
        buttons.append(self.cancel_button)

        self.confirm_button = Gtk.Button(label=t("exit_confirm.confirm"), hexpand=True)
        self.confirm_button.add_css_class("exit-confirm-button")
        self.confirm_button.add_css_class("exit-confirm-danger")
        self.confirm_button.connect("clicked", lambda *_: self._resolve(confirmed=True))
        buttons.append(self.confirm_button)

        card.append(buttons)

        self.hint_label = Gtk.Label(
            label=t("exit_confirm.hint"),
            halign=Gtk.Align.CENTER,
            justify=Gtk.Justification.CENTER,
            wrap=True,
            wrap_mode=Pango.WrapMode.WORD_CHAR,
        )
        self.hint_label.add_css_class("exit-confirm-hint")
        card.append(self.hint_label)

        self.set_child(card)

    def _install_key_controller(self) -> None:
        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, _controller, keyval: int, _keycode: int, _state) -> bool:
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            self.navigate("left")
            return True
        if keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            self.navigate("right")
            return True
        if keyval in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            self.navigate("right" if self._selected == "cancel" else "left")
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.navigate("confirm")
            return True
        if keyval == Gdk.KEY_Escape:
            self.navigate("cancel")
            return True
        return False

    def navigate(self, action: str) -> None:
        """Apply a controller or keyboard navigation action to the dialog."""
        if self._resolved:
            return
        if action == "left":
            self._selected = "cancel"
            self._sync_selection()
        elif action == "right":
            self._selected = "confirm"
            self._sync_selection()
        elif action == "confirm":
            self._resolve(confirmed=(self._selected == "confirm"))
        elif action == "cancel":
            self._resolve(confirmed=False)

    def _sync_selection(self) -> None:
        cancel_selected = self._selected == "cancel"
        if cancel_selected:
            self.cancel_button.add_css_class("is-selected")
            self.confirm_button.remove_css_class("is-selected")
            self.cancel_button.grab_focus()
        else:
            self.confirm_button.add_css_class("is-selected")
            self.cancel_button.remove_css_class("is-selected")
            self.confirm_button.grab_focus()

    def _resolve(self, *, confirmed: bool) -> None:
        if self._resolved:
            return
        self._resolved = True
        self.close()
        if confirmed:
            self._on_confirm()
        elif self._on_cancel is not None:
            self._on_cancel()

    def dismiss(self) -> None:
        """Close the overlay programmatically without invoking confirm or cancel callbacks."""
        if self._resolved:
            return
        self._resolved = True
        self.close()

    def retranslate(self, *_args) -> None:
        """Refresh all localized strings in place."""
        self.set_title(t("exit_confirm.window_title"))
        self.title_label.set_label(t("exit_confirm.heading"))
        self.body_label.set_label(t("exit_confirm.body"))
        self.cancel_button.set_label(t("exit_confirm.cancel"))
        self.confirm_button.set_label(t("exit_confirm.confirm"))
        self.hint_label.set_label(t("exit_confirm.hint"))

    def _on_theme_changed(self, style_manager, _pspec) -> None:
        if style_manager.get_dark():
            self.remove_css_class("light")
        else:
            self.add_css_class("light")

    def _on_close_request(self, _window) -> bool:
        if not self._resolved:
            self._resolved = True
            if self._on_cancel is not None:
                self._on_cancel()
        return False

    def _on_destroy(self, _window) -> None:
        unsubscribe(self.retranslate)
        if self._style_handler_id:
            self._style_manager.disconnect(self._style_handler_id)
            self._style_handler_id = 0
