#!/bin/bash

cd "$(dirname "$0")"

# Compile GResource
echo "📦 Compiling GResource..."
glib-compile-resources \
  --target=res/twinverse.gresource \
  --sourcedir=res \
  res/twinverse.gresources.xml

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
