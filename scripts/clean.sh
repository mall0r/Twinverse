#!/bin/bash
set -e

# Get the directory where the script is located and go to project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "═══════════════════════════════════════════════════════════"
echo "  🧹 Cleaning up..."
echo "═══════════════════════════════════════════════════════════"
echo ""

# Passo 1: Stop processes
echo "1️⃣  Stoping processes..."
pkill -9 -f twinverse 2>/dev/null || true
pkill -9 -f gamescope 2>/dev/null || true
pkill -9 -f wine 2>/dev/null || true
sleep 1
echo "   ✅ Processes stopped"

# Passo 2: Cleaning cache
echo "2️⃣  Cleaning cache..."
find . -type d -name "__pycache__" -exec rm -rf {} \; 2>/dev/null || true
find . -type d -name "*.egg-info" -exec rm -rf {} \; 2>/dev/null || true
rm -rf .pytest_cache .mypy_cache
sleep 1
echo "   ✅ Cache cleaned"

# Passo 3: Cleaning files build
echo "3️⃣  Cleaning files build..."
rm -rf build dist AppDir *.AppDir .venv squashfs-root build-dir
rm -rf builddir repo flatpak-repo .flatpak-builder
rm -rf *.spec
rm -rf linuxdeploy-plugin-gtk.sh
rm -rf *.AppImage
rm -rf *.log
rm -rf *.flatpak
sleep 1
echo "   ✅ Files cleaned"

# Passo 4: Finalizing
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ CLEANED!"
echo "═══════════════════════════════════════════════════════════"
