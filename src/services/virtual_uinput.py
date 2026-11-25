"""Userspace `/dev/uinput` staging, hotplug controller bridge, and `/dev/hidraw*` isolation."""

import errno
import logging
import os
import shutil
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.utils import Utils

logger = logging.getLogger(__name__)

NATIVE_REL_DIR = Path("res/native")
STAGED_DIR_NAME = ".tw-in"
SOCK_SUBDIR_NAME = "sock"
BRIDGE_BIN_SUBDIR = "bin"
BRIDGE_BIN_NAME = "twinverse-input-bridge"
HIDRAW_ALLOW_FILENAME = "tw_hidraw.allow"
INPUT_MUTE_FILENAME = "tw_input.mute"
DEFAULT_SYSFS_ROOT = Path("/sys")
DEFAULT_DEV_ROOT = Path("/dev")

# Order matters: interposer first, then libudev shim; 64-bit then 32-bit.
# ld.so silently ignores entries of the wrong ELF class (32-bit in 64-bit
# processes and vice versa), so one LD_PRELOAD covers both 32-bit Steam and
# 64-bit Proton/games.
NATIVE_LIBRARIES: tuple[tuple[str, str], ...] = (
    ("lib64", "libtwinverse_uinput.so"),
    ("lib64", "libtwinverse_udev.so"),
    ("lib32", "libtwinverse_uinput.so"),
    ("lib32", "libtwinverse_udev.so"),
)

ENV_VIRTUAL_UINPUT = "TWINVERSE_VIRTUAL_UINPUT"
ENV_VIRTUAL_UINPUT_PRELOAD = "TWINVERSE_VIRTUAL_UINPUT_PRELOAD"
ENV_SOCKET_DIR = "TWINVERSE_UINPUT_SOCKET_DIR"
ENV_PHYSICAL_BRIDGE = "TWINVERSE_PHYSICAL_BRIDGE"
ENV_HIDRAW_FILTER = "TWINVERSE_HIDRAW_FILTER"


@dataclass(frozen=True)
class VirtualUinputConfig:
    """Sandbox-side paths and host supervisor paths for userspace `/dev/uinput`."""

    socket_dir: Path
    preload_paths: tuple[Path, ...]
    host_socket_dir: Optional[Path] = None
    bridge_binary: Optional[Path] = None

    @property
    def preload_value(self) -> str:
        """Return the colon-separated ``LD_PRELOAD`` string."""
        return ":".join(str(path) for path in self.preload_paths)


def find_native_libraries(base_path: Optional[Path] = None) -> Optional[list[tuple[str, str, Path]]]:
    """Return all 4 required native ``.so`` files, or ``None`` if any are missing."""
    root = (base_path if base_path is not None else Utils.get_base_path()) / NATIVE_REL_DIR
    found: list[tuple[str, str, Path]] = []
    for arch, filename in NATIVE_LIBRARIES:
        candidate = root / arch / filename
        if not candidate.is_file():
            return None
        found.append((arch, filename, candidate))
    return found


def find_input_bridge_binary(base_path: Optional[Path] = None) -> Optional[Path]:
    """Return the built ``twinverse-input-bridge`` host binary, or ``None`` if absent."""
    root = (base_path if base_path is not None else Utils.get_base_path()) / NATIVE_REL_DIR
    candidate = root / BRIDGE_BIN_SUBDIR / BRIDGE_BIN_NAME
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    return None


def is_virtual_uinput_available(base_path: Optional[Path] = None) -> bool:
    """Return True when both 64-bit and 32-bit native virtual uinput libraries are built."""
    return find_native_libraries(base_path) is not None


def _files_have_same_content(src: Path, dst: Path) -> bool:
    """Return True when ``src`` and ``dst`` have identical byte contents."""
    chunk_size = 65536
    with src.open("rb") as src_fp, dst.open("rb") as dst_fp:
        while True:
            src_chunk = src_fp.read(chunk_size)
            dst_chunk = dst_fp.read(chunk_size)
            if src_chunk != dst_chunk:
                return False
            if not src_chunk:
                return True


