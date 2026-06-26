# bandcamp → rekordbox

Converts your private Bandcamp playlists into a Rekordbox XML file, matched against your local music library.

## How it works

1. Scrapes your private Bandcamp playlists using a real browser session (no credentials stored)
2. Fuzzy-matches each track to your local files by reading their embedded metadata tags
3. Generates a Rekordbox XML file you can import directly into rekordbox

---

## Requirements

- macOS or Windows
- Local music files (AIFF, MP3, WAV, M4A)
- Bandcamp account with purchased tracks

---

## Setup

**First time only** — double-click the setup script for your platform:

- **macOS**: double-click `setup.command` (or right-click → Open if macOS blocks it)
- **Windows**: double-click `setup.bat`

That's it. The script installs everything automatically — Python, all dependencies, and the Chromium browser used for Bandcamp login. No prior installation required.

---

## Usage

### Web interface (recommended)

**Double-click `start.command`** (macOS) or **`start.bat`** (Windows) — the server starts and your browser opens automatically.

**Steps in the UI:**
1. **Set your music folder** — type the path or click Browse… to pick it
2. **Index Library** — reads track metadata from your files (cached after first run)
3. **Connect Bandcamp** — opens a browser window, log in normally, then come back
4. **Select playlists** — check the ones you want to export
5. **Export** — matches tracks and downloads the XML

---

## Importing into Rekordbox

1. Open Rekordbox
2. **Preferences → Advanced → rekordbox xml → Imported Library** → point to your `.xml` file
3. The playlists appear in the left sidebar under **rekordbox xml**
4. Drag playlists into your main library

> **Note:** Rekordbox on macOS requires the drive to be mounted when importing. Make sure your music drive is connected before importing.

---

## Troubleshooting

**"Directory not found" error**
Make sure the drive is mounted/connected and the path is correct before indexing.

**Tracks show as missing in Rekordbox**
The XML uses `file://localhost/Volumes/...` paths. If tracks still show missing, try re-importing after mounting the drive.

**Low match rate**
Tracks without embedded metadata tags fall back to filename parsing, which is less reliable. Adding proper ID3 tags to your files (with a tool like MusicBrainz Picard) will improve matching.

**Browser doesn't open / login times out**
Re-click "Connect Bandcamp". You have 3 minutes to log in before it times out.

---

## Project structure

```
rekordbox-bandcamp/
├── setup.command      # One-time setup (macOS)
├── setup.bat          # One-time setup (Windows)
├── start.command      # Launch app (macOS)
├── start.bat          # Launch app (Windows)
├── server.py          # Web server (FastAPI + WebSocket)
├── main.py            # CLI version + shared scraping/matching logic
├── static/
│   ├── index.html     # Web UI
│   ├── style.css      # Styles
│   └── app.js         # Client-side logic
├── pyproject.toml     # Dependencies (used by uv)
└── requirements.txt   # Legacy fallback
```
