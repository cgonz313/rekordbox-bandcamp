#!/usr/bin/env python3
"""
bandcamp → rekordbox
Scrapes your private Bandcamp playlists and generates a Rekordbox XML file
you can import directly into rekordbox via File > Import > Import rekordbox XML.

Usage:
    python3 main.py

On first run, a browser window opens. Log into Bandcamp normally —
the script takes over once you're in.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs, urlencode
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

import mutagen
from rapidfuzz import fuzz, process
from playwright.async_api import async_playwright, Page, Response

# ── Config ────────────────────────────────────────────────────────────────────

MUSIC_DIR      = Path.home() / "Music"
OUTPUT_PATH    = Path("rekordbox_playlists.xml")
AUDIO_EXTS     = {".mp3", ".aiff", ".aif", ".wav", ".m4a"}
MATCH_THRESHOLD = 75   # 0–100; lower = more permissive


# ── 1. Index local files ──────────────────────────────────────────────────────

def _str_tag(val) -> str:
    """Safely convert a mutagen tag value to a plain string."""
    if val is None:
        return ""
    if isinstance(val, list):
        val = val[0] if val else ""
    return str(val).strip()


def read_tags(path: Path) -> dict:
    artist = title = ""
    duration = 0

    try:
        f = mutagen.File(path)
        if f is not None:
            if hasattr(f, "info") and hasattr(f.info, "length"):
                duration = int(f.info.length)

            tags = f.tags
            if tags is not None:
                # ID3-style tags: MP3, AIFF, WAV-with-ID3
                title  = _str_tag(tags.get("TIT2")) or _str_tag(tags.get("TIT2:"))
                artist = _str_tag(tags.get("TPE1")) or _str_tag(tags.get("TPE1:"))

                # MP4/M4A tags (iTunes-style)
                if not title:
                    title  = _str_tag(tags.get("\xa9nam"))
                if not artist:
                    artist = _str_tag(tags.get("\xa9ART"))
    except Exception:
        pass

    # Filename fallback when tags are missing
    if not title:
        stem = path.stem.replace("_", " ")
        if " - " in stem:
            parts = stem.split(" - ", 1)
            if not artist:
                artist = parts[0].strip()
            title = parts[1].strip()
        else:
            title = stem.strip()

    return {
        "path":       path,
        "artist":     artist,
        "title":      title,
        "duration":   duration,
        "size":       path.stat().st_size,
        "search_key": f"{artist} {title}".strip().lower(),
    }


def index_local_files() -> list[dict]:
    print(f"Indexing {MUSIC_DIR} …")
    files = [
        read_tags(f)
        for f in sorted(MUSIC_DIR.iterdir())
        if f.suffix.lower() in AUDIO_EXTS and not f.name.startswith("._")
    ]
    print(f"  {len(files)} audio files indexed")
    return files


# ── 2. Scrape Bandcamp with Playwright ────────────────────────────────────────

async def wait_for_login(page: Page) -> str:
    """Open Bandcamp login page and block until the user is logged in."""
    print("\nOpening Bandcamp — log in when the browser appears …")
    await page.goto("https://bandcamp.com/login")

    # Wait up to 3 minutes for the user to log in (URL leaves /login)
    await page.wait_for_function(
        "() => !window.location.pathname.startsWith('/login')",
        timeout=180_000,
    )
    await page.wait_for_load_state("networkidle")

    username: str = await page.evaluate("""() => {
        // Bandcamp puts the fan username in several places depending on version
        const selectors = [
            'a.fan-username',
            '[class*="fan-username"]',
            'a[href*="bandcamp.com/"][class*="nav"]',
        ];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) {
                const m = el.href && el.href.match(/bandcamp\\.com\\/([^\\/?#]+)/);
                if (m) return m[1];
                const t = el.textContent.trim();
                if (t) return t;
            }
        }
        // Fallback: scan all nav links for the fan page URL
        for (const a of document.querySelectorAll('header a, nav a')) {
            const m = a.href && a.href.match(/bandcamp\\.com\\/([^\\/?#]+)$/);
            if (m && !['login','signup','help','about','discover'].includes(m[1])) {
                return m[1];
            }
        }
        return null;
    }""")

    if not username:
        username = input("  Could not auto-detect username — enter your Bandcamp username: ").strip()

    print(f"  Signed in as: {username}")
    return username


def _find_cursor(data: dict) -> str | None:
    """Extract the pagination cursor from any Bandcamp API response shape."""
    return (data.get("last_token") or data.get("nextCursor") or
            data.get("next_cursor") or data.get("cursor") or None)


async def _find_playlist_stubs(page: Page, username: str) -> list[dict]:
    """
    Return [{name, url}] for every playlist on the /playlists page.
    Tries network capture, window globals, DOM links, then clicking each card.
    """
    playlists_url = f"https://bandcamp.com/{username}/playlists"
    print(f"\nNavigating to {playlists_url} …")

    captured: list[dict] = []

    async def on_response(response: Response):
        if response.status != 200:
            return
        if "json" not in response.headers.get("content-type", ""):
            return
        try:
            data = await response.json()
            captured.append({"url": response.url, "data": data})
        except Exception:
            pass

    page.on("response", on_response)
    await page.goto(playlists_url)
    await page.wait_for_load_state("networkidle")

    # Phase 1: click "View more results" button until it disappears
    while True:
        btn = await page.query_selector("button.load-more-button")
        if not btn:
            break
        try:
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(500)
        except Exception:
            break

    # Phase 2: infinite scroll for the remainder
    prev_count = 0
    for _ in range(50):
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(800)
        if len(captured) == prev_count:
            break
        prev_count = len(captured)

    page.remove_listener("response", on_response)

    # Cursor-based pagination: use the cursor from the first API response
    # to explicitly fetch all remaining pages via Playwright's request context
    # (which carries the browser's session cookies)
    playlist_api = next(
        (item for item in captured
         if "fan_collection" in item["url"] and "playlist" in item["url"]),
        None,
    )
    if playlist_api:
        parsed    = urlparse(playlist_api["url"])
        base_url  = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        base_params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        cursor = _find_cursor(playlist_api["data"])
        while cursor:
            next_url = base_url + "?" + urlencode({**base_params, "older_than_token": cursor})
            try:
                resp = await page.request.get(next_url, headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": playlists_url,
                })
                if not resp.ok:
                    break
                next_data = await resp.json()
                captured.append({"url": next_url, "data": next_data})
                cursor = _find_cursor(next_data)
            except Exception:
                break

    # 1) Parse all captured responses (initial + paginated)
    all_stubs: list[dict] = []
    seen_urls: set[str] = set()
    for item in captured:
        for stub in _extract_stubs_from_json(item["data"], username):
            if stub["url"] not in seen_urls:
                seen_urls.add(stub["url"])
                all_stubs.append(stub)
    if all_stubs:
        print(f"  Found {len(all_stubs)} playlist(s) via network capture")
        return all_stubs

    # 2) Window globals — Bandcamp stashes page data in JS variables
    stubs = await page.evaluate("""(username) => {
        const seen = new Set();
        const results = [];

        const tryExtract = (obj) => {
            if (!obj || typeof obj !== 'object') return;
            const lists = obj.playlists || obj.playlist_items || obj.items;
            if (!Array.isArray(lists)) return;
            for (const pl of lists) {
                if (typeof pl !== 'object') continue;
                const name = pl.title || pl.name || 'Untitled';
                const id   = pl.id || pl.playlist_id;
                const url  = pl.url || (id ? `https://bandcamp.com/${username}/playlists/${id}` : null);
                if (url && !seen.has(url)) {
                    seen.add(url);
                    results.push({ name, url, _raw: pl });
                }
            }
        };

        // Check every window-level variable
        for (const key of Object.keys(window)) {
            try { tryExtract(window[key]); } catch(e) {}
        }

        // Check data-blob attributes
        document.querySelectorAll('[data-blob]').forEach(el => {
            try { tryExtract(JSON.parse(el.dataset.blob)); } catch(e) {}
        });

        // Check inline <script> tags for JSON objects
        document.querySelectorAll('script:not([src])').forEach(s => {
            const m = s.textContent.match(/(\{[\s\S]{20,}\})/g) || [];
            for (const chunk of m.slice(0, 5)) {
                try { tryExtract(JSON.parse(chunk)); } catch(e) {}
            }
        });

        // Anchor tags with /playlist/ in href (singular — Bandcamp's actual format)
        document.querySelectorAll('a[href]').forEach(a => {
            const h = a.href.split('?')[0];  // strip query params
            if (/\/playlist\//.test(h) && !seen.has(h)) {
                seen.add(h);
                const name = a.querySelector('[class*="title"]')?.textContent.trim()
                          || a.textContent.trim() || 'Untitled';
                results.push({ name, url: h });
            }
        });

        return results;
    }""", username)

    if stubs:
        print(f"  Found {len(stubs)} playlist(s) via window globals / DOM")
        return stubs

    # 3) Click-based discovery: click each playlist card and capture the URL
    print("  Trying click-based playlist discovery …")
    stubs = await _find_stubs_by_clicking(page, playlists_url, username)
    if stubs:
        return stubs

    return []


async def _find_stubs_by_clicking(page: Page, playlists_url: str, username: str) -> list[dict]:
    """Click every playlist card on the page, capture the URL it navigates to."""
    # Scroll back to top and re-load the list
    await page.goto(playlists_url)
    await page.wait_for_load_state("networkidle")

    # Collect bounding boxes of all playlist card elements we can click
    cards_info: list[dict] = await page.evaluate("""() => {
        const candidates = [
            ...document.querySelectorAll('[class*="playlist"]'),
        ].filter(el => {
            const r = el.getBoundingClientRect();
            return r.width > 50 && r.height > 50;
        });

        // Deduplicate by top-left position
        const seen = new Set();
        const results = [];
        for (const el of candidates) {
            const r = el.getBoundingClientRect();
            const key = `${Math.round(r.top)},${Math.round(r.left)}`;
            if (!seen.has(key)) {
                seen.add(key);
                // Walk up to find a title
                let name = el.querySelector('[class*="title"]')?.textContent.trim() || '';
                if (!name) {
                    let p = el.parentElement;
                    for (let i = 0; i < 3 && p; i++, p = p.parentElement) {
                        name = p.querySelector('[class*="title"]')?.textContent.trim() || '';
                        if (name) break;
                    }
                }
                results.push({ x: r.left + r.width / 2, y: r.top + r.height / 2, name: name || 'Untitled' });
            }
        }
        return results.slice(0, 100);  // cap at 100
    }""")

    if not cards_info:
        print("  No clickable playlist elements found.")
        return []

    print(f"  Found {len(cards_info)} clickable element(s) — clicking each to capture URLs …")
    stubs: list[dict] = []
    seen_urls: set[str] = set()

    for card in cards_info:
        try:
            await page.mouse.click(card["x"], card["y"])
            await page.wait_for_timeout(800)
            url = page.url
            if (
                url != playlists_url
                and f"/{username}/playlist/" in url   # singular
                and url not in seen_urls
            ):
                seen_urls.add(url)
                stubs.append({"name": card["name"], "url": url})
                await page.go_back()
                await page.wait_for_load_state("networkidle")
        except Exception:
            # click didn't navigate — not a card link
            if page.url != playlists_url:
                await page.goto(playlists_url)
                await page.wait_for_load_state("networkidle")

    print(f"  Click discovery found {len(stubs)} playlist(s)")
    return stubs


def _extract_stubs_from_json(data, username: str) -> list[dict]:
    """Pull {name, url} stubs out of any shape of Bandcamp JSON response."""
    if not isinstance(data, dict):
        return []

    for key in ("playlists", "playlist_items", "items", "results"):
        items = data.get(key)
        if not (items and isinstance(items, list)):
            continue
        stubs = []
        for pl in items:
            if not isinstance(pl, dict):
                continue
            name = pl.get("title") or pl.get("name") or "Untitled"
            # Bandcamp uses itemUrl (new API) or url (older shape)
            url = pl.get("itemUrl") or pl.get("url") or ""
            url = url.split("?")[0]  # strip tracking query params
            if not url:
                pl_id = pl.get("itemId") or pl.get("id") or pl.get("playlist_id")
                if pl_id:
                    url = f"https://bandcamp.com/{username}/playlist/{pl_id}"
            if url:
                stubs.append({"name": name, "url": url, "_raw": pl})
        if stubs:
            return stubs

    return []


async def scrape_playlists(page: Page, username: str) -> list[dict]:
    """Return a list of {name, tracks:[{artist,title}]} dicts for chosen playlists."""
    stubs = await _find_playlist_stubs(page, username)

    if not stubs:
        print("\nCould not find playlists automatically.")
        print("In the browser, click on a playlist — the URL in the address bar")
        print("will look like:  https://bandcamp.com/cgonz313/playlists/1234567")
        print("Paste those URLs one per line, then press Enter on a blank line:")
        stubs = []
        while True:
            line = input("  url> ").strip()
            if not line:
                break
            if not line.startswith("http"):
                line = "https://" + line
            name = input("  name for this playlist> ").strip() or "Untitled"
            stubs.append({"name": name, "url": line})

    if not stubs:
        return []

    # Let the user pick which playlists to export
    stubs = _pick_playlists(stubs)
    if not stubs:
        return []

    # Fetch tracks for each chosen playlist
    return await _fetch_playlist_tracks(page, stubs)


def _pick_playlists(stubs: list[dict]) -> list[dict]:
    """Print a numbered list and let the user pick which playlists to export."""
    print(f"\nFound {len(stubs)} playlist(s):")
    for i, s in enumerate(stubs, 1):
        print(f"  {i:>3}. {s['name']}")
    print("\nWhich playlists do you want to export?")
    print("  Enter numbers separated by commas (e.g. 1,3,5), a range (e.g. 1-5), or 'all':")

    raw = input("  > ").strip().lower()
    if raw == "all":
        return stubs

    chosen: list[dict] = []
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            chosen.extend(stubs[int(lo) - 1 : int(hi)])
        elif part.isdigit():
            chosen.append(stubs[int(part) - 1])

    print(f"  Exporting {len(chosen)} playlist(s)")
    return chosen


async def _fetch_playlist_tracks(page: Page, stubs: list[dict]) -> list[dict]:
    """Navigate to each playlist URL and extract its track listing."""
    playlists = []

    for stub in stubs:
        url = stub["url"]

        # If the raw API payload already includes tracks, use them directly
        raw = stub.get("_raw", {})
        items = raw.get("items") or raw.get("tracks") or []
        if items:
            tracks = [
                {
                    "artist": t.get("band_name") or t.get("artist") or "",
                    "title":  t.get("title") or t.get("track_title") or "",
                }
                for t in items
            ]
            playlists.append({"name": stub["name"], "tracks": tracks})
            print(f"  {stub['name']}: {len(tracks)} track(s) (from API cache)")
            continue

        # Otherwise navigate to the playlist page
        print(f"  Fetching {stub['name']} …")
        captured: list[dict] = []

        async def on_resp(response: Response):
            if response.status != 200:
                return
            if "json" not in response.headers.get("content-type", ""):
                return
            try:
                captured.append(await response.json())
            except Exception:
                pass

        page.on("response", on_resp)
        await page.goto(url)
        await page.wait_for_load_state("networkidle")

        prev_count = 0
        for _ in range(50):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)
            if len(captured) == prev_count:
                break
            prev_count = len(captured)

        page.remove_listener("response", on_resp)

        # Try API responses first
        tracks = []
        for data in captured:
            tracks = _extract_tracks_from_json(data)
            if tracks:
                break

        # DOM fallback
        if not tracks:
            tracks = await _tracks_from_dom(page)

        if tracks:
            playlists.append({"name": stub["name"], "tracks": tracks})
            print(f"    {len(tracks)} track(s)")
        else:
            print(f"    Warning: no tracks found at {url}")

    return playlists


def _extract_tracks_from_json(data) -> list[dict]:
    if not isinstance(data, dict):
        return []
    for key in ("items", "tracks", "playlist_items"):
        items = data.get(key)
        if items and isinstance(items, list):
            tracks = []
            for t in items:
                if not isinstance(t, dict):
                    continue
                artist = t.get("band_name") or t.get("artist") or ""
                title  = t.get("title") or t.get("track_title") or ""
                if title:
                    tracks.append({"artist": artist, "title": title})
            if tracks:
                return tracks
    return []


async def _tracks_from_dom(page: Page) -> list[dict]:
    return await page.evaluate("""() => {
        const tracks = [];
        const rows = document.querySelectorAll(
            '[class*="playlist-item"], [class*="track-item"], [class*="queue-item"], li[class*="item"]'
        );
        rows.forEach(el => {
            const artist = el.querySelector('[class*="artist"], [class*="band"]')
                            ?.textContent.trim() || '';
            const title  = el.querySelector('[class*="title"]')
                            ?.textContent.trim() || '';
            if (title) tracks.push({ artist, title });
        });
        return tracks;
    }""")


# ── 3. Match Bandcamp tracks → local files ────────────────────────────────────

def match_track(track: dict, local_files: list[dict]) -> dict | None:
    artist = track.get("artist", "")
    title  = track.get("title", "")

    # Try artist+title together first
    query = f"{artist} {title}".strip().lower()
    keys  = [f["search_key"] for f in local_files]

    hit = process.extractOne(query, keys, scorer=fuzz.WRatio)
    if hit and hit[1] >= MATCH_THRESHOLD:
        return local_files[hit[2]]

    # Retry with title only (useful when local files lack artist tags)
    if title:
        hit2 = process.extractOne(title.lower(), keys, scorer=fuzz.WRatio)
        if hit2 and hit2[1] >= MATCH_THRESHOLD:
            return local_files[hit2[2]]

    return None


# ── 4. Build Rekordbox XML ────────────────────────────────────────────────────

_KIND = {
    ".mp3":  "MP3 File",
    ".aiff": "AIFF File",
    ".aif":  "AIFF File",
    ".wav":  "WAV File",
    ".m4a":  "AAC File",
}


def _location_uri(path: Path) -> str:
    # Rekordbox on macOS requires file://localhost/... (not file:///)
    return "file://localhost" + quote(str(path), safe="/:@")


def build_rekordbox_xml(playlists: list[dict]) -> Element:
    # Deduplicate tracks across all playlists; assign stable IDs
    track_id_map: dict[str, int] = {}
    ordered_tracks: list[dict] = []
    next_id = 1

    for pl in playlists:
        for local in pl.get("matched", []):
            if local is None:
                continue
            key = str(local["path"])
            if key not in track_id_map:
                track_id_map[key] = next_id
                ordered_tracks.append(local)
                next_id += 1

    root = Element("DJ_PLAYLISTS", Version="1.0.0")
    SubElement(root, "PRODUCT", Name="rekordbox", Version="6.0.0", Company="AlphaTheta")

    collection = SubElement(root, "COLLECTION", Entries=str(len(ordered_tracks)))
    for local in ordered_tracks:
        p = local["path"]
        SubElement(collection, "TRACK",
            TrackID=str(track_id_map[str(p)]),
            Name=local["title"] or p.stem,
            Artist=local["artist"],
            Composer="",
            Album="",
            Grouping="",
            Genre="",
            Kind=_KIND.get(p.suffix.lower(), "Unknown"),
            Size=str(local["size"]),
            TotalTime=str(local["duration"]),
            DiscNumber="0",
            TrackNumber="0",
            Year="",
            Bpm="0.00",
            DateAdded="",
            BitRate="0",
            SampleRate="44100",
            Comments="",
            PlayCount="0",
            LastPlayed="",
            Rating="0",
            Location=_location_uri(p),
            Remixer="",
            Tonality="",
            Label="",
            Mix="",
        )

    playlists_node = SubElement(root, "PLAYLISTS")
    root_node = SubElement(playlists_node, "NODE", Type="0", Name="ROOT",
                           Count=str(len(playlists)))

    for pl in playlists:
        matched = [m for m in pl.get("matched", []) if m is not None]
        pl_node = SubElement(root_node, "NODE",
            Name=pl["name"],
            Type="1",
            KeyType="0",
            Entries=str(len(matched)),
        )
        for local in matched:
            SubElement(pl_node, "TRACK", Key=str(track_id_map[str(local["path"])]))

    return root


# ── Main ──────────────────────────────────────────────────────────────────────

def _output_path(playlists: list[dict]) -> Path:
    if len(playlists) == 1:
        safe = playlists[0]["name"]
        # Remove characters that are invalid in filenames
        for ch in r'\/:*?"<>|':
            safe = safe.replace(ch, "_")
        return Path(f"{safe}.xml")
    return OUTPUT_PATH

async def main() -> None:
    if not MUSIC_DIR.exists():
        print(f"Error: music directory not found: {MUSIC_DIR}")
        sys.exit(1)

    # Phase 1 — index local files
    local_files = index_local_files()

    # Phase 2 — scrape Bandcamp
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page    = await browser.new_page()
        try:
            username         = await wait_for_login(page)
            bandcamp_playlists = await scrape_playlists(page, username)
        finally:
            await browser.close()

    if not bandcamp_playlists:
        print("\nNo playlists found — nothing to export.")
        sys.exit(1)

    print(f"\n{len(bandcamp_playlists)} playlist(s) found:")
    for pl in bandcamp_playlists:
        print(f"  {pl['name']}  ({len(pl['tracks'])} tracks)")

    # Phase 3 — match tracks
    print("\nMatching tracks to local files …")
    unmatched: list[str] = []

    for pl in bandcamp_playlists:
        pl["matched"] = []
        for track in pl["tracks"]:
            local = match_track(track, local_files)
            pl["matched"].append(local)
            if local is None:
                unmatched.append(f"  [{pl['name']}] {track['artist']} – {track['title']}")

    matched_total = sum(1 for pl in bandcamp_playlists for m in pl["matched"] if m)
    track_total   = sum(len(pl["tracks"]) for pl in bandcamp_playlists)
    print(f"  {matched_total}/{track_total} tracks matched")

    if unmatched:
        print(f"\nUnmatched ({len(unmatched)}) — these won't appear in rekordbox:")
        for line in unmatched:
            print(line)

    # Phase 4 — write XML
    output_path = _output_path(bandcamp_playlists)
    xml_root = build_rekordbox_xml(bandcamp_playlists)
    indent(xml_root, space="  ")
    ElementTree(xml_root).write(output_path, encoding="utf-8", xml_declaration=True)

    print(f"\nWrote {output_path}")
    print("In Rekordbox: Preferences → Advanced → rekordbox xml → set path to this file")


if __name__ == "__main__":
    asyncio.run(main())
