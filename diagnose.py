#!/usr/bin/env python3
"""
Diagnostic script — opens your Bandcamp playlists page, captures all
network responses and the page HTML, then writes them to files so we
can figure out the right selectors.

Usage:
    python3 diagnose.py
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

USERNAME = "cgonz313"


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page()

        # ── Login ──────────────────────────────────────────────────────────
        print("Opening Bandcamp — log in, then press Enter here …")
        await page.goto("https://bandcamp.com/login")
        input("  (press Enter once you're logged in) ")
        await page.wait_for_load_state("networkidle")

        # ── Navigate to playlists ──────────────────────────────────────────
        playlists_url = f"https://bandcamp.com/{USERNAME}/playlists"
        print(f"\nNavigating to {playlists_url} …")

        network_log = []

        async def on_response(response):
            ct = response.headers.get("content-type", "")
            entry = {"url": response.url, "status": response.status, "content-type": ct}
            if "json" in ct and response.status == 200:
                try:
                    entry["body"] = await response.json()
                except Exception:
                    pass
            network_log.append(entry)

        page.on("response", on_response)
        await page.goto(playlists_url)
        await page.wait_for_load_state("networkidle")

        for _ in range(6):
            await page.keyboard.press("End")
            await page.wait_for_timeout(600)
        await page.wait_for_load_state("networkidle")

        page.remove_listener("response", on_response)

        # ── Dump page HTML ─────────────────────────────────────────────────
        html = await page.content()
        Path("debug_page.html").write_text(html, encoding="utf-8")
        print(f"  Wrote debug_page.html ({len(html):,} chars)")

        # ── Dump network log ───────────────────────────────────────────────
        Path("debug_network.json").write_text(
            json.dumps(network_log, indent=2, default=str), encoding="utf-8"
        )
        json_calls = [e for e in network_log if "json" in e.get("content-type", "")]
        print(f"  Wrote debug_network.json ({len(network_log)} requests, {len(json_calls)} JSON)")
        print("\n  JSON API calls made:")
        for e in json_calls:
            print(f"    [{e['status']}] {e['url'][:100]}")

        # ── Dump all anchor hrefs ──────────────────────────────────────────
        links = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('a[href]'))
                 .map(a => a.href)
                 .filter(h => h.includes('bandcamp'))
        """)
        Path("debug_links.txt").write_text("\n".join(links), encoding="utf-8")
        print(f"\n  Wrote debug_links.txt ({len(links)} links)")
        playlist_links = [l for l in links if "/playlists/" in l]
        print(f"  Links containing /playlists/: {len(playlist_links)}")
        for l in playlist_links[:10]:
            print(f"    {l}")

        # ── Dump element classes that contain 'playlist' ───────────────────
        classes = await page.evaluate("""() => {
            const seen = new Set();
            document.querySelectorAll('*').forEach(el => {
                (el.className || '').toString().split(' ').forEach(c => {
                    if (c.toLowerCase().includes('playlist')) seen.add(c);
                });
            });
            return [...seen];
        }""")
        print(f"\n  CSS classes containing 'playlist': {classes}")

        # ── Visit first individual playlist page ───────────────────────────
        # Fetch the first playlist URL from the API
        first_playlist = await page.evaluate("""async () => {
            const resp = await fetch('https://bandcamp.com/api/fan_collection/1/playlists',
                                     { credentials: 'include' });
            const data = await resp.json();
            const first = (data.items || [])[0];
            return first ? { name: first.title, url: first.itemUrl } : null;
        }""")

        if first_playlist:
            print(f"\nVisiting first playlist: {first_playlist['name']} — {first_playlist['url']}")
            pl_network = []

            async def on_pl_response(response):
                ct = response.headers.get("content-type", "")
                entry = {"url": response.url, "status": response.status, "content-type": ct}
                if "json" in ct and response.status == 200:
                    try:
                        entry["body"] = await response.json()
                    except Exception:
                        pass
                pl_network.append(entry)

            page.on("response", on_pl_response)
            await page.goto(first_playlist["url"])
            await page.wait_for_load_state("networkidle")
            for _ in range(3):
                await page.keyboard.press("End")
                await page.wait_for_timeout(500)
            await page.wait_for_load_state("networkidle")
            page.remove_listener("response", on_pl_response)

            Path("debug_playlist_network.json").write_text(
                json.dumps(pl_network, indent=2, default=str), encoding="utf-8"
            )
            pl_json = [e for e in pl_network if "json" in e.get("content-type","") and e["status"]==200]
            print(f"  Wrote debug_playlist_network.json ({len(pl_json)} JSON responses)")
            for e in pl_json:
                body = e.get("body", {})
                keys = list(body.keys()) if isinstance(body, dict) else type(body).__name__
                print(f"  [{e['status']}] {e['url'][:100]}")
                print(f"    keys: {keys}")

        await browser.close()
        print("\nDone. Check debug_playlist_network.json")


if __name__ == "__main__":
    asyncio.run(main())
