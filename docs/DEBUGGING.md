<p align="right">
  <a href="https://mall0r.github.io/Twinverse/#cli-debugging"><img src="https://img.shields.io/badge/Docs-GitHub%20Pages-1f6feb.svg?logo=githubpages&logoColor=white" alt="Interactive Documentation"/></a>
  <a href="DEBUGGING.md"><img src="https://img.shields.io/badge/en-US-darkblue.svg" alt="English"/></a>
  <a href="DEBUGGING.pt-br.md"><img src="https://img.shields.io/badge/pt-BR-darkgreen.svg" alt="Portuguese"/></a>
</p>

# Debugging and logs

Twinverse writes developer logs for diagnosing launch failures and crashes. The
logs are disposable, stay on your machine, and are not shown in the interface.
They are written with the Python standard library only.

## Where the logs are

Logs follow the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/)
and live under `XDG_STATE_HOME`:

| Context | Directory |
| --- | --- |
| Native | `~/.local/state/twinverse/logs` |
| Flatpak | `~/.var/app/io.github.mall0r.Twinverse/.local/state/twinverse/logs` |
| `XDG_STATE_HOME` set | `$XDG_STATE_HOME/twinverse/logs` |

Inside Flatpak, the XDG variables exported by current Flatpak releases already
point to the application's own directories. Older Flatpak releases may omit
them; Twinverse then falls back directly to
`~/.var/app/$FLATPAK_ID/.local/state`, so no extra permission or `--persist`
argument is needed.

The directory and its files are created with owner-only permissions (`0700`
for directories, `0600` for files).

## What is in the directory

```
logs/
├── twinverse.log       # main log, rotated
├── crash.log           # low-level crash output (faulthandler)
├── crash.log.1         # the crash of the previous session
├── instances/          # one file per instance launch
│   ├── instance-01-20261020-140102-a8d1f372.log
│   └── latest.log -> instance-01-...log
└── helpers/            # standalone helper logs, such as overlay focus
    └── overlay-focus-a8d1f372-instance-01.log
```

The main log keeps five rotated files of 2 MiB by default. Instance logs are
retained per instance (five newest files, at most 14 days) and helper logs keep
the two newest files per run. A total limit of 256 MiB for the whole directory
removes the oldest files when it is reached. The limits can be changed with the
environment variables below.

The crash log is rotated when the application starts: the crash of the previous
session stays in `crash.log.1`, and a fresh `crash.log` is created. The two
files together are always bounded.

Every record includes the run identifier and, when available, the instance and
the phase (`launch`, `stop`, or `terminal`). Example:

```
2026-10-20T14:01:02.349-03:00 INFO     src.services.instance [run_id=a8d1f372 instance=2 phase=launch] Launching instance 2
```

The per-instance logs also contain the command line (with common secret
arguments masked), the environment variable names, the output of the
instance process, and the exit code written when the instance stops. The
instance writes to its own log file, so the output keeps being recorded even
when Twinverse itself dies.

## Cleaning the logs

The logs are disposable. To start from an empty directory, without opening the
interface:

```bash
twinverse --clear-logs
```

The cleanup also happens on its own: the rotated files are replaced when they
reach the size limit, the instance and helper logs expire, and the total size
of the directory is kept under the limit below.

## Running with debug logs

The graphical interface has no log controls. Start Twinverse from a terminal
or edit the `.desktop` command if you need a different level:

```bash
# Debug messages on the console and in the file
twinverse --debug

# Only warnings and errors on the console; the file stays at debug
twinverse --quiet

# Choose the console level explicitly
twinverse --log-level DEBUG

# Keep logs outside the default XDG directory
twinverse --log-dir /tmp/twinverse-debug --debug
```

