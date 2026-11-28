"""Shared Steam library isolation, manifest sanitization, and OverlayFS helpers.

Twinverse shares host Steam game and Proton installations across isolated player
sandboxes without duplicating gigabytes of data.  To prevent sandboxed Steam
clients from mutating or corrupting host installations (or racing with host Steam
on shared ``steamapps/common`` folders and external ``libraryfolders.vdf``
libraries), this module enforces a strict single-writer boundary:

1. Shared ``steamapps/common/*`` and ``compatibilitytools.d/*`` folders are
   mounted read-only underneath a per-instance OverlayFS layer (when ``bwrap``
   supports ``--overlay`` on the host kernel/filesystem) or via ``--ro-bind``
   with minimal per-instance runtime mounts for Proton ``dist.lock`` and
   Steam Linux Runtime ``var/``.
2. Host ``appmanifest_*.acf`` files synced into each sandbox are sanitized to
   disable background auto-updates and strip dirty staging/validation state,
   and stale sandbox download directories are pruned when host builds advance.
3. External Steam libraries discovered from host ``libraryfolders.vdf`` receive
   the same per-instance ``steamapps`` isolation and read-only lowerdir mounts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Collection, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from src.core.utils import Utils

logger = logging.getLogger(__name__)

OVERLAY_DIR_NAME = ".tw-overlays"
RUNTIME_DIR_NAME = ".tw-runtime"
LIBRARIES_DIR_NAME = ".tw-libraries"

COMPAT_IGNORE = frozenset({"LegacyRuntime"})
STEAM_TOOL_PREFIXES = ("Proton", "SteamLinuxRuntime")
STEAM_TOOL_NAMES = frozenset({"Steamworks Shared", "Steam Controller Configs"})
TOOL_SENTINEL_FILES = ("toolmanifest.vdf", "version", "VERSIONS.txt", "steampipe_fixups.json")
STEAM_SUBDIRS = ("common", "compatdata", "downloading", "shadercache", "sourcemods", "temp", "workshop")

STATE_FULLY_INSTALLED = 4

DIRTY_MANIFEST_SCALAR_KEYS = frozenset(
    {
        "StagingSize",
        "UpdateResult",
        "BytesToDownload",
        "BytesDownloaded",
        "BytesToStage",
        "BytesStaged",
        "TargetBuildID",
        "FullValidateBeforeNextUpdate",
        "FullValidateAfterNextUpdate",
    }
)
DIRTY_MANIFEST_BLOCK_KEYS = frozenset({"StagedDepots", "DownloadingDepots"})

_KV_LINE_RE = re.compile(r'^([ \t]*)"((?:[^"\\]|\\.)*)"([ \t]+)"((?:[^"\\]|\\.)*)"([ \t]*)$')
_KEY_ONLY_RE = re.compile(r'^([ \t]*)"((?:[^"\\]|\\.)*)"[ \t]*$')
_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")

_OVERLAY_SUPPORT_CACHE: Dict[Tuple[bool, int], bool] = {}


@dataclass(frozen=True)
class AppManifestInfo:
    """Subset of metadata parsed from a Steam ``appmanifest_<id>.acf`` file."""

    appid: str
    name: str
    installdir: str
    buildid: str
    last_updated: str
    state_flags: int
    installed_depots: Tuple[str, ...] = ()

    @property
    def is_clean_installed(self) -> bool:
        """Return True when the app is cleanly installed with no pending update/error."""
        return self.state_flags == STATE_FULLY_INSTALLED


@dataclass
class SteamMountPlan:
    """Bubblewrap mount arguments and fallback environment for shared Steam folders."""

    bwrap_args: List[str] = field(default_factory=list)
    extra_env: Dict[str, str] = field(default_factory=dict)


def clear_overlay_support_cache() -> None:
    """Clear the cached ``bwrap --overlay`` capability probe results."""
    _OVERLAY_SUPPORT_CACHE.clear()


def _unescape_vdf(value: str) -> str:
    """Unescape common Valve KeyValues escape sequences."""
    return value.replace("\\\\", "\\").replace('\\"', '"')


def _safe_folder_key(name: str) -> str:
    """Build a deterministic, collision-free directory key for ``name``."""
    digest = hashlib.sha256(name.encode("utf-8", errors="surrogateescape")).hexdigest()[:12]
    cleaned = _SAFE_SEGMENT_RE.sub("_", name).strip("._-")
    if len(cleaned) > 48:
        cleaned = cleaned[:48].rstrip("._-")
    return f"{cleaned}_{digest}" if cleaned else digest


def _force_rmtree(path: Path) -> None:
    """Remove a directory tree even if it contains read-only files or folders."""
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or not path.is_dir():
        try:
            path.unlink()
        except PermissionError:
            path.parent.chmod(0o700)
            path.unlink()
        return

    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        root_path = Path(root)
        try:
            root_path.chmod(0o700)
        except OSError:
            pass
        for name in dirs:
            try:
                (root_path / name).chmod(0o700)
            except OSError:
                pass
        for name in files:
            file_path = root_path / name
            if not file_path.is_symlink():
                try:
                    file_path.chmod(0o600)
                except OSError:
                    pass
    shutil.rmtree(path)


def _remove_file_if_exists(path: Path) -> None:
    """Remove a single file or symlink if present, clearing read-only bits if needed."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        path.unlink()
    except PermissionError:
        if not path.is_symlink():
            path.chmod(0o600)
        path.unlink()


