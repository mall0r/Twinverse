#!/bin/bash

# MultiScope Uninstallation Script
# This script removes the MultiScope executable and desktop entry.

set -e # Exit on any error

echo "🚀 Starting MultiScope Uninstallation..."

# --- Configuration ---
BINARY_NAME="multi-scope"
INSTALL_DIR="$HOME/.local/bin"
APP_NAME="MultiScope"
DESKTOP_FILE_NAME="multiscope.desktop"
DESKTOP_DIR="$HOME/.local/share/applications"

# --- 1. Remove the binary ---
if [ -f "$INSTALL_DIR/$BINARY_NAME" ]; then
    echo "🗑️ Removing executable from '$INSTALL_DIR'..."
    rm "$INSTALL_DIR/$BINARY_NAME"
    echo "✅ Executable removed."
else
    echo "ℹ️ Executable not found at '$INSTALL_DIR/$BINARY_NAME'. Skipping."
fi

# --- 2. Remove .desktop file ---
if [ -f "$DESKTOP_DIR/$DESKTOP_FILE_NAME" ]; then
    echo "🗑️ Removing desktop entry from '$DESKTOP_DIR'..."
    rm "$DESKTOP_DIR/$DESKTOP_FILE_NAME"
    echo "✅ Desktop entry removed."
else
    echo "ℹ️ Desktop entry not found. Skipping."
fi

# --- 3. Remove PATH configuration ---
echo "🔧 Checking shell configuration..."
SHELL_CONFIG_FILE=""
CURRENT_SHELL=$(basename "$SHELL")

if [ "$CURRENT_SHELL" = "bash" ]; then
    SHELL_CONFIG_FILE="$HOME/.bashrc"
elif [ "$CURRENT_SHELL" = "zsh" ]; then
    SHELL_CONFIG_FILE="$HOME/.zshrc"
fi

if [ -n "$SHELL_CONFIG_FILE" ] && [ -f "$SHELL_CONFIG_FILE" ]; then
    # Use sed to remove the block. -i modifies the file in place.
    # We match the comment and the export line.
    if grep -q "# Add MultiScope to PATH" "$SHELL_CONFIG_FILE"; then
        echo "   Removing PATH configuration from '$SHELL_CONFIG_FILE'..."
        sed -i '/# Add MultiScope to PATH/d' "$SHELL_CONFIG_FILE"
        sed -i '/export PATH="\$HOME\/.local\/bin:\$PATH"/d' "$SHELL_CONFIG_FILE"
        echo "✅ PATH configuration removed."
    else
        echo "ℹ️ PATH configuration not found in '$SHELL_CONFIG_FILE'. Skipping."
    fi
fi

# --- Final Instructions ---
echo ""
echo "🎉 MultiScope has been successfully uninstalled!"
echo ""
echo "‼️ Important Next Steps:"
echo "   1. Restart your shell for the PATH changes to take effect."
echo "   2. You may need to log out and log back in for '$APP_NAME' to be removed from your application menu."
echo ""
echo "✨ Uninstallation complete!"
