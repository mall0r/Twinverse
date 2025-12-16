#!/bin/bash

# MultiScope Installation Script
# This script installs the MultiScope executable and creates a desktop entry.

set -e # Exit on any error

echo "🚀 Starting MultiScope Installation..."

# --- Configuration ---
BINARY_NAME="multiscope"
SOURCE_DIR="dist"
INSTALL_DIR="$HOME/.local/bin"
APP_NAME="MultiScope"
DESKTOP_FILE_NAME="multiscope.desktop"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons"

# --- 1. Verify that the binary exists ---
if [ ! -f "$SOURCE_DIR/$BINARY_NAME" ]; then
    echo "❌ Error: Executable not found at '$SOURCE_DIR/$BINARY_NAME'."
    echo "   Please run the build script (./build.sh) before installing."
    exit 1
fi
echo "✅ Verified executable exists."

# --- 2. Create installation directory ---
echo "🔧 Ensuring installation directory exists at '$INSTALL_DIR'"
mkdir -p "$INSTALL_DIR"
echo "✅ Directory created or already exists."

# --- 3. Copy the binary ---
echo "📂 Copying executable to '$INSTALL_DIR'"
cp "$SOURCE_DIR/$BINARY_NAME" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/$BINARY_NAME"
echo "✅ Executable copied and made executable."

# --- 4. Add to PATH if not already present ---
echo "🔧 Updating shell configuration..."
SHELL_CONFIG_FILE=""
CURRENT_SHELL=$(basename "$SHELL")

if [ "$CURRENT_SHELL" = "bash" ]; then
    SHELL_CONFIG_FILE="$HOME/.bashrc"
elif [ "$CURRENT_SHELL" = "zsh" ]; then
    SHELL_CONFIG_FILE="$HOME/.zshrc"
else
    echo "⚠️ Warning: Unsupported shell '$CURRENT_SHELL'. Please add the following line to your shell's startup file:"
    echo "   export PATH=\"
$HOME/.local/bin:$PATH\""
fi

if [ -n "$SHELL_CONFIG_FILE" ]; then
    if grep -q "export PATH=\"
$HOME/.local/bin:$PATH\"" "$SHELL_CONFIG_FILE"; then
        echo "✅ PATH is already configured in '$SHELL_CONFIG_FILE'."
    else
        echo "   Adding '$INSTALL_DIR' to PATH in '$SHELL_CONFIG_FILE'."
        echo "" >> "$SHELL_CONFIG_FILE"
        echo "# Add MultiScope to PATH" >> "$SHELL_CONFIG_FILE"
        echo "export PATH=\"
$HOME/.local/bin:$PATH\"" >> "$SHELL_CONFIG_FILE"
        echo "✅ PATH configured."
    fi
fi

# --- 5. Create .desktop file ---
echo "📝 Creating desktop entry..."
mkdir -p "$DESKTOP_DIR"
cp "res/multiscope.svg" "$ICON_DIR"

# Create the .desktop file content
cat > "$DESKTOP_DIR/$DESKTOP_FILE_NAME" << EOF
[Desktop Entry]
Name=$APP_NAME
Exec=$INSTALL_DIR/$BINARY_NAME
Icon=multiscope
Type=Application
Categories=Game;Utility;
Comment=MultiScope is an open-source tool for Linux that enables the creation and management of gamescope sessions of steam, allowing several players to play simultaneously on a single computer.
Terminal=false
EOF

# Validate the desktop file
if desktop-file-validate "$DESKTOP_DIR/$DESKTOP_FILE_NAME"; then
    echo "✅ Desktop entry created and validated successfully."
else
    echo "⚠️ Warning: Desktop entry created, but 'desktop-file-validate' reported issues."
    echo "   The application might not appear correctly in your application menu."
fi

# --- 6. Criar atalho na área de trabalho ---
echo "📋 Criando atalho na área de trabalho..."

# Detectar o diretório da área de trabalho
DESKTOP_TARGET=""
if [ -d "$HOME/Desktop" ]; then
    DESKTOP_TARGET="$HOME/Desktop"
elif [ -d "$HOME/Área de Trabalho" ]; then
    DESKTOP_TARGET="$HOME/Área de Trabalho"
elif [ -d "$HOME/Escritorio" ]; then
    DESKTOP_TARGET="$HOME/Escritorio"
else
    # Tentar detectar via xdg-user-dir se disponível
    if command -v xdg-user-dir &> /dev/null; then
        DESKTOP_TARGET=$(xdg-user-dir DESKTOP)
    fi
fi

if [ -n "$DESKTOP_TARGET" ] && [ -d "$DESKTOP_TARGET" ]; then
    cp "$DESKTOP_DIR/$DESKTOP_FILE_NAME" "$DESKTOP_TARGET/"
    echo "✅ Atalho criado na área de trabalho: $DESKTOP_TARGET/$DESKTOP_FILE_NAME"
else
    echo "⚠️  Não foi possível encontrar o diretório da área de trabalho."
    echo "   O arquivo .desktop foi criado apenas em: $DESKTOP_DIR/$DESKTOP_FILE_NAME"
fi

# --- Final Instructions ---
echo ""
echo "🎉 MultiScope has been successfully installed!"

echo "‼️ Important Next Steps:"
echo "   1. Restart your shell or run 'source $SHELL_CONFIG_FILE' for the PATH changes to take effect."
echo "   2. You may need to log out and log back in for '$APP_NAME' to appear in your application menu."
echo "   3. You can now run the application by typing '$BINARY_NAME' in your terminal or finding it in your app menu."

echo "✨ Installation complete!"
