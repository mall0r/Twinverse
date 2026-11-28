"""Tests for shared Steam library isolation, OverlayFS mounts, and fallbacks."""

import os
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock

from src.core import Utils
from src.models import PlayerInstanceConfig, Profile
from src.services.cmd_builder import CommandBuilder
from src.services.steam_library import (
    OVERLAY_DIR_NAME,
    _safe_folder_key,
    build_shared_steam_mounts,
    bwrap_supports_overlay,
    clear_overlay_support_cache,
    external_library_mirror_dir,
    parse_app_manifest,
    parse_external_library_folders,
    sanitize_sandbox_manifest,
)


def _sample_manifest(
    appid: str = "4628710",
    name: str = "Proton 11.0",
    installdir: str = "Proton 11.0",
    buildid: str = "25833067",
    last_updated: str = "1791588906",
    state_flags: str = "4",
    auto_update: str = "0",
) -> str:
    """Return a minimal realistic Valve KeyValues ``appmanifest`` string."""
    return (
        '"AppState"\n'
        "{\n"
        f'\t"appid"\t\t"{appid}"\n'
        f'\t"name"\t\t"{name}"\n'
        f'\t"StateFlags"\t\t"{state_flags}"\n'
        f'\t"installdir"\t\t"{installdir}"\n'
        f'\t"LastUpdated"\t\t"{last_updated}"\n'
        f'\t"buildid"\t\t"{buildid}"\n'
        f'\t"AutoUpdateBehavior"\t\t"{auto_update}"\n'
        '\t"InstalledDepots"\n'
        "\t{\n"
        f'\t\t"{appid}1"\n'
        "\t\t{\n"
        '\t\t\t"manifest"\t\t"111"\n'
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )


def _make_steam_tree(host_home: Path) -> Path:
    """Create a realistic host Steam directory containing games, Proton, and SLR."""
    steam = host_home / ".local/share/Steam"
    common = steam / "steamapps/common"
    (common / "Hollow Knight").mkdir(parents=True)
    (common / "Hollow Knight/game.bin").write_bytes(b"v1")

    proton = common / "Proton 11.0"
    proton.mkdir(parents=True)
    (proton / "toolmanifest.vdf").write_text('"manifest"\n{\n}\n')
    (proton / "proton").write_text("#!/usr/bin/env python3\n")
    (proton / "dist.lock").touch()
    (proton / "version").write_text("1791588906 proton-11.0\n")

    slr = common / "SteamLinuxRuntime_4"
    (slr / "var").mkdir(parents=True)
    (slr / "toolmanifest.vdf").write_text('"manifest"\n{\n}\n')
    (slr / "_v2-entry-point").write_text("#!/bin/sh\n")

    compat = steam / "compatibilitytools.d"
    (compat / "GE-Proton10-1").mkdir(parents=True)
    (compat / "GE-Proton10-1/proton").write_text("#!/usr/bin/env python3\n")
    (compat / "GE-Proton10-1/dist.lock").touch()
    (compat / "LegacyRuntime").mkdir(parents=True)

    (steam / "steamapps/appmanifest_367520.acf").write_text(
        _sample_manifest(appid="367520", name="Hollow Knight", installdir="Hollow Knight", buildid="100")
    )
    (steam / "steamapps/appmanifest_4628710.acf").write_text(
        _sample_manifest(appid="4628710", name="Proton 11.0", installdir="Proton 11.0", buildid="25833067")
    )
    return steam


def test_sanitize_injects_auto_update_and_preserves_uninstalled_flags():
    """Inject AutoUpdateBehavior when missing and preserve uninstalled StateFlags."""
    uninstalled = (
        '"AppState"\n'
        "{\n"
        '\t"appid"\t\t"999"\n'
        '\t"StateFlags"\t\t"1026"\n'
        '\t"installdir"\t\t"Pending"\n'
        '\t"TargetBuildID"\t\t"42"\n'
        "}\n"
    )
    sanitized = sanitize_sandbox_manifest(uninstalled)
    parsed = parse_app_manifest(sanitized)
    assert parsed is not None
    assert parsed.state_flags == 1026
    assert '"AutoUpdateBehavior"\t\t"1"' in sanitized
    assert "TargetBuildID" not in sanitized


