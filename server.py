#!/usr/bin/env python3
"""
Local web server for bandcamp → rekordbox.
Run: python3 server.py   (or double-click start.command)
Then open: http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
import string
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from xml.etree.ElementTree import ElementTree
from xml.etree.ElementTree import indent as xml_indent

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright, Browser, Page

from main import (
    AUDIO_EXTS,
    read_tags,
    match_track,
    build_rekordbox_xml,
    _output_path,
    _find_playlist_stubs,
    _fetch_playlist_tracks,
)

# ── Constants ─────────────────────────────────────────────────────────────────

_HERE       = Path(__file__).parent
CONFIG_PATH = _HERE / "config.json"
CACHE_PATH  = _HERE / "index_cache.json"
STATIC_DIR  = Path(__file__).parent / "static"
WORKERS     = 8

_DEFAULT_MUSIC_DIR  = str(Path.home() / "Music")
_DEFAULT_EXPORT_DIR = str(Path(__file__).parent / "exports")

# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    cfg.setdefault("music_dir", _DEFAULT_MUSIC_DIR)
    cfg.setdefault("export_dir", _DEFAULT_EXPORT_DIR)
    return cfg


def save_config(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# ── Global state (single-user local tool) ─────────────────────────────────────

class State:
    pw          = None
    browser: Browser | None = None
    page: Page  | None = None
    username: str | None = None
    local_files: list[dict] = []
    playlists:   list[dict] = []
    last_export: str | None = None
    config: dict = None

    @property
    def music_dir(self) -> Path:
        return Path(self.config["music_dir"])

    @property
    def export_dir(self) -> Path:
        return Path(self.config["export_dir"])

state = State()
state.config = load_config()

# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_open_browser())
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


async def _open_browser():
    await asyncio.sleep(1.5)
    webbrowser.open("http://localhost:8000")


# ── HTTP routes ───────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/browse")
async def browse(path: str = ""):
    if not path:
        if sys.platform == "win32":
            entries = [
                {"name": f"{d}:\\", "path": f"{d}:\\", "is_dir": True}
                for d in string.ascii_uppercase
                if Path(f"{d}:\\").exists()
            ]
            return {"path": "", "entries": entries}
        path = str(Path.home())

    p = Path(path)
    if not p.exists() or not p.is_dir():
        return {"error": f"Not a directory: {path}"}

    try:
        entries = sorted(
            [
                {"name": child.name, "path": str(child)}
                for child in p.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            ],
            key=lambda e: e["name"].lower(),
        )
    except PermissionError:
        entries = []

    parent = str(p.parent) if p.parent != p else None
    return {"path": str(p), "parent": parent, "entries": entries}


@app.get("/download/{filename:path}")
async def download(filename: str):
    path = Path(filename)
    if not path.exists() or not filename.endswith(".xml"):
        return {"error": "File not found"}
    return FileResponse(path, filename=path.name, media_type="application/xml")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    await _send_init(ws)
    try:
        while True:
            msg    = await ws.receive_json()
            action = msg.get("action")
            if action == "set_music_dir":
                await _handle_set_music_dir(ws, msg.get("path", ""))
            elif action == "set_export_dir":
                await _handle_set_export_dir(ws, msg.get("path", ""))
            elif action == "index":
                await _handle_index(ws, msg.get("path", ""))
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


async def _send(ws: WebSocket, **kwargs):
    await ws.send_json(kwargs)


async def _send_init(ws: WebSocket):
    await _send(ws,
        type       = "init",
        indexed    = len(state.local_files),
        username   = state.username,
        playlists  = [_pl_summary(p) for p in state.playlists],
        last_export= state.last_export,
        music_dir  = str(state.music_dir),
        export_dir = str(state.export_dir),
    )


def _pl_summary(p: dict) -> dict:
    return {"name": p["name"], "url": p["url"], "track_count": p.get("track_count", 0)}


# ── Handlers ──────────────────────────────────────────────────────────────────

async def _handle_set_music_dir(ws: WebSocket, path: str):
    p = Path(path.strip())
    if not p.exists():
        await _send(ws, type="error", message=f"Path not found: {p}")
        return
    state.config["music_dir"] = str(p)
    save_config(state.config)
    state.local_files = []
    await _send(ws, type="music_dir_set", path=str(p), indexed=0)


async def _handle_set_export_dir(ws: WebSocket, path: str):
    p = Path(path.strip())
    if not p.exists():
        await _send(ws, type="error", message=f"Path not found: {p}")
        return
    state.config["export_dir"] = str(p)
    save_config(state.config)
    await _send(ws, type="export_dir_set", path=str(p))


async def _handle_index(ws: WebSocket, path: str = ""):
    if path and path != str(state.music_dir):
        state.config["music_dir"] = path
        save_config(state.config)

    if not state.music_dir.exists():
        await _send(ws, type="error", message=f"Directory not found: {state.music_dir}")
        return

    files = sorted(
        f for f in state.music_dir.iterdir()
        if f.suffix.lower() in AUDIO_EXTS and not f.name.startswith("._")
    )
    total = len(files)
    await _send(ws, type="index_start", total=total)

    cache   = _load_cache()
    indexed = []
    pending = []

    for f in files:
        cached = cache.get(str(f))
        if cached and cached.get("_key") == _cache_key(f):
            indexed.append({**cached, "path": f})
        else:
            pending.append(f)

    await _send(ws, type="index_progress", current=len(indexed), total=total,
                message=f"{len(indexed)} from cache, reading {len(pending)} new/changed…")

    if pending:
        loop     = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=WORKERS)
        done     = 0

        tasks = [asyncio.create_task(loop.run_in_executor(executor, read_tags, f)) for f in pending]
        for coro in asyncio.as_completed(tasks):
            indexed.append(await coro)
            done += 1
            if done % 200 == 0 or done == len(pending):
                await _send(ws, type="index_progress", current=len(cache) + done, total=total)

        executor.shutdown(wait=False)

    state.local_files = indexed
    _save_cache(indexed)
    await _send(ws, type="index_done", count=len(indexed))


async def _handle_login(ws: WebSocket):
    if state.browser is None:
        state.pw      = await async_playwright().start()
        state.browser = await state.pw.chromium.launch(headless=False)

    state.page = await state.browser.new_page()
    await state.page.goto("https://bandcamp.com/login")
    await _send(ws, type="login_opened")

    try:
        await state.page.wait_for_function(
            "() => !window.location.pathname.startsWith('/login')",
            timeout=180_000,
        )
        await state.page.wait_for_load_state("networkidle")
    except Exception as e:
        await _send(ws, type="error", message=f"Login timed out: {e}")
        return

    username = await _detect_username(state.page)
    if not username:
        await _send(ws, type="need_username")
        return

    state.username = username
    await _send(ws, type="logged_in", username=username)


async def _handle_set_username(ws: WebSocket, username: str):
    state.username = username.strip().lstrip("@")
    await _send(ws, type="logged_in", username=state.username)


async def _handle_get_playlists(ws: WebSocket):
    if not state.page:
        await _send(ws, type="error", message="Not logged in yet")
        return

    await _send(ws, type="status", message="Fetching your playlists…")
    stubs = await _find_playlist_stubs(state.page, state.username)

    for stub in stubs:
        summary = (stub.get("_raw") or {}).get("tracksSummary") or {}
        stub["track_count"] = summary.get("totalCount", 0)

    state.playlists = stubs
    await _send(ws, type="playlists", items=[_pl_summary(p) for p in stubs])


async def _handle_export(ws: WebSocket, selected: list[dict]):
    if not state.local_files:
        await _send(ws, type="error", message="Index your library first")
        return
    if not state.page:
        await _send(ws, type="error", message="Connect to Bandcamp first")
        return

    selected_urls  = {s["url"] for s in selected}
    selected_stubs = [p for p in state.playlists if p["url"] in selected_urls] or selected

    await _send(ws, type="status", message=f"Fetching tracks for {len(selected_stubs)} playlist(s)…")
    playlists = await _fetch_playlist_tracks(state.page, selected_stubs)

    for pl in playlists:
        pl["matched"] = []
        matched_count = 0
        for i, track in enumerate(pl["tracks"]):
            local = await asyncio.to_thread(match_track, track, state.local_files)
            pl["matched"].append(local)
            if local:
                matched_count += 1
            await _send(ws,
                type="match_progress",
                playlist=pl["name"],
                current=i + 1,
                total=len(pl["tracks"]),
                matched=matched_count,
            )

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
    await _send(ws,
        type      = "export_done",
        filename  = str(output_path),
        matched   = sum(1 for pl in playlists for m in pl["matched"] if m),
        total     = sum(len(pl["tracks"]) for pl in playlists),
        unmatched = unmatched,
    )


# ── Bandcamp auth ─────────────────────────────────────────────────────────────

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


# ── Index cache ───────────────────────────────────────────────────────────────

def _cache_key(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def _save_cache(files: list[dict]):
    rows = [{**f, "path": str(f["path"]), "_key": _cache_key(f["path"])} for f in files]
    CACHE_PATH.write_text(json.dumps(rows))


def _load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return {r["path"]: r for r in json.loads(CACHE_PATH.read_text())}
    except Exception:
        return {}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Starting server → http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
