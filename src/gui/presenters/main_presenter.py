"""Mediates between the view (window) and the controllers."""

import logging
from typing import Optional

from gi.repository import Adw, GLib, Gtk

from src.core import Utils
from src.core.i18n import (
    LANGUAGE_PT_BR,
    get_language,
    normalize_language_preference,
    set_language,
    t,
)
from src.core.logging import log_context
from src.gui.controllers import (
    LaunchController,
    SettingsController,
    VerificationController,
)
from src.gui.dialogs import ErrorDialog
from src.gui.notifications import BUSY, ERROR
from src.gui.utils import ErrorHandler
from src.gui.widgets.player_row import (
    INSTANCE_IDLE,
    INSTANCE_RUNNING,
    INSTANCE_STARTING,
    INSTANCE_STOPPING,
)
from src.gui.windows import MainWindow, PreferencesWindow
from src.services import DeviceManager, InstanceService, KdeManager, SteamVerifier
from src.services.steam_probe import is_update_progress

logger = logging.getLogger(__name__)


class MainPresenter:
    """Mediator between the view and controllers."""

    def __init__(self, application):
        """Initialize the main presenter."""
        self._app = application

        self._kde_manager = KdeManager()
        self._instance_service = InstanceService(kde_manager=self._kde_manager)
        self._steam_verifier = SteamVerifier()
        self._device_manager = DeviceManager()

        self._launch_controller = LaunchController(self._instance_service, self._kde_manager)
        self._verification_controller = VerificationController(self._steam_verifier)
        self._settings_controller = SettingsController(self._device_manager)

        set_language(getattr(self._settings_controller.get_profile(), "language", "auto"))

        self.window = MainWindow(application, self)

        self._bulk_operation_in_progress = False
        self._save_timeout_id = 0
        self._instance_watch_id = 0
        self._starting_instances: set[int] = set()
        self._owned_instances: set[int] = set()
        self._instance_states: dict[int, str] = {}
        self._progress_shown: dict[int, tuple[str, Optional[int]]] = {}
        self._minimized_after_launch = False

        self._load_initial_data()

    @staticmethod
    def _row_instance_num(row, fallback_index: int) -> int:
        player_num = getattr(row, "_player_num", None)
        return player_num if isinstance(player_num, int) else fallback_index

    @staticmethod
    def _row_is_active(row) -> bool:
        if getattr(row, "_is_running", False):
            return True
        get_state = getattr(row, "get_instance_state", None)
        return callable(get_state) and get_state() in (INSTANCE_STARTING, INSTANCE_RUNNING, INSTANCE_STOPPING)

    def _get_player_row(self, instance_num: int):
        layout_page = self.window.get_layout_page()
        for index, row in enumerate(layout_page.player_rows):
            if self._row_instance_num(row, index) == instance_num:
                return row
        return None

    def _load_initial_data(self):
        """Load initial data into the UI."""
        profile = self._settings_controller.get_profile()
        devices_info = self._settings_controller.get_devices_info()

        self._verification_controller.verify_instances(
            profile.party_indices(), on_each_complete=lambda i, verified: None  # Silent initial verification
        )

        verification_statuses = self._verification_controller.get_all_statuses()

        layout_page = self.window.get_layout_page()
        layout_page.load_data(profile, devices_info, verification_statuses)

        self._show_recovered_instances()
        self._update_launch_button_sensitivity()
        self._sync_launch_button_action()

    def _show_recovered_instances(self):
        """Show the instances that outlived the session that launched them."""
        for record in self._instance_service.recovered_instances:
            logger.info(
                "Instance %s is still running from the previous session",
                record.instance + 1,
            )
            # The recovery confirmed that the process is alive, so these are
            # running instances and the button can offer to stop them.
            self._set_instance_state(record.instance, INSTANCE_RUNNING)
            if record.instance in self._instance_service.processes:
                self._owned_instances.add(record.instance)
                self._ensure_instance_watch()

    def _begin_instance_stop(self, instance_num: int) -> None:
        """Mark an instance as intentionally stopping so the watcher never flags it as a crash."""
        self._starting_instances.discard(instance_num)
        self._owned_instances.discard(instance_num)
        self._forget_progress(instance_num)
        self._set_instance_state(instance_num, INSTANCE_STOPPING)

    def _watch_instance_start(self, instance_num: int):
        """Tell the user that the Steam client is starting, and follow it."""
        self._owned_instances.add(instance_num)
        self._starting_instances.add(instance_num)
        self._set_instance_detail(instance_num, "")
        self._set_instance_state(instance_num, INSTANCE_STARTING)
        # The client may take a long time when it updates itself, so the
        # message says that something is still working.
        self.window.show_toast(
            t("presenter.starting_instance", num=instance_num + 1),
            level=BUSY,
        )
        self._ensure_instance_watch()

    def _ensure_instance_watch(self):
        """Start the timer that follows the instances, only once."""
        if self._instance_watch_id:
            return
        self._instance_watch_id = GLib.timeout_add_seconds(1, self._watch_instances)

    def _watch_instances(self) -> bool:
        """Follow the instances that are starting and notice the ones that stop."""
        service = self._instance_service

        for instance_num in list(self._starting_instances):
            if self._instance_states.get(instance_num) == INSTANCE_STOPPING:
                self._starting_instances.discard(instance_num)
                continue
            process = service.processes.get(instance_num)
            if process is None:
                self._starting_instances.discard(instance_num)
                continue
            exit_code = process.poll()
            if exit_code is not None:
                self._starting_instances.discard(instance_num)
                self._owned_instances.discard(instance_num)
                self._forget_progress(instance_num)
                self._report_instance_stopped(instance_num, exit_code=exit_code)
                continue

            status = service.client_status(instance_num)

            # A client that is up is a client that works: the log of the Steam
            # may hold old complaints that do not concern this launch.
            if service.is_client_up(instance_num):
                self._starting_instances.discard(instance_num)
                self._forget_progress(instance_num)
                self._set_instance_detail(instance_num, "")
                with log_context(instance=instance_num + 1):
                    logger.info("The Steam client of instance %s started", instance_num + 1)
                self._verify_instance(instance_num)
                self._set_instance_state(instance_num, INSTANCE_RUNNING)
                self.window.show_toast(t("presenter.started_instance", num=instance_num + 1))
                continue

            if status.failure:
                self._starting_instances.discard(instance_num)
                self._forget_progress(instance_num)
                self._report_instance_failure(instance_num, status.failure)
                continue

            # Keep the last Steam console line visible between quiet intervals
            # (such as long package extractions) instead of blanking the line.
            if status.progress:
                self._set_instance_detail(instance_num, status.progress)
            self._report_progress(instance_num, status.progress, status.percent)

        for instance_num in list(self._owned_instances):
            process = service.processes.get(instance_num)
            if process is None:
                self._owned_instances.discard(instance_num)
                self._starting_instances.discard(instance_num)
                self._forget_progress(instance_num)
                if self._instance_states.get(instance_num) != INSTANCE_IDLE:
                    self._set_instance_state(instance_num, INSTANCE_IDLE)
                    self._verify_instance(instance_num)
                    self._update_number_of_instances_sensitivity()
                continue
            # An instance that is being stopped intentionally (by the user or
            # after a reported failure) may exit with SIGTERM/SIGKILL before
            # the stop worker clears ``service.processes``; never flag it as an
            # unexpected crash or race the worker's cleanup.
            if self._instance_states.get(instance_num) == INSTANCE_STOPPING:
                continue
            exit_code = process.poll()
            if exit_code is None:
                continue
            self._owned_instances.discard(instance_num)
            self._starting_instances.discard(instance_num)
            self._forget_progress(instance_num)
            self._report_instance_stopped(instance_num, exit_code=exit_code)

        self._minimize_when_all_open()
        return True

    def _minimize_when_all_open(self):
        """Minimize the window once every instance was confirmed to be open."""
        if self._minimized_after_launch:
            return
        if self._footer_state() != INSTANCE_RUNNING:
            return
        self._minimized_after_launch = True
        logger.info("Every instance is open, minimizing the window")
        self.window.minimize_window()

    def _set_instance_detail(self, instance_num: int, detail: Optional[str]):
        """Tell the row of an instance what the Steam client is doing."""
        row = self._get_player_row(instance_num)
        if row is not None:
            row.set_status_detail(detail or "")

    def _report_progress(self, instance_num: int, progress: Optional[str], percent: Optional[int] = None):
        """
        Show how far the update of the client went.

        A client that updates itself can take minutes, so the row of the
        instance records its progress next to its name, and the user sees that
        the wait is not a hang. A message would be read as noise, because it
        changes all the time.
        """
        if not progress or not is_update_progress(progress):
            return
        if progress == self._progress_shown.get(instance_num, (None, None))[0]:
            return
        self._progress_shown[instance_num] = (progress, percent)
        self._show_progress_bar()

    def _forget_progress(self, instance_num: int):
        """Forget the progress of an instance that is not updating anymore."""
        self._progress_shown.pop(instance_num, None)
        self._show_progress_bar()

    def _show_progress_bar(self):
        """Propagate update progress to every active player row."""
        layout_page = self.window.get_layout_page()
        rows = layout_page.player_rows

        for index, row in enumerate(rows):
            instance_num = self._row_instance_num(row, index)
            progress = self._progress_shown.get(instance_num)
            if progress is None:
                row.clear_update_progress()
                continue
            detail, percent = progress
            row.set_update_progress(detail, percent)

    def _report_instance_failure(self, instance_num: int, reason: str):
        """Tell the user that the Steam client of an instance gave up."""
        message = t("presenter.failed_instance", num=instance_num + 1, reason=reason)
        with log_context(instance=instance_num + 1):
            logger.warning("%s", message)
        self.window.show_toast(message, level=ERROR)
        # The reason stays on the row, because the toast is gone in seconds.
        self._set_instance_detail(instance_num, reason)
        # The client never came up, so there is no game to preserve. The
        # leftover is stopped, and the instance goes back to the idle state.
        self._stop_failed_instance(instance_num)

    def _stop_failed_instance(self, instance_num: int):
        """Stop the leftover of an instance whose Steam client never came up."""
        self._starting_instances.discard(instance_num)
        self._set_instance_state(instance_num, INSTANCE_STOPPING)
        self._launch_controller.terminate_single_instance(instance_num)

    def _report_instance_stopped(self, instance_num: int, exit_code: Optional[int] = None):
        """Handle an instance that exited on its own or was closed manually."""
        with log_context(instance=instance_num + 1):
            reason = self._instance_service.client_status(instance_num).failure
            if reason:
                message = t("presenter.failed_instance", num=instance_num + 1, reason=reason)
                logger.warning("%s (exit_code=%s)", message, exit_code)
                self.window.show_toast(message, level=ERROR)
                self._set_instance_detail(instance_num, reason)
            elif exit_code == 0:
                message = t("presenter.stopped_instance", num=instance_num + 1)
                logger.info("%s (exit_code=0)", message)
                self.window.show_toast(message)
                self._set_instance_detail(instance_num, "")
            else:
                message = t("presenter.stopped_unexpectedly", num=instance_num + 1)
                logger.warning("%s (exit_code=%s)", message, exit_code)
                self.window.show_toast(message, level=ERROR)
                self._set_instance_detail(instance_num, "")

            self._instance_service.cleanup_stopped_instance(instance_num, exit_code=exit_code)
            self._instance_service.processes.pop(instance_num, None)
            self._launch_controller.sync_running_state()
            self._set_instance_state(instance_num, INSTANCE_IDLE)
            self._verify_instance(instance_num)
            self._update_number_of_instances_sensitivity()

    def on_launch_clicked(self):
        """Handle launch button clicked."""
        if self._footer_state() in (INSTANCE_RUNNING, INSTANCE_STOPPING):
            self._on_stop_requested()
        else:
            self._on_launch_requested()

        self._update_number_of_instances_sensitivity()

    def _any_instance_running(self) -> bool:
        """Report whether any instance is currently running."""
        layout_page = self.window.get_layout_page()
        return any(getattr(row, "_is_running", False) for row in layout_page.player_rows)

    def _running_instances(self) -> set:
        """Return the indices of the instances that are actually running."""
        layout_page = self.window.get_layout_page()
        running = set()
        for index, row in enumerate(layout_page.player_rows):
            if getattr(row, "_is_running", False):
                running.add(self._row_instance_num(row, index))
        return running

    def _schedule_profile_save(self):
        """Write the profile once the user stops changing the settings."""
        if self._save_timeout_id:
            GLib.source_remove(self._save_timeout_id)
        self._save_timeout_id = GLib.timeout_add(300, self._save_profile_now)

    def _save_profile_now(self) -> bool:
        """Write the profile and stop the debounce timer."""
        self._save_timeout_id = 0
        self._settings_controller.save_profile()
        return False

    def on_language_changed(self, language: str):
        """Persist and apply a live UI language change from the main window menu."""
        normalized = normalize_language_preference(language)
        self._on_preference_changed("language", normalized)

    def on_settings_changed(self):
        """Handle settings changed in UI."""
        layout_page = self.window.get_layout_page()
        profile = self._settings_controller.get_profile()
        old_party = profile.party_indices()

        ui_data = layout_page.get_data()
        new_party = (
            list(ui_data["party_players"]) if "party_players" in ui_data else list(range(ui_data["num_players"]))
        )
        current_row_ids = [self._row_instance_num(row, index) for index, row in enumerate(layout_page.player_rows)]

        self._settings_controller.update_from_ui_data(ui_data)

        if current_row_ids != new_party:
            devices_info = self._settings_controller.get_devices_info()
            verification_statuses = self._verification_controller.get_all_statuses()
            layout_page.load_data(profile, devices_info, verification_statuses)
            self._settings_controller.update_from_ui_data(layout_page.get_data())

        # The page reports a change for every keystroke, so the profile is
        # written once the user stops typing.
        self._schedule_profile_save()

        if old_party != profile.party_indices():
            self._run_all_verifications()

        self._update_launch_button_sensitivity()

    def on_verification_completed(self):
        """Handle verification completed."""
        self._update_launch_button_sensitivity()

    def on_instance_launch_requested(self, instance_num: int):
        """Handle single instance launch request."""
        profile = self._settings_controller.get_profile()
        layout_page = self.window.get_layout_page()
        player_row = self._get_player_row(instance_num)

        if player_row is None:
            return

        state = player_row.get_instance_state()

        if state == INSTANCE_STOPPING:
            return

        if state in (INSTANCE_STARTING, INSTANCE_RUNNING):
            # An instance that is starting can be cancelled, and one that is
            # running is stopped. Both end with the death of the instance.
            if state == INSTANCE_STARTING:
                logger.info("Cancelling the start of instance %s", instance_num + 1)
                self.window.show_toast(t("presenter.cancelled_instance", num=instance_num + 1))
            else:
                logger.info("Stop requested for instance %s", instance_num + 1)
            self._begin_instance_stop(instance_num)
            self._launch_controller.terminate_single_instance(
                instance_num, on_complete=lambda: GLib.idle_add(self._on_single_instance_stopped, instance_num)
            )
        else:
            layout_error = layout_page.get_layout_error(instance_num)
            if layout_error:
                self.window.show_error(layout_error)
                return
            logger.info("Launch requested for instance %s (no verification required).", instance_num + 1)

            self._save_current_settings()

            self._set_instance_state(instance_num, INSTANCE_STARTING)

            logger.info("Initiating launch of instance %s...", instance_num + 1)

            if profile.enable_kwin_script:
                logger.info("Starting KDE script setup...")
                self._kde_manager.start_kwin_script(profile)

            # The launch runs on a worker thread, so the window stays alive
            # while the instance is prepared and started.
            self._launch_controller.launch_single_instance(
                profile,
                instance_num,
                use_gamescope_override=False,
                on_complete=lambda: GLib.idle_add(self._on_single_instance_launched, instance_num),
                on_error=lambda error: GLib.idle_add(self._on_single_instance_error, instance_num, error),
            )

    def on_instance_terminal_requested(self, prefs_window, instance_num: int):
        """Open a terminal using the selected player's current settings."""
        if not 0 <= instance_num < 8:
            return
        try:
            self._save_current_settings()
            self._instance_service.open_terminal(self._settings_controller.get_profile(), instance_num)
        except Exception as e:
            logger.exception("Failed to open terminal for instance %s: %s", instance_num + 1, e)
            ErrorDialog(prefs_window, t("common.error"), ErrorHandler.format_error(e)).present()

    def on_preferences_clicked(self):
        """Handle preferences menu clicked."""
        profile = self._settings_controller.get_profile()
        prefs_window = PreferencesWindow(self.window, profile, self._on_preference_changed)
        prefs_window.connect("instance-terminal-requested", self.on_instance_terminal_requested)
        prefs_window.present()

    def on_about_clicked(self):
        """Handle about menu clicked."""
        is_pt = get_language() == LANGUAGE_PT_BR
        website = (
            "https://github.com/mall0r/Twinverse/blob/main/docs/README.pt-br.md"
            if is_pt
            else "https://github.com/mall0r/Twinverse/blob/main/README.md"
        )
        support_url = (
            "https://mall0r.github.io/Twinverse/?lang=pt#step-by-step"
            if is_pt
            else "https://mall0r.github.io/Twinverse/#step-by-step"
        )
        about = Adw.AboutDialog(
            application_name="Twinverse",
            application_icon="io.github.mall0r.Twinverse",
            developer_name="Mallor (mall0r)",
            version=Utils.get_version(),
            developers=["Mallor"],
            website=website,
            issue_url="https://github.com/mall0r/Twinverse/issues",
            license_type=Gtk.License.GPL_3_0,
            comments=t("about.comments"),
            support_url=support_url,
        )

        about.add_link(t("about.contributing"), "https://github.com/mall0r/Twinverse/blob/main/CONTRIBUTING.md")
        about.add_link(t("about.donate"), "https://ko-fi.com/mallor")
        about.present(parent=self.window)

    def on_close_requested(self):
        """Handle window close request."""
        self.window.set_sensitive(False)

        # The settings of this session are kept before the app goes away.
        self._save_current_settings()

        for instance_num in list(self._instance_states):
            if self._instance_states.get(instance_num) != INSTANCE_IDLE:
                self._begin_instance_stop(instance_num)
        self._starting_instances.clear()
        self._owned_instances.clear()

        self._launch_controller.stop_instances(on_complete=lambda: GLib.idle_add(self._app.quit))

    def on_devices_refresh_requested(self):
        """Handle devices refresh request."""
        logger.info("Refreshing devices...")
        self._settings_controller.refresh_devices()
        devices_info = self._settings_controller.get_devices_info()

        layout_page = self.window.get_layout_page()
        layout_page.update_devices_info(devices_info)
        self._update_launch_button_sensitivity()

    def _on_launch_requested(self):
        """Handle launch request."""
        logger.info("Launch requested by user.")
        layout_error = self.window.get_layout_page().get_layout_error()
        if layout_error:
            self.window.show_error(layout_error)
            return

        self._bulk_operation_in_progress = True

        self._save_current_settings()

        self._run_all_verifications()

        layout_page = self.window.get_layout_page()
        selected_players = layout_page.get_selected_players()

        if not selected_players:
            logger.warning("No instances selected to launch.")
            self.window.show_error(t("presenter.no_instances_selected"))
            self._bulk_operation_in_progress = False
            return

        logger.info("Selected players for launch: %s", [player + 1 for player in selected_players])

        # Every selected instance is starting, even the ones the launch has
        # not reached yet. The footer must not offer to stop while the launch
        # is still going on.
        for instance_num in selected_players:
            if self._instance_states.get(instance_num) != INSTANCE_RUNNING:
                self._set_instance_state(instance_num, INSTANCE_STARTING)

        profile = self._settings_controller.get_profile()
        profile.selected_players = selected_players
        self._settings_controller.save_profile()

        self.window.show_launching_state()
        self._minimized_after_launch = False

        logger.info("Initiating launch of instances...")
        started = self._launch_controller.launch_instances(
            profile,
            on_progress=self._on_launch_progress,
            on_complete=self._on_launch_complete,
            on_error=self._on_launch_error,
        )
        if not started:
            logger.warning("Another launch is already in progress.")
            self._bulk_operation_in_progress = False
            self.window.show_idle_state()
            self._update_launch_button_sensitivity()
            self._update_number_of_instances_sensitivity()

    def _on_stop_requested(self):
        """Handle stop request."""
        logger.info("Stop all instances requested by user.")
        for instance_num in list(self._instance_states):
            if self._instance_states.get(instance_num) != INSTANCE_IDLE:
                self._begin_instance_stop(instance_num)
        self._starting_instances.clear()
        self._owned_instances.clear()

        self._bulk_operation_in_progress = True

        self._launch_controller.stop_instances(on_complete=lambda: GLib.idle_add(self._on_stop_complete))

    def _on_launch_progress(self, instance_num: int):
        """Handle launch progress update."""
        logger.info("Launched instance %s", instance_num + 1)
        # The progress arrives on the launch worker thread, and the widgets
        # can only be touched from the main thread.
        GLib.idle_add(self._watch_instance_start, instance_num)

    def _on_launch_complete(self):
        """Handle launch complete."""
        GLib.idle_add(self._sync_launch_button_action)
        GLib.idle_add(self._update_number_of_instances_sensitivity)
        GLib.idle_add(self._clear_bulk_operation_flag)

    def _on_launch_error(self, error: Exception):
        """Handle launch error."""
        logger.error("Launch error: %s", error)
        error_msg = ErrorHandler.format_error(error)
        GLib.idle_add(self.window.show_error, error_msg)
        GLib.idle_add(self._restore_after_failed_launch)
        GLib.idle_add(self._update_number_of_instances_sensitivity)
        GLib.idle_add(self._clear_bulk_operation_flag)

    def _on_stop_complete(self) -> bool:
        """Handle stop complete on the main thread."""
        self._starting_instances.clear()
        self._owned_instances.clear()
        for instance_num in list(self._instance_states):
            self._forget_progress(instance_num)
            self._set_instance_detail(instance_num, "")
            self._set_instance_state(instance_num, INSTANCE_IDLE)
        self.window.show_toast(t("presenter.all_stopped"))
        self._sync_launch_button_action()
        self._run_all_verifications()
        self._update_launch_button_sensitivity()
        self._update_number_of_instances_sensitivity()
        self._clear_bulk_operation_flag()
        return False

    def _on_single_instance_launched(self, instance_num: int):
        """Handle single instance launched."""
        GLib.idle_add(self._verify_instance, instance_num)
        GLib.idle_add(self._update_number_of_instances_sensitivity)
        GLib.idle_add(self._watch_instance_start, instance_num)

    def _on_single_instance_stopped(self, instance_num: int):
        """Handle single instance stopped."""
        self._starting_instances.discard(instance_num)
        self._owned_instances.discard(instance_num)
        self._forget_progress(instance_num)
        self._set_instance_detail(instance_num, "")
        self._set_instance_state(instance_num, INSTANCE_IDLE)
        self.window.show_toast(t("presenter.stopped_instance", num=instance_num + 1))

        GLib.idle_add(self._verify_instance, instance_num)
        GLib.idle_add(self._update_number_of_instances_sensitivity)
        GLib.idle_add(self._sync_launch_button_action)

    def _on_single_instance_error(self, instance_num: int, error: Exception):
        """Handle single instance error."""
        logger.error("Error in instance %s: %s", instance_num + 1, error)
        error_msg = ErrorHandler.format_error(error)
        self._set_instance_state(instance_num, INSTANCE_IDLE)
        self.window.show_error(error_msg)
        GLib.idle_add(self._update_number_of_instances_sensitivity)

    def _set_instance_running_state(self, instance_num: int, is_running: bool) -> bool:
        """Update the state of one instance row, from the main thread."""
        row = self._get_player_row(instance_num)
        if row is not None:
            row.set_running_state(is_running)
        return False

    def _set_instance_state(self, instance_num: int, state: str) -> bool:
        """Set the state of one instance, from the main thread."""
        self._instance_states[instance_num] = state
        row = self._get_player_row(instance_num)
        if row is not None:
            row.set_instance_state(state)
        self._sync_launch_button_action()
        return False

    def _footer_state(self) -> str:
        """
        Return the state that the tracked instances have in common.

        The footer only offers to stop when every tracked instance was
        confirmed to be running, so a launch that is still going on cannot be
        interrupted halfway.
        """
        states = [state for state in self._instance_states.values() if state != INSTANCE_IDLE]
        if not states:
            return INSTANCE_IDLE
        if all(state == INSTANCE_RUNNING for state in states):
            return INSTANCE_RUNNING
        if any(state == INSTANCE_STARTING for state in states):
            return INSTANCE_STARTING
        if any(state == INSTANCE_STOPPING for state in states):
            return INSTANCE_STOPPING
        return INSTANCE_RUNNING

    def _sync_launch_button_action(self):
        """Keep the footer button in step with the state of the instances."""
        state = self._footer_state()
        if state == INSTANCE_STARTING:
            self.window.show_launching_state()
        elif state == INSTANCE_STOPPING:
            self.window.show_stopping_state()
        elif state == INSTANCE_RUNNING:
            self.window.show_running_state()
        else:
            self.window.show_idle_state()

    def _on_preference_changed(self, key: str, value):
        """Handle preference changed."""
        if hasattr(self._settings_controller.get_profile(), key):
            setattr(self._settings_controller.get_profile(), key, value)
            self._settings_controller.save_profile()
            logger.info("Preference '%s' updated to: %s", key, value)
        else:
            self._settings_controller.update_preference(key, value)

        if key == "language":
            set_language(value)
            sync_lang = getattr(self.window, "sync_language_action", None)
            if callable(sync_lang):
                sync_lang(value)

        if key == "use_gamescope":
            self.window.get_layout_page().set_gamescope_enabled(bool(value))

        if key == "isolate_network":
            self.window.get_layout_page().set_network_isolation_enabled(bool(value))

        if key == "player_configs":
            profile = self._settings_controller.get_profile()
            devices_info = self._settings_controller.get_devices_info()
            layout_page = self.window.get_layout_page()

            verification_statuses = self._verification_controller.get_all_statuses()

            layout_page.load_data(profile, devices_info, verification_statuses)

            self._run_all_verifications()

        if key == "num_players":
            self._run_all_verifications()

    def _save_current_settings(self):
        """Save current settings from UI."""
        layout_page = self.window.get_layout_page()
        ui_data = layout_page.get_data()
        self._settings_controller.update_from_ui_data(ui_data)
        self._settings_controller.save_profile()

    def _run_all_verifications(self):
        """Run verifications for all active party instances."""
        profile = self._settings_controller.get_profile()
        layout_page = self.window.get_layout_page()

        self._verification_controller.verify_instances(
            profile.party_indices(),
            on_each_complete=lambda i, verified: layout_page.update_verification_status(i, verified),
        )

    def _verify_instance(self, instance_num: int):
        """Verify a specific instance."""
        is_verified = self._verification_controller.verify_instance(instance_num)
        layout_page = self.window.get_layout_page()
        layout_page.update_verification_status(instance_num, is_verified)

    def _update_launch_button_sensitivity(self):
        """Update launch button enabled state."""
        layout_page = self.window.get_layout_page()
        if self._footer_state() == INSTANCE_RUNNING:
            self.window.update_launch_button_sensitivity(True)
            return
        selected_players = layout_page.get_selected_players()

        if not selected_players or layout_page.get_layout_error():
            self.window.update_launch_button_sensitivity(False)
            return

        all_verified = all(self._verification_controller.get_verification_status(p) for p in selected_players)

        self.window.update_launch_button_sensitivity(all_verified)

    def _update_number_of_instances_sensitivity(self):
        """Update the sensitivity of the party add/remove controls."""
        layout_page = self.window.get_layout_page()

        is_any_running = any(self._row_is_active(player_row) for player_row in layout_page.player_rows)

        layout_page.set_number_of_instances_sensitive(not is_any_running)
        layout_page.set_screen_settings_sensitive(not is_any_running)
        layout_page.set_checkboxes_sensitive(not is_any_running)
        self._update_play_button_for_individual_instances(is_any_running)

    def _update_play_button_for_individual_instances(self, is_any_running):
        """Update the Play button sensitivity based on individual instances state."""
        if hasattr(self, "_bulk_operation_in_progress") and self._bulk_operation_in_progress:
            self.window.launch_button.set_sensitive(False)
        else:
            self._update_launch_button_sensitivity()

    def _clear_bulk_operation_flag(self):
        """Clear the bulk operation flag."""
        self._bulk_operation_in_progress = False
        self._update_launch_button_sensitivity()

    def _restore_after_failed_launch(self):
        """Restore the UI after a failed launch, keeping the instances that started."""
        running = self._running_instances()
        for instance_num in list(self._instance_states):
            if instance_num not in running:
                self._set_instance_state(instance_num, INSTANCE_IDLE)

        for index in running:
            row = self._get_player_row(index)
            if row is not None:
                row.set_instance_state(INSTANCE_RUNNING)

        self._run_all_verifications()
        self._update_launch_button_sensitivity()
        self._update_number_of_instances_sensitivity()
        self._bulk_operation_in_progress = False
