#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "bandcamp → rekordbox  |  Setup"
echo "================================"
echo ""

# Install uv if not present
if ! command -v uv &>/dev/null && [ ! -f "$HOME/.local/bin/uv" ]; then
    echo "Installing uv (Python manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo ""
fi

# Find uv (may not be in PATH yet for new installs)
UV=$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")

echo "Installing dependencies (this may take a minute)..."
"$UV" sync

echo ""
echo "Installing Chromium browser for Bandcamp login..."
"$UV" run playwright install chromium

echo ""
echo "================================"
echo "Setup complete!"
echo "Double-click start.command to launch the app."
echo "================================"
echo ""
read -p "Press Enter to close..."
