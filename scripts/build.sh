#!/bin/bash

# Twinverse PyInstaller Build Script
# This script compiles the Twinverse project into a standalone executable

set -e  # Exit on any error

echo "🚀 Starting Twinverse Build Process..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
fi

echo "🔧 Activating virtual environment..."
source .venv/bin/activate

echo "📥 Installing dependencies..."
pip install .

echo "📦 Compiling GResource..."
glib-compile-resources \
  --target=res/twinverse.gresource \
  --sourcedir=res \
  res/twinverse.gresources.xml

if ! pip show pyinstaller >/dev/null 2>&1; then
    echo "📦 Installing PyInstaller..."
    pip install pyinstaller
fi

echo "🧹 Cleaning previous builds..."
rm -rf build/ dist/ *.spec

echo "🔍 Detecting GTK libraries..."
GTK_LIBDIR=$(pkg-config --variable=libdir gtk4 2>/dev/null || echo "/usr/lib/x86_64-linux-gnu")
GI_TYPELIB_PATH=$(pkg-config --variable=typelibdir gobject-introspection-1.0 2>/dev/null || echo "/usr/lib/x86_64-linux-gnu/girepository-1.0")

echo "   GTK Library Path: $GTK_LIBDIR"
echo "   GI Typelib Path: $GI_TYPELIB_PATH"

echo "📝 Creating PyInstaller spec file..."
cat > twinverse.spec << 'EOF'
# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path
import subprocess

project_root = Path.cwd()

src_path = project_root / 'src'
gui_path = src_path / 'gui'
scripts_path = project_root / 'scripts'

src_files = []
for src_file in (project_root / 'src').rglob('*'):
    if src_file.is_file():
        src_files.append((str(src_file), 'src'))

res_files = []
for res_file in (project_root / 'res').rglob('*'):
    if res_file.is_file():
        rel_path = res_file.relative_to(project_root / 'res')
        res_files.append((str(res_file), f'res/{rel_path.parent}'))

data_files = src_files + res_files

hidden_imports = [
    'gi',
    'gi.repository',
    'gi.repository.Gtk',
    'gi.repository.Gsk',
    'gi.repository.Graphene',
    'gi.repository.Adw',
    'gi.repository.Gdk',
    'gi.repository.GLib',
    'gi.repository.Gio',
    'gi.repository.GObject',
    'gi.repository.GdkPixbuf',
    'gi.repository.Pango',
    'gi.repository.PangoCairo',
    'gi.repository.PangoFT2',
    'pydantic',
    'cairo',
    'evdev',
    'pydbus',
    'screeninfo'
]

block_cipher = None

a = Analysis(
    ['twinverse.py'],
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
    name='twinverse',
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

echo "🔨 Building executable with PyInstaller..."
pyinstaller twinverse.spec --clean --noconfirm

if [ -f "dist/twinverse" ]; then
    echo "✅ Build successful!"
    echo "📁 Executable created at: dist/twinverse"
    echo "📏 File size: $(du -h dist/twinverse | cut -f1)"

    chmod +x dist/twinverse

    echo ""
    echo "🎉 Twinverse has been successfully compiled!"
    echo ""
    echo "To run the compiled version:"
    echo "  ./dist/twinverse"
    echo ""
    echo "To open GUI:"
    echo "  ./dist/twinverse gui"
    echo ""
    echo "To run a profile:"
    echo "  ./dist/twinverse <profile_name>"
    echo ""

else
    echo "❌ Build failed! Check the output above for errors."
    exit 1
fi
