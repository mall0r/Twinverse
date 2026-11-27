"""Tests for userspace /dev/uinput staging, /dev/hidraw* isolation, and CommandBuilder wiring."""

import io
import os
import socket
import subprocess
from pathlib import Path
from unittest.mock import Mock

from src.core.config import Config
from src.core.utils import Utils
from src.models import Profile
from src.services.cmd_builder import CommandBuilder
from src.services.instance import InstanceService
from src.services.virtual_uinput import (
    BRIDGE_BIN_NAME,
    BRIDGE_BIN_SUBDIR,
    ENV_HIDRAW_FILTER,
    ENV_PHYSICAL_BRIDGE,
    ENV_SOCKET_DIR,
    ENV_VIRTUAL_UINPUT,
    ENV_VIRTUAL_UINPUT_PRELOAD,
    HIDRAW_ALLOW_FILENAME,
    NATIVE_LIBRARIES,
    NATIVE_REL_DIR,
    VirtualUinputConfig,
    build_input_bridge_command,
    find_hidraw_devices_to_mask,
    find_input_bridge_binary,
    find_native_libraries,
    is_virtual_uinput_available,
    stage_virtual_uinput,
)


def _create_fake_native_libs(base_dir: Path, include_bridge: bool = False) -> None:
    """Populate all four expected native library files under ``base_dir``."""
    for arch, filename in NATIVE_LIBRARIES:
        path = base_dir / NATIVE_REL_DIR / arch / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"ELF:{arch}:{filename}".encode("utf-8"))
    if include_bridge:
        bridge = base_dir / NATIVE_REL_DIR / BRIDGE_BIN_SUBDIR / BRIDGE_BIN_NAME
        bridge.parent.mkdir(parents=True, exist_ok=True)
        bridge.write_bytes(b"#!/bin/sh\nexit 0\n")
        os.chmod(bridge, 0o755)


def _mock_device_manager() -> Mock:
    """Return a mock DeviceManager configured with display size and refresh rate."""
    dm = Mock()
    dm.get_instance_dimensions.return_value = (1280, 720)
    dm.get_instance_refresh_rate.return_value = 60
    return dm


def _setenv_map(cmd: list[str]) -> dict[str, str]:
    """Extract all ``--setenv KEY VAL`` pairs from a bwrap command list."""
    env: dict[str, str] = {}
    idx = 0
    while idx < len(cmd):
        if cmd[idx] == "--setenv" and idx + 2 < len(cmd):
            env[cmd[idx + 1]] = cmd[idx + 2]
            idx += 3
        else:
            idx += 1
    return env


def test_find_native_libraries_requires_all_four(tmp_path: Path) -> None:
    """Return None when any 64-bit or 32-bit library is missing."""
    assert find_native_libraries(tmp_path) is None
    assert is_virtual_uinput_available(tmp_path) is False

    _create_fake_native_libs(tmp_path)
    libs = find_native_libraries(tmp_path)
    assert libs is not None
    assert len(libs) == 4
    assert is_virtual_uinput_available(tmp_path) is True

    # Removing one 32-bit library invalidates the full set.
    (tmp_path / NATIVE_REL_DIR / "lib32/libtwinverse_udev.so").unlink()
    assert find_native_libraries(tmp_path) is None
    assert is_virtual_uinput_available(tmp_path) is False


