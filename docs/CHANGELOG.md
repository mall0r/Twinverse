
# Changelog

All notable changes to this project will be documented in this file. This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) and follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.

## [Unreleased]

### Added

- Add a pure-Rust userspace `/dev/uinput` interposer (`libtwinverse_uinput.so`) and `libudev` shim (`libtwinverse_udev.so`), built for both 64-bit and 32-bit with zero external Cargo dependencies, enabling full per-instance **Steam Input** without touching host `/dev/uinput` or leaking virtual controllers across instances.
- Add a pure-Rust host input supervisor (`twinverse-input-bridge`) that bridges each player's physical controller over a persistent synthetic `/dev/input/event3000` Unix socket, emits disconnect neutralizer events on unplug, isolates identical sibling controllers, dynamically filters `/dev/hidraw*` via `tw_hidraw.allow` (preserving native gyro, rumble, touchpad, and LEDs), and automatically reconnects controllers mid-session when unplugged and replugged.
- Add an **Isolate network** toggle (`ISOLATE_NETWORK`, default `On`) in `Preferences -> Engine` to disable per-instance `pasta` network isolation (for LAN discovery and local P2P), disabling the per-player `Guest IP` entry while keeping any saved IP intact.
- Add a marquee-scrolling controller dropdown (`MarqueeLabel`) with full-name tooltips and a themed selection dot in Player Setup, plus controller-name tooltips when hovering a player space's enlarged gamepad badge on the layout canvas.

### Fixed

- Verify staged native Rust binaries and shared libraries by byte content (not just file size and `mtime`) so Flatpak/OSTree updates always refresh staged files under `~/.tw-in/` even when `mtime` is epoch 0.
- Allow variadic `open`/`open64` interposition signatures in `twinverse-uinput-interposer` so the native workspace builds cleanly on Rust 1.100+.

### Changed

- Keep Steam Input enabled by default when the native userspace virtual `/dev/uinput` libraries are active, falling back to static device bind-mounts and one-time per-account Steam Input disabling only when running without the native libraries.
- Build and bundle the 64-bit and 32-bit native Rust input libraries and `twinverse-input-bridge` across development runs (`./run.sh`), `make build-native`, `make build`, CI, Flatpak, and AppImage builds (with `GLIBC <= 2.35` validation).
- Rewrite the AppImage symbolic icon appearance verification helper in pure Rust (`scripts/appimage/check-appearance.rs`), removing the last C source file from the repository.

## [2.0.0-alpha.1] - 2026-11-20

### Added