Unknown arguments are passed to GTK, so desktop or session-manager flags keep
working.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `TWINVERSE_DEBUG` | unset | `1` enables debug on the console and in the file |
| `TWINVERSE_LOG_LEVEL` | `INFO` | Console level (name or number) |
| `TWINVERSE_LOG_FILE_LEVEL` | `DEBUG` | File level (name or number) |
| `TWINVERSE_LOG_DIR` | XDG state | Alternative log directory |
| `TWINVERSE_LOG_FORMAT` | `text` | `text` or `json` |
| `TWINVERSE_LOG_CONSOLE` | `1` | Set to `0` to disable console output |
| `TWINVERSE_LOG_MAX_BYTES` | `2097152` | Main log size before rotation |
| `TWINVERSE_LOG_BACKUPS` | `5` | Number of rotated main logs |
| `TWINVERSE_INSTANCE_LOG_MAX_BYTES` | `104857600` | Size cap for each instance log |
| `TWINVERSE_LOG_KEEP_INSTANCES` | `5` | Instance logs kept for each instance |
| `TWINVERSE_LOG_KEEP_HELPERS` | `2` | Helper logs kept for each run |
| `TWINVERSE_LOG_MAX_AGE_DAYS` | `14` | Age of the oldest log that is kept |
| `TWINVERSE_LOG_MAX_TOTAL_MB` | `256` | Size limit of the whole log directory |
| `TWINVERSE_UINPUT_LOG` | unset | Set to `1` to enable verbose stderr logs from `twinverse-input-bridge`, `libtwinverse_uinput.so`, and `libtwinverse_udev.so` inside the instance log |

Command-line options win over the environment.

## Diagnostics without opening the window

`--diagnostics` configures logging, prints a report to stdout, and exits before
GTK is imported. That makes it useful on a machine where the interface does not
start:

```bash
twinverse --diagnostics
twinverse --diagnostics --json > twinverse-diagnostics.json
```

The report includes the Twinverse version, Python and platform, Flatpak
metadata, session type, XDG paths, log sizes, available optional dependencies
(`bwrap`, `pasta`, `gamescope`, `steam`), and the end of the recent logs. It
does not include the full environment or the instance environments.

When reporting a problem, include the report and the relevant files from the
log directory. Review them before sharing: paths and command lines can still
identify your setup, even though common passwords and tokens are masked.

## Virtual uinput, Steam Input & controller hotplug

When the native Rust input artifacts are present (always bundled in Flatpak and
AppImage, and built into `res/native/` by `./run.sh` or `make build-native`),
Twinverse stages a small per-player runtime directory inside each player's home:

```text
<home_N>/.tw-in/
├── bin/
│   └── twinverse-input-bridge   # host hotplug & hidraw allowlist supervisor
├── lib64/
│   ├── libtwinverse_uinput.so   # 64-bit userspace /dev/uinput + event + hidraw interposer
│   └── libtwinverse_udev.so     # 64-bit libudev shim (virtual evdev + hidraw hotplug)
├── lib32/
│   ├── libtwinverse_uinput.so   # 32-bit interposer (for Steam's 32-bit client)
│   └── libtwinverse_udev.so     # 32-bit libudev shim
└── sock/
    ├── tw_event3000.sock        # bridged physical controller socket (when bridge active)
    ├── tw_event2000.sock        # Steam Input virtual controller sockets (2000+)
    └── tw_hidraw.allow          # dynamic newline-separated allowlist of hidraw nodes
```

Key troubleshooting notes:

- **Verbose native tracing:** Set `TWINVERSE_UINPUT_LOG=1` either in the player's
  **Environment variables** (for `libtwinverse_uinput.so` / `libtwinverse_udev.so`)
  or in the environment before launching Twinverse (to also log `twinverse-input-bridge`
  unplug/reconnect and `hidraw` allowlist transitions). Output is recorded in
  `logs/instances/instance-NN-*.log`.
- **Deferred `LD_PRELOAD`:** Gamescope itself is never preloaded. Twinverse
  passes `TWINVERSE_VIRTUAL_UINPUT=1`, `TWINVERSE_UINPUT_SOCKET_DIR`,
  `TWINVERSE_PHYSICAL_BRIDGE`, and `TWINVERSE_HIDRAW_FILTER` into the sandbox and
  uses `GAMESCOPE_RUNTIME_SETUP` so `LD_PRELOAD` activates only for Steam and
  its child game processes.