def test_stage_virtual_uinput_copies_and_cleans_dead_sockets(tmp_path: Path) -> None:
    """Stage all libraries, skip redundant copies, and remove only dead sockets."""
    base = tmp_path / "base"
    home = tmp_path / "home_1"
    sandbox_home = Path("/home/player")
    _create_fake_native_libs(base)

    sock_dir = home / ".tw-in/sock"
    sock_dir.mkdir(parents=True)

    # Create a dead socket file + descriptor, stale allowlist, and a live listening socket.
    dead_sock = sock_dir / "tw_event3000.sock"
    dead_desc = sock_dir / "tw_event3000.desc"
    stale_allow = sock_dir / HIDRAW_ALLOW_FILENAME
    dead_sock.write_bytes(b"")
    dead_desc.write_bytes(b"desc")
    stale_allow.write_text("hidraw1\n", encoding="utf-8")

    live_sock_path = sock_dir / "tw_event3001.sock"
    live_desc = sock_dir / "tw_event3001.desc"
    live_desc.write_bytes(b"live")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(str(live_sock_path))
        srv.listen(1)

        cfg = stage_virtual_uinput(home, sandbox_home, base_path=base)
        assert cfg is not None
        assert cfg.socket_dir == sandbox_home / ".tw-in/sock"
        assert cfg.host_socket_dir == sock_dir
        assert cfg.bridge_binary is None
        assert cfg.preload_paths == (
            sandbox_home / ".tw-in/lib64/libtwinverse_uinput.so",
            sandbox_home / ".tw-in/lib64/libtwinverse_udev.so",
            sandbox_home / ".tw-in/lib32/libtwinverse_uinput.so",
            sandbox_home / ".tw-in/lib32/libtwinverse_udev.so",
        )
        assert cfg.preload_value == ":".join(str(p) for p in cfg.preload_paths)

        # Dead socket + desc + stale allowlist removed; live socket + desc preserved.
        assert not dead_sock.exists()
        assert not dead_desc.exists()
        assert not stale_allow.exists()
        assert live_sock_path.exists()
        assert live_desc.exists()

        # Verify all 4 files were copied with identical bytes.
        staged_file = home / ".tw-in/lib64/libtwinverse_uinput.so"
        assert staged_file.read_bytes() == b"ELF:lib64:libtwinverse_uinput.so"
        inode_before = staged_file.stat().st_ino

        # Re-staging with unchanged files skips rewriting (inode stays identical).
        cfg_again = stage_virtual_uinput(home, sandbox_home, base_path=base)
        assert cfg_again == cfg
        assert staged_file.stat().st_ino == inode_before
    finally:
        srv.close()


def test_stage_virtual_uinput_overwrites_same_size_epoch_zero_flatpak_update(tmp_path: Path) -> None:
    """Replace staged binaries when Flatpak/OSTree keeps mtime=0 and ELF size unchanged."""
    base = tmp_path / "base"
    home = tmp_path / "home_1"
    sandbox_home = Path("/home/player")
    _create_fake_native_libs(base, include_bridge=True)

    src_bridge = base / NATIVE_REL_DIR / BRIDGE_BIN_SUBDIR / BRIDGE_BIN_NAME
    src_bridge.write_bytes(b"#!/bin/sh\n#v1\n")
    os.chmod(src_bridge, 0o755)
    os.utime(src_bridge, (0, 0))

    cfg = stage_virtual_uinput(home, sandbox_home, base_path=base)
    assert cfg is not None and cfg.bridge_binary is not None
    assert cfg.bridge_binary.read_bytes() == b"#!/bin/sh\n#v1\n"

    # Simulate a Flatpak update with identical file size and OSTree epoch-0 mtime.
    src_bridge.write_bytes(b"#!/bin/sh\n#v2\n")
    os.chmod(src_bridge, 0o755)
    os.utime(src_bridge, (0, 0))

    cfg_updated = stage_virtual_uinput(home, sandbox_home, base_path=base)
    assert cfg_updated is not None and cfg_updated.bridge_binary is not None
    assert cfg_updated.bridge_binary.read_bytes() == b"#!/bin/sh\n#v2\n"


