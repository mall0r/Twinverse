#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NATIVE_DIR="$PROJECT_ROOT/native"
TARGET_DIR="${CARGO_TARGET_DIR:-$NATIVE_DIR/target}"
OUT_DIR="${OUT_DIR:-$PROJECT_ROOT/res/native}"
UDEV_SYM="$NATIVE_DIR/twinverse-udev-shim/libudev.sym"

# Locate a cargo/rustc pair that supports i686-unknown-linux-gnu if available.
has_i686_std() {
    local rustc_bin="$1"
    local sysroot
    sysroot="$("$rustc_bin" --print sysroot 2>/dev/null || true)"
    [ -n "$sysroot" ] && [ -d "$sysroot/lib/rustlib/i686-unknown-linux-gnu/lib" ]
}

select_toolchain() {
    local candidates=()

    if [ -n "${CARGO:-}" ] && [ -n "${RUSTC:-}" ]; then
        candidates+=("$(dirname "$CARGO")")
    fi
    if command -v cargo >/dev/null 2>&1; then
        candidates+=("$(dirname "$(command -v cargo)")")
    fi
    if [ -d "/usr/lib/sdk/rust-stable/bin" ]; then
        candidates+=("/usr/lib/sdk/rust-stable/bin")
    fi
    if [ -d "$HOME/.cargo/bin" ]; then
        candidates+=("$HOME/.cargo/bin")
    fi
    for ext in "$HOME"/.local/share/flatpak/runtime/org.freedesktop.Sdk.Extension.rust-stable/x86_64/*/active/files/bin \
               /var/lib/flatpak/runtime/org.freedesktop.Sdk.Extension.rust-stable/x86_64/*/active/files/bin; do
        if [ -d "$ext" ]; then
            candidates+=("$ext")
        fi
    done

    local fallback_dir=""
    for dir in "${candidates[@]}"; do
        if [ -x "$dir/cargo" ] && [ -x "$dir/rustc" ]; then
            if [ -z "$fallback_dir" ]; then
                fallback_dir="$dir"
            fi
            if has_i686_std "$dir/rustc"; then
                TOOLCHAIN_BIN="$dir"
                HAS_I686_TARGET=1
                return 0
            fi
        fi
    done

    if [ -n "$fallback_dir" ]; then
        TOOLCHAIN_BIN="$fallback_dir"
        HAS_I686_TARGET=0
        return 0
    fi

    echo "ERROR: No Rust toolchain (cargo/rustc) found." >&2
    exit 1
}

select_c_linkers() {
    CC64="${CC64:-${CC:-gcc}}"
    CC64_ARCH_FLAG="-m64"

    if [ -n "${CC32:-}" ]; then
        CC32_ARCH_FLAG=""
    elif [ -x "/usr/lib/sdk/toolchain-i386/bin/i686-unknown-linux-gnu-gcc" ]; then
        # Flatpak SDK (org.freedesktop.Sdk.Extension.toolchain-i386 + Compat.i386)
        export PATH="/usr/lib/sdk/toolchain-i386/bin:$PATH"
        CC32="/usr/lib/sdk/toolchain-i386/bin/i686-unknown-linux-gnu-gcc"
        CC32_ARCH_FLAG=""
    elif command -v i686-unknown-linux-gnu-gcc >/dev/null 2>&1; then
        CC32="$(command -v i686-unknown-linux-gnu-gcc)"
        CC32_ARCH_FLAG=""
    else
        CC32="${CC:-gcc}"
        CC32_ARCH_FLAG="-m32"
    fi
}

# Detect portable linker flags per emulation so newer toolchains (glibc 2.41+ /
# binutils 2.43+) do not emit GLIBC_ABI_GNU_TLS / GLIBC_ABI_DT_RELR tags that
# fail to load on older hosts (e.g., Flatpak -> flatpak-spawn --host on Ubuntu 22.04).
probe_ld_flags() {
    local cc_bin="$1"
    local arch_flag="$2"
    local -a arch_arr=()
    if [ -n "$arch_flag" ]; then
        arch_arr+=("$arch_flag")
    fi
    local flag
    local out_flags=""

    for flag in "-Wl,--no-gnu-tls-tag" "-Wl,--no-gnu2-tls-tag" "-Wl,-z,nopack-relative-relocs"; do
        if printf 'int x;\n' | "$cc_bin" "${arch_arr[@]}" -x c -shared "$flag" -o /dev/null - 2>/dev/null; then
            out_flags+=" $flag"
        fi
    done
    printf '%s' "$out_flags"
}

link_udev_so() {
    local cc_bin="$1"
    local arch_flag="$2"
    local static_lib="$3"
    local out_so="$4"
    local extra_flags="$5"
    local -a arch_arr=()
    if [ -n "$arch_flag" ]; then
        arch_arr+=("$arch_flag")
    fi
    local -a compat_arr=()
    if [ -n "$extra_flags" ]; then
        read -r -a compat_arr <<< "$extra_flags"
    fi

    "$cc_bin" "${arch_arr[@]}" -shared \
        "${compat_arr[@]}" \
        -Wl,--whole-archive "$static_lib" -Wl,--no-whole-archive \
        -Wl,-soname,libudev.so.1 \
        -Wl,--version-script="$UDEV_SYM" \
        -Wl,--gc-sections \
        -Wl,-z,relro,-z,now \
        -Wl,-O1 \
        -Wl,--strip-all \
        -Wl,--as-needed \
        -ldl -lpthread -lm -lc \
        -o "$out_so"
}

