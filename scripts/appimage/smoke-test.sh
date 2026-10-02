#!/bin/bash
set -euo pipefail

appimage=$(readlink -f "${1:?Usage: smoke-test.sh Twinverse.AppImage}")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# A fresh HOME avoids an existing profile, session bus owner or host settings
# making a broken release appear to start successfully.
mkdir -p "$work/home"
export HOME="$work/home" XDG_CONFIG_HOME="$work/home/.config"
export XDG_DATA_HOME="$work/home/.local/share" XDG_CACHE_HOME="$work/home/.cache"
export GDK_BACKEND=x11 LIBGL_ALWAYS_SOFTWARE=1
export APPIMAGE_EXTRACT_AND_RUN=1
if [ ! -x "$appimage" ]; then
    chmod +x "$appimage"
fi
dbus-run-session -- xvfb-run -a bash -s -- "$appimage" "$work" <<'TEST'
set -euo pipefail
"$1" >"$2/startup.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; cat "$2/startup.log"' EXIT
for attempt in $(seq 1 60); do
    if ! kill -0 "$pid" 2>/dev/null; then
        echo "AppImage exited before showing a window" >&2
        exit 1
    fi
    if xdotool search --onlyvisible --name 'Twinverse' >/dev/null 2>&1; then
        sleep 15
        kill -0 "$pid"
        xdotool search --onlyvisible --name 'Twinverse'
        echo "AppImage window opened and remained visible for 15 seconds."
        exit 0
    fi
    sleep 1
done
echo "No visible Twinverse window within 60 seconds" >&2
exit 1
TEST
