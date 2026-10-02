#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Never reuse the workstation's .venv or native libraries for release builds.
ENGINE=${CONTAINER_ENGINE:-}
if [ -z "$ENGINE" ]; then
    for candidate in podman docker; do
        if command -v "$candidate" >/dev/null; then
            ENGINE=$candidate
            break
        fi
    done
fi
if [ -z "$ENGINE" ]; then
    echo "Install Podman or Docker, or set CONTAINER_ENGINE." >&2
    exit 1
fi
if [ "$(uname -m)" != x86_64 ]; then
    echo "The AppImage build currently requires an x86_64 host." >&2
    exit 1
fi

image=twinverse-appimage-builder:ubuntu22.04
"$ENGINE" build -t "$image" -f scripts/appimage/Dockerfile .
user_args=(--user "$(id -u):$(id -g)")
if [[ "$(basename "$ENGINE")" == podman ]]; then
    user_args+=(--userns=keep-id)
fi
"$ENGINE" run --rm "${user_args[@]}" \
    -e HOME=/tmp -v "$PROJECT_ROOT:/project:Z" "$image"
