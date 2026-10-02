#!/bin/bash
set -euo pipefail

mkdir -p /tmp/gnome-build
cd /tmp/gnome-build
# CI has four cores; compiling serially there would exceed the job timeout.
JOBS=${JOBS:-$(nproc)}
build() {
    local name=$1 version=$2
    shift 2
    curl --fail --location --retry 3 \
        "https://download.gnome.org/sources/$name/${version%.*}/$name-$version.tar.xz" \
        -o "$name.tar.xz"
    tar -xf "$name.tar.xz"
    meson setup "$name-$version/build" "$name-$version" \
        --prefix="$PREFIX" --libdir=lib --buildtype=release --wrap-mode=nofallback "$@"
    ninja -C "$name-$version/build" -j"$JOBS"
    ninja -C "$name-$version/build" install
}

# Bootstrap introspection, then generate the GLib typelibs using the new scanner.
build glib 2.82.5 -Dintrospection=disabled -Dtests=false -Ddocumentation=false
build gobject-introspection 1.82.0 -Ddoctool=disabled
meson configure glib-2.82.5/build -Dintrospection=enabled
ninja -C glib-2.82.5/build -j"$JOBS"
ninja -C glib-2.82.5/build install

curl --fail --location --retry 3 \
    https://gitlab.freedesktop.org/wayland/wayland/-/releases/1.23.1/downloads/wayland-1.23.1.tar.xz \
    -o wayland.tar.xz
tar -xf wayland.tar.xz
meson setup wayland-1.23.1/build wayland-1.23.1 --prefix="$PREFIX" --libdir=lib \
    -Ddocumentation=false -Dtests=false
ninja -C wayland-1.23.1/build -j"$JOBS" install
curl --fail --location --retry 3 \
    https://gitlab.freedesktop.org/wayland/wayland-protocols/-/releases/1.36/downloads/wayland-protocols-1.36.tar.xz \
    -o protocols.tar.xz
tar -xf protocols.tar.xz
meson setup wayland-protocols-1.36/build wayland-protocols-1.36 --prefix="$PREFIX" -Dtests=false
ninja -C wayland-protocols-1.36/build install

curl --fail --location --retry 3 https://cairographics.org/releases/cairo-1.18.4.tar.xz -o cairo.tar.xz
tar -xf cairo.tar.xz
meson setup cairo-1.18.4/build cairo-1.18.4 --prefix="$PREFIX" --libdir=lib \
    -Dtests=disabled -Dgtk_doc=false
ninja -C cairo-1.18.4/build -j"$JOBS" install
curl --fail --location --retry 3 \
    https://github.com/harfbuzz/harfbuzz/releases/download/8.5.0/harfbuzz-8.5.0.tar.xz \
    -o harfbuzz.tar.xz
tar -xf harfbuzz.tar.xz
meson setup harfbuzz-8.5.0/build harfbuzz-8.5.0 --prefix="$PREFIX" --libdir=lib \
    --buildtype=release -Dtests=disabled -Ddocs=disabled -Dutilities=disabled \
    -Dgobject=enabled -Dintrospection=enabled
ninja -C harfbuzz-8.5.0/build -j"$JOBS" install
build pango 1.54.0 -Dbuild-testsuite=false -Dbuild-examples=false -Ddocumentation=false
build gtk 4.16.13 -Dbuild-tests=false -Dbuild-testsuite=false -Dbuild-examples=false \
    -Dbuild-demos=false -Dmedia-gstreamer=disabled -Dprint-cups=disabled \
    -Dvulkan=disabled -Ddocumentation=false -Dintrospection=enabled
build libadwaita 1.6.6 -Dtests=false -Dexamples=false -Dgtk_doc=false -Dvapi=false -Dintrospection=enabled
rm -rf /tmp/gnome-build
