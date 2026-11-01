"""Film the README clips in the running app (S15).

Each scene drives the real web app in headless Chromium at twice the window's pixels and
records it with scripts/tour/recorder.py; scripts/tour/animate.py (NextTex's camera) turns
each recording into docs/tour/<scene>.webp.

Researchers appear by alias only: every API response passing through the browser has the
researcher's display name replaced with their alias from data/overrides/pi_aliases.csv,
as the replay preview does. Paper titles and records are public and shown as they are.
Private mode is filmed with the SYNTHETIC persona-1 files.

  uv run --with playwright --with pillow python scripts/tour/film.py \\
      [--base http://127.0.0.1:8090] [--scenes hero industry handoff scout private student]

The demo (`make demo`) or a dev server on the same settings must be up, with private mode
on for the private and student scenes.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import glob
import json
import os
import re
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
SCOUT_Q = "Which of my NSF leads close by 1 Mar 2027?"  # one of Scout's own examples


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
            ctype = r.headers.get("content-type", "")
            if "json" not in ctype and "/export." not in route.request.url:  # exports too
                await route.fulfill(response=r)
                return
            body = await r.text()
            for real, alias in names.items():
                body = body.replace(real, alias)
            # Model text can name a researcher by surname alone ("Dr. ..."), so the
            # surnames go too, as whole words.
            for real, alias in names.items():
                last = real.split()[-1]
                if len(last) > 2:
                    body = re.sub(rf"\b{re.escape(last)}\b", alias, body)
            # An ORCID leads straight to the person, so it goes too, as in the replay.
            body = re.sub(r'"orcid":\s*"[^"]*"', '"orcid": null', body)
            await route.fulfill(response=r, body=body)
        except Exception:  # noqa: BLE001 - the page closed mid-request
            return

    for path in ("/authors/**", "/briefs/**", "/records/**", "/scout/**", "/private/**"):
        await page.route(f"**{path}", handle)


def evidence_panel(page: Page):  # noqa: ANN201 - a Locator
    """The record opens in the rail on a laptop (S24), in the sheet otherwise."""
    return page.locator("#rail-ev")


async def pick(page: Page, rec: Recorder | None = None) -> None:
    """Search the demo researcher and pick them (S24 pick screen)."""
    q = page.locator("#q")
    if rec:
        await click(page, q)
        await q.press_sequentially(AUTHOR, delay=70)
        await rec.focus(page.locator("form[role=search]"), pad=30)
        await rec.hold(300)
        await click(page, page.locator(".searchbox button[type=submit]"))
    else:
        await page.fill("#q", AUTHOR)
        await page.click(".searchbox button[type=submit]")
    card = page.locator(".cand").first
    if rec:
        await rec.quickly(lambda: card.wait_for())
        await rec.focus(card, pad=30)
        await rec.hold(1200)
        if await card.locator("button.btn.outline").count():  # an exact id picks itself (W1)
            await click(page, card.locator("button.btn.outline"))
            await rec.hold(500)
    elif await card.locator("button.btn.outline").count():
        await card.locator("button.btn.outline").click()


async def hero(page: Page, base: str) -> Recorder:
    await page.goto(base + "/#/")
    await page.wait_for_timeout(1200)
    rec = Recorder(page, "hero", RAW)
    await rec.start()
    await rec.hold(900)
    await pick(page, rec)
    rec.wide()
    await rec.hold(900)
    await click(page, page.locator("[data-key=build]"))
    await rec.quickly(lambda: page.locator(".leads > li").first.wait_for(timeout=240_000))
    await page.wait_for_timeout(1200)
    await rec.hold(1200)
    lead = page.locator(".leads > li").first
    await rec.focus(lead, pad=20)
    await rec.hold(1600)
    await click(page, lead.locator("summary[data-key=why]"))
    await rec.hold(500)
    await rec.focus(lead, pad=20)
    await rec.hold(1800)
    await click(page, lead.locator(".paper-ref").first)
    panel = evidence_panel(page)
    await panel.locator(".rec-title").wait_for()
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
    await pick(page)
    await page.click("[data-key=build]")
    await page.locator("text=Brief ready").wait_for(timeout=300_000)
    await page.wait_for_timeout(1200)


async def industry(page: Page, base: str) -> Recorder:
    await open_brief(page, base)
    rec = Recorder(page, "industry", RAW)
    await rec.start()
    await rec.hold(800)
    btn = page.locator("[data-key=route-B]")
    await rec.focus(page.locator(".route-switch:not(.sort-switch)"), pad=30)
    await click(page, btn)
    await rec.hold(900)
    rec.wide()
    await rec.hold(900)
    lead = page.locator(".leads > li").first
    # The card's head down to its Inference line: tags, name, other names, the label.
    top = await lead.evaluate("""e => { const a = e.getBoundingClientRect(),
        b = e.querySelector('.provenance').getBoundingClientRect();
        return {x: a.x, y: a.y, width: a.width, height: b.bottom - a.y}; }""")
    await rec.focus(top, pad=30)
    await rec.hold(2200)
    # Each kind of signal with its newest record; the rest stay folded (S22).
    for sig in (await lead.locator(".signals > li").all())[:2]:
        await sig.scroll_into_view_if_needed()
        await rec.focus(sig, pad=24)
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
        if not await keeps.nth(i).is_visible():  # weak matches fold under a count (U24)
            await click(page, page.locator("details.weak-fold > summary"))
        await rec.focus(page.locator(".leads > li").nth(i), pad=16)
        await click(page, keeps.nth(i))
        await rec.hold(700)
    rec.wide()
    bar = page.locator("[data-key=sl-compare]")
    await rec.focus(page.locator(".shortlist"), pad=40)
    await rec.hold(1200)
    await click(page, bar)
    rec.wide(ease=0.4)
    table = page.locator("#panel table").first
    await table.wait_for()
    await page.wait_for_timeout(300)
    # The hand-off form (office, Draft the email) sits above the table (review W2).
    await page.locator("#handoff-title").evaluate(
        "e => window.scrollBy(0, e.getBoundingClientRect().top - 130)")
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
    # The subject line just under the sticky bar and tabs, the email below it.
    await subject.evaluate("e => window.scrollBy(0, e.getBoundingClientRect().top - 150)")
    await rec.hold(400)
    await rec.focus(draft, pad=30)
    await rec.hold(3600)
    rec.wide()
    await rec.hold(700)
    await rec.stop()
    return rec


async def scout(page: Page, base: str) -> Recorder:
    """Ask Scout (S27, S28): a chat with the box at the bottom. The answer comes with
    "How Scout read your question", one line per step with its filters; the step cards
    fold under Steps; New conversation sits beside the box."""
    await open_brief(page, base)
    await page.click("#tab-scout")
    await page.wait_for_timeout(800)
    rec = Recorder(page, "scout", RAW)
    await rec.start()
    await rec.hold(900)
    q = page.locator("#scout-q")
    await click(page, q)
    await q.press_sequentially(SCOUT_Q, delay=45)
    await rec.focus(page.locator(".scout-ask"), pad=40)
    await rec.hold(500)
    await click(page, page.locator(".scout-ask button[type=submit]"))
    rec.wide()
    answer = page.locator(".scout-answer").last
    await rec.quickly(lambda: answer.wait_for(timeout=240_000), speed=8)
    await page.wait_for_timeout(1500)
    await rec.hold(800)
    read = page.locator(".scout-x").last.locator(".scout-read")
    if await read.count():
        await rec.focus(read, pad=24)
        await rec.hold(3000)
    await rec.focus(answer, pad=30)
    await rec.hold(3600)
    steps = page.locator(".scout-x").last.locator("details.scout-steps > summary")
    if await steps.count():
        await click(page, steps)
        await rec.hold(400)
        await page.locator(".scout-scroll").evaluate(
            "b => { const c = b.querySelector('.scout-x:last-child .scout-cards');"
            " if (c) b.scrollTop += c.getBoundingClientRect().top"
            " - b.getBoundingClientRect().top - 40; }")
        await rec.hold(300)
        await rec.focus(page.locator(".scout-x").last.locator(".scout-cards"), pad=24)
        await rec.hold(2600)
    await rec.focus(page.locator(".scout-ask"), pad=60)
    await rec.hold(1400)
    rec.wide()
    await rec.hold(800)
    await rec.stop()
    return rec


async def private(page: Page, base: str) -> Recorder:
    """Tell Perch more (S24): the SYNTHETIC sample's direction, keywords and draft aims
    steer a brief whose explanations cite the draft with a lock."""
    await page.goto(base + "/#/")
    await page.wait_for_timeout(1200)
    rec = Recorder(page, "private", RAW)
    await rec.start()
    await rec.hold(600)
    await pick(page, rec)
    panel = page.locator(".more-panel")
    await click(page, page.locator("[data-key=more-ctx]"))  # folded under Build (W1)
    await rec.focus(panel, pad=10)
    await rec.hold(900)
    await click(page, page.locator("[data-key=fill-sample]"))
    await rec.hold(700)
    # The filled fields. The pick screen fades back in after the fill; a camera move
    # after it makes the clip redraw every pixel, so no part of the fade stays behind.
    await page.locator("#sample-status").evaluate(
        "e => window.scrollBy(0, e.getBoundingClientRect().top - 110)")
    await page.wait_for_timeout(300)
    grid = await page.locator(".more-panel .box-grid").evaluate("""e => {
        const a = e.getBoundingClientRect();
        return {x: a.x, y: a.y, width: a.width,
                height: Math.min(a.height, innerHeight - a.y - 20)}; }""")
    await rec.focus(grid, pad=16)
    await rec.hold(3000)
    await page.evaluate("window.scrollTo(0, 0)")
    rec.wide()
    await rec.hold(500)
    await click(page, page.locator("[data-key=build]"))
    await rec.quickly(lambda: page.locator("text=Brief ready").wait_for(timeout=300_000),
                      speed=30)
    await rec.hold(800)
    lead = page.locator(".leads > li").first
    why = lead.locator("details.why")
    if not await why.evaluate("e => e.open"):  # open by itself when it cites a document
        await click(page, lead.locator("summary[data-key=why]"))
        await rec.hold(400)
    await why.evaluate("e => window.scrollBy(0, e.getBoundingClientRect().top - 160)")
    await page.wait_for_timeout(300)
    await rec.focus(why, pad=20)
    await rec.hold(4000)
    rec.wide()
    await rec.hold(500)
    await rec.stop()
    await page.click("#end-session")
    await page.click("[data-key=end-ok]")
    return rec


async def student(page: Page, base: str) -> Recorder:
    """Student mode (S24) with the SYNTHETIC persona-ug sample: the form, then the sample
    scholarships tab with its badges."""
    await page.goto(base + "/#/")
    await page.wait_for_timeout(1000)
    rec = Recorder(page, "student", RAW)
    await rec.start()
    await rec.hold(600)
    await click(page, page.locator("[data-key=seg-s]"))
    await rec.hold(400)
    await click(page, page.locator("[data-key=student]"))
    await page.locator("[data-key=st-fill]").wait_for()
    await click(page, page.locator("[data-key=st-fill]"))
    await rec.hold(700)
    await rec.focus(page.locator(".st-cols"), pad=16)
    await rec.hold(1800)
    rec.wide()
    await click(page, page.locator("[data-key=st-build]"))
    await rec.quickly(lambda: page.locator("text=Brief ready").wait_for(timeout=300_000),
                      speed=30)
    await click(page, page.locator("[data-key=route-S]"))
    await rec.hold(900)
    card = page.locator(".leads > li").first
    await card.evaluate("e => window.scrollBy(0, e.getBoundingClientRect().top - 150)")
    await page.wait_for_timeout(300)
    await rec.focus(card, pad=16)
    await rec.hold(3600)
    rec.wide()
    await rec.hold(600)
    await rec.stop()
    await page.click("#end-session")
    await page.click("[data-key=end-ok]")
    return rec


SCENES = {"hero": hero, "industry": industry, "handoff": handoff, "scout": scout,
          "private": private, "student": student}


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
