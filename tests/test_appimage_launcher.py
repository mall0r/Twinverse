"""Check AppImage-only desktop integration without launching the application."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def launch(tmp_path):
    """Run the real launcher against a fake executable that records its environment."""
    appdir = tmp_path / "AppDir with spaces"
    binary = appdir / "usr/bin/twinverse"
    binary.parent.mkdir(parents=True)
    binary.write_text(
        f"#!{sys.executable}\nimport json, os, sys\nprint(json.dumps([dict(os.environ), sys.argv[1:]]))\n"
    )
    binary.chmod(0o755)
    for subdir in ("wayland-client", "wayland-cursor", "wayland-egl"):
        (appdir / "usr/lib/fallback" / subdir).mkdir(parents=True)
    launcher = appdir / "AppRun"
    shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/appimage/AppRun", launcher)

    def run(**overrides):
        integration_vars = {
            "GDK_DEBUG",
            "GDK_DISABLE",
            "FONTCONFIG_PATH",
            "FONTCONFIG_FILE",
            "XDG_DATA_DIRS",
            "LD_LIBRARY_PATH",
            "GDK_BACKEND",
        }
        env = {key: value for key, value in os.environ.items() if key not in integration_vars}
        env.update(overrides)
        result = subprocess.check_output(["bash", str(launcher), "argument with spaces", "--test"], env=env, text=True)
        return json.loads(result), appdir

    return run


def test_host_themes_before_bundled_fallback(launch):
    """Prefer host themes while preserving library paths and launch arguments."""
    (env, args), appdir = launch(XDG_DATA_DIRS="/custom/share:/usr/share", LD_LIBRARY_PATH="/custom/lib")
    assert env["XDG_DATA_DIRS"] == f"/custom/share:/usr/share:{appdir}/usr/share:{appdir}/usr/bin/_internal/share"
    assert env["LD_LIBRARY_PATH"].startswith(f"{appdir}/usr/lib:/custom/lib")
    assert args == ["argument with spaces", "--test"]


def test_launcher_uses_portal_without_forcing_display_backend(launch):
    """Use desktop preferences without selecting X11 or Wayland for the user."""
    (env, _), appdir = launch()
    assert env["GDK_DEBUG"] == "portals"
    assert "GDK_BACKEND" not in env
    assert env["XDG_DATA_DIRS"] == f"/usr/local/share:/usr/share:{appdir}/usr/share:{appdir}/usr/bin/_internal/share"


@pytest.mark.parametrize("flags", ["no-portals", "settings,no-portals", "settings:no-portals", "no-portals;settings"])
def test_explicit_portal_opt_out_is_preserved(launch, flags):
    """Respect an explicit portal opt-out and display backend selection."""
    (env, _), _appdir = launch(GDK_DEBUG=flags, GDK_BACKEND="x11")
    assert env["GDK_DEBUG"] == flags
    assert env["GDK_BACKEND"] == "x11"


def test_existing_debug_flags_are_preserved(launch):
    """Append portal integration without discarding existing debug flags."""
    (env, _), _appdir = launch(GDK_DEBUG="settings")
    assert env["GDK_DEBUG"] == "settings,portals"


@pytest.mark.parametrize("config", [{"FONTCONFIG_FILE": "/custom/fonts.conf"}, {"FONTCONFIG_PATH": "/custom/fonts"}])
def test_user_fontconfig_is_not_overridden(launch, config):
    """Leave user-supplied fontconfig overrides unchanged."""
    (env, _), _appdir = launch(**config)
    for key in ("FONTCONFIG_PATH", "FONTCONFIG_FILE"):
        assert env.get(key) == config.get(key)


def test_host_fontconfig_is_preferred(launch):
    """Use host font rules when available instead of the bundled configuration."""
    (env, _), appdir = launch()
    expected = "/etc/fonts" if Path("/etc/fonts/fonts.conf").is_file() else f"{appdir}/usr/bin/_internal/etc/fonts"
    assert env["FONTCONFIG_PATH"] == expected
    assert env["FONTCONFIG_FILE"] == f"{expected}/fonts.conf"


def test_bundled_fontconfig_is_only_a_fallback(launch, tmp_path):
    """Simulate missing host data without touching the real /etc/fonts."""
    bash_env = tmp_path / "no-host-fontconfig.sh"
    bash_env.write_text(
        "function [() {\n"
        '    if [[ "$1" == -r && "$2" == /etc/fonts/fonts.conf ]]; then return 1; fi\n'
        '    builtin [ "$@"\n'
        "}\n"
    )
    (env, _), appdir = launch(BASH_ENV=str(bash_env))
    assert env["FONTCONFIG_PATH"] == f"{appdir}/usr/bin/_internal/etc/fonts"
    assert env["FONTCONFIG_FILE"] == f"{appdir}/usr/bin/_internal/etc/fonts/fonts.conf"


def test_bundled_wayland_is_only_used_when_missing_from_host(launch, tmp_path):
    """Append Wayland fallback directories only for libraries missing on the host."""
    bash_env = tmp_path / "partial-host-wayland.sh"
    bash_env.write_text(
        "function [() {\n"
        '    if [[ "$1" == -r && "$2" == *libwayland-client.so.0 ]]; then return 0; fi\n'
        '    if [[ "$1" == -r && "$2" == *libwayland-cursor.so.0 ]]; then return 1; fi\n'
        '    if [[ "$1" == -r && "$2" == *libwayland-egl.so.1 ]]; then return 1; fi\n'
        '    if [[ "$1" == -x && "$2" == *ldconfig ]]; then return 1; fi\n'
        '    builtin [ "$@"\n'
        "}\n"
        "command() {\n"
        '    if [[ "$1" == -v && "$2" == ldconfig ]]; then return 1; fi\n'
        '    builtin command "$@"\n'
        "}\n"
    )
    (env, _), appdir = launch(BASH_ENV=str(bash_env), LD_LIBRARY_PATH="/custom/lib")
    assert env["LD_LIBRARY_PATH"] == (
        f"{appdir}/usr/lib:/custom/lib"
        f":{appdir}/usr/lib/fallback/wayland-cursor"
        f":{appdir}/usr/lib/fallback/wayland-egl"
    )


def test_host_wayland_libraries_are_not_shadowed(launch, tmp_path):
    """Leave fallback directories off LD_LIBRARY_PATH when host Wayland exists."""
    bash_env = tmp_path / "full-host-wayland.sh"
    bash_env.write_text(
        "function [() {\n"
        '    if [[ "$1" == -r && "$2" == *libwayland-* ]]; then return 0; fi\n'
        '    builtin [ "$@"\n'
        "}\n"
    )
    (env, _), appdir = launch(BASH_ENV=str(bash_env), LD_LIBRARY_PATH="/custom/lib")
    assert env["LD_LIBRARY_PATH"] == f"{appdir}/usr/lib:/custom/lib"


def test_gles_api_is_disabled_when_host_lacks_libglesv2(launch, tmp_path):
    """Disable GDK's GLES API when the host omits libGLESv2.so.2, preserving other flags."""
    bash_env = tmp_path / "no-host-glesv2.sh"
    bash_env.write_text(
        "function [() {\n"
        '    if [[ "$1" == -r && "$2" == *libGLESv2.so.2 ]]; then return 1; fi\n'
        '    if [[ "$1" == -x && "$2" == *ldconfig ]]; then return 1; fi\n'
        '    builtin [ "$@"\n'
        "}\n"
        "command() {\n"
        '    if [[ "$1" == -v && "$2" == ldconfig ]]; then return 1; fi\n'
        '    builtin command "$@"\n'
        "}\n"
    )
    (env, _), _appdir = launch(BASH_ENV=str(bash_env))
    assert env["GDK_DISABLE"] == "gles-api"

    (env_existing, _), _appdir = launch(BASH_ENV=str(bash_env), GDK_DISABLE="vulkan")
    assert env_existing["GDK_DISABLE"] == "vulkan,gles-api"

    (env_already, _), _appdir = launch(BASH_ENV=str(bash_env), GDK_DISABLE="vulkan,gles-api")
    assert env_already["GDK_DISABLE"] == "vulkan,gles-api"


def test_gles_api_is_kept_when_host_provides_libglesv2(launch, tmp_path):
    """Leave GDK_DISABLE untouched when host libGLESv2.so.2 is available."""
    bash_env = tmp_path / "with-host-glesv2.sh"
    bash_env.write_text(
        "function [() {\n"
        '    if [[ "$1" == -r && "$2" == *libGLESv2.so.2 ]]; then return 0; fi\n'
        '    builtin [ "$@"\n'
        "}\n"
    )
    (env, _), _appdir = launch(BASH_ENV=str(bash_env))
    assert "GDK_DISABLE" not in env


def test_spec_excludes_host_abi_libraries():
    """Keep host C++ runtime and Wayland libraries out of PyInstaller's _internal."""
    spec_text = (Path(__file__).resolve().parents[1] / "scripts/appimage/twinverse.spec.in").read_text()
    for lib in (
        "libstdc++.so.6",
        "libgcc_s.so.1",
        "libexpat.so.1",
        "libz.so.1",
        "libwayland-client.so.0",
        "libwayland-cursor.so.0",
        "libwayland-egl.so.1",
    ):
        assert lib in spec_text