to_rustflags() {
    local flags="$1"
    local out=""
    local f
    for f in $flags; do
        out+=" -C link-arg=$f"
    done
    printf '%s' "$out"
}

TOOLCHAIN_BIN=""
HAS_I686_TARGET=0
select_toolchain

CC64=""
CC64_ARCH_FLAG=""
CC32=""
CC32_ARCH_FLAG=""
select_c_linkers

CARGO_BIN="$TOOLCHAIN_BIN/cargo"
RUSTC_BIN="$TOOLCHAIN_BIN/rustc"

export PATH="$TOOLCHAIN_BIN:$PATH"
export RUSTC="$RUSTC_BIN"
export CARGO_TARGET_DIR="$TARGET_DIR"

echo "[build-native] Using rustc: $("$RUSTC_BIN" --version) ($TOOLCHAIN_BIN)"

if [ "${1:-}" = "--test" ]; then
    "$CARGO_BIN" test --manifest-path "$NATIVE_DIR/Cargo.toml" --offline
    exit 0
fi

COMPAT64_LD="$(probe_ld_flags "$CC64" "$CC64_ARCH_FLAG")"
COMPAT64_RUST="$(to_rustflags "$COMPAT64_LD")"

# Build 64-bit libraries + host hotplug bridge binary
echo "[build-native] Building x86_64-unknown-linux-gnu (linker: $CC64)..."
CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER="${CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER:-$CC64}" \
CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS="${CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS:-}$COMPAT64_RUST" \
"$CARGO_BIN" build \
    --manifest-path "$NATIVE_DIR/Cargo.toml" \
    --release \
    --offline \
    --target x86_64-unknown-linux-gnu

mkdir -p "$OUT_DIR/lib64" "$OUT_DIR/bin"
cp -f "$TARGET_DIR/x86_64-unknown-linux-gnu/release/libtwinverse_uinput.so" "$OUT_DIR/lib64/"
cp -f "$TARGET_DIR/x86_64-unknown-linux-gnu/release/twinverse-input-bridge" "$OUT_DIR/bin/"
chmod +x "$OUT_DIR/bin/twinverse-input-bridge"
link_udev_so "$CC64" "$CC64_ARCH_FLAG" \
    "$TARGET_DIR/x86_64-unknown-linux-gnu/release/libtwinverse_udev.a" \
    "$OUT_DIR/lib64/libtwinverse_udev.so" \
    "$COMPAT64_LD"

# Build 32-bit libraries (needed for 32-bit Steam client & 32-bit games)
if [ "${SKIP_32BIT:-0}" = "1" ]; then
    echo "[build-native] SKIP_32BIT=1 set; skipping i686-unknown-linux-gnu."
    exit 0
fi

if [ "$HAS_I686_TARGET" -ne 1 ]; then
    echo "ERROR: Rust target i686-unknown-linux-gnu is not installed for $RUSTC_BIN." >&2
    echo "Install it via: rustup target add i686-unknown-linux-gnu" >&2
    exit 1
fi

COMPAT32_LD="$(probe_ld_flags "$CC32" "$CC32_ARCH_FLAG")"
COMPAT32_RUST="$(to_rustflags "$COMPAT32_LD")"
DEFAULT_RUSTFLAGS_32=""
if [ -n "$CC32_ARCH_FLAG" ]; then
    DEFAULT_RUSTFLAGS_32="-C link-arg=$CC32_ARCH_FLAG"
fi

export CARGO_TARGET_I686_UNKNOWN_LINUX_GNU_LINKER="${CARGO_TARGET_I686_UNKNOWN_LINUX_GNU_LINKER:-$CC32}"
export CARGO_TARGET_I686_UNKNOWN_LINUX_GNU_RUSTFLAGS="${CARGO_TARGET_I686_UNKNOWN_LINUX_GNU_RUSTFLAGS:-$DEFAULT_RUSTFLAGS_32}$COMPAT32_RUST"

echo "[build-native] Building i686-unknown-linux-gnu (linker: $CC32 ${CC32_ARCH_FLAG})..."
"$CARGO_BIN" build \
    --manifest-path "$NATIVE_DIR/Cargo.toml" \
    --release \
    --offline \
    --package twinverse-uinput-interposer \
    --package twinverse-udev-shim \
    --target i686-unknown-linux-gnu

mkdir -p "$OUT_DIR/lib32"
cp -f "$TARGET_DIR/i686-unknown-linux-gnu/release/libtwinverse_uinput.so" "$OUT_DIR/lib32/"
link_udev_so "$CC32" "$CC32_ARCH_FLAG" \
    "$TARGET_DIR/i686-unknown-linux-gnu/release/libtwinverse_udev.a" \
    "$OUT_DIR/lib32/libtwinverse_udev.so" \
    "$COMPAT32_LD"

echo "[build-native] Built native libraries and bridge in $OUT_DIR:"
ls -lh "$OUT_DIR/lib64" "$OUT_DIR/lib32" "$OUT_DIR/bin"
