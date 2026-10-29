"""Film the README clips in the running app (S15).

Each scene drives the real web app in headless Chromium at twice the window's pixels and
records it with scripts/tour/recorder.py; scripts/tour/animate.py (NextTex's camera) turns
each recording into docs/tour/<scene>.webp.

Researchers appear by alias only: every API response passing through the browser has the
researcher's display name replaced with their alias from data/overrides/pi_aliases.csv,
as the replay preview does. Paper titles and records are public and shown as they are.
Private mode is filmed with the SYNTHETIC persona-1 files.

  uv run --with playwright --with pillow python scripts/tour/film.py \\
      [--base http://127.0.0.1:8090] [--scenes hero industry handoff scout private]

The demo must be up (`make demo`), with private mode on for the private scene.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import glob
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from playwright.async_api import Page, Route, async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recorder import Recorder, click  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/tour"
RAW = ROOT / "build/tour"
PERSONA = ROOT / "data/synthetic/persona-1"
AUTHOR = "A5026494099"  # PI-4, the demo researcher
VIEW = {"width": 1280, "height": 800}


def aliases() -> dict[str, str]:
    """Real display name -> alias, for the researchers in the alias table."""
    ids = {}
    with (ROOT / "data/overrides/pi_aliases.csv").open() as f:
        for r in csv.DictReader(f):
            ids[f"https://openalex.org/{r['openalex_id']}"] = r["alias"]
    out = {}
    for db in (ROOT / "data/demo/perch.db", ROOT / "data/perch.db"):
        if db.is_file():
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for i, data in con.execute("SELECT id, data FROM records WHERE kind='researcher'"):
                if i in ids:
                    out[json.loads(data)["display_name"]] = ids[i]
            con.close()
    return out


async def alias_responses(page: Page, names: dict[str, str]) -> None:
    async def handle(route: Route) -> None:
        try:
            r = await route.fetch()
        except Exception:  # noqa: BLE001 - the page closed mid-request
            return
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype:
            await route.fulfill(response=r)
            return
        body = await r.text()
        for real, alias in names.items():
            body = body.replace(real, alias)
        await route.fulfill(response=r, body=body)

    for path in ("/authors/**", "/briefs/**", "/records/**", "/scout/**", "/private/**"):
        await page.route(f"**{path}", handle)


async def hero(page: Page, base: str) -> Recorder:
    await page.goto(base + "/#/")
    await page.wait_for_timeout(1200)
    rec = Recorder(page, "hero", RAW)
    await rec.start()
    await rec.hold(900)
    q = page.locator("#q")
    await click(page, q)
    await q.press_sequentially(AUTHOR, delay=70)
    await rec.focus(page.locator("form.search"), pad=30)
    await rec.hold(300)
    await click(page, page.locator("button:has-text('Find researcher')"))
    card = page.locator(".candidate").first
    await rec.quickly(lambda: card.wait_for())
    await rec.focus(card, pad=30)
    await rec.hold(1400)
    await click(page, card.locator("button:has-text('Build brief')"))
    rec.wide()
    await rec.quickly(lambda: page.locator("#tab-routes").wait_for())
    await page.wait_for_timeout(1500)
    await rec.hold(1200)
    await click(page, page.locator("#tab-routes"))
    await rec.hold(900)
    lead = page.locator(".leads > li").first
    await rec.focus(lead, pad=20)
    await rec.hold(1600)
    why = lead.locator("summary[data-key=why]")
    await click(page, why)
    await rec.hold(500)
    await rec.focus(lead, pad=20)
    await rec.hold(1800)
    ref = lead.locator(".paper-ref").first
    await click(page, ref)
    panel = page.locator("#evidence")
    await panel.wait_for()
    await rec.hold(500)
    await rec.focus(panel, pad=10)
    await rec.hold(2600)
    rec.wide()
    await rec.hold(800)
    await rec.stop()
    return rec


async def open_brief(page: Page, base: str) -> None:
    """A fresh copy of the demo researcher's brief, on Routes."""
    await page.goto(base + "/#/")
    await page.fill("#q", AUTHOR)
    await page.click("button:has-text('Find researcher')")
    await page.locator(".candidate button:has-text('Build brief')").first.click()
    await page.locator("#tab-routes").wait_for()
    await page.wait_for_timeout(1200)
    await page.click("#tab-routes")
    await page.wait_for_timeout(800)


async def industry(page: Page, base: str) -> Recorder:
    await open_brief(page, base)
    rec = Recorder(page, "industry", RAW)
    await rec.start()
    await rec.hold(800)
    btn = page.locator("[data-key=route-B]")
    await rec.focus(page.locator(".route-switch"), pad=30)
    await click(page, btn)
    await rec.hold(900)
    rec.wide()
    await rec.hold(900)
    lead = page.locator(".leads > li").first
    await rec.focus(lead, pad=16)
    await rec.hold(3200)
    more = lead.locator("summary").first
    if await more.count():
        await click(page, more)
        await rec.hold(500)
        await rec.focus(lead, pad=16)
        await rec.hold(2600)
    rec.wide()
    await rec.hold(700)
    await rec.stop()
    return rec


