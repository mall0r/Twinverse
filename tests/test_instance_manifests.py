"""Check manifest synchronization and preservation on failure."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core.exceptions import TwinverseError
from src.services.instance import InstanceService


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
    """Abort synchronization before cleanup if copying fails."""
    service, home, host, dest = manifest_setup
    (host / "appmanifest_1.acf").write_text("new")
    (dest / "appmanifest_2.acf").write_text("keep")
    monkeypatch.setattr("src.services.instance.shutil.copy", Mock(side_effect=PermissionError("denied")))

    with pytest.raises(TwinverseError, match="Failed to synchronize"):
        service._sync_app_manifests(home)

    assert (dest / "appmanifest_2.acf").read_text() == "keep"


def test_running_instance_rejected_before_preparation():
    """Prevent launch preparation from changing a running instance's manifests."""
    service = InstanceService.__new__(InstanceService)
    service.processes = {0: Mock(poll=Mock(return_value=None))}
    service._prepare_home = Mock()

    with pytest.raises(TwinverseError, match="already running"):
        service._prepare_instance_launch(Mock(), 0)

    service._prepare_home.assert_not_called()