def test_stage_virtual_uinput_stages_bridge_binary_and_builds_command(tmp_path: Path) -> None:
    """Stage twinverse-input-bridge with +x and construct supervisor commands."""
    base = tmp_path / "base"
    home = tmp_path / "home_1"
    sandbox_home = Path("/home/player")
    _create_fake_native_libs(base, include_bridge=True)

    assert find_input_bridge_binary(base) == base / NATIVE_REL_DIR / BRIDGE_BIN_SUBDIR / BRIDGE_BIN_NAME

    cfg = stage_virtual_uinput(home, sandbox_home, base_path=base)
    assert cfg is not None
    expected_bin = home / ".tw-in/bin/twinverse-input-bridge"
    assert cfg.bridge_binary == expected_bin
    assert expected_bin.is_file()
    assert os.access(expected_bin, os.X_OK)

    # Physical controller present -> includes both --device-id and --resolved-event.
    cmd = build_input_bridge_command(cfg, "/dev/input/by-id/usb-pad", "/dev/input/event23")
    assert cmd == [
        str(expected_bin),
        "--socket-dir",
        str(home / ".tw-in/sock"),
        "--device-id",
        "/dev/input/by-id/usb-pad",
        "--resolved-event",
        "/dev/input/event23",
    ]

    # Controller unplugged at launch -> still returns bridge command using configured --device-id.
    cmd_unplugged = build_input_bridge_command(cfg, "/dev/input/by-id/usb-pad", None)
    assert cmd_unplugged == [
        str(expected_bin),
        "--socket-dir",
        str(home / ".tw-in/sock"),
        "--device-id",
        "/dev/input/by-id/usb-pad",
    ]

    # No physical controller assigned without placeholder -> no bridge command.
    assert build_input_bridge_command(cfg, None, None) is None

    # Placeholder mode -> launches userspace placeholder joystick on event3000.
    cmd_placeholder = build_input_bridge_command(cfg, None, None, placeholder=True)
    assert cmd_placeholder == [
        str(expected_bin),
        "--socket-dir",
        str(home / ".tw-in/sock"),
        "--placeholder",
    ]


def test_find_hidraw_devices_to_mask_isolates_controllers(tmp_path: Path) -> None:
    """Keep hidraw nodes sharing a HID or USB device parent and mask everything else."""
    sysfs = tmp_path / "sys"
    dev = tmp_path / "dev"
    dev.mkdir()

    # Controller 1: USB device with two interfaces (hidraw0 for gamepad, hidraw1 for vendor/touchpad).
    usb1 = sysfs / "devices/pci0/usb1/1-1"
    (usb1 / "idVendor").parent.mkdir(parents=True)
    (usb1 / "idVendor").write_text("054c\n")
    (usb1 / "idProduct").write_text("0ce6\n")
    c1_hid0 = usb1 / "1-1:1.0/0003:054C:0CE6.0001"
    c1_input = c1_hid0 / "input/input10"
    c1_input.mkdir(parents=True)
    c1_hid1 = usb1 / "1-1:1.3/0003:054C:0CE6.0002"
    c1_hid1.mkdir(parents=True)

    # Controller 2: separate USB device (hidraw2).
    usb2 = sysfs / "devices/pci0/usb1/1-2"
    usb2.mkdir(parents=True)
    (usb2 / "idVendor").write_text("045e\n")
    (usb2 / "idProduct").write_text("028e\n")
    c2_hid = usb2 / "1-2:1.0/0003:045E:028E.0003"
    c2_hid.mkdir(parents=True)

    # Unrelated Bluetooth HID keyboard (hidraw3).
    bt_hid = sysfs / "devices/virtual/misc/uhid/0005:0001:0002.0004"
    bt_hid.mkdir(parents=True)

    # Wire /sys/class/input/event5/device -> c1_input
    ev5 = sysfs / "class/input/event5"
    ev5.mkdir(parents=True)
    (ev5 / "device").symlink_to(c1_input)

    # Wire /sys/class/hidraw/hidraw{0,1,2,3}/device
    for name, target in [
        ("hidraw0", c1_hid0),
        ("hidraw1", c1_hid1),
        ("hidraw2", c2_hid),
        ("hidraw3", bt_hid),
    ]:
        hdir = sysfs / "class/hidraw" / name
        hdir.mkdir(parents=True)
        (hdir / "device").symlink_to(target)
        (dev / name).write_bytes(b"")

    (dev / "input").mkdir()
    ev5_dev = dev / "input/event5"
    ev5_dev.write_bytes(b"")

    # Assigned controller 1 -> keeps hidraw0 & hidraw1, masks hidraw2 & hidraw3.
    masked = find_hidraw_devices_to_mask(str(ev5_dev), sysfs_root=sysfs, dev_root=dev)
    assert masked == [str(dev / "hidraw2"), str(dev / "hidraw3")]

    # No joystick assigned -> masks all hidraw nodes.
    masked_none = find_hidraw_devices_to_mask(None, sysfs_root=sysfs, dev_root=dev)
    assert masked_none == [str(dev / f"hidraw{i}") for i in range(4)]


