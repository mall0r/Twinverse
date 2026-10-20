
# Changelog

All notable changes to this project will be documented in this file. This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.

## [Unreleased]

### Added

- Rewrite the logging system with the Python standard library. Logs now live in the XDG state directory, use per-run and per-instance context, rotate and expire old files, mask common secrets, and capture unhandled exceptions and native crashes.
- Add `--debug`, `--quiet`, `--log-level`, `--log-dir`, `--log-format`, `--json` and `--diagnostics` command-line options, plus `TWINVERSE_*` environment variables for the same settings.
- Add English and Portuguese debugging guides.
- Record one log per instance launch with the command line, the environment variable names, the output of the instance process and the exit code when it stops.
- Add `--clear-logs`, which empties the log directory and exits, and `TWINVERSE_LOG_KEEP_INSTANCES`, `TWINVERSE_LOG_KEEP_HELPERS`, `TWINVERSE_LOG_MAX_AGE_DAYS` and `TWINVERSE_LOG_MAX_TOTAL_MB` to adjust the retention.
- Find the instances that outlived a previous session: Twinverse remembers what it launched, shows the survivors as running, and stops them with the same button.
- Put the footer button in stop mode when an instance survived a crash, instead of waiting for a single instance to be stopped.

### Fixed

- Keep the run identifier in the records written by the launch worker thread, so every line of a launch can be tied to its session.
- Write the logs of the instances in the directory chosen with `--log-dir`, instead of always in the XDG state directory.
- Write the output of an instance straight to its log file in the Flatpak path as well, so an instance that outlives the application keeps its output and never blocks on a broken pipe.
- Rotate the crash log when the application starts, so the crash of the previous session is kept in `crash.log.1` and the size stays bounded.
- Lay out the selected instances in the order they were selected, instead of using the instance number, so a selection that skips an instance no longer builds an invalid command and fails to start.
- Report a display size that cannot be resolved as an error, instead of building a command that made bwrap try to run a program named `--`.
- Create the virtual joystick for the instances that take part in the launch, instead of for the first ones of the list.
- Keep the settings of the instances that are hidden by a lower instance count, and restore them when the count goes up again.
- Restore the selection of the instances from the profile, which was replaced by "all selected" on every reload.
- Keep the performance overlay level chosen in the Steam menu, which was reset on every launch.
- Stop an instance without killing the Wine helpers of the other instances and of the Steam client of the user.
- Write the output of the instance to its log file, so a chatty session cannot fill a pipe and freeze the instance.
- Ask the instance group to stop before killing it, so the Gamescope window, the sandbox and the network helper close in order, instead of the namespace being killed with SIGKILL right after the stop request.
- Report the process group of the instance on the host, so it can be stopped as a whole in the Flatpak.
- Mount the shared game folders and the compatibility tools from the path the host uses, so they are found in the Flatpak.
- Keep the widgets of the instances untouched from the worker threads, and keep the window state in step with the instances that are really running.
- Keep the footer button in step with the instances that are really open, so it does not stay on stop after every instance was closed one by one.
- Stop the launch sequence when the user asks for it, instead of starting the next instance after the stop.
- Finish the stop even when one of the instances fails, instead of leaving the window locked.
- Write the profile once the user stops typing, instead of on every keystroke.
- Restore the panel visibility of the desktop, which was broken by the line break of the value.
- Stop throwing in the KWin script when no window is focused, and restore the selection of the mouse only on one instance.

### Changed

- Move the logs from the XDG cache directory to `$XDG_STATE_HOME/twinverse/logs`, matching the XDG specification and the Flatpak application state directory.
- Give each instance launch its own log under `logs/instances`, instead of reusing `steam_instance_N.log`, and move helper logs under `logs/helpers`.
- Replace the custom `Logger` wrapper and logger injection with module-level standard-library loggers configured once at the entry point.
- Mark the instance home directory of the player as read-only for the instances, and keep the input device of the virtual joystick private.
- Reset all the settings of the profile in the preferences window, and report a home directory that could not be removed.
- Present the same window when the application is started again, instead of opening a second one.

