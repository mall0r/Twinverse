"""Instance launch lifecycle."""

import logging
import threading
import time
from typing import Callable, Optional

from src.core.logging import log_context
from src.models import Profile
from src.services import InstanceService, KdeManager

logger = logging.getLogger(__name__)


class LaunchController:
    """Runs launches and stops on worker threads, one bulk operation at a time."""

    def __init__(self, instance_service: InstanceService, kde_manager: KdeManager):
        """Initialize the launch controller."""
        self._instance_service = instance_service
        self._kde_manager = kde_manager
        self._launch_thread: Optional[threading.Thread] = None
        self._stop_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._is_running = False

    def is_running(self) -> bool:
        """Check if instances are running."""
        return self._is_running

    def sync_running_state(self) -> bool:
        """Refresh the running flag from the processes that are still alive."""
        self._is_running = self._has_running_instances()
        return self._is_running

    def launch_instances(
        self,
        profile: Profile,
        on_progress: Optional[Callable[[int], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> bool:
        """
        Launch instances asynchronously, ignoring a second concurrent launch.

        Args:
            on_progress: Called with each instance number as it starts.
            on_complete: Called once every instance has been launched.
            on_error: Called with the exception that aborted the launch.

        Returns:
            True when the launch started, False when one was already running.
        """
        if self._launch_thread and self._launch_thread.is_alive():
            logger.warning("Launch already in progress")
            return False

        self._cancel_event.clear()
        self._launch_thread = threading.Thread(
            target=self._launch_worker,
            args=(profile, on_progress, on_complete, on_error),
            name="twinverse-launch",
        )
        self._launch_thread.start()
        return True

    def stop_instances(self, on_complete: Optional[Callable[[], None]] = None):
        """
        Stop all running instances.

        Args:
            on_complete: Called once every instance has stopped.
        """
        if self._launch_thread and self._launch_thread.is_alive():
            logger.info("Cancelling the in-progress launch")
            self._cancel_event.set()

        self._stop_thread = threading.Thread(
            target=self._stop_worker,
            args=(on_complete,),
            name="twinverse-stop",
        )
        self._stop_thread.start()

    def launch_single_instance(
        self,
        profile: Profile,
        instance_num: int,
        use_gamescope_override: bool = False,
        on_complete: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        """
        Launch a single instance.

        Args:
            use_gamescope_override: Forces gamescope on or off, instead of
                following the profile.
        """
        launch_thread = threading.Thread(
            target=self._single_instance_worker,
            args=(profile, instance_num, use_gamescope_override, on_complete, on_error),
            name=f"twinverse-launch-{instance_num + 1}",
        )
        launch_thread.start()

    def terminate_single_instance(
        self,
        instance_num: int,
        on_complete: Optional[Callable[[], None]] = None,
    ):
        """
        Terminate a single instance.

        Args:
            on_complete: Called once that instance has stopped.
        """
        terminate_thread = threading.Thread(
            target=self._terminate_single_worker,
            args=(instance_num, on_complete),
            name=f"twinverse-stop-{instance_num + 1}",
        )
        terminate_thread.start()

    def _launch_worker(
        self,
        profile: Profile,
        on_progress: Optional[Callable[[int], None]],
        on_complete: Optional[Callable[[], None]],
        on_error: Optional[Callable[[Exception], None]],
    ):
        """Worker thread for launching instances."""
        selected_players = profile.selected_players
        with log_context(phase="launch"):
            display_players = (
                [player + 1 for player in selected_players]
                if isinstance(selected_players, (list, tuple, set))
                else selected_players
            )
            logger.info("Launch worker started for players %s", display_players)
            try:
                if profile.enable_kwin_script:
                    logger.info("Starting KDE script setup")
                    self._kde_manager.start_kwin_script(profile)

                self._kde_manager.save_panel_states()
                self._kde_manager.set_panels_dodge_windows()
                logger.info("KDE panel states saved and updated")

                for instance_num in selected_players:
                    if self._cancel_event.is_set():
                        logger.info("Launch sequence cancelled by the user")
                        break

                    with log_context(instance=instance_num + 1):
                        logger.info("Launching instance %s", instance_num + 1)
                        self._instance_service.launch_instance(profile, instance_num)
                        logger.info("Instance %s launch initiated", instance_num + 1)

                    if on_progress:
                        on_progress(instance_num)

                    logger.info("Waiting 5 seconds before launching the next instance")
                    time.sleep(5)

                if not self._cancel_event.is_set():
                    logger.info("All instances launched successfully; updating the running state")
                    self._is_running = True
                    if on_complete:
                        on_complete()
                else:
                    logger.info("Launch sequence was cancelled")

            except Exception as error:
                logger.exception("Launch error")
                self._kde_manager.restore_panel_states()
                if on_error:
                    on_error(error)

    def _stop_worker(self, on_complete: Optional[Callable[[], None]]):
        """Worker thread for stopping instances."""
        with log_context(phase="stop"):
            logger.info("Stop worker started")
            try:
                self._instance_service.terminate_all()
                self._kde_manager.restore_panel_states()
                self._is_running = False
            except Exception:
                # The stop has to finish even when one of the instances fails,
                # otherwise the window stays locked and the app never quits.
                logger.exception("Stop error")
            finally:
                # The cancel flag stays set while the launch thread is alive, so
                # it does not start another instance after the stop. The next
                # launch clears it.
                if on_complete:
                    on_complete()

    def _single_instance_worker(
        self,
        profile: Profile,
        instance_num: int,
        use_gamescope_override: bool,
        on_complete: Optional[Callable[[], None]],
        on_error: Optional[Callable[[Exception], None]],
    ):
        """Worker thread for launching a single instance."""
        with log_context(phase="launch", instance=instance_num + 1):
            try:
                logger.info("Starting single instance worker")
                self._instance_service.launch_instance(
                    profile, instance_num, use_gamescope_override=use_gamescope_override
                )
                logger.info("Instance %s launched successfully", instance_num + 1)
                self._is_running = True
                if on_complete:
                    on_complete()
            except Exception as error:
                logger.exception("Single instance launch error")
                if on_error:
                    on_error(error)

    def _terminate_single_worker(
        self,
        instance_num: int,
        on_complete: Optional[Callable[[], None]],
    ):
        """Worker thread for terminating a single instance."""
        with log_context(phase="stop", instance=instance_num + 1):
            try:
                self._instance_service.terminate_instance(instance_num)
            except Exception:
                logger.exception("Error terminating instance %s", instance_num + 1)
            finally:
                # Stopping one instance at a time has to clear the running state
                # as well, so the button of the footer follows what is open.
                self._is_running = self._has_running_instances()
                if on_complete:
                    on_complete()

    def _has_running_instances(self) -> bool:
        """Report whether any tracked instance is still running."""
        for process in self._instance_service.processes.values():
            if process.poll() is None:
                return True
        return False
