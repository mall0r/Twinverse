#!/bin/bash

cd "$(dirname "$0")"

# Compile GResource
echo "📦 Compiling GResource..."
glib-compile-resources \
  --target=res/twinverse.gresource \
  --sourcedir=res \
  res/twinverse.gresources.xml

# Build native Rust virtual uinput libraries & hotplug bridge if missing
if [ ! -f "res/native/lib64/libtwinverse_uinput.so" ] || \
   [ ! -f "res/native/lib64/libtwinverse_udev.so" ] || \
   [ ! -f "res/native/lib32/libtwinverse_uinput.so" ] || \
   [ ! -f "res/native/lib32/libtwinverse_udev.so" ] || \
   [ ! -x "res/native/bin/twinverse-input-bridge" ]; then
    echo "🦀 Building native virtual uinput libraries..."
    if ! ./scripts/build-native.sh; then
        echo "⚠️  Could not build native virtual uinput libraries; continuing with Steam Input fallback." >&2
    fi
fi

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install .

# Run application
echo "🚀 Running application..."
python3 twinverse.py "$@"