def _copy_if_changed(src: Path, dst: Path, executable: bool = False) -> None:
    """Atomically copy ``src`` to ``dst`` when size or byte content differs.

    Flatpak (OSTree) and reproducible builds normalize file ``mtime`` to epoch
    0, and ELF page alignment often keeps binary sizes identical across
    rebuilds. Comparing bytes when sizes match guarantees staged native
    libraries and ``twinverse-input-bridge`` always stay up to date.
    """
    src_stat = src.stat()
    try:
        dst_stat = dst.stat()
        if dst_stat.st_size == src_stat.st_size and _files_have_same_content(src, dst):
            if executable and not os.access(dst, os.X_OK):
                os.chmod(dst, 0o755)
            return
    except OSError:
        pass

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_dst = dst.with_name(f".{dst.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(src, tmp_dst)
        if executable:
            os.chmod(tmp_dst, 0o755)
        os.replace(tmp_dst, dst)
    except Exception:
        tmp_dst.unlink(missing_ok=True)
        raise


def _is_unix_socket_listening(sock_path: Path) -> bool:
    """Return True if a process is actively accepting connections on ``sock_path``."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    dir_fd: Optional[int] = None
    try:
        sock.setblocking(False)
        target = str(sock_path)
        if len(os.fsencode(target)) >= 108:
            dir_fd = os.open(sock_path.parent, os.O_RDONLY | os.O_DIRECTORY)
            target = f"/proc/self/fd/{dir_fd}/{sock_path.name}"
        sock.connect(target)
        return True
    except BlockingIOError:
        return True
    except OSError as exc:
        return exc.errno == errno.EINPROGRESS
    finally:
        sock.close()
        if dir_fd is not None:
            try:
                os.close(dir_fd)
            except OSError:
                pass


def _cleanup_stale_sockets(sock_dir: Path) -> None:
    """Remove dead virtual uinput sockets/descriptors without disturbing live ones."""
    if not sock_dir.is_dir():
        return
    bridge_live = False
    for entry in list(sock_dir.iterdir()):
        name = entry.name
        if name.endswith(".sock") and (name.startswith("tw_event") or name.startswith("selkies_")):
            if _is_unix_socket_listening(entry):
                if name == "tw_event3000.sock":
                    bridge_live = True
                continue
            entry.unlink(missing_ok=True)
            desc = entry.with_suffix(".desc")
            desc.unlink(missing_ok=True)
        elif name.endswith(".desc") and (name.startswith("tw_event") or name.startswith("selkies_")):
            sock = entry.with_suffix(".sock")
            if not sock.exists():
                entry.unlink(missing_ok=True)

    if not bridge_live:
        (sock_dir / HIDRAW_ALLOW_FILENAME).unlink(missing_ok=True)
        (sock_dir / INPUT_MUTE_FILENAME).unlink(missing_ok=True)


def stage_virtual_uinput(
    home_path: Path,
    sandbox_home: Path,
    base_path: Optional[Path] = None,
) -> Optional[VirtualUinputConfig]:
    """
    Stage native virtual uinput libraries and the hotplug bridge into ``home_path/.tw-in``.

    Because ``home_path`` is bind-mounted at ``sandbox_home`` inside ``bwrap``
    and inherited into ``pressure-vessel``, staging under ``.tw-in`` keeps the
    library, bridge, and socket paths accessible across Native, Flatpak,
    AppImage, and Steam Linux Runtime containers while staying well under the
    108-byte ``AF_UNIX`` ``sun_path`` limit.
    """
    libs = find_native_libraries(base_path)
    if libs is None:
        logger.debug("Native virtual uinput libraries not found; skipping virtual uinput setup")
        return None

    stage_root = home_path / STAGED_DIR_NAME
    sock_dir_host = stage_root / SOCK_SUBDIR_NAME
    staged_bridge: Optional[Path] = None
    try:
        sock_dir_host.mkdir(parents=True, exist_ok=True)
        _cleanup_stale_sockets(sock_dir_host)

        sandbox_preload: list[Path] = []
        for arch, filename, src in libs:
            dst = stage_root / arch / filename
            _copy_if_changed(src, dst)
            sandbox_preload.append(sandbox_home / STAGED_DIR_NAME / arch / filename)

        bridge_src = find_input_bridge_binary(base_path)
        if bridge_src is not None:
            bridge_dst = stage_root / BRIDGE_BIN_SUBDIR / BRIDGE_BIN_NAME
            _copy_if_changed(bridge_src, bridge_dst, executable=True)
            staged_bridge = bridge_dst
    except OSError:
        logger.exception("Failed to stage virtual uinput libraries into '%s'", stage_root)
        return None

    return VirtualUinputConfig(
        socket_dir=sandbox_home / STAGED_DIR_NAME / SOCK_SUBDIR_NAME,
        preload_paths=tuple(sandbox_preload),
        host_socket_dir=sock_dir_host,
        bridge_binary=staged_bridge,
    )


def build_input_bridge_command(
    config: Optional[VirtualUinputConfig],
    device_id: Optional[str],
    resolved_event: Optional[str] = None,
) -> Optional[list[str]]:
    """
    Build the ``twinverse-input-bridge`` supervisor prefix for a physical controller.

    Returns ``None`` when no physical controller is configured or when the native
    bridge binary is unavailable (allowing graceful fallback to static binding).
    """
    if config is None or config.bridge_binary is None or config.host_socket_dir is None:
        return None

    target_id = (device_id or "").strip()
    resolved = (resolved_event or "").strip()
    if not target_id:
        target_id = resolved
    if not target_id:
        return None

    cmd = [
        str(config.bridge_binary),
        "--socket-dir",
        str(config.host_socket_dir),
        "--device-id",
        target_id,
    ]
    if resolved and resolved != target_id:
        cmd.extend(["--resolved-event", resolved])
    return cmd


def _find_usb_device_ancestor(sysdev: Path) -> Optional[Path]:
    """Return the nearest USB device sysfs ancestor (containing ``idVendor``), if any."""
    for candidate in (sysdev, *sysdev.parents):
        if (candidate / "idVendor").is_file() and (candidate / "idProduct").is_file():
            return candidate
    return None


def _resolve_event_sysdev(joystick_path: str, sysfs_root: Path) -> Optional[Path]:
    """Resolve ``/dev/input/eventN`` (or symlink) to its real sysfs device directory."""
    try:
        resolved = Path(joystick_path).resolve()
    except OSError:
        resolved = Path(joystick_path)
    name = resolved.name
    if not name.startswith("event"):
        return None
    sysdev = sysfs_root / "class/input" / name / "device"
    try:
        return sysdev.resolve(strict=True)
    except OSError:
        return None


def find_hidraw_devices_to_mask(
    joystick_path: Optional[str],
    sysfs_root: Path = DEFAULT_SYSFS_ROOT,
    dev_root: Path = DEFAULT_DEV_ROOT,
) -> list[str]:
    """
    Return ``/dev/hidrawN`` paths that do not belong to ``joystick_path``.

    Steam's ``hidapi`` and Proton's ``winebus`` scan ``/dev/hidraw*`` directly
    for DualSense, DualShock, Switch Pro, and Steam Controllers. Masking every
    ``/dev/hidraw*`` that does not share a HID or USB physical parent with this
    instance's assigned controller prevents cross-instance controller leaks
    while preserving full native HID features (gyro, rumble, touchpad, LEDs)
    for the assigned controller.
    """
    hidraw_class = sysfs_root / "class/hidraw"
    if not hidraw_class.is_dir():
        return []

    event_sysdev = _resolve_event_sysdev(joystick_path, sysfs_root) if joystick_path else None
    event_usb_parent = _find_usb_device_ancestor(event_sysdev) if event_sysdev is not None else None

    masked: list[str] = []
    try:
        entries = sorted(hidraw_class.iterdir(), key=lambda p: p.name)
    except OSError:
        return []

    for entry in entries:
        if not entry.name.startswith("hidraw"):
            continue
        dev_node = dev_root / entry.name
        if not dev_node.exists():
            continue

        belongs_to_instance = False
        if event_sysdev is not None:
            try:
                hid_sysdev = (entry / "device").resolve(strict=True)
            except OSError:
                hid_sysdev = None

            if hid_sysdev is not None:
                if event_sysdev == hid_sysdev or event_sysdev.is_relative_to(hid_sysdev):
                    belongs_to_instance = True
                elif event_usb_parent is not None and _find_usb_device_ancestor(hid_sysdev) == event_usb_parent:
                    belongs_to_instance = True

        if not belongs_to_instance:
            masked.append(str(dev_node))

    return masked
