"""Check the message that appears over the window."""

from unittest.mock import Mock

from src.gui.notifications import BUSY, ERROR, INFO
from src.gui.widgets.toast import LEVEL_CLASSES, ToastOverlay


def _overlay():
    """Build the parts of the overlay that the toast uses."""
    overlay = Mock()
    overlay._timeout_id = 0
    return overlay


def test_a_failure_is_outlined_in_red():
    """A failure is not read as a notice."""
    overlay = _overlay()
    style = overlay._card.get_style_context.return_value

    ToastOverlay.show_toast(overlay, "a Steam nao abriu", ERROR)

    assert style.add_class.call_args[0][0] == "toast-error"


def test_a_message_of_a_work_in_progress_is_not_an_error():
    """A client that is starting, or updating, is only busy."""
    overlay = _overlay()
    style = overlay._card.get_style_context.return_value

    ToastOverlay.show_toast(overlay, "Starting the Steam client…", BUSY)

    assert style.add_class.call_args[0][0] == "toast-busy"


def test_the_card_takes_the_icon_of_the_message():
    """The card shows the icon that represents what happened."""
    overlay = _overlay()

    ToastOverlay.show_toast(overlay, "a Steam nao abriu", ERROR)

    assert overlay._icon.set_from_icon_name.call_args[0][0] == "dialog-error"


def test_the_look_of_the_previous_message_is_taken_away():
    """A message that comes after a failure is not red anymore."""
    overlay = _overlay()
    style = overlay._card.get_style_context.return_value

    ToastOverlay.show_toast(overlay, "a Steam nao abriu", ERROR)
    ToastOverlay.show_toast(overlay, "Steam started", INFO)

    removed = [call[0][0] for call in style.remove_class.call_args_list]
    assert "toast-error" in removed
    assert style.add_class.call_args[0][0] == LEVEL_CLASSES[INFO]