- Redesign the interface and preferences window as a three-pane **Session Studio** (Party Roster, Session Layout canvas, and collapsible Player Setup inspector).
- Add per-monitor tiling templates (`Fullscreen`, `Columns`, `Rows`, `Main left`, `Main top`, and `Grid`) with the `TilingPicker` native thumbnail widget, persistent per-connector layouts, `Automatic` vs. `Custom` placement, and animated drag-and-drop card motion (`CardMotion`).
- Add direct `+ Add player` and per-player removal controls in the Party Roster, inline editable player names (up to 32 characters), mouse-grab indicators, and `Ready` check icons.
- Bundle custom symbolic SVG icons (`res/icons/`) replacing system theme icons, add a dedicated `StudioSpinner` widget for reliable GTK4 animation, redesign floating toast notifications, and introduce a WCAG AA/AAA light mode color palette.
- Add a bilingual (English & Português BR) static documentation site hosted on GitHub Pages (`docs/index.html`, search, dark/light toggle, lightbox, and automated deployment workflow).
- Support SemVer pre-releases (`x.y.z-alpha.N`, `x.y.z-beta.N`, etc.) in CI/CD, `version_manager.py`, `create_release.sh`, and AppStream validation.
- Rewrite the logging system with the Python standard library. Logs now live in the XDG state directory, use per-run and per-instance context, rotate and expire old files, mask common secrets, and capture unhandled exceptions and native crashes.
- Add `--debug`, `--quiet`, `--log-level`, `--log-dir`, `--log-format`, `--json` and `--diagnostics` command-line options, plus `TWINVERSE_*` environment variables for the same settings.
- Add English and Portuguese debugging guides.
- Record one log per instance launch with the command line, the environment variable names, the output of the instance process and the exit code when it stops.
- Add `--clear-logs`, which empties the log directory and exits, and `TWINVERSE_LOG_KEEP_INSTANCES`, `TWINVERSE_LOG_KEEP_HELPERS`, `TWINVERSE_LOG_MAX_AGE_DAYS` and `TWINVERSE_LOG_MAX_TOTAL_MB` to adjust the retention.
- Find the instances that outlived a previous session: Twinverse remembers what it launched, shows the survivors as running, and stops them with the same button.
- Put the footer button in stop mode when an instance survived a crash, instead of waiting for a single instance to be stopped.
- Follow the startup of every instance: the interface says that the Steam client is starting, confirms when it opens, and reports the reason the Steam gave when it fails or the instance stops on its own. The check tracks the SteamRT3 `steamwebhelper` client tree scoped by the instance process group, so instances and the host Steam are never mixed, and waits without an artificial timeout.
- Make the buttons of the interface follow the state that was confirmed: an instance only offers to stop after its Steam client was confirmed to be up, and only goes back to start after the instance was confirmed to be gone. The button of the footer only turns into a stop when every instance it follows is confirmed to be running, and a client that never came up leaves the leftover stopped.
- Let an instance that is still starting be cancelled, so a Steam client that never comes up and never writes a log does not leave the interface stuck.
- Show a spinner and a plain single-line live Steam startup log in Player Setup while an instance bootstraps or updates itself, and minimize the window only after the last instance is confirmed to be open.
- Show the messages of the application as desktop notifications while the window is hidden, so a failure is not missed behind a game.
- Give every isolated instance its own free IPv4 address from the host's subnet, so a game client and a dedicated server on the same machine no longer share an address and Steam can connect directly instead of through a relay. Add a per-instance `GUEST_IP` setting to override the automatic choice.

### Fixed

- Orient display dimensions accurately for rotated monitors.
- Render fitting monitor preview spaces at 1:1 integer pixels to prevent blur, stabilize light mode layout, hide disconnected controllers from the dropdown, and thicken the gamepad badge icon.
- Resolve symlinked `/etc/resolv.conf` targets cleanly before passing them to `pasta` to avoid SELinux denials on systemd-resolved systems.
- Terminate SteamRT3 `setsid` descendant processes safely on stop without affecting other instances or the host Steam client, unlock Session Layout when Steam exits on its own, and prevent false unexpected-stop toasts.
- Keep `Automatic` placement when switching monitor tiling templates instead of unexpectedly flipping to `Custom`.
- Deduplicate logging handler errors, prevent `NullHandler` leaks, and close implicit instance log descriptors after writes.
- Follow desktop themes, cursors, and fonts in the AppImage via Settings portal (`GDK_DEBUG=portals`) and host `/etc/fonts`, and patch symbolic icon classification for GTK 4.16.
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
- Bind the `linux-dmabuf` interface of the GTK bundled in the AppImage to version 5, so the window opens on a compositor that advertises version 6, such as KWin 6.8, instead of crashing during `Gtk.init()`.
- Re-apply the cursor theme configured in the user settings on startup and whenever the `gtk-cursor-theme-name` setting changes, so a resolution that missed on the first pass does not leave the built-in default cursor in the AppImage.

### Changed

- Move the logs from the XDG cache directory to `$XDG_STATE_HOME/twinverse/logs`, matching the XDG specification and the Flatpak application state directory.
- Give each instance launch its own log under `logs/instances`, instead of reusing `steam_instance_N.log`, and move helper logs under `logs/helpers`.
- Replace the custom `Logger` wrapper and logger injection with module-level standard-library loggers configured once at the entry point.
- Mark the instance home directory of the player as read-only for the instances, and keep the input device of the virtual joystick private.
- Reset all the settings of the profile in the preferences window, and report a home directory that could not be removed.
- Present the same window when the application is started again, instead of opening a second one.
- Show the messages of the application with the icon of what they are: a failure is an error, a client that is starting or updating itself is a work in progress, and the other messages are only information. The desktop notification follows the same level, and a failure is critical, so it is not missed behind a game.
- Replace the Steam update progress bar with a plain single-line startup log strip in Player Setup so users can follow Steam bootstrap and update output cleanly.
- Update `pyproject.toml` license metadata for `setuptools>=77`.

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
