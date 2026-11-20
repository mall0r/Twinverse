"""Check that the buttons follow the state that was confirmed."""

from unittest.mock import Mock

from src.gui.notifications import BUSY, ERROR
from src.gui.presenters.main_presenter import MainPresenter
from src.gui.widgets.player_row import (
    INSTANCE_IDLE,
    INSTANCE_RUNNING,
    INSTANCE_STARTING,
    INSTANCE_STOPPING,
)
from src.models import Profile
from src.services.instance_registry import InstanceRecord
from src.services.steam_probe import ClientUpdate


class _Row:
    """A player row that remembers the state of its instance."""

    def __init__(self):
        """Start with the instance idle."""
        self._is_running = False
        self._state = INSTANCE_IDLE
        self._detail = ""
        self.update = None

    def set_running_state(self, is_running: bool):
        """Store the running state."""
        self._is_running = is_running

    def set_instance_state(self, state: str):
        """Store the state of the instance."""
        self._state = state
        self._is_running = state == INSTANCE_RUNNING

    def set_status_detail(self, detail: str):
        """Store what the instance is doing."""
        self._detail = detail

    def set_update_progress(self, detail: str, percent=None):
        """Store how far the update of the client went."""
        self.update = (detail, percent)

    def clear_update_progress(self):
        """Forget the update of the client."""
        self.update = None

    def get_instance_state(self) -> str:
        """Return the state of the instance."""
        return self._state

    def get_status_detail(self) -> str:
        """Return what the instance is doing."""
        return self._detail


def _presenter(recovered=None):
    """Build a presenter that only knows about the recovered instances."""
    presenter = MainPresenter.__new__(MainPresenter)
    presenter._instance_service = Mock()
    presenter._instance_service.recovered_instances = recovered or []
    presenter._instance_service.processes = {}
    presenter._instance_service.client_status.return_value = ClientUpdate()
    presenter._verification_controller = Mock()
    presenter._verification_controller.get_verification_status.return_value = True
    presenter._verification_controller.get_all_statuses.return_value = {}
    presenter._settings_controller = Mock()
    presenter._settings_controller.get_profile.return_value = Profile()
    presenter._settings_controller.get_devices_info.return_value = []
    presenter._launch_controller = Mock()
    presenter._launch_controller.is_running.return_value = False
    presenter._instance_watch_id = 1
    presenter._starting_instances = set()
    presenter._owned_instances = set()
    presenter._instance_states = {}
    presenter._progress_shown = {}
    presenter._minimized_after_launch = False
    presenter.window = Mock()
    layout_page = Mock()
    layout_page.get_selected_players.return_value = [0, 1]
    layout_page.get_layout_error.return_value = None
    layout_page.player_rows = [_Row(), _Row()]
    presenter.window.get_layout_page.return_value = layout_page
    return presenter


def _running_process():
    """Build a process that is still alive."""
    process = Mock()
    process.poll.return_value = None
    return process


def _footer_label(presenter) -> str:
    """Return the label the footer button shows."""
    calls = presenter.window.mock_calls
    for call in reversed(calls):
        name = call[0]
        if name == "show_running_state":
            return "Stop"
        if name == "show_idle_state":
            return "Play"
        if name == "show_launching_state":
            return "Starting"
        if name == "show_stopping_state":
            return "Stopping"
    return "Play"


def test_unassigned_players_block_bulk_launch_before_starting_clients():
    """Insufficient monitor capacity is reported before changing any instance state."""
    presenter = _presenter()
    page = presenter.window.get_layout_page()
    page.get_layout_error.return_value = "Player 2 has no display space."
    presenter._on_launch_requested()
    presenter.window.show_error.assert_called_once_with("Player 2 has no display space.")
    presenter._launch_controller.launch_instances.assert_not_called()
    presenter._settings_controller.save_profile.assert_not_called()
    assert presenter._instance_states == {}


def test_unassigned_player_cannot_launch_individually():
    """The per-player action obeys the same monitor capacity validation."""
    presenter = _presenter()
    page = presenter.window.get_layout_page()
    page.get_layout_error.return_value = "Player 1 has no display space."
    presenter.on_instance_launch_requested(0)
    page.get_layout_error.assert_called_once_with(0)
    presenter.window.show_error.assert_called_once_with("Player 1 has no display space.")
    presenter._launch_controller.launch_single_instance.assert_not_called()
    assert presenter._instance_states == {}


def test_unassigned_players_disable_session_launch():
    """Launch readiness includes available monitor capacity."""
    presenter = _presenter()
    presenter.window.get_layout_page().get_layout_error.return_value = "Choose a larger template."
    presenter._update_launch_button_sensitivity()
    presenter.window.update_launch_button_sensitivity.assert_called_once_with(False)


