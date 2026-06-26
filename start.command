#!/bin/bash
cd "$(dirname "$0")"

UV=$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")

if [ ! -f "$UV" ] && ! command -v uv &>/dev/null; then
    echo "Setup has not been run yet. Please double-click setup.command first."
    read -p "Press Enter to close..."
    exit 1
fi

"$UV" run server.py
