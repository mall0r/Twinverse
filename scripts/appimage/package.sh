#!/bin/bash
set -euo pipefail

cd /project
version=$(cat version)
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
appdir="$work/AppDir"
mkdir -p "$appdir/usr/bin" "$appdir/usr/share"

cp -a res "$work/res"
glib-compile-resources --target="$work/res/twinverse.gresource" \
    --sourcedir=res res/twinverse.gresources.xml
# One directory exposes every ELF for dependency and GLIBC auditing. A nested
# PyInstaller --onefile archive hides libraries from linuxdeploy and scanners.
export TWINVERSE_BUILD_DIR="$work"
cp scripts/appimage/twinverse.spec.in "$work/twinverse.spec"
pyinstaller --noconfirm --clean --distpath "$work/dist" --workpath "$work/build" \
    "$work/twinverse.spec"
cp -a "$work/dist/twinverse/." "$appdir/usr/bin/"
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
export OUTPUT="/project/Twinverse-$version-x86_64.AppImage"
export LINUXDEPLOY_OUTPUT_VERSION="$version" ARCH=x86_64
"$work/linuxdeploy.AppImage" --appdir "$appdir" --output appimage
test -s "$OUTPUT"
echo "Created $OUTPUT (requires glibc 2.35 or newer)."