- **Byte-verified staging (Flatpak/OSTree):** Staged files under `~/.tw-in/` are
  compared by byte content (not just size and `mtime`) so Flatpak updates always
  refresh native libraries even when OSTree sets `mtime` to epoch 0.
- **Fallback detection:** If `twinverse.log` notes that native virtual uinput
  libraries were not found (e.g., running from source without Rust), Twinverse
  automatically falls back to static `/dev/input/eventX` bind-mounts, static
  `/dev/hidraw*` masking, and one-time per-account Steam Input disabling.

## Crashes and unhandled exceptions
Twinverse installs exception hooks and enables `faulthandler`. Python
tracebacks go to `twinverse.log`; native crashes and hard aborts write a Python
stack to `crash.log`, including the state of every thread. A crash in a child
process does not stop the other instances, and its output remains in that
instance's log.

When Twinverse itself dies, the Steam instances are not stopped: they run
outside the process group of the application, so the clients keep running.
Their logs keep being written, because each instance writes to its own file.

The next session finds those instances. Twinverse remembers what it launched
in `instances.json`, inside the XDG state directory, and checks on startup
whether the processes are still alive and still the ones it launched. The
instances that survived are shown as running, and the stop button closes them.
A process group that the system recycled in the meantime is never touched.

The log system never uses a pipe for the instance output: the child writes
directly to its file, so a chatty Steam or Proton session cannot fill a pipe
and freeze the instance. The Flatpak path uses the same redirect, so the
output of an instance that outlives the application is never lost.

### The window never appears on Wayland

An AppImage can die before its window exists for a reason outside Twinverse:
the GTK it bundles. GTK 4.16 binds the `linux-dmabuf` version that the
compositor advertises, but it only implements the feedback of version 5. On a
compositor that advertises version 6, such as KWin 6.8, no `main_device` event
arrives and the first `tranche_done` event dereferences a NULL pointer, so the
process dies with `SIGSEGV` inside `Gtk.init()`.

`crash.log` shows the failure in `gi/overrides/Gtk.py`, before any code of the
application runs. The Flatpak is not affected, because the GNOME runtime ships
a current GTK. If an AppImage still bundles GTK 4.16, run it on the X11
backend, which never binds the Wayland interface:

```bash
GDK_BACKEND=x11 ./Twinverse-x86_64.AppImage
```

`GDK_DISABLE=dmabuf` does not help: the display binds the interface before it
consults that setting.

### Windows swap positions when starting or closing a game

The KWin layout associates each window with an explicit instance, not its
position in `workspace.windowList()`. The launcher sets
`TWINVERSE_KWIN_INSTANCE` in Gamescope's environment. A Twinverse D-Bus
service identifies the instance using KWin's window-owner PID; in Flatpak,
the lookup uses the host PID. The game title, window object and PID can
change without changing that instance's reserved position.

The split count comes from the player selection, not the number of windows
currently visible. A disappearing window leaves its slot reserved instead
of moving or enlarging the other instances. The script corrects external
geometry changes and ignores Gamescope windows outside the selected instances.

Keep Twinverse running, even minimized, to identify new windows. Debug logs
record the PID and instance without recording the process environment. KWin
also prints instance-to-slot associations in its own logs. Layout changes
unload the previous script by plugin name; numeric script IDs are not valid
names for `unloadScript`.

### The cursor changes inside the window

The application never sets a cursor. GTK chooses it from the theme named by
`gtk-cursor-theme-name` and the size from `gtk-cursor-theme-size`, and falls
back to the built-in default cursor when the theme cannot be loaded.

The application now re-applies the cursor theme configured in the user
settings on startup and whenever the `gtk-cursor-theme-name` setting changes,
so a resolution that missed on the first pass does not leave the built-in
default cursor in place. However, reapplying the value does not help if GTK
reads the wrong theme: the AppImage's GTK 4.16 used GSettings without the host
settings backend and obtained `Adwaita` instead of the KDE cursor preference.
This also happens on Wayland; it does not imply a switch to X11.

