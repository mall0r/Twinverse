"""Knows whether the Steam client of an instance is really running.

The launcher can only tell that the sandbox started. The Steam client itself
lives in the host, and it may never come up. This module answers that
question without mixing the instances with each other, and without confusing
them with the Steam of the desktop.

The check is always scoped to the process tree rooted at the process group of
the instance, so the Steam client of another instance, and the Steam of the
user, are never taken for ours. Watching the UI process (`steamwebhelper`)
rather than the `steam` bootstrapper ensures the updater does not report the
client as running before the Steam UI actually opens.
"""

import logging
import os
import re
import shlex
from pathlib import Path
from typing import NamedTuple, Optional

from src.core import Config, Utils

logger = logging.getLogger(__name__)


class ClientUpdate(NamedTuple):
    """What the log of the client tells about this launch."""

    progress: Optional[str] = None
    failure: Optional[str] = None
    percent: Optional[int] = None


# The Steam client UI process. The bootstrapper/updater itself runs as "steam"
# for minutes during first install or updates, whereas "steamwebhelper" only
# starts once the actual Steam client opens.
STEAM_CLIENT_NAMES = ("steamwebhelper",)

STATUS_UP = "up"
STATUS_DOWN = "down"

# What the Steam client writes when it cannot go on. The pattern is kept
# narrow on purpose: a line that only looks like a failure would stop an
# update that is still going on.
FATAL_PATTERN = re.compile(
    r"fatal IO error|Segmentation fault|\bPANIC\b|core dumped",
    re.IGNORECASE,
)


def _read_proc_entry(pid_str: str) -> Optional[tuple[int, int, int, str]]:
    """Return ``(pid, ppid, pgrp, comm)`` from ``/proc/<pid>/stat``, or None."""
    try:
        stat = Path(f"/proc/{pid_str}/stat").read_text()
    except OSError:
        return None
    open_paren = stat.find("(")
    close_paren = stat.rfind(")")
    if open_paren == -1 or close_paren <= open_paren:
        return None
    comm = stat[open_paren + 1 : close_paren]
    fields = stat[close_paren + 1 :].split()
    if len(fields) < 3:
        return None
    try:
        return int(pid_str), int(fields[1]), int(fields[2]), comm
    except ValueError:
        return None


def find_client_pids(pgid: int) -> list[int]:
    """Return the Steam client UI processes belonging to the given instance group.

    Inside SteamRT3, pressure-vessel (``pv-adverb``) and ``steamwebhelper``
    start new process groups with ``setsid``, so matching ``pgrp == pgid``
    alone misses them. Walking descendants of every process in ``pgid`` keeps
    each instance strictly isolated from other instances and desktop Steam.
    """
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return []

    children: dict[int, list[int]] = {}
    comms: dict[int, str] = {}
    queue: list[int] = []
    visited: set[int] = set()

    for entry in entries:
        if not entry.name.isdigit():
            continue
        parsed = _read_proc_entry(entry.name)
        if parsed is None:
            continue
        pid, ppid, pgrp, comm = parsed
        comms[pid] = comm
        children.setdefault(ppid, []).append(pid)
        if pgrp == pgid or pid == pgid:
            if pid not in visited:
                visited.add(pid)
                queue.append(pid)

    found: list[int] = []
    while queue:
        current = queue.pop()
        if comms.get(current) in STEAM_CLIENT_NAMES:
            found.append(current)
        for child in children.get(current, ()):
            if child not in visited:
                visited.add(child)
                queue.append(child)
    return found


# Lines Steam prints in every session or internal update-UI IPC chatter that
# add noise or overwrite the actual human-readable console status line.
NOISE_PATTERN = re.compile(
    r"ld\.so|LD_PRELOAD|Fontconfig|XOpenIM|unsetenv count|srt-logger"
    r"|set percent complete:|^(?:create|show|destroy) window$"
    r"|ProcessNextMessage:|No more messages are expected"
    r"|CProcessEnvironmentManager|minidumps folder is set"
    r"|Installing breakpad exception handler|Using update UI:"
    r"|Failed to load cached hosts file|ILocalize::AddFile"
    r"|Package file .* missing or incorrect size"
    r"|Add pending download:|Manifest download: send request"
    r"|crash_reporting\.cc",
    re.IGNORECASE,
)

# The lines that say that the client is updating itself. A client that only
# starts does not write them, so the user only hears about an update when
# there is one.
UPDATE_PATTERN = re.compile(
    r"updat|download|install|patch|unpack|extract|verify|verifying|cleaning up",
    re.IGNORECASE,
)

# The Steam writes how far the update went in brackets, and the steps that
# have no percentage as dashes.
PERCENT_PATTERN = re.compile(r"\[\s*(\d{1,3})\s*%\]")

# The update UI IPC also reports an integer percentage on its own line.
SET_PERCENT_PATTERN = re.compile(r"set percent complete:\s*(\d{1,3})\b", re.IGNORECASE)

# The client also says how much it downloaded, and how much it has to.
DOWNLOAD_PATTERN = re.compile(
    r"downloading update \(\s*([\d,]+) of ([\d,]+) KB\s*\)",
    re.IGNORECASE,
)

_TIMESTAMP_PATTERN = re.compile(r"^\[[^\]]*\]\s*")
_STATUS_MESSAGE_PREFIX = re.compile(r"^set status message:\s*", re.IGNORECASE)


