#!/usr/bin/env python3
"""
Local web server for bandcamp → rekordbox.
Run: python3 server.py
Then open: http://localhost:8000
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from xml.etree.ElementTree import ElementTree
from xml.etree.ElementTree import indent as xml_indent

import uvicorn
from fastapi import BackgroundTasks, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright, Browser, Page

import json

from main import (
    AUDIO_EXTS,
    read_tags,
    match_track,
    build_rekordbox_xml,
    _output_path,
    _find_playlist_stubs,
    _fetch_playlist_tracks,
)

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path("config.json")
_DEFAULT_MUSIC_DIR  = str(Path.home() / "Music")
_DEFAULT_EXPORT_DIR = str(Path(__file__).parent / "exports")


def load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    # Migrate legacy single music_dir → list
    if "music_dir" in cfg and "music_dirs" not in cfg:
        cfg["music_dirs"] = [cfg.pop("music_dir")]
    elif "music_dir" in cfg:
        cfg.pop("music_dir")
    cfg.setdefault("music_dirs", [_DEFAULT_MUSIC_DIR])
    cfg.setdefault("export_dir", _DEFAULT_EXPORT_DIR)
    return cfg


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI()
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    return FileResponse(static_dir / "index.html")


@app.get("/browse")
async def browse(path: str = ""):
    import sys
    if not path:
        # Sensible starting point per platform
        if sys.platform == "win32":
            import string
            entries = [
                {"name": f"{d}:\\", "path": f"{d}:\\", "is_dir": True}
                for d in string.ascii_uppercase
                if Path(f"{d}:\\").exists()
            ]
            return {"path": "", "entries": entries}
        else:
            path = str(Path.home())

    p = Path(path)
    if not p.exists() or not p.is_dir():
        return {"error": f"Not a directory: {path}"}

    try:
        entries = sorted(
            [
                {"name": child.name, "path": str(child), "is_dir": child.is_dir()}
                for child in p.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            ],
            key=lambda e: e["name"].lower(),
        )
    except PermissionError:
        entries = []

    parent = str(p.parent) if p.parent != p else None
    return {"path": str(p), "parent": parent, "entries": entries}


@app.post("/shutdown")
async def shutdown(background_tasks: BackgroundTasks):
    async def _stop():
        await asyncio.sleep(0.3)  # let the response reach the client first
        if state.browser:
            try:
                await state.browser.close()
            except Exception:
                pass
        if state.pw:
            try:
                await state.pw.stop()
            except Exception:
                pass
        import os, signal
        os.kill(os.getpid(), signal.SIGTERM)

    background_tasks.add_task(_stop)
    return {"ok": True}


@app.get("/download/{filename:path}")
async def download(filename: str):
    path = Path(filename)
    if not path.exists() or not filename.endswith(".xml"):
        return {"error": "File not found"}
    return FileResponse(path, filename=path.name, media_type="application/xml")


# ── Global state (single-user local tool) ─────────────────────────────────────

class State:
    pw = None
    browser: Browser | None = None
    page: Page | None = None
    username: str | None = None
    local_files: list[dict] = []
    playlists: list[dict] = []      # [{name, url, track_count, _raw}]
    last_export: str | None = None  # path to most recent XML
    config: dict = None             # loaded from config.json

    @property
    def music_dirs(self) -> list[Path]:
        return [Path(d) for d in self.config["music_dirs"]]

    @property
    def export_dir(self) -> Path:
        return Path(self.config["export_dir"])

state = State()
state.config = load_config()


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await _send_initial_state(ws)
    try:
        while True:
            msg = await ws.receive_json()
            action = msg.get("action")
            if action == "add_music_dir":
                await _handle_add_music_dir(ws, msg.get("path", ""))
            elif action == "remove_music_dir":
                await _handle_remove_music_dir(ws, msg.get("path", ""))
            elif action == "set_export_dir":
                await _handle_set_export_dir(ws, msg.get("path", ""))
            elif action == "index":
                await _handle_index(ws)
            elif action == "login":
                await _handle_login(ws)
            elif action == "set_username":
                await _handle_set_username(ws, msg.get("username", ""))
                await _handle_get_playlists(ws)
            elif action == "get_playlists":
                await _handle_get_playlists(ws)
            elif action == "export":
                await _handle_export(ws, msg.get("playlists", []))
    except WebSocketDisconnect:
        pass


async def send(ws: WebSocket, **kwargs):
    await ws.send_json(kwargs)


async def _send_initial_state(ws: WebSocket):
    await send(ws,
        type="init",
        indexed=len(state.local_files),
        username=state.username,
        playlists=[_stub_summary(p) for p in state.playlists],
        last_export=state.last_export,
        music_dirs=state.config["music_dirs"],
        export_dir=str(state.export_dir),
    )


def _stub_summary(p: dict) -> dict:
    return {
        "name": p["name"],
        "url": p["url"],
        "track_count": p.get("track_count", 0),
    }


# ── Handlers ──────────────────────────────────────────────────────────────────

CACHE_PATH = Path("index_cache.json")
WORKERS = 8


def _cache_key(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def _save_cache(files: list[dict]):
    serialisable = [
        {**f, "path": str(f["path"]), "_key": _cache_key(f["path"])}
        for f in files
    ]
    CACHE_PATH.write_text(json.dumps(serialisable))


def _load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    try:
        rows = json.loads(CACHE_PATH.read_text())
        return {r["path"]: r for r in rows}
    except Exception:
        return {}


async def _handle_add_music_dir(ws: WebSocket, path: str):
    p = Path(path.strip())
    if not p.exists():
        await send(ws, type="error", message=f"Path not found: {p}")
        return
    dirs = state.config["music_dirs"]
    if str(p) not in dirs:
        dirs.append(str(p))
        save_config(state.config)
    state.local_files = []
    await send(ws, type="music_dirs_updated", dirs=state.config["music_dirs"])


async def _handle_remove_music_dir(ws: WebSocket, path: str):
    dirs = state.config["music_dirs"]
    if path in dirs:
        dirs.remove(path)
        save_config(state.config)
    state.local_files = []
    await send(ws, type="music_dirs_updated", dirs=state.config["music_dirs"])


async def _handle_set_export_dir(ws: WebSocket, path: str):
    p = Path(path.strip())
    if not p.exists():
        await send(ws, type="error", message=f"Path not found: {p}")
        return
    state.config["export_dir"] = str(p)
    save_config(state.config)
    await send(ws, type="export_dir_set", path=str(p))


async def _handle_index(ws: WebSocket):
    from concurrent.futures import ThreadPoolExecutor

    dirs = state.music_dirs
    if not dirs:
        await send(ws, type="error", message="No music directories configured — add at least one folder")
        return
    missing = [d for d in dirs if not d.exists()]
    if missing:
        await send(ws, type="error", message=f"Directory not found: {missing[0]}")
        return

    await send(ws, type="status", message="Scanning directories…")

    # Discover files off the event loop so the WS stays responsive
    loop = asyncio.get_running_loop()
    def _find_files():
        import os
        found = []
        for d in dirs:
            for root, _, filenames in os.walk(d):
                root_path = Path(root)
                for name in filenames:
                    if not name.startswith("._") and Path(name).suffix.lower() in AUDIO_EXTS:
                        found.append(root_path / name)
        return sorted(found)
    files = await loop.run_in_executor(None, _find_files)

    total = len(files)
    await send(ws, type="index_start", total=total)

    cache = _load_cache()
    indexed = []
    pending = []

    for f in files:
        cached = cache.get(str(f))
        if cached and cached.get("_key") == _cache_key(f):
            indexed.append({**cached, "path": f})
        else:
            pending.append(f)

    await send(ws, type="index_progress",
               current=len(indexed), total=total,
               message=f"{len(indexed)} from cache, reading {len(pending)} new/changed…")

    if pending:
        executor = ThreadPoolExecutor(max_workers=WORKERS)
        done = 0

        async def read_one(f: Path) -> dict:
            return await loop.run_in_executor(executor, read_tags, f)

        tasks = [asyncio.create_task(read_one(f)) for f in pending]
        for coro in asyncio.as_completed(tasks):
            entry = await coro
            indexed.append(entry)
            done += 1
            if done % 200 == 0 or done == len(pending):
                await send(ws, type="index_progress",
                           current=len(indexed), total=total)

        executor.shutdown(wait=False)

    state.local_files = indexed
    _save_cache(indexed)
    await send(ws, type="index_done", count=len(indexed))


async def _handle_login(ws: WebSocket):
    if state.browser is None:
        state.pw = await async_playwright().start()
        state.browser = await state.pw.chromium.launch(headless=False)

    state.page = await state.browser.new_page()
    await state.page.goto("https://bandcamp.com/login")
    await send(ws, type="login_opened")

    try:
        await state.page.wait_for_function(
            "() => !window.location.pathname.startsWith('/login')",
            timeout=180_000,
        )
        await state.page.wait_for_load_state("networkidle")
    except Exception as e:
        await send(ws, type="error", message=f"Login timed out: {e}")
        return

    username = await _detect_username(state.page)

    if not username:
        # Ask the UI for the username
        await send(ws, type="need_username")
        return

    state.username = username
    await send(ws, type="logged_in", username=username)


async def _handle_set_username(ws: WebSocket, username: str):
    state.username = username.strip().lstrip("@")
    await send(ws, type="logged_in", username=state.username)


async def _detect_username(page: Page) -> str | None:
    """Read fan.username from Bandcamp's menubar API, which fires on every page load."""
    found: dict = {}

    async def on_resp(response):
        if "design_system/1/menubar" in response.url and response.status == 200:
            try:
                data = await response.json()
                found["username"] = (data.get("fan") or {}).get("username")
            except Exception:
                pass

    page.on("response", on_resp)
    await page.goto("https://bandcamp.com")
    await page.wait_for_load_state("networkidle")
    page.remove_listener("response", on_resp)

    return found.get("username") or None