async def handoff(page: Page, base: str) -> Recorder:
    await open_brief(page, base)
    rec = Recorder(page, "handoff", RAW)
    await rec.start()
    await rec.hold(700)
    keeps = page.locator(".leads > li [data-key=keep]")
    for i in range(2):
        k = keeps.nth(i)
        await rec.focus(page.locator(".leads > li").nth(i), pad=16)
        await click(page, k)
        await rec.hold(700)
    bar = page.locator("[data-key=keep-compare]")
    await rec.focus(bar, pad=60)
    await rec.hold(900)
    await click(page, bar)
    rec.wide(ease=0.4)
    table = page.locator("#panel table").first
    await table.wait_for()
    await page.wait_for_timeout(300)
    await table.evaluate("e => e.scrollIntoView({block: 'center'})")
    rec.wide()
    await rec.hold(700)
    await rec.focus(table, pad=20)
    await rec.hold(2600)
    make = page.locator("[data-key=handoff-make]")
    await make.scroll_into_view_if_needed()
    await rec.focus(page.locator("#handoff-title"), pad=120)
    await click(page, make)
    subject = page.locator("[data-key=handoff-subject]")
    await rec.quickly(lambda: subject.wait_for(timeout=120_000), speed=8)
    draft = page.locator("#panel textarea").last
    await draft.evaluate("e => e.scrollIntoView({block: 'center'})")
    await rec.hold(400)
    await rec.focus(draft, pad=30)
    await rec.hold(3600)
    rec.wide()
    await rec.hold(700)
    await rec.stop()
    return rec


async def scout(page: Page, base: str) -> Recorder:
    await open_brief(page, base)
    await page.click("#tab-scout")
    await page.wait_for_timeout(800)
    rec = Recorder(page, "scout", RAW)
    await rec.start()
    await rec.hold(700)
    run = page.locator("input[name=scout-mode][value=run]")
    await click(page, run)
    q = page.locator("#scout-q")
    await click(page, q)
    await rec.focus(page.locator("#panel"), pad=0)
    await q.press_sequentially("Why does the top lead fit?", delay=45)
    await rec.hold(300)
    await click(page, page.locator("#panel button:has-text('Ask')"))
    answer = page.locator(".scout-answer").last
    await rec.quickly(lambda: answer.wait_for(timeout=180_000), speed=6)
    await page.wait_for_timeout(1500)
    rec.wide()
    await rec.hold(800)
    if await answer.count():
        await answer.scroll_into_view_if_needed()
        await rec.focus(answer, pad=40)
    await rec.hold(3600)
    await rec.stop()
    return rec


async def private(page: Page, base: str) -> Recorder:
    files = {"cv": "cv.md", "proposal": "specific_aims_draft.md",
             "manuscript": "unpublished_manuscript.md"}
    await page.goto(base + "/#/")
    await page.wait_for_timeout(1200)
    rec = Recorder(page, "private", RAW)
    await rec.start()
    await rec.hold(600)
    await click(page, page.locator("summary:has-text('Options')"))
    link = page.locator("text=Private mode: add a CV")
    await rec.focus(link, pad=80)
    await rec.hold(700)
    await click(page, link)
    await rec.hold(600)
    rec.wide()
    start = page.locator("text=Start a private session")
    await rec.focus(page.locator(".private"), pad=10)
    await rec.hold(1500)
    await click(page, start)
    await rec.hold(500)
    for kind, name in files.items():
        box = page.locator(f"#doc-{kind}")
        await click(page, box, steps=8)
        await box.fill((PERSONA / name).read_text())
        await click(page, page.locator(f"#doc-{kind} ~ .doc-actions button:has-text('Add text')"),
                    steps=8)
        await page.wait_for_timeout(500)
    await rec.focus(page.locator(".private-docs"), pad=10)
    await rec.hold(1200)
    build = page.locator("button:has-text('Build private brief')")
    await click(page, build)
    rec.wide()
    await rec.quickly(lambda: page.locator("text=Brief ready").wait_for(timeout=240_000),
                      speed=12)
    await rec.hold(800)
    await click(page, page.locator("#tab-routes"))
    await rec.hold(700)
    lead = page.locator(".leads > li").first
    await click(page, lead.locator("summary[data-key=why]"))
    await rec.hold(400)
    await rec.focus(lead, pad=16)
    await rec.hold(3600)
    rec.wide()
    await rec.hold(500)
    await rec.stop()
    await page.locator("text=End private session").first.click()
    return rec


SCENES = {"hero": hero, "industry": industry, "handoff": handoff, "scout": scout,
          "private": private}


async def main(base: str, names: list[str], width: int, fps: int, quality: int) -> None:
    alias = aliases()
    exe = sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))[-1]
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        for name in names:
            ctx = await b.new_context(viewport=VIEW, device_scale_factor=2,
                                      color_scheme="light")
            page = await ctx.new_page()
            await Recorder.install(page)
            await alias_responses(page, alias)
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            await SCENES[name](page, base)
            await ctx.close()
            subprocess.run([sys.executable, str(Path(__file__).with_name("animate.py")),
                            str(RAW / name), str(OUT / f"{name}.webp"), "--width", str(width),
                            "--fps", str(fps), "--quality", str(quality)], check=True)
            if errors:
                print(f"{name}: page errors: {errors}")
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8090")
    ap.add_argument("--scenes", nargs="*", default=list(SCENES))
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--quality", type=int, default=70)
    a = ap.parse_args()
    asyncio.run(main(a.base, a.scenes, a.width, a.fps, a.quality))