def test_missing_display_space_never_disables_session_stop():
    """A disconnected monitor must not strand already running clients."""
    presenter = _presenter()
    presenter._instance_states = {0: INSTANCE_RUNNING}
    presenter.window.get_layout_page().get_layout_error.return_value = "Monitor disconnected."
    presenter._update_launch_button_sensitivity()
    presenter.window.update_launch_button_sensitivity.assert_called_once_with(True)


def test_an_instance_that_survived_the_crash_puts_the_footer_in_stop():
    """The recovered instances were confirmed to be alive, so they can be stopped."""
    presenter = _presenter([InstanceRecord(instance=0, pgid=42, mode="native", home="/home/1")])

    presenter._load_initial_data()

    assert _footer_label(presenter) == "Stop"
    assert presenter.window.get_layout_page().player_rows[0].get_instance_state() == INSTANCE_RUNNING


def test_without_recovered_instances_the_footer_stays_in_play():
    """A session without leftovers has to show the launch action."""
    presenter = _presenter()

    presenter._load_initial_data()

    assert _footer_label(presenter) == "Play"


def test_the_button_only_becomes_stop_when_the_client_is_confirmed():
    """A launch that is still going on does not offer to stop."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()

    presenter._watch_instance_start(0)

    assert presenter.window.get_layout_page().player_rows[0].get_instance_state() == INSTANCE_STARTING
    assert _footer_label(presenter) == "Starting"

    presenter._instance_service.is_client_up.return_value = True
    presenter._watch_instances()

    assert presenter.window.get_layout_page().player_rows[0].get_instance_state() == INSTANCE_RUNNING
    assert _footer_label(presenter) == "Stop"


def test_the_footer_waits_for_every_instance_to_be_confirmed():
    """One instance that is still starting keeps the footer locked."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.processes[1] = _running_process()
    # The client of the first instance is up, the second one is not.
    presenter._instance_service.is_client_up.side_effect = lambda number: number == 0

    presenter._watch_instance_start(0)
    presenter._watch_instance_start(1)
    presenter._watch_instances()

    assert presenter.window.get_layout_page().player_rows[0].get_instance_state() == INSTANCE_RUNNING
    assert presenter.window.get_layout_page().player_rows[1].get_instance_state() == INSTANCE_STARTING
    assert _footer_label(presenter) == "Starting"


def test_the_button_leaves_stop_only_when_the_instance_is_gone():
    """The stop only ends when the death of the instance is confirmed."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = True
    presenter._watch_instance_start(0)
    presenter._watch_instances()

    assert presenter.window.get_layout_page().player_rows[0].get_instance_state() == INSTANCE_RUNNING

    presenter._on_stop_requested()

    assert presenter.window.get_layout_page().player_rows[0].get_instance_state() == INSTANCE_STOPPING
    assert _footer_label(presenter) == "Stopping"

    presenter._on_single_instance_stopped(0)

    assert presenter.window.get_layout_page().player_rows[0].get_instance_state() == INSTANCE_IDLE
    assert _footer_label(presenter) == "Play"


def test_the_footer_stays_locked_while_the_launch_goes_on():
    """The instances the launch has not reached yet keep the footer locked."""
    presenter = _presenter()
    presenter._instance_service.processes = {0: _running_process(), 1: _running_process()}

    presenter._on_launch_requested()

    rows = presenter.window.get_layout_page().player_rows
    assert rows[0].get_instance_state() == INSTANCE_STARTING
    assert rows[1].get_instance_state() == INSTANCE_STARTING
    assert _footer_label(presenter) == "Starting"


def test_the_row_tells_what_the_steam_is_doing():
    """While the client starts, the row shows what the Steam is doing."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(
        progress="Manifest download: waiting for download to finish",
    )

    presenter._watch_instance_start(0)
    presenter._watch_instances()

    row = presenter.window.get_layout_page().player_rows[0]
    assert row.get_instance_state() == INSTANCE_STARTING
    assert row.get_status_detail() == "Manifest download: waiting for download to finish"


def test_the_window_is_minimized_only_when_every_instance_is_open():
    """The window goes away when the last Steam client was confirmed."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.processes[1] = _running_process()
    presenter._instance_service.is_client_up.side_effect = lambda number: number == 0

    presenter._watch_instance_start(0)
    presenter._watch_instance_start(1)
    presenter._watch_instances()

    assert not presenter.window.minimize_window.called

    presenter._instance_service.is_client_up.side_effect = lambda number: True
    presenter._watch_instances()

    presenter.window.minimize_window.assert_called_once()


def test_a_starting_instance_can_be_cancelled():
    """An instance whose client never came up can still be cancelled."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._watch_instance_start(0)

    presenter.on_instance_launch_requested(0)

    row = presenter.window.get_layout_page().player_rows[0]
    assert row.get_instance_state() == INSTANCE_STOPPING
    presenter._launch_controller.terminate_single_instance.assert_called_once()
    assert "Cancelled" in presenter.window.show_toast.call_args[0][0]


