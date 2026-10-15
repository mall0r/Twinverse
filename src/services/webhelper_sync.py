"""Gate Steam's UI startup and start the helpers that Steam's own scripts miss."""

import os
from pathlib import Path

from src.core import Config, Utils

# These names were observed in the current Linux Steam client. If Valve changes
# them, the bounded wait falls back to the original launcher and reports it.
WEBHELPER_GATE = r"""#!/bin/bash
# BASH_ENV runs before non-interactive Bash scripts.
if [[ -n ${TWINVERSE_ORIGINAL_BASH_ENV:-} && "$TWINVERSE_ORIGINAL_BASH_ENV" != "$BASH_ENV" ]]; then
    source "$TWINVERSE_ORIGINAL_BASH_ENV"
fi
tv_ui=0
tv_session=
case "$0" in
    */steamwebhelper.sh|steamwebhelper.sh) tv_ui=1 ;;
    # Steam's SteamRT3 client starts steamwebhelper without a shell wrapper, so
    # the launcher is the only script Bash runs in every client layout. It also
    # parents the client in both, so it anchors the whole Steam session.
    */steam.sh|steam.sh) tv_session=$$ ;;
    *) return 0 ;;
esac
tv_pid=
for tv_arg in "$@"; do
    case "$tv_arg" in
        -steampid=*) tv_pid=${tv_arg#-steampid=} ;;
    esac
done
if [[ -n "$tv_pid" ]]; then
    tv_session=$tv_pid
fi
# The launcher only anchors the repair; gating Steam's UI waits for a client.
if (( tv_ui )); then
    tv_ready=0
    tv_started=$SECONDS
    tv_uid=$UID
    case "$tv_pid" in
        ''|*[!0-9]*) ;;
        *)
            while (( SECONDS - tv_started < 20 )) && [[ -d /proc/$tv_pid ]]; do
                tv_count=0
                for tv_hash in c9edbd50 fe20b6d7 671c2a99; do
                    tv_path="/dev/shm/u${tv_uid}-Shm_$tv_hash"
                    [[ -e "$tv_path" ]] || continue
                    for tv_fd in /proc/"$tv_pid"/fd/*; do
                        # Bash compares device and inode directly, without
                        # spawning readlink/stat for every descriptor.
                        # Stale handles fail.
                        [[ "$tv_fd" -ef "$tv_path" ]] || continue
                        ((tv_count+=1))
                        break
                    done
                done
                if (( tv_count == 3 )); then
                    tv_ready=1
                    break
                fi
                sleep 0.1
            done
            ;;
    esac
    if (( tv_ready )); then
        echo "Twinverse: Steam $tv_pid controller shared memory ready after $((SECONDS-tv_started))s" >&2
    else
        echo "Twinverse: controller shared memory wait expired or Steam PID unavailable; starting UI normally" >&2
    fi
fi
# Bash now continues with the unmodified Steam launcher and its original args.
"""


def build_webhelper_mounts(home_path: Path, instance_num: int, fix_overlay_focus: bool = False) -> list[str]:
    """Install a Bash startup hook without overlaying Steam-managed files."""
    relative_script = Path(".local/share/Steam/ubuntu12_64/steamwebhelper.sh")
    original = home_path / relative_script
    if not original.is_file() and not fix_overlay_focus:
        # A fresh Steam installation may not have downloaded its UI yet.
        return []

    cache = Config.CACHE_DIR / "steam-webhelper" / f"instance_{instance_num + 1}"
    cache.mkdir(parents=True, exist_ok=True)
    wrapper = cache / "gate.sh"
    gate = WEBHELPER_GATE
    mounts = [
        "--ro-bind",
        str(cache),
        "/tmp/twinverse-webhelper",
        "--setenv",
        "BASH_ENV",
        "/tmp/twinverse-webhelper/gate.sh",
    ]
    if fix_overlay_focus:
        helper = Utils.get_base_path() / "res/steam/overlay_focus.py"
        (cache / "overlay_focus.py").write_text(helper.read_text())
        # The repair runs on the host inside the sandbox, so it needs only the
        # host Python. The instance home shadows the real home directory, so
        # the shared log directory is mounted at a fixed path instead. Its name
        # carries the same instance number as the cache directory above.
        log_name = f"overlay_focus_instance_{instance_num + 1}.log"
        # Either script can start it and the helper deduplicates itself, so a
        # client layout that skips one launcher still gets the repair.
        gate += f"""
if [[ "$tv_session" =~ ^[0-9]+$ ]] && [[ -d /proc/$tv_session ]]; then
    python3 /tmp/twinverse-webhelper/overlay_focus.py "$tv_session" \\
        </dev/null >>/tmp/twinverse-logs/{log_name} 2>&1 &
fi
"""
        log_dir = Config.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        mounts.extend(["--bind", str(log_dir), "/tmp/twinverse-logs"])
    wrapper.write_text(gate)
    wrapper.chmod(0o755)
    if os.environ.get("BASH_ENV"):
        mounts.extend(["--setenv", "TWINVERSE_ORIGINAL_BASH_ENV", os.environ["BASH_ENV"]])
    return mounts
