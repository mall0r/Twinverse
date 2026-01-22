"""
Launch controller module.

This module manages the lifecycle of launching instances.
"""

import threading
import time
from typing import Callable, Optional

from src.core import Logger
from src.models import Profile
from src.services import InstanceService, KdeManager


class LaunchController:
    """Manages the lifecycle of launching instances."""

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
        Launch instances asynchronously.

        Args:
            profile: The profile configuration
            on_progress: Callback for progress updates (called with instance number)
            on_complete: Callback when launch completes successfully
            on_error: Callback when an error occurs (called with exception)
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
            on_complete: Callback when stop completes
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
            profile: The profile configuration
            instance_num: The instance number to launch
            use_gamescope_override: Override gamescope setting
            on_complete: Callback when launch completes
            on_error: Callback when an error occurs
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
            instance_num: The instance number to terminate
            on_complete: Callback when termination completes
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
            # Setup KDE if enabled
            if profile.enable_kwin_script:
                self._kde_manager.start_kwin_script(profile)

            self._kde_manager.save_panel_states()
            self._kde_manager.set_panels_dodge_windows()

            # Launch each instance
            for instance_num in selected_players:
                if self._cancel_event.is_set():
                    self._logger.info("Launch sequence cancelled by user.")
                    break

                self._logger.info(f"Worker launching instance {instance_num}...")
                self._instance_service.launch_instance(profile, instance_num)

                if on_progress:
                    on_progress(instance_num)

                time.sleep(5)

            if not self._cancel_event.is_set():
                self._is_running = True
                if on_complete:
                    on_complete()

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
            self._instance_service.launch_instance(profile, instance_num, use_gamescope_override=use_gamescope_override)
            if on_complete:
                on_complete()
        except Exception as e:
            self._logger.error(f"Single instance launch error: {e}")
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
