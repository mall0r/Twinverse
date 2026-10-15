"""Instance launch lifecycle."""

import threading
import time
from typing import Callable, Optional

from src.core import Logger
from src.models import Profile
from src.services import InstanceService, KdeManager


class LaunchController:
    """Runs launches and stops on worker threads, one bulk operation at a time."""

    def __init__(self, instance_service: InstanceService, kde_manager: KdeManager, logger: Logger):
        """Initialize the launch controller."""
        self._instance_service = instance_service
        self._kde_manager = kde_manager
        self._logger = logger
        self._launch_thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._is_running = False

    def is_running(self) -> bool:
        """Check if instances are running."""
        return self._is_running

    def launch_instances(
        self,
        profile: Profile,
        on_progress: Optional[Callable[[int], None]] = None,
        on_complete: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        """
        Launch instances asynchronously, ignoring a second concurrent launch.

        Args:
            on_progress: Called with each instance number as it starts.
            on_complete: Called once every instance has been launched.
            on_error: Called with the exception that aborted the launch.
        """
        if self._launch_thread and self._launch_thread.is_alive():
            self._logger.warning("Launch already in progress")
            return

        self._cancel_event.clear()
        self._launch_thread = threading.Thread(
            target=self._launch_worker, args=(profile, on_progress, on_complete, on_error)
        )
        self._launch_thread.start()

    def stop_instances(self, on_complete: Optional[Callable[[], None]] = None):
        """
        Stop all running instances.

        Args:
            on_complete: Called once every instance has stopped.
        """
        if self._launch_thread and self._launch_thread.is_alive():
            self._logger.info("Cancelling in-progress launch...")
            self._cancel_event.set()

        stop_thread = threading.Thread(target=self._stop_worker, args=(on_complete,))
        stop_thread.start()

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
        terminate_thread = threading.Thread(target=self._terminate_single_worker, args=(instance_num, on_complete))
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
        self._logger.info(f"Launch worker started for players: {selected_players}")

        try:
            if profile.enable_kwin_script:
                self._logger.info("Starting KDE script setup...")
                self._kde_manager.start_kwin_script(profile)

            self._kde_manager.save_panel_states()
            self._kde_manager.set_panels_dodge_windows()
            self._logger.info("KDE panel states saved and updated.")

            for instance_num in selected_players:
                if self._cancel_event.is_set():
                    self._logger.info("Launch sequence cancelled by user.")
                    break

                self._logger.info(f"Worker launching instance {instance_num}...")
                self._instance_service.launch_instance(profile, instance_num)
                self._logger.info(f"Instance {instance_num} launch initiated successfully.")

                if on_progress:
                    on_progress(instance_num)

                self._logger.info("Waiting 5 seconds before launching next instance...")
                time.sleep(5)

            if not self._cancel_event.is_set():
                self._logger.info("All instances launched successfully. Updating running state.")
                self._is_running = True
                if on_complete:
                    on_complete()
            else:
                self._logger.info("Launch sequence was cancelled.")

        except Exception as e:
            self._logger.error(f"Launch error: {e}")
            self._logger.logger.exception("Exception details:")  # Use underlying logger for exception details
            self._kde_manager.restore_panel_states()
            if on_error:
                on_error(e)

    def _stop_worker(self, on_complete: Optional[Callable[[], None]]):
        """Worker thread for stopping instances."""
        self._logger.info("Stop worker started.")
        self._instance_service.terminate_all()
        self._kde_manager.restore_panel_states()
        self._is_running = False
        self._cancel_event.clear()

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
        try:
            self._logger.info(f"Starting single instance worker for instance {instance_num}")
            self._instance_service.launch_instance(profile, instance_num, use_gamescope_override=use_gamescope_override)
            self._logger.info(f"Successfully launched instance {instance_num}")
            if on_complete:
                on_complete()
        except Exception as e:
            self._logger.error(f"Single instance launch error for instance {instance_num}: {e}")
            self._logger.logger.exception("Exception details:")  # Use underlying logger for exception details
            if on_error:
                on_error(e)

    def _terminate_single_worker(
        self,
        instance_num: int,
        on_complete: Optional[Callable[[], None]],
    ):
        """Worker thread for terminating a single instance."""
        self._instance_service.terminate_instance(instance_num)
        if on_complete:
            on_complete()
