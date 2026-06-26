#!/bin/bash
cd "$(dirname "$0")"

echo "bandcamp -> rekordbox  |  setup"
echo "================================"
echo ""

# Check for Python 3
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is not installed."
    echo ""
    echo "Install it one of these ways:"
    echo "  - Download from https://www.python.org/downloads/"
    echo "  - Or via Homebrew: brew install python3"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

PYTHON_VER=$(python3 --version 2>&1)
echo "[ok] $PYTHON_VER found"

# Check version is 3.9+
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]; }; then
    echo "ERROR: Python 3.9 or newer is required (you have $PYTHON_VER)."
    echo "Download the latest version from https://www.python.org/downloads/"
    read -p "Press Enter to exit..."
    exit 1
fi

# Install pip dependencies
echo ""
echo "Installing dependencies..."
python3 -m pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: pip install failed. Try running manually:"
    echo "  python3 -m pip install -r requirements.txt"
    read -p "Press Enter to exit..."
    exit 1
fi
echo "[ok] Dependencies installed"

# Install Playwright browser
echo ""
echo "Installing Chromium browser for Bandcamp login..."
python3 -m playwright install chromium
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Playwright install failed. Try running manually:"
    echo "  python3 -m playwright install chromium"
    read -p "Press Enter to exit..."
    exit 1
fi
echo "[ok] Chromium installed"

# Make launchers executable
chmod +x "$(dirname "$0")/start.command"
chmod +x "$(dirname "$0")/setup.command"

echo ""
echo "================================"
echo "Setup complete!"
echo "Double-click start.command to launch the app."
echo ""
read -p "Press Enter to exit..."
