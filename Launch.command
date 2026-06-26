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
    mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

    cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIdentifier</key><string>com.bandcamp-rekordbox</string>
  <key>CFBundleName</key><string>Rekordbox-Bandcamp</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1.0</string>
</dict>
</plist>
PLIST

    # Launcher inside the .app just opens Launch.command in Terminal
    cat > "$APP/Contents/MacOS/launcher" << LAUNCHER
#!/bin/bash
open -a Terminal "$SCRIPT_DIR/Launch.command"
LAUNCHER
    chmod +x "$APP/Contents/MacOS/launcher"

    # Convert the Bandcamp PNG to .icns for the app icon
    PNG="$SCRIPT_DIR/static/images/bc-logo-512.png"
    if [ -f "$PNG" ]; then
        TMP=$(mktemp -d)
        ICONSET="$TMP/AppIcon.iconset"
        mkdir "$ICONSET"
        for size in 16 32 128 256 512; do
            sips -z $size $size "$PNG" --out "$ICONSET/icon_${size}x${size}.png" 2>/dev/null
            sips -z $((size*2)) $((size*2)) "$PNG" --out "$ICONSET/icon_${size}x${size}@2x.png" 2>/dev/null
        done
        iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null
        rm -rf "$TMP"
    fi

    # Register so Finder shows the icon immediately
    touch "$APP"
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null

    echo "→ Created Rekordbox-Bandcamp.app"
    echo "  Drag it to your Applications folder or Dock to use it anytime."
    echo ""
fi

# ── Launch ────────────────────────────────────────────────────────────────────
"$UV" run "$SCRIPT_DIR/server.py"
