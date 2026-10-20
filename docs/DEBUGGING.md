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
├── instances/          # one file per instance launch
│   ├── instance-01-20261020-140102-a8d1f372.log
│   └── latest.log -> instance-01-...log
└── helpers/            # standalone helper logs, such as overlay focus
    └── overlay-focus-a8d1f372-instance-01.log
```

The main log keeps five rotated files of 2 MiB by default. Instance logs are
retained per instance (five newest files, at most 14 days) and helper logs keep
the two newest files per run. The limits can be changed with the environment
variables below.

Every record includes the run identifier and, when available, the instance and
the phase (`launch`, `stop`, or `terminal`). Example:

```
2026-10-20T14:01:02.349-03:00 INFO     src.services.instance [run_id=a8d1f372 instance=2 phase=launch] Launching instance 2
```

The per-instance logs also contain the command line (with common secret
arguments masked), the environment variable names, the output of the
instance process, and the exit code written when the instance stops.

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

When Twinverse itself dies, the Steam instances are not stopped: the sandbox
runs outside the process group of the application, so the clients keep running
without anybody draining their output. Their logs stop growing at that moment,
and the instances have to be closed by hand.

The log system never uses a pipe for the instance output: the child writes
directly to its file, so a chatty Steam or Proton session cannot fill a pipe
and freeze the instance. In the Flatpak path, the host pipes are drained in
background threads to the same file.

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