def is_update_progress(message: str) -> bool:
    """Tell whether the line says that the client is updating itself."""
    return bool(UPDATE_PATTERN.search(message))


def _percent_of(line: str) -> Optional[int]:
    """Return how far the update went, in percent, or None when it is unknown."""
    match = PERCENT_PATTERN.search(line)
    if match:
        return min(int(match.group(1)), 100)

    match = SET_PERCENT_PATTERN.search(line)
    if match:
        return min(int(match.group(1)), 100)

    match = DOWNLOAD_PATTERN.search(line)
    if match:
        done = int(match.group(1).replace(",", ""))
        total = int(match.group(2).replace(",", ""))
        if total > 0:
            return min(int(done * 100 / total), 100)
    return None


def _useful_line(line: str) -> str:
    """Return the part of a log line that is worth showing."""
    text = line.strip()
    if not text:
        return ""
    while True:
        stripped = _TIMESTAMP_PATTERN.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    text = _STATUS_MESSAGE_PREFIX.sub("", text, count=1).strip()
    if not text or NOISE_PATTERN.search(text):
        return ""
    if len(text) > 140:
        text = text[:137] + "…"
    return text


def status_directory() -> Path:
    """Return the directory that holds the state files, creating it."""
    directory = Config.state_dir() / "instances"
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
    except OSError:
        pass
    return directory


class SteamClientProbe:
    """The state of the Steam client of one instance."""

    def __init__(self, instance_num: int):
        """Initialize the probe of one instance."""
        self.instance_num = instance_num

    @property
    def status_path(self) -> Path:
        """Return the file where the host watcher writes the state."""
        return status_directory() / f"instance-{self.instance_num + 1:02d}.status"

    def is_client_up(self, pgid: int) -> bool:
        """
        Report whether the Steam client of this instance is running.

        Inside a Flatpak the watcher on the host answers, because the
        processes of the instance live outside the sandbox. Natively the
        process table of the machine is enough.
        """
        if Utils.is_flatpak():
            return self._read_host_status() == STATUS_UP
        return bool(find_client_pids(pgid))

    def _read_host_status(self) -> Optional[str]:
        """Read the state that the watcher on the host wrote."""
        try:
            return self.status_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    def clear_status(self) -> None:
        """Remove the state file of the instance."""
        try:
            self.status_path.unlink(missing_ok=True)
        except OSError:
            pass

    @property
    def client_log_path(self) -> Path:
        """Return the log that the Steam client of the instance writes."""
        return Config.get_steam_home_path(self.instance_num) / ".local/share/Steam/logs/console-linux.txt"

    def client_log_size(self) -> int:
        """Return the current size of the log of the Steam client."""
        try:
            return self.client_log_path.stat().st_size
        except OSError:
            return 0

    def read_updates(self, since: int = 0) -> ClientUpdate:
        """
        Return what the Steam client is doing and the reason it gave up.

        Only the lines written since the given offset are read, so a long
        update does not make every check read the whole log again. The
        percentage is the one of the last line that gave one, so the bar of
        the update knows how far it went.
        """
        try:
            with self.client_log_path.open("rb") as stream:
                stream.seek(since)
                text = stream.read().decode("utf-8", "replace")
        except OSError:
            return ClientUpdate()

        progress = None
        failure = None
        percent = None
        for line in text.splitlines():
            found = _percent_of(line)
            if found is not None:
                percent = found
            message = _useful_line(line)
            if not message:
                continue
            if failure is None and FATAL_PATTERN.search(message):
                failure = message
                continue
            progress = message
        return ClientUpdate(progress, failure, percent)

    def failure_reason(self, since: int = 0) -> Optional[str]:
        """Return the fatal line the Steam client reported, if any."""
        try:
            with self.client_log_path.open("rb") as stream:
                stream.seek(since)
                text = stream.read().decode("utf-8", "replace")
        except OSError:
            return None
        for line in reversed(text.splitlines()):
            if FATAL_PATTERN.search(line):
                return line.strip()
        return None

    def watcher_script(self) -> str:
        """
        Return the shell code that watches the client from the host.

        The watcher runs with the command of the launch, on the host, and
        writes the state of the client in a file that both sides can read. It
        only writes when the state changes, and it ends with the instance.
        Checking descendants of the launch process group follows SteamRT3's
        sub-sessions without ever matching desktop Steam or another instance.
        """
        status = shlex.quote(str(self.status_path))
        name_checks = " || ".join(f'$4=="{name}"' for name in STEAM_CLIENT_NAMES)
        awk_program = shlex.quote(
            f"{{ p[$1]=$2; if ($3==g || $1==g) m[$1]=1; if (NF==4 && ({name_checks})) w[$1]=1 }} "
            "END { for (k in w) { c=k; n=0; while (c && !m[c] && ++n<64) c=p[c]; if (m[c]) exit 0 } exit 1 }"
        )
        return (
            "( state=; "
            "while kill -0 $$ 2>/dev/null; do "
            f"if ps -eo pid=,ppid=,pgid=,comm= 2>/dev/null | awk -v g=$$ {awk_program}; "
            "then current=up; else current=down; fi; "
            f'[ "$state" = "$current" ] || {{ echo $current > {status}; state=$current; }}; '
            "sleep 1; done ) >/dev/null 2>&1 &"
        )
