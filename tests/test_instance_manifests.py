"""Check manifest synchronization, sanitization, and preservation on failure."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core.exceptions import TwinverseError
from src.services.instance import InstanceService
from src.services.steam_library import (
    OVERLAY_DIR_NAME,
    _safe_folder_key,
    external_library_mirror_dir,
    parse_app_manifest,
)

DIRTY_PROTON_MANIFEST = """"AppState"
{
\t"appid"\t\t"4628710"
\t"Universe"\t\t"1"
\t"name"\t\t"Proton 11.0"
\t"StateFlags"\t\t"1702"
\t"installdir"\t\t"Proton 11.0"
\t"LastUpdated"\t\t"1791588906"
\t"StagingSize"\t\t"487868177"
\t"buildid"\t\t"25833067"
\t"UpdateResult"\t\t"38"
\t"BytesToDownload"\t\t"250717168"
\t"BytesDownloaded"\t\t"20286128"
\t"BytesToStage"\t\t"1030159970"
\t"BytesStaged"\t\t"219097015"
\t"TargetBuildID"\t\t"26870980"
\t"AutoUpdateBehavior"\t\t"0"
\t"ScheduledAutoUpdate"\t\t"1799999999"
\t"FullValidateBeforeNextUpdate"\t\t"1"
\t"FullValidateAfterNextUpdate"\t\t"1"
\t"InstalledDepots"
\t{
\t\t"4628711"
\t\t{
\t\t\t"manifest"\t\t"2461712087958400360"
\t\t\t"size"\t\t"1445064740"
\t\t}
\t}
\t"StagedDepots"
\t{
\t\t"4628711"
\t\t{
\t\t\t"manifest"\t\t"8394053305694874906"
\t\t\t"size"\t\t"1465272931"
\t\t}
\t}
}
"""


@pytest.fixture
def manifest_setup(monkeypatch, tmp_path):
    """Create isolated host and instance libraries."""
    service = InstanceService.__new__(InstanceService)
    service.logger = Mock()
    host_home = tmp_path / "host"
    monkeypatch.setattr(Path, "home", lambda: host_home)
    host = host_home / ".local/share/Steam/steamapps"
    host.mkdir(parents=True)
    home = tmp_path / "instance"
    service._prepare_home(home)
    dest = home / ".local/share/Steam/steamapps"
    return service, home, host, dest


def test_sync_updates_adds_and_removes_manifests(manifest_setup):
    """Make instance manifests match the host without touching other files."""
    service, home, host, dest = manifest_setup
    (host / "appmanifest_1.acf").write_text("updated")
    (host / "appmanifest_2.acf").write_text("new")
    (dest / "appmanifest_1.acf").write_text("old")
    (dest / "appmanifest_3.acf").write_text("obsolete")
    (dest / "libraryfolders.vdf").write_text("keep")

    service._sync_app_manifests(home)

    assert (dest / "appmanifest_1.acf").read_text() == "updated"
    assert (dest / "appmanifest_2.acf").read_text() == "new"
    assert not (dest / "appmanifest_3.acf").exists()
    assert (dest / "libraryfolders.vdf").read_text() == "keep"


def test_missing_source_preserves_manifests(manifest_setup):
    """Keep existing manifests when the host library is unavailable."""
    service, home, host, dest = manifest_setup
    host.rmdir()
    (dest / "appmanifest_1.acf").write_text("keep")

    service._sync_app_manifests(home)

    assert (dest / "appmanifest_1.acf").read_text() == "keep"


def test_copy_failure_does_not_remove_obsolete_manifests(manifest_setup, monkeypatch):
    """Abort synchronization before cleanup if writing fails."""
    service, home, host, dest = manifest_setup
    (host / "appmanifest_1.acf").write_text("new")
    (dest / "appmanifest_2.acf").write_text("keep")
    monkeypatch.setattr(
        "src.services.steam_library._write_manifest_file",
        Mock(side_effect=PermissionError("denied")),
    )

    with pytest.raises(TwinverseError, match="Failed to synchronize"):
        service._sync_app_manifests(home)

    assert (dest / "appmanifest_2.acf").read_text() == "keep"


def test_sync_sanitizes_dirty_host_manifest_and_cleans_stale_downloads(manifest_setup):
    """Sanitize pending/corrupt host manifests and clear read-only sandbox downloads."""
    service, home, host, dest = manifest_setup
    (host / "appmanifest_4628710.acf").write_text(DIRTY_PROTON_MANIFEST)

    stale_dir = dest / "downloading/4628710/files/lib/wine/i386-unix"
    stale_dir.mkdir(parents=True)
    ro_file = stale_dir / "winscard.so"
    ro_file.write_bytes(b"ELF")
    ro_file.chmod(0o555)
    (dest / "downloading/state_4628710_4628711.patch").write_bytes(b"patch")
    (dest / "downloading/depot_4628711_old_new.delta").write_bytes(b"delta")
    (dest / "appmanifest_4628710.acf.tmp").write_text("stray")

    service._sync_app_manifests(home)

    synced_text = (dest / "appmanifest_4628710.acf").read_text()
    parsed = parse_app_manifest(synced_text)
    assert parsed is not None
    assert parsed.state_flags == 4
    assert parsed.buildid == "25833067"
    assert '"AutoUpdateBehavior"\t\t"1"' in synced_text
    assert '"ScheduledAutoUpdate"\t\t"0"' in synced_text
    assert "StagedDepots" not in synced_text
    assert "FullValidateBeforeNextUpdate" not in synced_text
    assert "TargetBuildID" not in synced_text
    assert "BytesToDownload" not in synced_text
    assert "InstalledDepots" in synced_text
    assert not (dest / "downloading/4628710").exists()
    assert not (dest / "downloading/state_4628710_4628711.patch").exists()
    assert not (dest / "downloading/depot_4628711_old_new.delta").exists()
    assert not (dest / "appmanifest_4628710.acf.tmp").exists()


def test_sync_resets_drifted_tool_overlay_when_sandbox_buildid_diverges(manifest_setup):
    """Reset a tool overlay when the sandbox updated to a different buildid than the host."""
    service, home, host, dest = manifest_setup
    proton_host_dir = host / "common/Proton 11.0"
    proton_host_dir.mkdir(parents=True)
    (proton_host_dir / "toolmanifest.vdf").write_text('"manifest"\n{\n}\n')

    host_manifest = DIRTY_PROTON_MANIFEST.replace('"1702"', '"4"')
    sandbox_drifted = host_manifest.replace('"25833067"', '"26870980"')
    (host / "appmanifest_4628710.acf").write_text(host_manifest)
    (dest / "appmanifest_4628710.acf").write_text(sandbox_drifted)

    tool_upper = home / OVERLAY_DIR_NAME / "common" / _safe_folder_key("Proton 11.0") / "upper"
    tool_upper.mkdir(parents=True)
    stale_bin = tool_upper / "wineserver"
    stale_bin.write_bytes(b"new-build-binary")

    service._sync_app_manifests(home)

    assert not stale_bin.exists()
    assert tool_upper.is_dir()


def test_sync_mirrors_external_library_manifests(manifest_setup, tmp_path):
    """Sync and sanitize manifests for external libraries declared in libraryfolders.vdf."""
    service, home, host, _dest = manifest_setup
    ext_root = tmp_path / "external_drive/Steam"
    ext_steamapps = ext_root / "steamapps"
    ext_steamapps.mkdir(parents=True)
    (ext_root / "libraryfolder.vdf").write_text('"libraryfolder"\n{\n\t"label"\t\t"Games"\n}\n')
    (ext_steamapps / "appmanifest_3321460.acf").write_text(
        DIRTY_PROTON_MANIFEST.replace("4628710", "3321460").replace("Proton 11.0", "Crimson Desert")
    )

    (host / "appmanifest_1.acf").write_text("primary")
    (host / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n'
        "{\n"
        '\t"0"\n'
        "\t{\n"
        f'\t\t"path"\t\t"{host.parent}"\n'
        "\t}\n"
        '\t"1"\n'
        "\t{\n"
        f'\t\t"path"\t\t"{ext_root}"\n'
        "\t}\n"
        "}\n"
    )

    service._sync_app_manifests(home)

    mirror = external_library_mirror_dir(home, ext_root)
    assert (mirror / "libraryfolder.vdf").is_file()
    ext_manifest_text = (mirror / "steamapps/appmanifest_3321460.acf").read_text()
    parsed = parse_app_manifest(ext_manifest_text)
    assert parsed is not None
    assert parsed.state_flags == 4
    assert '"AutoUpdateBehavior"\t\t"1"' in ext_manifest_text
    assert (mirror / "steamapps/compatdata").is_dir()


def test_running_instance_rejected_before_preparation():
    """Prevent launch preparation from changing a running instance's manifests."""
    service = InstanceService.__new__(InstanceService)
    service.processes = {0: Mock(poll=Mock(return_value=None))}
    service._prepare_home = Mock()

    with pytest.raises(TwinverseError, match="already running"):
        service._prepare_instance_launch(Mock(), 0)

    service._prepare_home.assert_not_called()
