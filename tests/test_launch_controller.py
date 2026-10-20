"""The launch state has to follow the instances that are really open."""

from unittest.mock import Mock

from src.gui.controllers.launch_controller import LaunchController


def _controller(processes=None):
    """Build a launch controller with a mocked instance service."""
    service = Mock()
    service.processes = processes if processes is not None else {}
    return LaunchController(service, Mock(), Mock()), service


def _process(alive: bool):
    """Build a process that is running or already gone."""
    process = Mock()
    process.poll.return_value = None if alive else 0
    return process


def test_stopping_the_last_instance_clears_the_running_state():
    """The button of the footer must not stay on stop when everything is closed."""
    controller, service = _controller({0: _process(True)})
    controller._is_running = True
    service.terminate_instance.side_effect = lambda number: service.processes.pop(number, None)

    controller._terminate_single_worker(0, None)

    assert controller.is_running() is False


def test_stopping_one_instance_keeps_the_state_of_the_others():
    """The state stays on while another instance is still open."""
    controller, service = _controller({0: _process(True), 1: _process(True)})
    controller._is_running = True
    service.terminate_instance.side_effect = lambda number: service.processes.pop(number, None)

    controller._terminate_single_worker(0, None)

    assert controller.is_running() is True


def test_a_failed_termination_still_finishes():
    """The caller is told that the instance stopped, even when it did not."""
    controller, service = _controller({0: _process(True)})
    controller._is_running = True
    service.terminate_instance.side_effect = RuntimeError("boom")
    finished = []

    controller._terminate_single_worker(0, lambda: finished.append(True))

    assert finished == [True]
    assert controller.is_running() is True


def test_the_state_follows_the_processes_that_are_gone():
    """An instance that ended on its own does not keep the state on."""
    controller, service = _controller({0: _process(False)})
    controller._is_running = True

    controller._terminate_single_worker(0, None)

    assert controller.is_running() is False