def parse_app_manifest(content: str) -> Optional[AppManifestInfo]:
    """Parse key metadata from a Valve KeyValues ``appmanifest_*.acf`` string.

    Returns ``None`` if ``content`` is not a Valve ``AppState`` document.
    """
    depth = 0
    saw_app_state = False
    pending_key: Optional[str] = None
    section_stack: List[str] = []
    scalars: Dict[str, str] = {}
    depots: List[str] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if line == "{":
            if depth == 0 and pending_key == "AppState":
                saw_app_state = True
            if pending_key is not None:
                section_stack.append(pending_key)
                if depth == 2 and len(section_stack) >= 3 and section_stack[1] == "InstalledDepots":
                    depots.append(pending_key)
                pending_key = None
            depth += 1
            continue
        if line == "}":
            depth = max(0, depth - 1)
            if section_stack:
                section_stack.pop()
            pending_key = None
            continue

        kv_match = _KV_LINE_RE.match(raw_line)
        if kv_match:
            key = _unescape_vdf(kv_match.group(2))
            value = _unescape_vdf(kv_match.group(4))
            if saw_app_state and depth == 1:
                scalars[key] = value
            pending_key = None
            continue

        key_match = _KEY_ONLY_RE.match(raw_line)
        if key_match:
            pending_key = _unescape_vdf(key_match.group(2))

    if not saw_app_state:
        return None

    raw_flags = scalars.get("StateFlags", str(STATE_FULLY_INSTALLED))
    try:
        state_flags = int(raw_flags)
    except ValueError:
        state_flags = STATE_FULLY_INSTALLED

    return AppManifestInfo(
        appid=scalars.get("appid", ""),
        name=scalars.get("name", ""),
        installdir=scalars.get("installdir", ""),
        buildid=scalars.get("buildid", ""),
        last_updated=scalars.get("LastUpdated", ""),
        state_flags=state_flags,
        installed_depots=tuple(depots),
    )


def sanitize_sandbox_manifest(content: str) -> str:
    """Sanitize a host ``appmanifest_*.acf`` copy for safe use inside a sandbox.

    Non-VDF content is returned unchanged.  For Valve ``AppState`` manifests:

    - Sets ``AutoUpdateBehavior`` to ``"1"`` (update only on launch) and
      ``ScheduledAutoUpdate`` to ``"0"`` so sandboxed Steam does not run
      background updates or depot reconciliations on shared folders.
    - Strips transient host staging/validation keys and ``StagedDepots`` /
      ``DownloadingDepots`` blocks so an interrupted host update does not
      trigger duplicate downloads inside sandboxes.
    - Normalizes ``StateFlags`` to ``"4"`` (Fully Installed) whenever the
      installed bit (``4``) is already set on the host.
    """
    info = parse_app_manifest(content)
    if info is None:
        return content

    line_ending = "\r\n" if "\r\n" in content else "\n"
    trailing_newline = content.endswith("\n") or content.endswith("\r")
    lines = content.splitlines()

    output: List[str] = []
    depth = 0
    pending_key: Optional[str] = None
    skip_block_depth: Optional[int] = None
    saw_auto_update = False
    normalize_state_flags = bool(info.state_flags & STATE_FULLY_INSTALLED)

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        stripped = raw_line.strip()

        if skip_block_depth is not None:
            if stripped == "{":
                depth += 1
            elif stripped == "}":
                depth = max(0, depth - 1)
                if depth <= skip_block_depth:
                    skip_block_depth = None
            i += 1
            continue

        if stripped == "{":
            depth += 1
            pending_key = None
            output.append(raw_line)
            i += 1
            continue

        if stripped == "}":
            if depth == 1 and not saw_auto_update:
                output.append('\t"AutoUpdateBehavior"\t\t"1"')
                saw_auto_update = True
            depth = max(0, depth - 1)
            pending_key = None
            output.append(raw_line)
            i += 1
            continue

        kv_match = _KV_LINE_RE.match(raw_line)
        if kv_match and depth == 1:
            indent, raw_key, sep, _raw_val, suffix = kv_match.groups()
            key = _unescape_vdf(raw_key)
            if key in DIRTY_MANIFEST_SCALAR_KEYS:
                i += 1
                continue
            if key == "AutoUpdateBehavior":
                saw_auto_update = True
                output.append(f'{indent}"{raw_key}"{sep}"1"{suffix}')
                i += 1
                continue
            if key == "ScheduledAutoUpdate":
                output.append(f'{indent}"{raw_key}"{sep}"0"{suffix}')
                i += 1
                continue
            if key == "StateFlags" and normalize_state_flags:
                output.append(f'{indent}"{raw_key}"{sep}"{STATE_FULLY_INSTALLED}"{suffix}')
                i += 1
                continue
            output.append(raw_line)
            i += 1
            continue

        key_match = _KEY_ONLY_RE.match(raw_line)
        if key_match and depth == 1:
            key = _unescape_vdf(key_match.group(2))
            if key in DIRTY_MANIFEST_BLOCK_KEYS:
                # Look ahead to consume the block opening brace.
                if i + 1 < len(lines) and lines[i + 1].strip() == "{":
                    skip_block_depth = depth
                    depth += 1
                    i += 2
                    continue
                # Orphan key without block; drop it safely.
                i += 1
                continue
            pending_key = key
        else:
            pending_key = None

        output.append(raw_line)
        i += 1

    # Keep ``pending_key`` referenced cleanly without lint complaints.
    _ = pending_key

    result = line_ending.join(output)
    if trailing_newline:
        result += line_ending
    return result


