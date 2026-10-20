"""Check that the footer button follows the instances that survived a crash."""

from unittest.mock import Mock

from src.gui.presenters.main_presenter import MainPresenter
from src.models import Profile
from src.services.instance_registry import InstanceRecord


class _Row:
    """A player row that remembers whether its instance is running."""

    def __init__(self):
        """Start with the instance stopped."""
        self._is_running = False

    def set_running_state(self, is_running: bool):
        """Store the state of the instance."""
        self._is_running = is_running


def _presenter(recovered):
    """Build a presenter that only knows about the recovered instances."""
    presenter = MainPresenter.__new__(MainPresenter)
    presenter._instance_service = Mock()
    presenter._instance_service.recovered_instances = recovered
    presenter._verification_controller = Mock()
    presenter._verification_controller.get_verification_status.return_value = True
    presenter._verification_controller.get_all_statuses.return_value = {}
    presenter._settings_controller = Mock()
    presenter._settings_controller.get_profile.return_value = Profile()
    presenter._settings_controller.get_devices_info.return_value = []
    presenter._launch_controller = Mock()
    presenter._launch_controller.is_running.return_value = False
    presenter.window = Mock()
    layout_page = Mock()
    layout_page.get_selected_players.return_value = [0, 1]
    layout_page.player_rows = [_Row(), _Row()]
    presenter.window.get_layout_page.return_value = layout_page
    return presenter


def test_an_instance_that_survived_the_crash_puts_the_footer_in_stop():
    """The recovered instances have to turn the footer button into a stop."""
    presenter = _presenter([InstanceRecord(instance=0, pgid=42, mode="native", home="/home/1")])

    presenter._load_initial_data()

    presenter.window.update_launch_button_action.assert_called_with(True)
    assert presenter.window.get_layout_page().player_rows[0]._is_running is True


def test_without_recovered_instances_the_footer_stays_in_play():
    """A session without leftovers has to show the launch action."""
    presenter = _presenter([])

    presenter._load_initial_data()

    presenter.window.update_launch_button_action.assert_called_with(False)
