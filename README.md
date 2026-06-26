# bandcamp → rekordbox

Converts your private Bandcamp playlists into a Rekordbox XML file, matched against your local music library.

## How it works

1. Scrapes your private Bandcamp playlists using a real browser session (no credentials stored)
2. Fuzzy-matches each track to your local files by reading their embedded metadata tags
3. Generates a Rekordbox XML file you can import directly into rekordbox

---

## Requirements

- macOS
- Python 3.9+
- Local music files on `/Volumes/GONZTRACKS/cuts/`
- Bandcamp account with purchased tracks

---

## Setup

Run once to install dependencies and download the browser:

```bash
pip3 install -r requirements.txt
python3 -m playwright install chromium
```

---

## Usage

### Web interface (recommended)

```bash
python3 server.py
```

Then open **http://localhost:8000** in your browser.

**Steps in the UI:**
1. **Index Library** — scans `/Volumes/GONZTRACKS/cuts/` and reads track metadata (~30–60s for 19k files)
2. **Connect Bandcamp** — opens a browser window, log in normally, then come back
3. **Select playlists** — check the ones you want to export
4. **Export** — matches tracks and downloads the XML

### Command line (alternative)

```bash
python3 main.py
```

---

## Importing into Rekordbox

1. Open Rekordbox
2. **Preferences → Advanced → rekordbox xml → Imported Library** → point to your `.xml` file
3. The playlists appear in the left sidebar under **rekordbox xml**
4. Drag playlists into your main library

> **Note:** Rekordbox on macOS requires the drive to be mounted when importing. Make sure `/Volumes/GONZTRACKS/` is connected.

---

## Troubleshooting

**"Drive not found" error**
Make sure `GONZTRACKS` is plugged in and mounted before indexing.

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
├── server.py          # Web server (FastAPI + WebSocket)
├── main.py            # CLI version + shared scraping/matching logic
├── diagnose.py        # Debug tool for inspecting Bandcamp page structure
├── static/
│   ├── index.html     # Web UI
│   ├── style.css      # Styles
│   └── app.js         # Client-side logic
└── requirements.txt
```