async def _handle_get_playlists(ws: WebSocket):
    if not state.page:
        await send(ws, type="error", message="Not logged in yet")
        return

    await send(ws, type="status", message="Fetching your playlists…")
    stubs = await _find_playlist_stubs(state.page, state.username)

    # Attach track count from the raw API payload if available
    for stub in stubs:
        raw = stub.get("_raw", {})
        summary = raw.get("tracksSummary") or {}
        stub["track_count"] = summary.get("totalCount", 0)

    state.playlists = stubs
    await send(ws, type="playlists", items=[_stub_summary(p) for p in stubs])


async def _handle_export(ws: WebSocket, selected: list[dict]):
    if not state.local_files:
        await send(ws, type="error", message="Index your library first")
        return
    if not state.page:
        await send(ws, type="error", message="Connect to Bandcamp first")
        return

    # Match selected names back to full stubs (which may have _raw tracks)
    selected_urls = {s["url"] for s in selected}
    selected_stubs = [p for p in state.playlists if p["url"] in selected_urls]
    if not selected_stubs:
        selected_stubs = selected  # fallback: use as-is

    await send(ws, type="status", message=f"Fetching tracks for {len(selected_stubs)} playlist(s)…")
    playlists = await _fetch_playlist_tracks(state.page, selected_stubs)

    # Match tracks with per-track progress
    for pl in playlists:
        pl["matched"] = []
        matched_count = 0
        total = len(pl["tracks"])
        for i, track in enumerate(pl["tracks"]):
            local = await asyncio.to_thread(match_track, track, state.local_files)
            pl["matched"].append(local)
            if local:
                matched_count += 1
            await send(ws,
                type="match_progress",
                playlist=pl["name"],
                current=i + 1,
                total=total,
                matched=matched_count,
            )

    # Build and write XML into the configured export directory
    state.export_dir.mkdir(parents=True, exist_ok=True)
    output_path = state.export_dir / _output_path(playlists).name
    xml_root = build_rekordbox_xml(playlists)
    xml_indent(xml_root, space="  ")
    ElementTree(xml_root).write(output_path, encoding="utf-8", xml_declaration=True)
    state.last_export = str(output_path)

    unmatched = [
        f"[{pl['name']}] {t['artist']} – {t['title']}"
        for pl in playlists
        for t, m in zip(pl["tracks"], pl["matched"])
        if m is None
    ]
    total_matched = sum(1 for pl in playlists for m in pl["matched"] if m)
    total_tracks  = sum(len(pl["tracks"]) for pl in playlists)

    await send(ws,
        type="export_done",
        filename=str(output_path),
        matched=total_matched,
        total=total_tracks,
        unmatched=unmatched,
    )


# ── Entry point ───────────────────────────────────────────────────────────────

async def _open_browser():
    import webbrowser
    await asyncio.sleep(1.0)
    webbrowser.open("http://localhost:8000")

@app.on_event("startup")
async def startup():
    asyncio.create_task(_open_browser())

if __name__ == "__main__":
    print("Starting server → http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