def test_parse_external_library_folders_skips_primary_and_deduplicates(tmp_path):
    """Return only distinct external libraries from host libraryfolders.vdf."""
    steam = tmp_path / "home/.local/share/Steam"
    (steam / "steamapps").mkdir(parents=True)
    ext_a = tmp_path / "mnt/Games/Steam"
    ext_b = tmp_path / "mnt/SSD/Steam"
    (steam / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders"\n'
        "{\n"
        '\t"0"\n'
        "\t{\n"
        f'\t\t"path"\t\t"{steam}"\n'
        "\t}\n"
        '\t"1"\n'
        "\t{\n"
        f'\t\t"path"\t\t"{ext_a}"\n'
        "\t}\n"
        '\t"2"\n'
        "\t{\n"
        f'\t\t"path"\t\t"{ext_a}/"\n'
        "\t}\n"
        '\t"3"\n'
        "\t{\n"
        f'\t\t"path"\t\t"{ext_b}"\n'
        "\t}\n"
        "}\n"
    )

    assert parse_external_library_folders(steam, steam) == [ext_a, ext_b]


def test_build_shared_steam_mounts_uses_overlayfs_and_isolates_external_libraries(monkeypatch, tmp_path):
    """Mount primary, compat, and external Steam folders via OverlayFS without host RW binds."""
    host_home = tmp_path / "host"
    steam = _make_steam_tree(host_home)
    ext_root = tmp_path / "mnt/Games/Steam"
    (ext_root / "steamapps/common/Crimson Desert").mkdir(parents=True)
    (ext_root / "libraryfolder.vdf").write_text('"libraryfolder"\n{\n}\n')
    (steam / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders"\n'
        "{\n"
        '\t"0"\n'
        "\t{\n"
        f'\t\t"path"\t\t"{steam}"\n'
        "\t}\n"
        '\t"1"\n'
        "\t{\n"
        f'\t\t"path"\t\t"{ext_root}"\n'
        "\t}\n"
        "}\n"
    )

    instance_home = tmp_path / "twinverse/home_1"
    instance_home.mkdir(parents=True)
    monkeypatch.setattr("src.services.steam_library.bwrap_supports_overlay", lambda _p: True)

    plan = build_shared_steam_mounts(instance_home, host_home, steam, steam)
    args = plan.bwrap_args

    # Host common and compat folders must NEVER be directly --bind mounted RW.
    for i, token in enumerate(args):
        if token == "--bind":
            src = Path(args[i + 1])
            assert not str(src).startswith(str(steam / "steamapps/common"))
            assert not str(src).startswith(str(steam / "compatibilitytools.d"))
            assert not str(src).startswith(str(ext_root / "steamapps/common"))

    # Primary game, Proton, SLR, compat tool (not LegacyRuntime), and external game use --overlay-src/--overlay.
    assert str(steam / "steamapps/common/Hollow Knight") in args
    assert str(steam / "steamapps/common/Proton 11.0") in args
    assert str(steam / "steamapps/common/SteamLinuxRuntime_4") in args
    assert str(steam / "compatibilitytools.d/GE-Proton10-1") in args
    assert str(steam / "compatibilitytools.d/LegacyRuntime") not in args
    assert str(ext_root / "steamapps/common/Crimson Desert") in args

    proton_src_idx = args.index(str(steam / "steamapps/common/Proton 11.0"))
    assert args[proton_src_idx - 1] == "--overlay-src"
    assert args[proton_src_idx + 1] == "--overlay"
    assert args[proton_src_idx + 4] == str(steam / "steamapps/common/Proton 11.0")

    # SteamLinuxRuntime_4 gets a dedicated native per-instance var/ bind-mount.
    slr_var_dest = str(steam / "steamapps/common/SteamLinuxRuntime_4/var")
    assert slr_var_dest in args
    slr_var_idx = args.index(slr_var_dest)
    assert args[slr_var_idx - 2] == "--bind"
    assert str(instance_home) in args[slr_var_idx - 1]

    # External library steamapps and libraryfolder.vdf are shadowed by per-instance mirrors.
    mirror = external_library_mirror_dir(instance_home, ext_root)
    ext_sa_idx = args.index(str(ext_root / "steamapps"))
    assert args[ext_sa_idx - 2 : ext_sa_idx + 1] == ["--bind", str(mirror / "steamapps"), str(ext_root / "steamapps")]
    ext_vdf_idx = args.index(str(ext_root / "libraryfolder.vdf"))
    assert args[ext_vdf_idx - 2 : ext_vdf_idx + 1] == [
        "--bind",
        str(mirror / "libraryfolder.vdf"),
        str(ext_root / "libraryfolder.vdf"),
    ]


