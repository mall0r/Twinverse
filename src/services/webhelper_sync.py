"""Synchronize webhelper startup with its client's controller shared memory."""

import os
from pathlib import Path

from src.core import Config, Utils

# These names were observed in the current Linux Steam client. If Valve changes
# them, the bounded wait falls back to the original launcher and reports it.
WEBHELPER_GATE = r"""#!/bin/bash
# BASH_ENV runs before non-interactive Bash scripts. Only gate Steam's UI.
if [[ -n ${TWINVERSE_ORIGINAL_BASH_ENV:-} && "$TWINVERSE_ORIGINAL_BASH_ENV" != "$BASH_ENV" ]]; then
    source "$TWINVERSE_ORIGINAL_BASH_ENV"
fi
case "$0" in
    */steamwebhelper.sh|steamwebhelper.sh) ;;
    *) return 0 ;;
esac
tv_pid=
for tv_arg in "$@"; do
    case "$tv_arg" in
        -steampid=*) tv_pid=${tv_arg#-steampid=} ;;
    esac
done
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
                    # Bash compares device and inode directly, without spawning
                    # readlink/stat for every descriptor. Stale handles fail.
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
        # the shared log directory is mounted at a fixed path instead.
        log_name = f"overlay_focus_instance_{instance_num}.log"
        gate += f"""
if [[ "$tv_pid" =~ ^[0-9]+$ && -d /proc/$tv_pid ]]; then
    python3 /tmp/twinverse-webhelper/overlay_focus.py "$tv_pid" \\
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
