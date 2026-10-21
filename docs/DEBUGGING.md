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

The check never mixes the instances. It only accepts a Steam client that
belongs to the process group of that instance, so the client of another
instance, and the Steam of the user, are never taken for ours.

While the client starts, the row of the instance shows a spinner and the
tooltip tells what the Steam is doing, taken from the log of the client. A
Steam that updates itself can take minutes, and the spinner makes it clear
that something is still happening. The window is only minimized once every
instance was confirmed to be open.

The messages of the application are shown over the window. When the window is
minimized, or in the background behind a game, the same message is also shown
as a desktop notification, so a failure is not missed while a game is in
front. The notification uses the notification portal, which needs no extra
permission.

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