def parse_external_library_folders(
    visible_steam_root: Path,
    host_steam_root: Optional[Path] = None,
) -> List[Path]:
    """Return additional Steam library roots declared in host ``libraryfolders.vdf``.

    The primary Steam root itself is excluded.  Paths are returned as declared
    in ``libraryfolders.vdf`` (host paths), deduplicated in declaration order.
    """
    vdf_candidates = (
        visible_steam_root / "steamapps/libraryfolders.vdf",
        visible_steam_root / "config/libraryfolders.vdf",
    )
    content: Optional[str] = None
    for candidate in vdf_candidates:
        try:
            if candidate.is_file():
                content = candidate.read_text(encoding="utf-8", errors="replace")
                break
        except OSError:
            continue

    if not content:
        return []

    primary_roots: Set[str] = set()
    for root in (visible_steam_root, host_steam_root):
        if root is None:
            continue
        primary_roots.add(os.path.normpath(str(root)))
        try:
            primary_roots.add(str(root.resolve()))
        except OSError:
            pass

    depth = 0
    saw_root = False
    pending_key: Optional[str] = None
    seen: Set[str] = set()
    libraries: List[Path] = []

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        if line == "{":
            if depth == 0 and pending_key == "libraryfolders":
                saw_root = True
            depth += 1
            pending_key = None
            continue
        if line == "}":
            depth = max(0, depth - 1)
            pending_key = None
            continue

        kv_match = _KV_LINE_RE.match(raw_line)
        if kv_match:
            key = _unescape_vdf(kv_match.group(2))
            value = _unescape_vdf(kv_match.group(4)).strip()
            if saw_root and depth == 2 and key == "path" and value:
                norm = os.path.normpath(value)
                candidate_path = Path(norm)
                resolved = norm
                try:
                    resolved = str(candidate_path.resolve())
                except OSError:
                    pass
                if norm not in primary_roots and resolved not in primary_roots and resolved not in seen:
                    seen.add(resolved)
                    libraries.append(candidate_path)
            pending_key = None
            continue

        key_match = _KEY_ONLY_RE.match(raw_line)
        if key_match:
            pending_key = _unescape_vdf(key_match.group(2))

    return libraries


def translate_host_path_to_visible(host_path: Path, visible_home: Path, host_home: Optional[Path]) -> Path:
    """Translate a host-side path to the path visible inside Flatpak when needed."""
    if host_home is None or host_home == visible_home:
        return host_path
    try:
        relative = host_path.relative_to(host_home)
    except ValueError:
        return host_path
    return visible_home / relative