def test_build_shared_steam_mounts_ro_bind_fallback_protects_host_and_keeps_runtime_writable(monkeypatch, tmp_path):
    """Fall back to --ro-bind plus private dist.lock and SLR var/ when overlayfs is unavailable."""
    host_home = tmp_path / "host"
    steam = _make_steam_tree(host_home)
    # Add a fresh SLR without a host var/ directory to verify PRESSURE_VESSEL_VARIABLE_DIR fallback.
    slr_fresh = steam / "steamapps/common/SteamLinuxRuntime_sniper"
    slr_fresh.mkdir(parents=True)
    (slr_fresh / "_v2-entry-point").write_text("#!/bin/sh\n")

    instance_home = tmp_path / "twinverse/home_1"
    instance_home.mkdir(parents=True)
    monkeypatch.setattr("src.services.steam_library.bwrap_supports_overlay", lambda _p: False)

    plan = build_shared_steam_mounts(instance_home, host_home, steam, steam)
    args = plan.bwrap_args

    assert "--overlay-src" not in args
    assert "--overlay" not in args

    for rel in (
        "steamapps/common/Hollow Knight",
        "steamapps/common/Proton 11.0",
        "steamapps/common/SteamLinuxRuntime_4",
        "steamapps/common/SteamLinuxRuntime_sniper",
        "compatibilitytools.d/GE-Proton10-1",
    ):
        target = str(steam / rel)
        idx = args.index(target)
        assert args[idx - 1] == "--ro-bind"
        assert args[idx + 1] == target

    # Proton dist.lock gets a per-instance writable bind-mount.
    lock_dest = str(steam / "steamapps/common/Proton 11.0/dist.lock")
    lock_idx = args.index(lock_dest)
    assert args[lock_idx - 2] == "--bind"
    assert Path(args[lock_idx - 1]).is_file()
    assert str(instance_home) in args[lock_idx - 1]

    # SLR with existing var/ gets a private var/ bind-mount; fresh SLR triggers PRESSURE_VESSEL_VARIABLE_DIR.
    assert str(steam / "steamapps/common/SteamLinuxRuntime_4/var") in args
    assert plan.extra_env["PRESSURE_VESSEL_VARIABLE_DIR"] == str(host_home / ".cache/twinverse/pv-var")
    assert (instance_home / ".cache/twinverse/pv-var").is_dir()


def test_overlay_invalidation_resets_tools_prunes_updated_games_and_cleans_orphans(monkeypatch, tmp_path):
    """Invalidate tool overlays fully, prune shadowed game files while keeping configs, and drop orphans."""
    host_home = tmp_path / "host"
    steam = _make_steam_tree(host_home)
    instance_home = tmp_path / "twinverse/home_1"
    instance_home.mkdir(parents=True)
    monkeypatch.setattr("src.services.steam_library.bwrap_supports_overlay", lambda _p: True)

    # First launch populates stamps and overlays.
    build_shared_steam_mounts(instance_home, host_home, steam, steam)

    proton_key = _safe_folder_key("Proton 11.0")
    game_key = _safe_folder_key("Hollow Knight")
    proton_upper = instance_home / OVERLAY_DIR_NAME / "common" / proton_key / "upper"
    proton_work = instance_home / OVERLAY_DIR_NAME / "common" / proton_key / "work"
    game_upper = instance_home / OVERLAY_DIR_NAME / "common" / game_key / "upper"

    (proton_upper / "stale_proton_file").write_text("old")
    (proton_work / "leftover_work").write_text("stale")
    (game_upper / "game.bin").write_bytes(b"shadowed-old-binary")
    (game_upper / "player_config.ini").write_text("volume=50\n")

    orphan = instance_home / OVERLAY_DIR_NAME / "common" / _safe_folder_key("Uninstalled Game")
    (orphan / "upper").mkdir(parents=True)

    # Simulate host Steam updating both Proton 11.0 and Hollow Knight.
    (steam / "steamapps/appmanifest_4628710.acf").write_text(
        _sample_manifest(appid="4628710", name="Proton 11.0", installdir="Proton 11.0", buildid="26870980")
    )
    (steam / "steamapps/appmanifest_367520.acf").write_text(
        _sample_manifest(appid="367520", name="Hollow Knight", installdir="Hollow Knight", buildid="200")
    )
    host_game_bin = steam / "steamapps/common/Hollow Knight/game.bin"
    host_game_bin.write_bytes(b"v2-from-host")
    future_ns = host_game_bin.stat().st_mtime_ns + 10_000_000_000
    os.utime(host_game_bin, ns=(future_ns, future_ns))

    build_shared_steam_mounts(instance_home, host_home, steam, steam)

    # Tool upper layer wiped; workdir emptied; updated host game binary unshadowed; player config kept; orphan gone.
    assert not (proton_upper / "stale_proton_file").exists()
    assert not any(proton_work.iterdir())
    assert not (game_upper / "game.bin").exists()
    assert (game_upper / "player_config.ini").read_text() == "volume=50\n"
    assert not orphan.exists()


