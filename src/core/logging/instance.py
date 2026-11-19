"""One log file per Steam instance launch, including the child process output."""

import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import IO, BinaryIO, Iterable, Optional

from .context import current_run_id, log_context
from .paths import LogPaths
from .redaction import redact_command
from .setup import get_log_paths

logger = logging.getLogger(__name__)


class InstanceLog:
    """A per-launch file that receives the application and child output."""

    def __init__(
        self,
        instance_num: int,
        path: Optional[Path],
        stream: Optional[BinaryIO] = None,
        max_bytes: int = 100 * 1024 * 1024,
        error: Optional[OSError] = None,
    ):
        """Initialize the log of one instance."""
        self.instance_num = instance_num
        self.display_num = instance_num + 1
        self.path = path
        self.max_bytes = max_bytes
        self.error = error
        self._stream = stream
        self._lock = threading.Lock()
        self._limit_reported = False

    @classmethod
    def create(
        cls,
        instance_num: int,
        command: Optional[Iterable[str]] = None,
        env_keys: Optional[Iterable[str]] = None,
        cwd: Optional[Path] = None,
        base_dir: Optional[Path] = None,
        max_bytes: int = 100 * 1024 * 1024,
    ) -> "InstanceLog":
        """Create the log file and write its header, returning a usable object."""
        if base_dir is not None:
            paths = LogPaths.resolve(base_dir)
        else:
            # The instance logs follow the directory of the running session, so
            # a custom log directory also receives them.
            paths = get_log_paths() or LogPaths.resolve()
        try:
            paths.ensure()
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_id = "".join(char for char in current_run_id() if char.isalnum())[:8] or "norun"
            path = paths.instances / f"instance-{instance_num + 1:02d}-{timestamp}-{run_id}.log"
            suffix = 1
            while path.exists():
                path = paths.instances / f"instance-{instance_num + 1:02d}-{timestamp}-{run_id}-{suffix}.log"
                suffix += 1

            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
            os.close(descriptor)
        except OSError as error:
            logger.warning("Could not create the log for instance %s: %s", instance_num + 1, error)
            return cls(instance_num, None, max_bytes=max_bytes, error=error)

        instance_log = cls(instance_num, path, max_bytes=max_bytes)
        instance_log._write_header(command=command, env_keys=env_keys, cwd=cwd)
        instance_log._update_latest()
        return instance_log

    def _write_header(
        self,
        command: Optional[Iterable[str]],
        env_keys: Optional[Iterable[str]],
        cwd: Optional[Path],
    ) -> None:
        lines = [
            "# Twinverse instance log",
            f"# run: {current_run_id()}",
            f"# instance: {self.display_num}",
            f"# started: {datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"# cwd: {cwd or Path.home()}",
        ]
        if command is not None:
            lines.append(f"# command: {' '.join(redact_command(list(command)))}")
        if env_keys is not None:
            lines.append(f"# environment keys: {', '.join(sorted(str(key) for key in env_keys))}")
        self.write(("\n".join(lines) + "\n\n").encode("utf-8"))

    def _update_latest(self) -> None:
        if self.path is None:
            return
        latest = self.path.parent / "latest.log"
        temporary = latest.with_name(latest.name + ".tmp")
        try:
            temporary.unlink(missing_ok=True)
            os.symlink(self.path.name, temporary)
            os.replace(temporary, latest)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def open_stream(self) -> BinaryIO:
        """Return a caller-managed append stream, reopening it when necessary."""
        with self._lock:
            if self._stream is None or self._stream.closed:
                if self.path is None:
                    raise OSError(self.error or "instance log is unavailable")
                self._stream = open(self.path, "ab")
            return self._stream

    def write(self, data: bytes) -> None:
        """Append bytes while enforcing the configured size limit."""
        if self.path is None:
            return
        with self._lock:
            try:
                if self._stream is not None and not self._stream.closed:
                    self._append(self._stream, data)
                else:
                    with open(self.path, "ab") as stream:
                        self._append(stream, data)
            except OSError as error:
                logger.warning("Could not write the log for instance %s: %s", self.display_num, error)

    def _append(self, stream: BinaryIO, data: bytes) -> None:
        """Append capped output with the lock held by the caller."""
        size = os.fstat(stream.fileno()).st_size
        if size >= self.max_bytes:
            if not self._limit_reported:
                stream.write(b"\n# log size limit reached; further output is not stored\n")
                stream.flush()
                self._limit_reported = True
            return
        remaining = self.max_bytes - size
        stream.write(data[:remaining])
        stream.flush()

    def start_drain(self, stream: IO[bytes]) -> threading.Thread:
        """Consume a pipe in the background so the child never blocks on it."""
        thread = threading.Thread(
            target=self._drain,
            args=(stream,),
            name=f"twinverse-log-instance-{self.display_num}",
            daemon=True,
        )
        thread.start()
        return thread

    def _drain(self, stream: IO[bytes]) -> None:
        try:
            with log_context(instance=self.display_num):
                for chunk in iter(lambda: stream.read(4096), b""):
                    self.write(chunk)
        except (OSError, TypeError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except (OSError, TypeError, ValueError):
                pass

    def finish(self, exit_code: Optional[int] = None) -> None:
        """Close the stream and append a small footer."""
        if self.path is None:
            return
        with self._lock:
            try:
                if self._stream is not None and not self._stream.closed:
                    self._stream.close()
                self._stream = None
                with open(self.path, "ab") as stream:
                    suffix = "" if exit_code is None else f" exit_code={exit_code}"
                    stream.write(
                        f"\n# finished: {datetime.now().astimezone().isoformat(timespec='seconds')}{suffix}\n".encode()
                    )
            except OSError:
                pass

    def tail(self, limit: int = 2000) -> str:
        """Return the end of the log, for an error message."""
        if self.path is None:
            return ""
        try:
            with open(self.path, "rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - limit))
                return stream.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""
