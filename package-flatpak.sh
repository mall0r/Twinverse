#!/bin/bash

# MultiScope Flatpak Packaging Script
set -e

echo "📦 Starting MultiScope Flatpak packaging..."

APP_ID="io.github.mallor.MultiScope"
REPO_DIR="flatpak-repo"
BUNDLE_NAME="MultiScope.flatpak"

# Build first if needed
if [ ! -d "build-dir" ]; then
    echo "🔨 Building application first..."
    ./build-flatpak.sh
fi

# Create repository if it doesn't exist
if [ ! -d "$REPO_DIR" ]; then
    echo "📁 Creating flatpak repository..."
    ostree init --mode=archive-z2 --repo="$REPO_DIR"
fi

# Export to repository
echo "📤 Exporting to repository..."
flatpak-builder --force-clean --repo="$REPO_DIR" build-dir "$APP_ID.yaml"

# Create single-file bundle
echo "📦 Creating flatpak bundle..."
flatpak build-bundle "$REPO_DIR" "$BUNDLE_NAME" "$APP_ID"

# Get bundle size
BUNDLE_SIZE=$(du -h "$BUNDLE_NAME" | cut -f1)

echo ""
echo "✅ Flatpak package created successfully!"
echo "📦 File: $BUNDLE_NAME"
echo "📏 Size: $BUNDLE_SIZE"
echo ""
echo "🚀 Distribution instructions:"
echo ""
echo "To install on any system:"
echo "  flatpak install $BUNDLE_NAME"
echo ""
echo "To install without system prompts:"
echo "  flatpak install --user $BUNDLE_NAME"
echo ""
echo "To run after installation:"
echo "  flatpak run $APP_ID"
echo ""
echo "To uninstall:"
echo "  flatpak uninstall $APP_ID"
echo ""
echo "📤 To publish to Flathub:"
echo "  1. Fork https://github.com/flathub/flathub"
echo "  2. Add your manifest: $APP_ID.yaml"
echo "  3. Submit pull request"
echo ""