def test_bwrap_supports_overlay_probes_and_caches(monkeypatch, tmp_path):
    """Verify overlay probe requires both help flags and a succeeding live bwrap test."""
    clear_overlay_support_cache()
    monkeypatch.setattr(Utils, "is_flatpak", lambda: False)

    calls = []

    def fake_spawn(cmd, **_kwargs):
        calls.append(cmd)
        if cmd == ["bwrap", "--help"]:
            return CompletedProcess(cmd, 0, "--overlay-src SRC\n--overlay RWSRC WORKDIR DEST\n", "")
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(Utils, "flatpak_spawn_host", fake_spawn)
    base = tmp_path / "overlays"
    assert bwrap_supports_overlay(base) is True
    assert len(calls) == 2
    assert not list(base.glob(".probe-*"))

    # Second call hits cache.
    assert bwrap_supports_overlay(base) is True
    assert len(calls) == 2

    # Probe returning non-zero falls back cleanly to False.
    clear_overlay_support_cache()
    monkeypatch.setattr(
        Utils,
        "flatpak_spawn_host",
        lambda cmd, **_kw: CompletedProcess(
            cmd,
            0 if cmd == ["bwrap", "--help"] else 1,
            "--overlay-src\n--overlay\n" if cmd == ["bwrap", "--help"] else "",
            "overlayfs denied",
        ),
    )
    assert bwrap_supports_overlay(base) is False
    assert not list(base.glob(".probe-*"))


def test_command_builder_preserves_env_invariants_with_steam_library_isolation(monkeypatch, tmp_path):
    """Keep bwrap at cmd[0], let user env override fallback PV var, and keep KWin/MangoHud last."""
    host_home = tmp_path / "host"
    steam = _make_steam_tree(host_home)
    slr_fresh = steam / "steamapps/common/SteamLinuxRuntime_sniper"
    slr_fresh.mkdir(parents=True)
    (slr_fresh / "_v2-entry-point").write_text("#!/bin/sh\n")

    instance_home = tmp_path / "twinverse/home_1"
    instance_home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: host_home)
    monkeypatch.setattr(Utils, "is_flatpak", lambda: False)
    monkeypatch.setattr("src.services.cmd_builder.stage_virtual_uinput", lambda *a, **kw: None)
    monkeypatch.setattr("src.services.steam_library.bwrap_supports_overlay", lambda _p: False)

    profile = Profile(
        use_gamescope=True,
        use_steamdeck_tag=True,
        player_configs=[
            PlayerInstanceConfig(
                env={
                    "PRESSURE_VESSEL_VARIABLE_DIR": "/custom/pv-var",
                    "MANGOHUD_CONFIG": "full",
                    "TWINVERSE_KWIN_INSTANCE": "99",
                }
            )
        ],
    )
    command = CommandBuilder(profile, {}, Mock(), 0, instance_home, None)._build_bwrap_command(0)

    assert command[0] == "bwrap"
    pv_idx = command.index("PRESSURE_VESSEL_VARIABLE_DIR")
    assert command[pv_idx + 1] == "/custom/pv-var"
    unset_idx = command.index("--unsetenv")
    assert command[unset_idx + 1] == "MANGOHUD_CONFIG"
    assert command.index("full") < unset_idx
    assert command[-3:] == ["--setenv", "TWINVERSE_KWIN_INSTANCE", "0"]
