#!/bin/bash
set -euo pipefail

cd /project
version=$(cat version)
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z]+(\.[0-9A-Za-z]+)*)?$ ]]
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
appdir="$work/AppDir"
mkdir -p "$appdir/usr/bin" "$appdir/usr/share"

cp -a res "$work/res"
rm -rf "$work/res/native"
CARGO_TARGET_DIR="$work/native-target" OUT_DIR="$work/res/native" bash scripts/build-native.sh
glib-compile-resources --target="$work/res/twinverse.gresource" \
    --sourcedir=res res/twinverse.gresources.xml
# A window-only smoke test misses icons that stay white in light mode. Test
# the exact GTK stack and resources being packaged, with real pixel output.
rustc --edition=2021 -O scripts/appimage/check-appearance.rs -o "$work/check-appearance" \
    $(pkg-config --libs gtk4)
xvfb-run -a env GDK_BACKEND=x11 "$work/check-appearance" "$work/res/twinverse.gresource"
# One directory exposes every ELF for dependency and GLIBC auditing. A nested
# PyInstaller --onefile archive hides libraries from linuxdeploy and scanners.
export TWINVERSE_BUILD_DIR="$work"
cp scripts/appimage/twinverse.spec.in "$work/twinverse.spec"
pyinstaller --noconfirm --clean --distpath "$work/dist" --workpath "$work/build" \
    "$work/twinverse.spec"
cp -a "$work/dist/twinverse/." "$appdir/usr/bin/"
for forbidden in \
    libstdc++.so.6 libgcc_s.so.1 libexpat.so.1 libz.so.1 \
    libwayland-client.so.0 libwayland-cursor.so.0 libwayland-egl.so.1
do
    if [ -e "$appdir/usr/bin/_internal/$forbidden" ]; then
        echo "Forbidden host-ABI library found in _internal: $forbidden" >&2
        exit 1
    fi
done
# Stage Wayland libraries in per-library fallback directories outside _internal.
# AppRun only appends a fallback directory when the host does not provide that
# library, preventing older bundled Wayland copies from shadowing host Mesa/EGL.
install -Dm644 /opt/twinverse/lib/libwayland-client.so.0 \
    "$appdir/usr/lib/fallback/wayland-client/libwayland-client.so.0"
install -Dm644 /opt/twinverse/lib/libwayland-cursor.so.0 \
    "$appdir/usr/lib/fallback/wayland-cursor/libwayland-cursor.so.0"
install -Dm644 /opt/twinverse/lib/libwayland-egl.so.1 \
    "$appdir/usr/lib/fallback/wayland-egl/libwayland-egl.so.1"
cp scripts/appimage/AppRun "$appdir/AppRun"
chmod +x "$appdir/AppRun"
app_id=io.github.mall0r.Twinverse
install -Dm644 "share/applications/$app_id.desktop" "$appdir/$app_id.desktop"
install -Dm644 "share/icons/hicolor/scalable/apps/$app_id.svg" "$appdir/$app_id.svg"
install -Dm644 "share/metainfo/$app_id.metainfo.xml" "$appdir/usr/share/metainfo/$app_id.metainfo.xml"
cp -a /usr/share/icons "$appdir/usr/share/"
cp -a /usr/share/mime "$appdir/usr/share/"

curl --fail --location --retry 3 \
    https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage \
    -o "$work/linuxdeploy.AppImage"
chmod +x "$work/linuxdeploy.AppImage"
export APPIMAGE_EXTRACT_AND_RUN=1 NO_STRIP=1
"$work/linuxdeploy.AppImage" --appdir "$appdir" \
    --desktop-file "share/applications/$app_id.desktop" \
    --icon-file "share/icons/hicolor/scalable/apps/$app_id.svg"
python3 scripts/appimage/check-glibc.py "$appdir" 2.35
export OUTPUT="${OUTPUT:-/project/Twinverse-$version-x86_64.AppImage}"
export LINUXDEPLOY_OUTPUT_VERSION="$version" ARCH=x86_64
# Resolve the latest stable release without hard-coding a versioned asset URL.
export LDAI_UPDATE_INFORMATION='gh-releases-zsync|mall0r|Twinverse|latest|Twinverse-*-x86_64.AppImage.zsync'
# appimagetool writes the zsync beside its working directory, even when OUTPUT
# is absolute. Keep both artifacts together when a separate output is requested.
(
    cd "$(dirname "$OUTPUT")"
    "$work/linuxdeploy.AppImage" --appdir "$appdir" --output appimage
)
test -s "$OUTPUT"
test -s "$OUTPUT.zsync"
if [[ "$(env -u APPIMAGE_EXTRACT_AND_RUN "$OUTPUT" --appimage-updateinformation)" != "$LDAI_UPDATE_INFORMATION" ]]; then
    echo "AppImage update information is missing or incorrect." >&2
    exit 1
fi
echo "Created $OUTPUT (requires glibc 2.35 or newer)."
echo "Publish $OUTPUT.zsync alongside the AppImage on the GitHub release."