def test_command_builder_gamescope_defers_ld_preload(monkeypatch, tmp_path: Path) -> None:
    """Defer LD_PRELOAD to GAMESCOPE_RUNTIME_SETUP so gamescope itself is not preloaded."""
    home = tmp_path / "home_1"
    home.mkdir()
    fake_cfg = VirtualUinputConfig(
        socket_dir=Path("/home/user/.tw-in/sock"),
        preload_paths=(
            Path("/home/user/.tw-in/lib64/libtwinverse_uinput.so"),
            Path("/home/user/.tw-in/lib64/libtwinverse_udev.so"),
            Path("/home/user/.tw-in/lib32/libtwinverse_uinput.so"),
            Path("/home/user/.tw-in/lib32/libtwinverse_udev.so"),
        ),
    )
    monkeypatch.setattr("src.services.cmd_builder.stage_virtual_uinput", lambda *a, **kw: fake_cfg)
    monkeypatch.setattr("src.services.cmd_builder.find_hidraw_devices_to_mask", lambda *a, **kw: ["/dev/hidraw9"])
    monkeypatch.setattr("src.services.cmd_builder.build_webhelper_mounts", lambda *a, **kw: [])

    profile = Profile()
    profile.use_gamescope = True
    builder = CommandBuilder(
        profile, {"joystick_path_str_for_instance": "/dev/input/event1"}, _mock_device_manager(), 0, home, None
    )
    cmd = builder.build_command(["steam"])

    env = _setenv_map(cmd)
    assert env[ENV_SOCKET_DIR] == str(fake_cfg.socket_dir)
    assert env[ENV_VIRTUAL_UINPUT_PRELOAD] == fake_cfg.preload_value
    assert "LD_PRELOAD" not in env
    assert ENV_VIRTUAL_UINPUT not in env
    assert builder.input_bridge_command is None

    # Verify /dev/hidraw9 was masked via --ro-bind /dev/null /dev/hidraw9.
    assert any(cmd[i : i + 3] == ["--ro-bind", "/dev/null", "/dev/hidraw9"] for i in range(len(cmd) - 2))

    # Execute GAMESCOPE_RUNTIME_SETUP in a real shell to confirm promotion preserves existing LD_PRELOAD.
    probe_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GAMESCOPE_LIMITER_FILE": "/run/user/1000/gamescope-limiter",
        "LD_PRELOAD": "/existing/lib.so",
        ENV_VIRTUAL_UINPUT_PRELOAD: fake_cfg.preload_value,
    }
    res = subprocess.run(
        [
            "sh",
            "-c",
            CommandBuilder.GAMESCOPE_RUNTIME_SETUP,
            "twinverse-gamescope",
            "sh",
            "-c",
            'printf "%s|%s|%s|%s" "$TWINVERSE_VIRTUAL_UINPUT" "$LD_PRELOAD" '
            '"${TWINVERSE_VIRTUAL_UINPUT_PRELOAD:-UNSET}" "$PRESSURE_VESSEL_FILESYSTEMS_RO"',
        ],
        env=probe_env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout == (f"1|{fake_cfg.preload_value}:/existing/lib.so|UNSET|/run/user/1000/gamescope-limiter")


def test_command_builder_enables_hotplug_bridge_for_physical_controller(monkeypatch, tmp_path: Path) -> None:
    """Use dynamic hotplug bridge instead of static evdev/hidraw binds when physical controller is assigned."""
    home = tmp_path / "home_1"
    home.mkdir()
    fake_cfg = VirtualUinputConfig(
        socket_dir=Path("/home/user/.tw-in/sock"),
        preload_paths=(Path("/home/user/.tw-in/lib64/libtwinverse_uinput.so"),),
        host_socket_dir=home / ".tw-in/sock",
        bridge_binary=home / ".tw-in/bin/twinverse-input-bridge",
    )
    monkeypatch.setattr("src.services.cmd_builder.stage_virtual_uinput", lambda *a, **kw: fake_cfg)
    monkeypatch.setattr("src.services.cmd_builder.find_hidraw_devices_to_mask", lambda *a, **kw: ["/dev/hidraw9"])
    monkeypatch.setattr("src.services.cmd_builder.build_webhelper_mounts", lambda *a, **kw: [])

    profile = Profile()
    profile.use_gamescope = True
    builder = CommandBuilder(
        profile,
        {
            "joystick_device_id_for_instance": "/dev/input/by-id/usb-xbox360",
            "joystick_path_str_for_instance": "/dev/input/event23",
        },
        _mock_device_manager(),
        0,
        home,
        None,
    )
    cmd = builder.build_command(["steam"])

    # bwrap must stay cmd[0] so network_command() can parse bwrap arguments.
    assert cmd[0] == "bwrap"
    assert builder.input_bridge_command == [
        str(home / ".tw-in/bin/twinverse-input-bridge"),
        "--socket-dir",
        str(home / ".tw-in/sock"),
        "--device-id",
        "/dev/input/by-id/usb-xbox360",
        "--resolved-event",
        "/dev/input/event23",
    ]

    env = _setenv_map(cmd)
    assert env[ENV_PHYSICAL_BRIDGE] == "1"
    assert env[ENV_HIDRAW_FILTER] == "1"
    assert env[ENV_SOCKET_DIR] == str(fake_cfg.socket_dir)

    # Static physical evdev bind and static hidraw /dev/null masks must be omitted.
    assert not any(
        cmd[i : i + 3] == ["--dev-bind", "/dev/input/event23", "/dev/input/event23"] for i in range(len(cmd) - 2)
    )
    assert not any(cmd[i : i + 3] == ["--ro-bind", "/dev/null", "/dev/hidraw9"] for i in range(len(cmd) - 2))


def test_command_builder_uses_placeholder_bridge_when_no_physical_controller(monkeypatch, tmp_path: Path) -> None:
    """Use userspace placeholder bridge and dynamic hidraw blocking when no physical controller is configured."""
    home = tmp_path / "home_1"
    home.mkdir()
    fake_cfg = VirtualUinputConfig(
        socket_dir=Path("/home/user/.tw-in/sock"),
        preload_paths=(Path("/home/user/.tw-in/lib64/libtwinverse_uinput.so"),),
        host_socket_dir=home / ".tw-in/sock",
        bridge_binary=home / ".tw-in/bin/twinverse-input-bridge",
    )
    monkeypatch.setattr("src.services.cmd_builder.stage_virtual_uinput", lambda *a, **kw: fake_cfg)
    monkeypatch.setattr("src.services.cmd_builder.find_hidraw_devices_to_mask", lambda *a, **kw: ["/dev/hidraw9"])
    monkeypatch.setattr("src.services.cmd_builder.build_webhelper_mounts", lambda *a, **kw: [])

    profile = Profile()
    profile.use_gamescope = True
    builder = CommandBuilder(profile, {}, _mock_device_manager(), 0, home, None)
    cmd = builder.build_command(["steam"])

    assert cmd[0] == "bwrap"
    assert builder.input_bridge_command == [
        str(home / ".tw-in/bin/twinverse-input-bridge"),
        "--socket-dir",
        str(home / ".tw-in/sock"),
        "--placeholder",
    ]
    env = _setenv_map(cmd)
    assert env[ENV_PHYSICAL_BRIDGE] == "1"
    assert env[ENV_HIDRAW_FILTER] == "1"
    assert not any(cmd[i : i + 3] == ["--ro-bind", "/dev/null", "/dev/hidraw9"] for i in range(len(cmd) - 2))


def test_command_builder_falls_back_to_static_virtual_joystick_without_bridge(monkeypatch, tmp_path: Path) -> None:
    """Fall back to static bind for host virtual joystick when the native bridge binary is unavailable."""
    home = tmp_path / "home_1"
    home.mkdir()
    fake_cfg = VirtualUinputConfig(
        socket_dir=Path("/home/user/.tw-in/sock"),
        preload_paths=(Path("/home/user/.tw-in/lib64/libtwinverse_uinput.so"),),
        host_socket_dir=home / ".tw-in/sock",
        bridge_binary=None,
    )
    monkeypatch.setattr("src.services.cmd_builder.stage_virtual_uinput", lambda *a, **kw: fake_cfg)
    monkeypatch.setattr("src.services.cmd_builder.find_hidraw_devices_to_mask", lambda *a, **kw: ["/dev/hidraw9"])
    monkeypatch.setattr("src.services.cmd_builder.build_webhelper_mounts", lambda *a, **kw: [])

    profile = Profile()
    profile.use_gamescope = True
    builder = CommandBuilder(profile, {}, _mock_device_manager(), 0, home, "/dev/input/event99")
    cmd = builder.build_command(["steam"])

    assert builder.input_bridge_command is None
    env = _setenv_map(cmd)
    assert ENV_PHYSICAL_BRIDGE not in env
    assert ENV_HIDRAW_FILTER not in env
    assert any(
        cmd[i : i + 3] == ["--dev-bind", "/dev/input/event99", "/dev/input/event99"] for i in range(len(cmd) - 2)
    )
    assert any(cmd[i : i + 3] == ["--ro-bind", "/dev/null", "/dev/hidraw9"] for i in range(len(cmd) - 2))


def test_command_builder_without_gamescope_sets_ld_preload_directly(monkeypatch, tmp_path: Path) -> None:
    """Set TWINVERSE_VIRTUAL_UINPUT and LD_PRELOAD directly in bwrap when Gamescope is off."""
    home = tmp_path / "home_1"
    home.mkdir()
    fake_cfg = VirtualUinputConfig(
        socket_dir=Path("/home/user/.tw-in/sock"),
        preload_paths=(Path("/home/user/.tw-in/lib64/libtwinverse_uinput.so"),),
    )
    monkeypatch.setattr("src.services.cmd_builder.stage_virtual_uinput", lambda *a, **kw: fake_cfg)
    monkeypatch.setattr("src.services.cmd_builder.find_hidraw_devices_to_mask", lambda *a, **kw: [])
    monkeypatch.setattr("src.services.cmd_builder.build_webhelper_mounts", lambda *a, **kw: [])
    monkeypatch.delenv("LD_PRELOAD", raising=False)

    profile = Profile()
    profile.use_gamescope = False
    builder = CommandBuilder(profile, {}, _mock_device_manager(), 0, home, None)
    cmd = builder.build_command(["steam"])

    env = _setenv_map(cmd)
    assert env[ENV_SOCKET_DIR] == str(fake_cfg.socket_dir)
    assert env[ENV_VIRTUAL_UINPUT] == "1"
    assert env["LD_PRELOAD"] == fake_cfg.preload_value
    assert ENV_VIRTUAL_UINPUT_PRELOAD not in env


def test_command_builder_omits_virtual_uinput_when_unavailable(monkeypatch, tmp_path: Path) -> None:
    """Do not inject LD_PRELOAD or virtual uinput env vars when native libs are absent."""
    home = tmp_path / "home_1"
    home.mkdir()
    monkeypatch.setattr("src.services.cmd_builder.stage_virtual_uinput", lambda *a, **kw: None)
    monkeypatch.setattr("src.services.cmd_builder.find_hidraw_devices_to_mask", lambda *a, **kw: [])
    monkeypatch.setattr("src.services.cmd_builder.build_webhelper_mounts", lambda *a, **kw: [])

    profile = Profile()
    profile.use_gamescope = True
    builder = CommandBuilder(profile, {}, _mock_device_manager(), 0, home, None)
    cmd = builder.build_command(["steam"])

    env = _setenv_map(cmd)
    assert ENV_SOCKET_DIR not in env
    assert ENV_VIRTUAL_UINPUT not in env
    assert ENV_VIRTUAL_UINPUT_PRELOAD not in env
    assert "LD_PRELOAD" not in env


def test_instance_service_wraps_bridge_outside_network_command(monkeypatch, tmp_path: Path) -> None:
    """Wrap twinverse-input-bridge outside network_command in both native and Flatpak launches."""
    monkeypatch.setattr(Config, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(Config, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr("src.services.instance.time.sleep", lambda _: None)

    service = InstanceService.__new__(InstanceService)
    bridge_cmd = [
        "/home/user/.tw-in/bin/twinverse-input-bridge",
        "--socket-dir",
        "/home/user/.tw-in/sock",
        "--device-id",
        "/dev/input/by-id/usb-pad",
    ]
    bwrap_cmd = ["bwrap", "--ro-bind", "/", "/", "--", "steam"]

    # 1. Native launch: bridge wraps pasta (network_command), which wraps bwrap.
    captured_native: list[list[str]] = []
    fake_proc = Mock(pid=4321)
    fake_proc.poll.return_value = None

    def fake_popen(cmd, **kwargs):
        captured_native.append(list(cmd))
        return fake_proc

    monkeypatch.setattr("src.services.instance.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("src.services.instance.network_command", lambda base, addr, idx: ["pasta", "--", *base])
    monkeypatch.setattr("src.services.instance.subprocess.Popen", fake_popen)

    proc, pgid = service._launch_natively(0, bwrap_cmd, {}, isolate_network=True, bridge_command=bridge_cmd)
    assert proc is fake_proc
    assert pgid == 4321
    assert captured_native == [[*bridge_cmd, "--", "pasta", "--", *bwrap_cmd]]

    # 2. Flatpak launch: inner_script execs bridge wrapping both pasta and fallback bwrap.
    captured_flatpak: list[list[str]] = []
    fake_fp_proc = Mock(pid=9876)
    fake_fp_proc.poll.return_value = None
    fake_fp_proc.stdout = io.BytesIO(b"5555\n")
    fake_fp_proc.stderr = io.BytesIO(b"")

    def fake_spawn_host(cmd, **kwargs):
        captured_flatpak.append(list(cmd))
        return fake_fp_proc

    monkeypatch.setattr(Utils, "flatpak_spawn_host", fake_spawn_host)
    _, fp_pgid = service._launch_in_flatpak(0, bwrap_cmd, {}, isolate_network=True, bridge_command=bridge_cmd)
    assert fp_pgid == 5555
    shell_cmd = captured_flatpak[0][2]
    assert "exec /home/user/.tw-in/bin/twinverse-input-bridge --socket-dir /home/user/.tw-in/sock" in shell_cmd
    assert "-- pasta -- bwrap" in shell_cmd
    else_branch = shell_cmd.split("else ", 1)[1]
    assert "exec /home/user/.tw-in/bin/twinverse-input-bridge" in else_branch
    assert "-- bwrap" in else_branch
