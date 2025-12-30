#!/bin/bash

# MultiScope Flatpak Build Script
set -e

echo "🚀 Starting MultiScope Flatpak build..."

# Check if flatpak-builder is installed
if ! command -v flatpak-builder &> /dev/null; then
    echo "❌ flatpak-builder is not installed!"
    echo "Install it with: sudo apt install flatpak-builder (Debian/Ubuntu)"
    echo "                 sudo dnf install flatpak-builder (Fedora)"
    exit 1
fi

# Check if required runtimes are installed
echo "🔍 Checking for required Flatpak runtimes..."
if ! flatpak list --runtime | grep -q "org.gnome.Platform.*48"; then
    echo "📦 Installing GNOME Platform runtime..."
    flatpak install -y flathub org.gnome.Platform//48 org.gnome.Sdk//48
fi

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build-dir .flatpak-builder

# Build the Flatpak
echo "🔨 Building Flatpak..."
flatpak-builder --force-clean --install-deps-from=flathub \
    build-dir io.github.mallor.MultiScope.yaml

# Test the build
echo "✅ Build complete! Testing..."
flatpak-builder --run build-dir io.github.mallor.MultiScope.yaml multiscope --help

echo ""
echo "🎉 Flatpak build successful!"
echo ""
echo "To test the application:"
echo "  flatpak-builder --run build-dir io.github.mallor.MultiScope.yaml multiscope"
echo ""
echo "To install locally:"
echo "  flatpak-builder --user --install --force-clean build-dir io.github.mallor.MultiScope.yaml"
echo ""
echo "To create a bundle for distribution:"
echo "  ./package-flatpak.sh"
echo ""
