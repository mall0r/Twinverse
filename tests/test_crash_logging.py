"""Prove that the logging really captures the failures it exists for."""

import logging
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from src.core.exceptions import DependencyError
from src.core.logging import LogSettings, configure_logging, current_run_id
from src.services.instance import InstanceService
from src.services.instance_registry import InstanceProbe, InstanceRegistry

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_CRASH_TEMPLATE = """
import sys

sys.path.insert(0, {root!r})

from src.core.logging import LogSettings, configure_logging

configure_logging(LogSettings(log_dir=sys.argv[1], console=False))
{body}
"""


def _run_crash(body: str, log_dir: Path) -> subprocess.CompletedProcess:
    """Run a script that crashes, with the real logging configuration."""
    script = _CRASH_TEMPLATE.format(root=str(PROJECT_ROOT), body=textwrap.dedent(body))
    environment = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT))
    return subprocess.run(
        [sys.executable, "-c", script, str(log_dir)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
    )


def test_an_unhandled_exception_reaches_the_log(tmp_path):
    """A crash of the application has to leave a traceback in the log."""
    result = _run_crash(
        """
        raise RuntimeError("boom in the main thread")
        """,
        tmp_path,
    )

    assert result.returncode == 1
    text = (tmp_path / "twinverse.log").read_text()
    assert "Unhandled exception" in text
    assert "RuntimeError: boom in the main thread" in text
    assert "Traceback (most recent call last)" in text


def test_an_unhandled_exception_in_a_thread_reaches_the_log(tmp_path):
    """The launch runs in a worker thread, so the hook has to cover it."""
    result = _run_crash(
        """
        import threading


        def boom():
            raise RuntimeError("boom in a worker thread")


        threading.Thread(target=boom, name="launch-worker").start()
        """,
        tmp_path,
    )

    assert result.returncode == 0
    text = (tmp_path / "twinverse.log").read_text()
    assert "Unhandled exception in thread launch-worker" in text
    assert "RuntimeError: boom in a worker thread" in text
    assert "run_id=unconfigured" not in text


def test_a_native_crash_reaches_the_crash_log(tmp_path):
    """A segmentation fault is not an exception, so faulthandler has to catch it."""
    result = _run_crash(
        """
        import ctypes

        ctypes.string_at(0)
        """,
        tmp_path,
    )

    assert result.returncode == -11
    crash = (tmp_path / "crash.log").read_text()
    assert "Fatal Python error" in crash
    assert "Segmentation fault" in crash
    assert "string_at" in crash


def test_the_run_id_reaches_the_worker_threads(tmp_path):
    """A launch happens in a thread, and every record has to carry the run id."""
    handle = configure_logging(LogSettings(log_dir=tmp_path, console=False))
    seen = []

    def worker():
        logging.getLogger("src.test").info("record from the worker thread")
        seen.append(current_run_id())

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    handle.shutdown()

    text = (tmp_path / "twinverse.log").read_text()
    assert seen == [handle.run_id]
    assert f"run_id={handle.run_id}" in text
    assert "run_id=unconfigured" not in text


def test_the_output_of_a_crashing_instance_stays_in_its_log(tmp_path, monkeypatch):
    """A Steam client that dies has to leave its output in the instance log."""
    monkeypatch.setattr(
        "src.services.instance.shutil.which",
        lambda name: None if name == "pasta" else f"/usr/bin/{name}",
    )
    handle = configure_logging(LogSettings(log_dir=tmp_path, console=False))
    service = InstanceService.__new__(InstanceService)
    command = [
        "bash",
        "-c",
        "echo 'steam started'; sleep 0.6; echo 'fatal error in the client' >&2; kill -SEGV $$",
    ]

    try:
        # The launch runs in a worker thread, exactly like the real interface.
        outcome = {}

        def worker():
            outcome["process"], outcome["pgid"] = service._launch_natively(0, command, {})

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=30)

        process = outcome["process"]
        assert process.poll() is None
        assert process.wait(timeout=30) == -11
    finally:
        handle.shutdown()

    instance_logs = list((tmp_path / "instances").glob("instance-01-*.log"))
    assert len(instance_logs) == 1
    text = instance_logs[0].read_text()
    assert "steam started" in text
    assert "fatal error in the client" in text
    # The run id of the application has to reach the log of the launch.
    assert f"# run: {handle.run_id}" in text
    assert "unconfigured" not in text


def test_an_instance_that_dies_immediately_reports_its_output(tmp_path, monkeypatch):
    """A client that dies during the launch is reported with what it printed."""
    monkeypatch.setattr(
        "src.services.instance.shutil.which",
        lambda name: None if name == "pasta" else f"/usr/bin/{name}",
    )
    service = InstanceService.__new__(InstanceService)
    command = ["bash", "-c", "echo 'fatal error in the client' >&2; exit 3"]

    handle = configure_logging(LogSettings(log_dir=tmp_path, console=False))
    try:
        with pytest.raises(DependencyError) as error:
            service._launch_natively(0, command, {})
    finally:
        handle.shutdown()

    assert "fatal error in the client" in str(error.value)
    instance_logs = list((tmp_path / "instances").glob("instance-01-*.log"))
    assert len(instance_logs) == 1
    assert "fatal error in the client" in instance_logs[0].read_text()


def test_the_next_session_finds_an_instance_that_outlived_the_crash(tmp_path):
    """A crash leaves the registry behind, and the next session finds the instance."""
    marker = tmp_path / "home_1"
    registry_path = tmp_path / "instances.json"

    result = _run_crash(
        f"""
        import os, subprocess, sys

        sys.path.insert(0, {str(PROJECT_ROOT)!r})

        from src.services.instance_registry import InstanceRecord, InstanceRegistry

        child = subprocess.Popen(
            ["bash", "-c", "exec -a {str(marker)!r} sleep 60"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        registry = InstanceRegistry({str(registry_path)!r})
        registry.add(
            InstanceRecord(
                instance=0,
                pgid=child.pid,
                mode="native",
                home={str(marker)!r},
            )
        )
        os.kill(os.getpid(), 9)
        """,
        tmp_path,
    )

    assert result.returncode == -9
    assert registry_path.exists()

    service = InstanceService.__new__(InstanceService)
    service._registry = InstanceRegistry(registry_path)
    service._probe = InstanceProbe(ttl=0.0)
    service.processes = {}
    service.pids = {}
    service.pgids = {}
    service.recovered_instances = []

    recovered = service._recover_instances()

    assert len(recovered) == 1
    assert recovered[0].instance == 0
    assert 0 in service.processes

    service.terminate_instance(0)

    assert registry_path.exists() is False
