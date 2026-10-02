FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates curl git binutils patchelf file \
    python3-dev python3-venv python3-pip python3-mako python3-markdown \
    pkg-config ninja-build gettext flex bison sassc gobject-introspection \
    libgirepository1.0-dev libffi-dev libpcre2-dev libmount-dev libselinux1-dev \
    zlib1g-dev libxml2-dev libcairo2-dev libgdk-pixbuf-2.0-dev \
    libpango1.0-dev libharfbuzz-dev libfribidi-dev libepoxy-dev \
    libgraphene-1.0-dev libxkbcommon-dev libx11-dev libxext-dev libxi-dev \
    libxrandr-dev libxcursor-dev libxdamage-dev libxfixes-dev libxinerama-dev \
    libwayland-dev libegl1-mesa-dev libgl1-mesa-dev libvulkan-dev libdrm-dev \
    libjpeg-dev libpng-dev libtiff-dev shared-mime-info adwaita-icon-theme \
    libappstream-dev librsvg2-common desktop-file-utils squashfs-tools && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir meson==1.7.2 packaging

# Build the modern GNOME stack against glibc 2.35, rather than copying it
# from a rolling-release workstation. Keep the prefix out of the host system.
ENV PREFIX=/opt/twinverse
ENV PATH=/opt/twinverse/bin:$PATH
ENV LD_LIBRARY_PATH=/opt/twinverse/lib
ENV PKG_CONFIG_PATH=/opt/twinverse/lib/pkgconfig:/opt/twinverse/share/pkgconfig
ENV GI_TYPELIB_PATH=/opt/twinverse/lib/girepository-1.0
ENV XDG_DATA_DIRS=/opt/twinverse/share:/usr/local/share:/usr/share
COPY scripts/appimage/build-stack.sh /tmp/build-stack.sh
RUN bash /tmp/build-stack.sh
ENV GI_TYPELIB_PATH=/opt/twinverse/lib/girepository-1.0:/usr/lib/x86_64-linux-gnu/girepository-1.0
RUN python3 -m venv /opt/python && /opt/python/bin/pip install --no-cache-dir \
    pyinstaller==6.14.2 PyGObject==3.52.3 pycairo==1.28.0 \
    'pydantic>=2,<3' evdev pydbus screeninfo
ENV PATH=/opt/python/bin:$PATH
WORKDIR /project
CMD ["bash", "scripts/appimage/package.sh"]
