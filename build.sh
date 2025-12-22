#!/bin/bash

# MultiScope PyInstaller Build Script
# This script compiles the MultiScope project into a standalone executable

set -e  # Exit on any error

echo "🚀 Starting MultiScope Build Process..."

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Install PyInstaller if not present
if ! pip show pyinstaller >/dev/null 2>&1; then
    echo "📦 Installing PyInstaller..."
    pip install pyinstaller
fi

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build/ dist/ *.spec

# Create PyInstaller spec file
echo "📝 Creating PyInstaller spec file..."
cat > multiscope.spec << 'EOF'
# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

# Get the project root directory
project_root = Path.cwd()

# Define paths
src_path = project_root / 'src'
gui_path = src_path / 'gui'
scripts_path = project_root / 'scripts'

# Collect all CSS files from the gui directory
css_files = []
if gui_path.exists():
    for css_file in gui_path.glob('style.css'):
        css_files.append((str(css_file), 'src/gui'))

# Collect all JS scripts from the scripts directory
js_files = []
if scripts_path.exists():
    for js_file in scripts_path.glob('*.js'):
        js_files.append((str(js_file), 'scripts'))

# Collect other resource files if needed
data_files = css_files + js_files

# Add hidden imports for PyInstaller
hidden_imports = [
    'gi',
    'gi.repository',
    'gi.repository.Gtk',
    'gi.repository.Adw',
    'gi.repository.Gdk',
    'gi.repository.GLib',
    'gi.repository.Gio',
    'pydantic',
    'cairo'
]

block_cipher = None

a = Analysis(
    ['multiscope.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=data_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='multiscope',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
EOF

# Build with PyInstaller
echo "🔨 Building executable with PyInstaller..."
pyinstaller multiscope.spec --clean --noconfirm

# Check if build was successful
if [ -f "dist/multiscope" ]; then
    echo "✅ Build successful!"
    echo "📁 Executable created at: dist/multiscope"
    echo "📏 File size: $(du -h dist/multiscope | cut -f1)"

    # Make executable
    chmod +x dist/multiscope

    echo ""
    echo "🎉 MultiScope has been successfully compiled!"
    echo ""
    echo "To run the compiled version:"
    echo "  ./dist/multiscope"
    echo ""
    echo "To open GUI:"
    echo "  ./dist/multiscope gui"
    echo ""
    echo "To run a profile:"
    echo "  ./dist/multiscope <profile_name>"
    echo ""

else
    echo "❌ Build failed! Check the output above for errors."
    exit 1
fi