The AppImage launcher enables the Settings portal (`GDK_DEBUG=portals`) to
receive the desktop's cursor theme, size and font, including live changes.
Host themes take precedence over the bundled fallback. For debugging,
`GDK_DEBUG=no-portals` explicitly disables this integration.

### Fonts and icons differ only in the AppImage

The AppImage uses the host's `/etc/fonts` and respects user-supplied
`FONTCONFIG_FILE` and `FONTCONFIG_PATH`. Its bundled configuration is only a
fallback when host configuration is absent. The bundled fontconfig is updated
to understand rules from recent distributions as well.

GTK 4.16 also failed to mark icons found directly in the `icons/` resource
directory as symbolic, leaving the SVG's white fill unchanged in light mode.
An AppImage-only patch fixes this classification. The build checks actual
icon pixels with black and white foregrounds using the GTK being packaged
(via `scripts/appimage/check-appearance.rs`), without modifying the SVGs used
by other packages.

## When the Steam client does not open

The sandbox can start while the Steam client never comes up, leaving a
compositor window that never appears. Twinverse follows the startup of every
instance it launches and tells the user what is happening:

- while the client starts, a message appears over the window;
- when the client reports that it opened, the message is replaced by a short
  confirmation;
- when the Steam client writes a fatal line in its own log, or the instance
  stops on its own, the message says what the Steam reported and the reason
  is written to `twinverse.log` as a warning.

There is no timeout in any of it. A slow machine takes as long as it needs,
and the message stays until the Steam client says it is up.

The check never mixes the instances. It tracks the SteamRT3 `steamwebhelper`
client tree scoped to that instance's process group (and safely terminates
`setsid` descendants on stop), so the client of another instance and the user's
host Steam are never confused or harmed.

While the client starts or updates itself (which can take several minutes),
the player row shows a spinning indicator and the Player Setup inspector
displays a plain single-line live Steam startup log directly above the
**Start player** / **Install Steam** button, polled every second from
`.local/share/Steam/logs/console-linux.txt`. The last console line is kept
across quiet intervals and cleared once the instance is `Running` or stopped.
The window is only minimized once every instance has been confirmed open.

The messages of the application are shown over the window. When the window is
minimized, or in the background behind a game, the same message is also shown
as a desktop notification, so a failure is not missed while a game is in
front. The notification uses the notification portal, which needs no extra
permission. A message has a level, and the level decides the icon and how
urgent it is: a failure is an error, and it is critical, so it is not missed,
while a client that is starting, or updating itself, is a work in progress,
and the other messages are only information.

The buttons of the interface follow the same rule. An instance only shows
"Stop" after its Steam client was confirmed to be up, and it only goes back
to "Start" after the instance was confirmed to be gone. While an instance is
starting its button says "Cancel", which stops the instance that never came
up, and while it is stopping the button cannot be pressed. The button of the
footer only turns into "Stop" when every instance it follows is confirmed to
be running, so a launch that is still going on cannot be interrupted halfway.
A client that never came up leaves nothing to preserve, so the leftover is
stopped and the instance goes back to "Start".

The log of the Steam client itself is in the home of the instance, at
`.local/share/Steam/logs/console-linux.txt`. That file holds the reason of a
failure in the words of the Steam, and the message of the interface quotes it.

## Privacy

Logs are local and are not uploaded automatically. Twinverse masks common
secret shapes (`PASSWORD=...`, `TOKEN=...`, Authorization headers, URL
credentials, and similar command-line flags) before writing. This is a
best-effort safety net, not a guarantee: remove the logs if they contain
information you do not want to share.

## Flatpak notes

No manifest change is required for the logs, and no extra filesystem
permission is added. The log directory is inside the application's own state
directory, which Flatpak keeps across updates. The helper log is mounted into
the instance sandbox at `/tmp/twinverse-logs` only while the overlay focus
helper is enabled.