def read_library_manifests(steamapps_dir: Path) -> Dict[str, AppManifestInfo]:
    """Read all ``appmanifest_*.acf`` files in ``steamapps_dir`` keyed by ``installdir``."""
    by_installdir: Dict[str, AppManifestInfo] = {}
    try:
        entries = list(steamapps_dir.iterdir())
    except OSError:
        return by_installdir

    for entry in entries:
        if entry.suffix != ".acf" or not entry.name.startswith("appmanifest_"):
            continue
        try:
            info = parse_app_manifest(entry.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if info and info.installdir:
            by_installdir[info.installdir] = info
    return by_installdir


def _cleanup_sandbox_downloads(dest_steamapps: Path, info: AppManifestInfo) -> None:
    """Remove stale sandbox staging files for ``info.appid`` when host has advanced."""
    if not info.appid:
        return
    downloading = dest_steamapps / "downloading"
    if not downloading.is_dir():
        return

    app_stage_dir = downloading / info.appid
    if app_stage_dir.exists() or app_stage_dir.is_symlink():
        logger.info("Cleaning stale sandbox download directory: %s", app_stage_dir)
        _force_rmtree(app_stage_dir)

    state_prefixes = (f"state_{info.appid}.", f"state_{info.appid}_")
    depot_prefixes = tuple(f"depot_{depot}_" for depot in info.installed_depots if depot)
    try:
        entries = list(downloading.iterdir())
    except OSError:
        return

    for entry in entries:
        name = entry.name
        if name.startswith(state_prefixes) or (depot_prefixes and name.startswith(depot_prefixes)):
            _remove_file_if_exists(entry)


def _write_manifest_file(dest: Path, content: str) -> None:
    """Write a manifest file to ``dest``, clearing read-only bits if present."""
    if dest.exists() or dest.is_symlink():
        _remove_file_if_exists(dest)
    dest.write_text(content, encoding="utf-8")


def _invalidate_drifted_overlay(
    home_path: Path,
    namespace: str,
    host_common_dir: Path,
    installdir: str,
) -> None:
    """Reset or prune an instance overlay whose sandbox manifest drifted from host."""
    overlay_root = home_path / OVERLAY_DIR_NAME / namespace / _safe_folder_key(installdir)
    upper = overlay_root / "upper"
    if not upper.is_dir():
        return

    host_folder = host_common_dir / installdir
    if is_steam_tool_folder(host_folder):
        logger.info("Resetting drifted tool overlay for '%s'", installdir)
        _force_rmtree(upper)
        upper.mkdir(parents=True, exist_ok=True)
        return

    # For games, remove any file in upper that shadows an existing host file
    # (e.g. binaries written by a sandbox update) while preserving player-created
    # configs or local saves that do not exist in the host installation.
    logger.info("Pruning host-shadowed files from drifted game overlay for '%s'", installdir)
    _prune_stale_game_upper(upper, host_folder, prev_synced_at_ns=0)


def sync_library_manifests(
    host_steamapps: Path,
    dest_steamapps: Path,
    *,
    home_path: Optional[Path] = None,
    overlay_namespace: Optional[str] = None,
) -> Dict[str, AppManifestInfo]:
    """Copy and sanitize host ``appmanifest_*.acf`` files into ``dest_steamapps``.

    Existing instance manifests are preserved if ``host_steamapps`` cannot be
    read or contains no ``.acf`` files.  Obsolete instance manifests are only
    removed after every host manifest has been written cleanly.
    """
    try:
        manifests = [path for path in host_steamapps.iterdir() if path.suffix == ".acf"]
    except OSError as e:
        logger.warning(f"Cannot read host Steam directory '{host_steamapps}'; preserving instance manifests: {e}")
        return {}

    if not manifests:
        logger.warning(f"Host Steam directory '{host_steamapps}' has no game manifests; preserving instance manifests.")
        return {}

    dest_steamapps.mkdir(parents=True, exist_ok=True)
    synced: Dict[str, AppManifestInfo] = {}

    for manifest in sorted(manifests, key=lambda p: p.name):
        raw_content = manifest.read_text(encoding="utf-8", errors="replace")
        host_info = parse_app_manifest(raw_content)

        dest_path = dest_steamapps / manifest.name
        prev_info: Optional[AppManifestInfo] = None
        if dest_path.is_file():
            try:
                prev_info = parse_app_manifest(dest_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                prev_info = None

        if host_info is not None:
            if not host_info.is_clean_installed:
                logger.warning(
                    "Host Steam app %s (%s) has StateFlags=%s (pending or incomplete update); "
                    "complete updates in host Steam to avoid version mismatches.",
                    host_info.appid or manifest.name,
                    host_info.name or host_info.installdir,
                    host_info.state_flags,
                )
            if host_info.installdir:
                synced[host_info.installdir] = host_info

        sanitized = sanitize_sandbox_manifest(raw_content)
        _write_manifest_file(dest_path, sanitized)

        if host_info is not None and (host_info.state_flags & STATE_FULLY_INSTALLED):
            build_changed = prev_info is not None and prev_info.buildid != host_info.buildid
            had_dirty_prev = prev_info is not None and not prev_info.is_clean_installed
            if build_changed or had_dirty_prev or (dest_steamapps / "downloading" / host_info.appid).exists():
                _cleanup_sandbox_downloads(dest_steamapps, host_info)
            if build_changed and home_path is not None and overlay_namespace is not None and host_info.installdir:
                _invalidate_drifted_overlay(
                    home_path,
                    overlay_namespace,
                    host_steamapps / "common",
                    host_info.installdir,
                )

    host_names = {manifest.name for manifest in manifests}
    for existing in dest_steamapps.iterdir():
        if existing.suffix == ".acf" and existing.name not in host_names:
            _remove_file_if_exists(existing)
        elif existing.name.startswith("appmanifest_") and existing.name.endswith(".acf.tmp"):
            _remove_file_if_exists(existing)

    return synced


def external_library_mirror_dir(home_path: Path, host_library_root: Path) -> Path:
    """Return the per-instance directory backing an external Steam library."""
    key = _safe_folder_key(os.path.normpath(str(host_library_root)))
    return home_path / LIBRARIES_DIR_NAME / key


def _ensure_steamapps_subdirs(steamapps_dir: Path) -> None:
    """Create the standard private Steam subdirectories under ``steamapps_dir``."""
    steamapps_dir.mkdir(parents=True, exist_ok=True)
    for subdir in STEAM_SUBDIRS:
        (steamapps_dir / subdir).mkdir(exist_ok=True)


def sync_all_steam_manifests(
    home_path: Path,
    visible_steam_root: Path,
    host_steam_root: Optional[Path] = None,
) -> None:
    """Sync manifests for the primary Steam library and all external libraries."""
    primary_host = visible_steam_root / "steamapps"
    primary_dest = home_path / ".local/share/Steam/steamapps"
    sync_library_manifests(
        primary_host,
        primary_dest,
        home_path=home_path,
        overlay_namespace="common",
    )

    visible_home = Path.home()
    host_home = Utils.get_host_home() if Utils.is_flatpak() else visible_home

    for host_ext_root in parse_external_library_folders(visible_steam_root, host_steam_root):
        visible_ext_root = translate_host_path_to_visible(host_ext_root, visible_home, host_home)
        visible_ext_steamapps = visible_ext_root / "steamapps"
        if not visible_ext_steamapps.is_dir():
            logger.debug("External Steam library '%s' is not accessible; skipping manifest sync", host_ext_root)
            continue

        mirror_root = external_library_mirror_dir(home_path, host_ext_root)
        mirror_steamapps = mirror_root / "steamapps"
        _ensure_steamapps_subdirs(mirror_steamapps)

        host_lib_vdf = visible_ext_root / "libraryfolder.vdf"
        if host_lib_vdf.is_file():
            try:
                shutil.copyfile(host_lib_vdf, mirror_root / "libraryfolder.vdf")
            except OSError as e:
                logger.warning("Could not copy external library metadata '%s': %s", host_lib_vdf, e)

        ext_namespace = f"ext_{_safe_folder_key(os.path.normpath(str(host_ext_root)))}"
        try:
            sync_library_manifests(
                visible_ext_steamapps,
                mirror_steamapps,
                home_path=home_path,
                overlay_namespace=ext_namespace,
            )
        except OSError as e:
            logger.warning("Failed to synchronize manifests for external library '%s': %s", host_ext_root, e)


def is_steam_tool_folder(folder: Path, *, is_compat_tool: bool = False) -> bool:
    """Return True if ``folder`` is a Proton/runtime/compatibility tool directory."""
    if is_compat_tool:
        return True
    name = folder.name
    if name in STEAM_TOOL_NAMES or name.startswith(STEAM_TOOL_PREFIXES):
        return True
    try:
        return (
            (folder / "toolmanifest.vdf").is_file()
            or (folder / "proton").is_file()
            or (folder / "_v2-entry-point").is_file()
        )
    except OSError:
        return False


def is_steam_linux_runtime(folder: Path) -> bool:
    """Return True if ``folder`` is a Steam Linux Runtime container directory."""
    if folder.name.startswith("SteamLinuxRuntime"):
        return True
    try:
        return (folder / "_v2-entry-point").is_file()
    except OSError:
        return False


def is_proton_folder(folder: Path) -> bool:
    """Return True if ``folder`` is a Proton compatibility tool directory."""
    try:
        return (folder / "proton").is_file() or (folder / "dist.lock").exists()
    except OSError:
        return False


def bwrap_supports_overlay(overlay_base: Path) -> bool:
    """Probe whether ``bwrap`` supports unprivileged ``--overlay`` on ``overlay_base``'s filesystem."""
    try:
        overlay_base.mkdir(parents=True, exist_ok=True)
        dev_id = overlay_base.stat().st_dev
    except OSError:
        return False

    cache_key = (Utils.is_flatpak(), dev_id)
    cached = _OVERLAY_SUPPORT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    supported = False
    try:
        help_result = Utils.flatpak_spawn_host(
            ["bwrap", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        help_text = f"{help_result.stdout or ''}\n{help_result.stderr or ''}"
        if help_result.returncode == 0 and "--overlay-src" in help_text and "--overlay" in help_text:
            probe_root = overlay_base / f".probe-{os.getpid()}-{time.monotonic_ns()}"
            lower = probe_root / "lower"
            upper = probe_root / "upper"
            work = probe_root / "work"
            dest = probe_root / "dest"
            try:
                for directory in (lower, upper, work, dest):
                    directory.mkdir(parents=True, exist_ok=True)
                probe_result = Utils.flatpak_spawn_host(
                    [
                        "bwrap",
                        "--dev-bind",
                        "/",
                        "/",
                        "--overlay-src",
                        str(lower),
                        "--overlay",
                        str(upper),
                        str(work),
                        str(dest),
                        "--",
                        "true",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                supported = probe_result.returncode == 0
                if not supported:
                    logger.info(
                        "bwrap --overlay probe failed (rc=%s): %s; falling back to read-only binds",
                        probe_result.returncode,
                        (probe_result.stderr or "").strip(),
                    )
            finally:
                _force_rmtree(probe_root)
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("bwrap --overlay probe error: %s", e)
        supported = False

    _OVERLAY_SUPPORT_CACHE[cache_key] = supported
    return supported


def _compute_folder_stamp(
    visible_folder: Path,
    manifest: Optional[AppManifestInfo],
    *,
    is_tool: bool,
) -> Dict[str, object]:
    """Build a comparable version fingerprint for a shared host Steam folder."""
    stamp: Dict[str, object] = {
        "folder": visible_folder.name,
        "is_tool": is_tool,
        "buildid": manifest.buildid if manifest else "",
        "last_updated": manifest.last_updated if manifest else "",
    }
    sentinels: Dict[str, int] = {}
    if is_tool or manifest is None:
        for sentinel in TOOL_SENTINEL_FILES:
            candidate = visible_folder / sentinel
            try:
                if candidate.exists():
                    sentinels[sentinel] = candidate.stat().st_mtime_ns
            except OSError:
                continue
        if not sentinels and manifest is None:
            try:
                sentinels["."] = visible_folder.stat().st_mtime_ns
            except OSError:
                pass
    stamp["sentinels"] = sentinels
    return stamp


def _is_overlay_whiteout(path: Path) -> bool:
    """Return True if ``path`` represents an overlayfs whiteout entry."""
    try:
        st = path.lstat()
    except OSError:
        return False
    # Traditional privileged overlayfs whiteout: char device 0:0.
    if stat.S_ISCHR(st.st_mode) and st.st_rdev == 0:
        return True
    # Unprivileged userxattr overlayfs whiteout: empty file with overlay.whiteout xattr.
    if stat.S_ISREG(st.st_mode) and st.st_size == 0 and hasattr(os, "listxattr"):
        try:
            xattrs = os.listxattr(path, follow_symlinks=False)
            return any(attr.endswith("overlay.whiteout") for attr in xattrs)
        except OSError:
            return False
    return False


def _prune_stale_game_upper(upper: Path, visible_host_dir: Path, prev_synced_at_ns: int) -> None:
    """Remove files from ``upper`` shadowed by newer files in an updated host game."""
    if not upper.is_dir():
        return

    for root, dirs, files in os.walk(upper, topdown=False, followlinks=False):
        root_path = Path(root)
        rel_root = root_path.relative_to(upper)
        for name in files:
            upper_file = root_path / name
            host_file = visible_host_dir / rel_root / name
            try:
                if _is_overlay_whiteout(upper_file):
                    if host_file.exists() or host_file.is_symlink():
                        _remove_file_if_exists(upper_file)
                    continue
                if host_file.exists() or host_file.is_symlink():
                    host_mtime_ns = host_file.lstat().st_mtime_ns
                    if prev_synced_at_ns <= 0 or host_mtime_ns > prev_synced_at_ns:
                        _remove_file_if_exists(upper_file)
            except OSError:
                continue

        for name in dirs:
            upper_dir = root_path / name
            try:
                if not any(upper_dir.iterdir()):
                    upper_dir.rmdir()
            except OSError:
                continue


def _prepare_overlay_dirs(
    overlay_root: Path,
    visible_folder: Path,
    manifest: Optional[AppManifestInfo],
    *,
    is_tool: bool,
) -> Tuple[Path, Path]:
    """Prepare ``upper`` and ``work`` directories and invalidate stale upper layers."""
    upper = overlay_root / "upper"
    work = overlay_root / "work"
    stamp_path = overlay_root / ".stamp.json"

    new_stamp = _compute_folder_stamp(visible_folder, manifest, is_tool=is_tool)
    prev_stamp: Optional[Dict[str, object]] = None
    prev_synced_at_ns = 0
    if stamp_path.is_file():
        try:
            loaded = json.loads(stamp_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw_synced = loaded.pop("synced_at_ns", 0)
                if isinstance(raw_synced, int):
                    prev_synced_at_ns = raw_synced
                prev_stamp = loaded
        except (OSError, json.JSONDecodeError):
            prev_stamp = None

    if prev_stamp is not None and prev_stamp != new_stamp:
        if is_tool:
            logger.info(
                "Host Steam tool '%s' changed; resetting instance overlay upper layer",
                visible_folder.name,
            )
            _force_rmtree(upper)
        else:
            logger.info(
                "Host Steam game '%s' updated; pruning shadowed files from instance overlay",
                visible_folder.name,
            )
            _prune_stale_game_upper(upper, visible_folder, prev_synced_at_ns)

    # Always recreate an empty workdir so kernel overlayfs never trips on stale
    # state left behind by a force-killed instance.
    _force_rmtree(work)
    upper.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    persisted = dict(new_stamp)
    persisted["synced_at_ns"] = time.time_ns()
    try:
        stamp_path.write_text(json.dumps(persisted, sort_keys=True), encoding="utf-8")
    except OSError as e:
        logger.debug("Could not write overlay stamp '%s': %s", stamp_path, e)

    return upper, work


def _prune_orphaned_overlays(namespace_root: Path, active_keys: Iterable[str]) -> None:
    """Remove per-folder overlays whose host Steam folder no longer exists."""
    if not namespace_root.is_dir():
        return
    keep = set(active_keys)
    try:
        entries = list(namespace_root.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.name.startswith(".probe-"):
            continue
        if entry.is_dir() and entry.name not in keep:
            logger.info("Removing orphaned instance overlay: %s", entry)
            _force_rmtree(entry)


def _iter_subdirs(directory: Path, *, ignore: Collection[str] = ()) -> List[Path]:
    """Return sorted direct subdirectories of ``directory`` excluding ``ignore``."""
    if not directory.is_dir():
        return []
    try:
        entries = [entry for entry in directory.iterdir() if entry.is_dir() and entry.name not in ignore]
    except OSError:
        return []
    entries.sort(key=lambda p: p.name)
    return entries


def _mount_shared_folders(
    plan: SteamMountPlan,
    *,
    home_path: Path,
    orig_home: Path,
    folders: Sequence[Path],
    host_parent: Path,
    sandbox_parent: Path,
    namespace: str,
    manifests: Dict[str, AppManifestInfo],
    is_compat_tool: bool,
    use_overlay: bool,
) -> None:
    """Append ``bwrap`` mount arguments for one collection of shared Steam folders."""
    overlay_ns_root = home_path / OVERLAY_DIR_NAME / namespace
    active_keys: List[str] = []

    for visible_folder in folders:
        folder_name = visible_folder.name
        host_folder = host_parent / folder_name
        sandbox_dest = sandbox_parent / folder_name
        key = _safe_folder_key(folder_name)
        active_keys.append(key)

        is_tool = is_steam_tool_folder(visible_folder, is_compat_tool=is_compat_tool)
        manifest = manifests.get(folder_name)

        if use_overlay:
            upper, work = _prepare_overlay_dirs(
                overlay_ns_root / key,
                visible_folder,
                manifest,
                is_tool=is_tool,
            )
            plan.bwrap_args.extend(
                [
                    "--overlay-src",
                    str(host_folder),
                    "--overlay",
                    str(upper),
                    str(work),
                    str(sandbox_dest),
                ]
            )
            if is_steam_linux_runtime(visible_folder):
                inst_var = home_path / RUNTIME_DIR_NAME / "slr" / f"{namespace}_{key}" / "var"
                inst_var.mkdir(parents=True, exist_ok=True)
                plan.bwrap_args.extend(["--bind", str(inst_var), str(sandbox_dest / "var")])
            continue

        # Fallback when bwrap --overlay is unavailable on this host/filesystem.
        plan.bwrap_args.extend(["--ro-bind", str(host_folder), str(sandbox_dest)])

        if is_proton_folder(visible_folder):
            lock_dir = home_path / RUNTIME_DIR_NAME / "locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            lock_file = lock_dir / f"{namespace}_{key}.lock"
            lock_file.touch(exist_ok=True)
            if (visible_folder / "dist.lock").exists():
                plan.bwrap_args.extend(["--bind", str(lock_file), str(sandbox_dest / "dist.lock")])
            else:
                logger.warning(
                    "Proton folder '%s' is mounted read-only (no bwrap --overlay) and has no dist.lock yet; "
                    "run it once in host Steam if Proton fails to acquire dist.lock.",
                    folder_name,
                )

        if is_steam_linux_runtime(visible_folder):
            inst_var = home_path / RUNTIME_DIR_NAME / "slr" / f"{namespace}_{key}" / "var"
            inst_var.mkdir(parents=True, exist_ok=True)
            if (visible_folder / "var").is_dir():
                plan.bwrap_args.extend(["--bind", str(inst_var), str(sandbox_dest / "var")])
            else:
                pv_var_host = home_path / ".cache/twinverse/pv-var"
                pv_var_host.mkdir(parents=True, exist_ok=True)
                plan.extra_env.setdefault(
                    "PRESSURE_VESSEL_VARIABLE_DIR",
                    str(orig_home / ".cache/twinverse/pv-var"),
                )

    if use_overlay:
        _prune_orphaned_overlays(overlay_ns_root, active_keys)


def build_shared_steam_mounts(
    home_path: Path,
    orig_home: Path,
    sandbox_steam_path: Path,
    host_steam_path: Path,
) -> SteamMountPlan:
    """Build isolated, host-safe ``bwrap`` mounts for primary and external Steam libraries."""
    plan = SteamMountPlan()

    visible_common = sandbox_steam_path / "steamapps/common"
    host_common = host_steam_path / "steamapps/common"
    common_folders = _iter_subdirs(visible_common)

    visible_compat = sandbox_steam_path / "compatibilitytools.d"
    host_compat = host_steam_path / "compatibilitytools.d"
    compat_folders = _iter_subdirs(visible_compat, ignore=COMPAT_IGNORE)

    host_home = Utils.get_host_home() if Utils.is_flatpak() else orig_home
    external_specs: List[Tuple[Path, Path, List[Path]]] = []
    for host_ext_root in parse_external_library_folders(sandbox_steam_path, host_steam_path):
        visible_ext_root = translate_host_path_to_visible(host_ext_root, orig_home, host_home)
        visible_ext_steamapps = visible_ext_root / "steamapps"
        if not visible_ext_steamapps.is_dir():
            continue
        ext_folders = _iter_subdirs(visible_ext_steamapps / "common")
        external_specs.append((host_ext_root, visible_ext_root, ext_folders))

    has_any_shared = bool(common_folders or compat_folders or any(folders for _, _, folders in external_specs))
    use_overlay = bwrap_supports_overlay(home_path / OVERLAY_DIR_NAME) if has_any_shared else False

    if common_folders:
        primary_manifests = read_library_manifests(sandbox_steam_path / "steamapps")
        _mount_shared_folders(
            plan,
            home_path=home_path,
            orig_home=orig_home,
            folders=common_folders,
            host_parent=host_common,
            sandbox_parent=visible_common,
            namespace="common",
            manifests=primary_manifests,
            is_compat_tool=False,
            use_overlay=use_overlay,
        )

    if compat_folders:
        _mount_shared_folders(
            plan,
            home_path=home_path,
            orig_home=orig_home,
            folders=compat_folders,
            host_parent=host_compat,
            sandbox_parent=visible_compat,
            namespace="compat",
            manifests={},
            is_compat_tool=True,
            use_overlay=use_overlay,
        )

    for host_ext_root, visible_ext_root, ext_folders in external_specs:
        mirror_root = external_library_mirror_dir(home_path, host_ext_root)
        mirror_steamapps = mirror_root / "steamapps"
        _ensure_steamapps_subdirs(mirror_steamapps)

        host_lib_vdf = visible_ext_root / "libraryfolder.vdf"
        mirror_lib_vdf = mirror_root / "libraryfolder.vdf"
        if host_lib_vdf.is_file():
            if not mirror_lib_vdf.is_file():
                try:
                    shutil.copyfile(host_lib_vdf, mirror_lib_vdf)
                except OSError:
                    pass
            if mirror_lib_vdf.is_file():
                plan.bwrap_args.extend(["--bind", str(mirror_lib_vdf), str(visible_ext_root / "libraryfolder.vdf")])

        plan.bwrap_args.extend(["--bind", str(mirror_steamapps), str(visible_ext_root / "steamapps")])

        if ext_folders:
            ext_manifests = read_library_manifests(visible_ext_root / "steamapps")
            ext_namespace = f"ext_{_safe_folder_key(os.path.normpath(str(host_ext_root)))}"
            _mount_shared_folders(
                plan,
                home_path=home_path,
                orig_home=orig_home,
                folders=ext_folders,
                host_parent=host_ext_root / "steamapps/common",
                sandbox_parent=visible_ext_root / "steamapps/common",
                namespace=ext_namespace,
                manifests=ext_manifests,
                is_compat_tool=False,
                use_overlay=use_overlay,
            )

    return plan
