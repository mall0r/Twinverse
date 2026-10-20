"""Persistent record of the instances that are still open.

The application can die while the Steam instances keep running, because the
instances live outside its process group. This registry remembers what was
launched, so a later session can find the instances that outlived it and stop
them from the interface.
"""

import json
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol

from src.core import Config, Utils

logger = logging.getLogger(__name__)

NATIVE = "native"
FLATPAK = "flatpak"


class ProcessHandle(Protocol):
    """The part of a process handle that the instance service uses."""

    @property
    def pid(self) -> int:
        """Return the identifier of the process."""
        ...

    def poll(self) -> Optional[int]:
        """Return the exit code of the process, or None while it runs."""
        ...

    def wait(self, timeout: Optional[float] = None) -> int:
        """Wait for the process to end and return its exit code."""
        ...

    def kill(self) -> None:
        """Stop the process without asking."""
        ...


@dataclass
class InstanceRecord:
    """One instance launched by a session of the application."""

    instance: int
    pgid: int
    mode: str
    home: str
    log: Optional[str] = None
    pid: Optional[int] = None
    started_at: str = ""
    run_id: str = ""

    def to_dict(self) -> dict:
        """Return the record as plain data."""
        return {
            "instance": self.instance,
            "pgid": self.pgid,
            "mode": self.mode,
            "home": self.home,
            "log": self.log,
            "pid": self.pid,
            "started_at": self.started_at,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, data: object) -> Optional["InstanceRecord"]:
        """Build a record from stored data, or None when it is incomplete."""
        if not isinstance(data, dict):
            return None
        try:
            instance = int(data["instance"])
            pgid = int(data["pgid"])
        except (KeyError, TypeError, ValueError):
            return None
        return cls(
            instance=instance,
            pgid=pgid,
            mode=str(data.get("mode", NATIVE)),
            home=str(data.get("home", "")),
            log=data.get("log"),
            pid=data.get("pid"),
            started_at=str(data.get("started_at", "")),
            run_id=str(data.get("run_id", "")),
        )


class InstanceRegistry:
    """The file that remembers the instances launched by the application."""

    def __init__(self, path: Optional[Path] = None):
        """Initialize the registry, defaulting to the XDG state directory."""
        self.path = Path(path) if path is not None else Config.state_dir() / "instances.json"

    def load(self) -> list[InstanceRecord]:
        """Return the stored records, ignoring a damaged file."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        records = []
        for item in data.get("instances", []):
            record = InstanceRecord.from_dict(item)
            if record is not None:
                records.append(record)
        return records

    def save(self, records: list[InstanceRecord]) -> None:
        """Write the records, keeping the file private and never half written."""
        if not records:
            self.clear()
            return
        payload = {
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "instances": [record.to_dict() for record in records],
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
            os.replace(temporary, self.path)
        except OSError as error:
            logger.warning("Could not write the instance registry: %s", error)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def add(self, record: InstanceRecord) -> None:
        """Remember one instance, replacing an older record of the same one."""
        records = [item for item in self.load() if item.instance != record.instance]
        records.append(record)
        self.save(records)

    def remove(self, instance_num: int) -> None:
        """Forget one instance that is not running anymore."""
        records = [item for item in self.load() if item.instance != instance_num]
        self.save(records)

    def clear(self) -> None:
        """Delete the registry file."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def read_cmdline(pid: int) -> str:
    """Return the command line of a process of this system."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "replace")


def read_host_cmdline(pid: int) -> str:
    """Return the command line of a host process, also from inside a Flatpak."""
    if not Utils.is_flatpak():
        return read_cmdline(pid)
    try:
        result = Utils.flatpak_spawn_host(
            ["sh", "-c", f"tr '\\0' ' ' < /proc/{pid}/cmdline 2>/dev/null"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def belongs_to_instance(record: InstanceRecord, cmdline: str) -> bool:
    """
    Report whether a running process is still the instance that was launched.

    The process group is only trusted when the command line still carries the
    home directory of the instance or the path of its log. A recycled process
    group would belong to something else, and must never be stopped.
    """
    if not cmdline:
        return False
    for marker in (record.home, record.log):
        if marker and marker in cmdline:
            return True
    return False


class InstanceProbe:
    """Checks whether the instances of a previous session are still running."""

    def __init__(self, ttl: float = 2.0):
        """Initialize the probe with the lifetime of its cached answers."""
        self._ttl = ttl
        self._cache: dict[int, tuple[float, bool]] = {}

    def alive(self, record: InstanceRecord) -> bool:
        """Report whether the instance of the record is still running."""
        now = time.monotonic()
        cached = self._cache.get(record.instance)
        if cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        alive = belongs_to_instance(record, read_host_cmdline(record.pgid))
        self._cache[record.instance] = (now, alive)
        return alive

    def forget(self, instance_num: int) -> None:
        """Drop the cached answer of one instance."""
        self._cache.pop(instance_num, None)


class RecoveredInstance:
    """The handle of an instance that outlived the session that launched it."""

    def __init__(self, record: InstanceRecord, probe: InstanceProbe):
        """Initialize the handle of a recovered instance."""
        self.record = record
        self.pid = record.pgid
        self._probe = probe

    def poll(self) -> Optional[int]:
        """Return None while the instance is running."""
        return None if self._probe.alive(self.record) else 0

    def wait(self, timeout: Optional[float] = None) -> int:
        """Wait until the instance is gone."""
        deadline = time.monotonic() + timeout if timeout is not None else None
        while self._probe.alive(self.record):
            if deadline is not None and timeout is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired("instance", timeout)
            time.sleep(0.5)
        return 0

    def terminate(self) -> None:
        """Ask the instance to stop."""
        try:
            os.killpg(self.record.pgid, signal.SIGTERM)
        except OSError:
            pass

    def kill(self) -> None:
        """Stop the instance without asking."""
        try:
            os.killpg(self.record.pgid, signal.SIGKILL)
        except OSError:
            pass