def test_a_client_that_never_came_up_leaves_the_leftover_stopped():
    """A failed client stops the instance, because there is no game to keep."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(failure="fatal IO error 110")
    presenter._watch_instance_start(0)

    presenter._watch_instances()

    assert presenter.window.get_layout_page().player_rows[0].get_instance_state() == INSTANCE_STOPPING
    presenter._launch_controller.terminate_single_instance.assert_called_once_with(0)


def test_a_failure_is_shown_as_an_error():
    """A client that gave up is a failure, and it is shown as one."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(failure="fatal IO error 110")
    presenter._watch_instance_start(0)

    presenter._watch_instances()

    assert presenter.window.show_toast.call_args.kwargs["level"] == ERROR


def test_a_client_that_is_starting_is_shown_as_busy():
    """A client that is starting, or updating itself, is only busy."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()

    presenter._watch_instance_start(0)

    assert presenter.window.show_toast.call_args.kwargs["level"] == BUSY


def test_an_instance_that_stops_on_its_own_is_shown_as_an_error():
    """An instance that dies is a failure, and it is shown as one."""
    presenter = _presenter()
    process = _running_process()
    presenter._instance_service.processes[0] = process
    presenter._instance_service.client_status.return_value = ClientUpdate(failure="fatal IO error 110")
    presenter._watch_instance_start(0)

    # The process of the instance is gone.
    process.poll.return_value = 1
    presenter._watch_instances()

    call = presenter.window.show_toast.call_args
    assert "fatal IO error 110" in call[0][0]
    assert call.kwargs["level"] == ERROR


def test_the_row_shows_the_update_of_the_client():
    """A client that updates itself shows how far it went."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(
        progress="Downloading update...",
        percent=41,
    )
    presenter._watch_instance_start(0)

    presenter._watch_instances()

    row = presenter.window.get_layout_page().player_rows[0]
    assert row.update == ("Downloading update...", 41)


def test_the_update_of_the_client_is_not_a_message():
    """A progress that changes all the time would be read as noise."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(progress="Downloading update...")
    presenter._watch_instance_start(0)

    presenter._watch_instances()

    assert presenter.window.show_toast.call_count == 1


def test_the_same_progress_is_not_told_again():
    """The bar follows the update, and does not repeat itself."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(progress="Downloading update...")
    presenter._watch_instance_start(0)

    presenter._watch_instances()
    presenter._watch_instances()

    row = presenter.window.get_layout_page().player_rows[0]
    assert row.update == ("Downloading update...", None)


def test_a_line_that_is_not_an_update_leaves_the_row_alone():
    """A client that only starts does not show a bar."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(progress="Build: Mar  8 2026, at 12:00:00")
    presenter._watch_instance_start(0)

    presenter._watch_instances()

    row = presenter.window.get_layout_page().player_rows[0]
    assert row.update is None


def test_the_bar_goes_away_when_the_client_is_up():
    """The bar of the update has no place when the client is running."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(
        progress="Downloading update...",
        percent=41,
    )
    presenter._watch_instance_start(0)
    presenter._watch_instances()

    presenter._instance_service.is_client_up.return_value = True
    presenter._watch_instances()

    row = presenter.window.get_layout_page().player_rows[0]
    assert row.update is None


def test_the_console_line_persists_across_quiet_ticks():
    """A tick with no new Steam console output must not blank out the previous line."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.side_effect = [
        ClientUpdate(progress="Extracting package..."),
        ClientUpdate(progress=None),
    ]
    presenter._watch_instance_start(0)

    presenter._watch_instances()
    presenter._watch_instances()

    row = presenter.window.get_layout_page().player_rows[0]
    assert row.get_status_detail() == "Extracting package..."


def test_the_console_line_clears_once_the_client_is_running():
    """Once the Steam client is running, the startup console line disappears and stops polling."""
    presenter = _presenter()
    presenter._instance_service.processes[0] = _running_process()
    presenter._instance_service.is_client_up.return_value = False
    presenter._instance_service.client_status.return_value = ClientUpdate(progress="Extracting package...")
    presenter._watch_instance_start(0)
    presenter._watch_instances()

    row = presenter.window.get_layout_page().player_rows[0]
    assert row.get_status_detail() == "Extracting package..."

    presenter._instance_service.is_client_up.return_value = True
    presenter._instance_service.client_status.return_value = ClientUpdate(progress="Loaded game list")
    presenter._watch_instances()

    assert row.get_instance_state() == INSTANCE_RUNNING
    assert row.get_status_detail() == ""
    presenter._verification_controller.verify_instance.assert_called_once_with(0)

    calls_at_running = presenter._instance_service.client_status.call_count
    presenter._watch_instances()
    assert row.get_status_detail() == ""
    assert presenter._instance_service.client_status.call_count == calls_at_running