## [1.1.4] - 2026-10-15

### Added

- Isolate each instance's network with `pasta` when it is available on the host, keeping internet access and running without root. Native and Flatpak launches detect it, and the shared host network is kept as the fallback when it is missing.
- Explain how to add the Flathub remote before installation, in the English and Portuguese READMEs.

### Fixed

- Route Steam's remote capture to the instance's own Gamescope through PipeWire, instead of recording the host's compositor.
- Run Gamescope, MangoApp and Steam inside the same sandbox, and unshare IPC per instance so Xwayland can create its own directory in `/tmp`.
- Expose the Gamescope limiter file to Proton, which the previous sandbox setup hid under the runtime and silently disabled the frame limiter.
- Match the Gamescope refresh rate to the monitor each instance was assigned, instead of reusing a single rate for all of them.
- Prioritize the primary monitor when placing instances, querying Plasma through D-Bus when the monitor backend cannot mark which one it is, and share that order with the KWin layout script.
- Allow all eight instances in fullscreen instead of capping them by the monitor count, and reuse the first monitor when an instance has no monitor of its own, for both its Gamescope resolution and its refresh rate.
- Apply the splitscreen menu overlay repair on every instance, not only on the ones whose Steam client still launches `steamwebhelper.sh`. Valve's SteamRT3 client starts `steamwebhelper` directly, so those instances never ran the startup gate and silently lost both the controller shared-memory wait and the narrow overlay focus repair.
- Wait for the instance's nested Gamescope X server instead of failing when the repair starts from Steam's launcher, and keep a single helper per sandbox through one lock file.

### Changed

- Build the Flatpak against the GNOME 51 runtime. Installing over the previous build updates it in place, and the instance homes under `~/.var/app/io.github.mall0r.Twinverse` are kept.
- Set the Gamescope refresh rate from the monitor, removing the manual setting from the preferences window, the profile and the guides.
- Rename the default audio option from "None" to "Default".
- Number `overlay_focus_instance_N.log` like the `instance_N` cache directory, so the helper's log and its gate share one index.
- Condense the docstrings and comments across the codebase, with no behaviour change.

## [1.1.3] - 2026-10-02

### Added

- Embed AppImage update information pointing to the latest stable GitHub release, enabling updates through AppImageUpdate and compatible tools.
- Generate and publish the matching `.AppImage.zsync` file alongside the AppImage.

### Changed

- Verify the embedded update information and require a non-empty `.zsync` file during packaging.
- Document the update and publishing process and include `.zsync` files in packaging cleanup and Git ignore rules.

Users of 1.1.2 or earlier must manually download 1.1.3 once to enable future updates through compatible tools.

## [1.1.2] - 2026-10-01

### Added

- Turn off Steam Input in the account settings of each instance on its first launch, so it stops overriding the per-instance controller devices.

### Fixed

- Restore controller navigation of the Steam side menus while a game is running in splitscreen instances.
- Build the AppImage in an Ubuntu 22.04 container that compiles its own GTK 4.16, libadwaita 1.6 and GLib 2.82 stack, instead of copying the libraries of the build workstation.
- Reject the AppImage when a bundled library requires a newer glibc than 2.35.

### Changed

- Verify in CI that the AppImage opens a window on Ubuntu 22.04 and Ubuntu 24.04 before it is attached to a release.
- Publish the Flatpak and the AppImage from separate CI jobs.
- Enable the SteamDeck tag by default in new profiles.

## [1.1.1] - 2026-10-01

### Fixed

- Restore Steam performance-menu control of MangoApp using a shared configuration file per instance.
- Prevent duplicated overlay elements by removing inline MangoHud configuration in native and Flatpak launches.
