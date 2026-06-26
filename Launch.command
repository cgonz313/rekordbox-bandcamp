#!/bin/bash
cd "$(dirname "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Already running? ──────────────────────────────────────────────────────────
if lsof -ti :8000 &>/dev/null; then
    open http://localhost:8000
    exit 0
fi

# ── Find uv ───────────────────────────────────────────────────────────────────
UV=$(command -v uv 2>/dev/null || echo "$HOME/.local/bin/uv")

# ── First-time setup ──────────────────────────────────────────────────────────
if [ ! -f "$UV" ] || [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo ""
    echo "bandcamp → rekordbox  |  First-time setup"
    echo "This takes about a minute and only happens once."
    echo ""

    if ! command -v uv &>/dev/null && [ ! -f "$HOME/.local/bin/uv" ]; then
        echo "→ Installing package manager..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        UV="$HOME/.local/bin/uv"
    fi

    echo "→ Installing Python and dependencies..."
    "$UV" sync

    echo "→ Installing browser for Bandcamp login..."
    "$UV" run playwright install chromium

    echo ""
fi

# ── Create .app bundle (once) ─────────────────────────────────────────────────
APP="$SCRIPT_DIR/Rekordbox-Bandcamp.app"
if [ ! -d "$APP" ]; then
    # osacompile produces a proper native binary — no Rosetta prompt
    osacompile -o "$APP" -e "do shell script \"open -a Terminal '$SCRIPT_DIR/Launch.command'\""

    # Replace the default applet icon with the Bandcamp logo
    PNG="$SCRIPT_DIR/static/images/bc-logo-512.png"
    if [ -f "$PNG" ]; then
        TMP=$(mktemp -d)
        ICONSET="$TMP/AppIcon.iconset"
        mkdir "$ICONSET"
        for size in 16 32 128 256 512; do
            sips -z $size $size "$PNG" --out "$ICONSET/icon_${size}x${size}.png" 2>/dev/null
            sips -z $((size*2)) $((size*2)) "$PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" 2>/dev/null
        done
        iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/applet.icns" 2>/dev/null
        rm -rf "$TMP"
    fi

    # Tell Finder to refresh the icon
    touch "$APP"
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null

    echo "→ Created Rekordbox-Bandcamp.app"
    echo "  Drag it to your Applications folder or Dock to use it anytime."
    echo ""
fi

# ── Launch ────────────────────────────────────────────────────────────────────
"$UV" run "$SCRIPT_DIR/server.py"
