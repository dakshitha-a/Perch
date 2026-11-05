"""Film the README tour clips in the running v1 app.

Each scene drives the real web app in headless Chromium at twice the window's pixels and
records it with scripts/tour/recorder.py; scripts/tour/animate.py turns each recording into
<out>/<scene>.webp.

Scenes (each 10 to 25 seconds once slow waits are played back quickly):
  hero      guest student: landing, "Try it as a guest", the SYNTHETIC sample student, the brief
            builds, scroll the list, open one card's evidence
  awards    Browse Temple awards: a school chip, sort by closing date, one award's evidence
  researcher guest researcher: find an OpenAlex id (--author), the brief, Grants, Temple
            internal when the brief has it, the top lead's evidence
  keep      signed in: keep two leads, Compare and draft, the table, a hand-off draft
  myperch   signed in: My Perch with kept items, a brief row, "Change details and run again"
  scout     signed in: one example question to Scout and its cited answer
  points    signed in: cover-letter points on one card

Researchers appear by alias only: every JSON response that passes through the browser has a
researcher's display name replaced with the alias from data/overrides/pi_aliases.csv
(scripts/tour/names.py). The signed-in scenes film SYNTHETIC text only and need --login.

  uv run --no-project --with playwright --with pillow python scripts/tour/film.py \\
      --base http://127.0.0.1:8191 --scenes hero awards researcher --out build/tour_test

Sign in (the signed-in scenes), either way:
  --login scripts/e2e_oidc_login.py   a helper with login(base) returning an httpx client whose
                                      cookies are the session, as ux_walk's --login-helper
  PERCH_TOUR_USER and PERCH_TOUR_PASSWORD in the environment (the default when set):
                                      the script fills the Keycloak form the app redirects to.
                                      The password is never printed or logged.
A scene whose element is missing fails with a message and the next scene runs.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from playwright.async_api import Page, Route, async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from names import swap_names  # noqa: E402
from recorder import Recorder, click  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "build/tour"
AUTHOR = "A5063022331"  # PI-1
VIEW = {"width": 1280, "height": 800}
SIGNED_IN = {"keep", "myperch", "scout", "points"}
LONG = 300_000  # a brief build, in ms


class SceneError(Exception):
    """A scene's element was not there; the message says which."""


def aliases() -> dict[str, str]:
    """Real display name -> alias, from the alias table."""
    with (ROOT / "data/overrides/pi_aliases.csv").open() as f:
        return {r["name"]: r["alias"] for r in csv.DictReader(f) if r.get("name")}


async def alias_responses(page: Page, names: dict[str, str]) -> None:
    """Swap every researcher name in the app's JSON answers; pages, scripts and styles pass."""
    async def handle(route: Route) -> None:
        try:
            if route.request.resource_type not in ("fetch", "xhr"):
                await route.continue_()
                return
            r = await route.fetch()
            if "json" not in r.headers.get("content-type", ""):
                await route.fulfill(response=r)
                return
            body = await r.text()
            try:
                # GET /briefs/<id> writes JSON with ASCII escapes ("ó"), which a name
                # swap on the raw text cannot match; the text is decoded to letters first (S52).
                body = json.dumps(json.loads(body), ensure_ascii=False, separators=(",", ":"))
            except ValueError:
                pass
            body = swap_names(body, names)
            # An ORCID leads straight to the person, so it goes too.
            body = re.sub(r'"orcid":\s*"[^"]*"', '"orcid": null', body)
            await route.fulfill(response=r, body=body)
        except Exception:  # noqa: BLE001 - the page closed mid-request
            return

    await page.route("**/*", handle)


# ---------- small helpers ----------

async def need(page: Page, selector: str, what: str, timeout: int = 20_000):  # noqa: ANN201
    """Wait for an element or fail the scene saying which one is missing."""
    loc = page.locator(selector).first
    try:
        await loc.wait_for(timeout=timeout)
    except Exception as e:  # noqa: BLE001
        raise SceneError(f"{what} not found ({selector}) after {timeout // 1000} s") from e
    return loc


async def scroll_by(page: Page, dy: int, steps: int = 6, pause: int = 70) -> None:
    """A calm scroll: small wheel steps, so the camera and the pointer stay readable."""
    for _ in range(steps):
        await page.mouse.wheel(0, dy / steps)
        await page.wait_for_timeout(pause)


async def settle(page: Page, ms: int = 600) -> None:
    await page.wait_for_timeout(ms)


async def session(page: Page) -> dict:
    return await page.evaluate("fetch('/auth/session').then(r => r.json())")


async def start_guest(page: Page, base: str, who: str = "s") -> None:
    """Landing, the side chosen, "Try it as a guest"."""
    await page.goto(base + "/#/")
    await need(page, ".landing h1", "the landing page")
    if who == "r":
        await page.click("[data-key=seg-r]")
    await page.click("[data-key=guest-start]")
    await need(page, "[data-key=guest-banner]", "the guest banner")


def evidence_box(page: Page, rail: bool):  # noqa: ANN201 - a Locator
    """The record opens in the rail on a brief's list, in the sheet on a browse list."""
    return page.locator("#rail-ev" if rail else "#evidence-body")


async def pick_author(page: Page, rec: Recorder | None, author: str) -> None:
    """Type an OpenAlex id in the researcher search, then Build brief. With `rec`, on camera."""
    q = page.locator("#q")
    await q.wait_for()
    if rec:
        await click(page, q)
        await q.press_sequentially(author, delay=70)
        await rec.focus(page.locator("form[role=search]").first, pad=30)
        await rec.hold(500)
        await click(page, page.locator(".searchbox button[type=submit]").first)
    else:
        await q.fill(author)
        await page.click(".searchbox button[type=submit]")
    await need(page, "[data-key=build], .cand button", "a match for the OpenAlex id", 60_000)
    if rec:
        await rec.hold(900)
    if not await page.locator("[data-key=build]").count():  # more than one match: pick the first
        await (click(page, page.locator(".cand button").first) if rec
               else page.locator(".cand button").first.click())
    await need(page, "[data-key=build]", "the Build brief button", 20_000)
    if rec:
        await rec.hold(700)


async def build_and_wait(page: Page, rec: Recorder | None, button: str, speed: float = 12) -> None:
    """Press the build button; the wait for the first lead plays back quickly."""
    await (click(page, page.locator(button).first) if rec else page.locator(button).first.click())
    wait = page.locator("#panel .leads > li").first.wait_for(timeout=LONG)
    try:
        await (rec.quickly(lambda: wait, speed=speed) if rec else wait)
    except Exception as e:  # noqa: BLE001
        raise SceneError(f"the brief did not show a lead in {LONG // 1000} s") from e
    # Then the rest of the build (explanations, industry leads), also played quickly, so the
    # scene shows a finished brief. A slow finish is not a failure: the leads are there.
    done = page.locator("#progress .pcard").wait_for(state="detached", timeout=120_000)
    try:
        await (rec.quickly(lambda: done, speed=speed) if rec else done)
    except Exception:  # noqa: BLE001
        print("the brief was still building when the scene went on")
    await settle(page, 900)


# ---------- signing in ----------

async def sign_in(page: Page, base: str, login: str | None) -> None:
    """Sign in before a signed-in scene, off camera. Never prints the password."""
    user, pw = os.environ.get("PERCH_TOUR_USER"), os.environ.get("PERCH_TOUR_PASSWORD")
    if login and login != "env":
        spec = importlib.util.spec_from_file_location("tour_login_helper", login)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        client = mod.login(base)
        await page.context.add_cookies(
            [{"name": c.name, "value": c.value, "url": base} for c in client.cookies.jar])
        await page.goto(base + "/")
    elif user and pw:
        await page.goto(base + "/auth/login")
        try:
            await page.locator("#username").wait_for(timeout=30_000)
        except Exception as e:  # noqa: BLE001
            raise SceneError("the Keycloak login form (#username) did not appear") from e
        await page.fill("#username", user)
        await page.fill("#password", pw)
        await page.click("#kc-login")
        await page.wait_for_url(re.compile(re.escape(base) + ".*"), timeout=30_000)
    else:
        raise SceneError("no sign-in: pass --login <helper.py> or set PERCH_TOUR_USER and "
                         "PERCH_TOUR_PASSWORD")
    await page.wait_for_selector("#acct-btn, .welcome", timeout=30_000)
    if await page.locator(".welcome").count() or "#/welcome" in page.url:
        # First visit: choose the researcher side and agree, as a new user would.
        await need(page, "[data-key=agree]", "the consent checkbox on the welcome step")
        if not await page.locator("[data-key^=role-]:checked").count():
            await page.check("[data-key=role-researcher]")
        if not await page.locator("[data-key=agree]").is_checked():
            await page.check("[data-key=agree]")
        await page.click("[data-key=continue]")
        await page.wait_for_selector("#acct-btn", timeout=30_000)
    s = await session(page)
    if not s.get("signed_in"):
        raise SceneError("the sign-in did not give a signed-in session")


async def open_brief(page: Page, base: str, author: str, tab: str = "routes") -> str:
    """Off camera: the newest brief on My Perch, or a new one when there is none. Returns the
    side ("student" or "researcher")."""
    aud = (await session(page)).get("audience") or "student"
    await page.goto(base + "/#/me")
    await need(page, ".my-perch", "My Perch")
    await need(page, ".brief-row, .home-briefs .empty-list", "the Briefs box")
    row = page.locator(".brief-row a.btn").first
    if await row.count():
        await row.click()
    elif aud == "student":
        await page.goto(base + "/#/student")
        await need(page, ".student-start", "the Check my fit form")
        load = page.locator("[data-key=load-sample]")
        if await load.count():
            await load.click()
            await page.click("[data-key=cv-save]")
            await page.wait_for_selector("[data-key=st-build]:not([disabled])", timeout=60_000)
        await page.click("[data-key=st-build]")
    else:
        await page.goto(base + "/#/start")
        await pick_author(page, None, author)
        await page.click("[data-key=build]")
    await need(page, "#panel .leads > li", "a brief with leads", LONG)
    await settle(page, 900)
    if tab != "routes":
        await page.click(f"#tab-{tab}")
        await settle(page, 800)
    return aud


# ---------- scenes ----------

async def hero(page: Page, base: str, o: argparse.Namespace) -> Recorder:
    await page.goto(base + "/#/")
    await need(page, ".landing h1", "the landing page")
    await settle(page, 800)
    rec = Recorder(page, "hero", RAW)
    await rec.start()
    await rec.hold(1400)
    # Accounts open: "Try it as a guest" starts the guest. Accounts closed (S51 D4): the
    # landing has no guest line, and "Try a sample student" starts the guest instead.
    if await page.locator("[data-key=guest-start]").count():
        await click(page, page.locator("[data-key=guest-start]"))
    else:
        await click(page, page.locator("[data-key=fit]"))
    await need(page, "[data-key=guest-banner]", "the guest banner")
    await rec.hold(1500)
    fit = await need(page, "[data-key=fit]", "the Try a sample student button")
    await click(page, fit)
    await need(page, ".student-start", "the Check my fit screen")
    await rec.hold(700)
    await rec.focus(page.locator(".student-start"), pad=10)
    await rec.hold(2200)
    rec.wide()
    await build_and_wait(page, rec, "[data-key=st-build]", speed=14)
    await rec.hold(800)
    first = page.locator("#panel .leads > li").first
    # The first card starts at the bottom edge: bring it up before the camera moves in.
    top = await first.evaluate("e => e.getBoundingClientRect().top")
    await scroll_by(page, max(0, top - 120), steps=8)
    await rec.hold(500)
    await rec.focus(first, pad=20)
    await rec.hold(2200)
    rec.wide()
    await scroll_by(page, 520)
    await rec.hold(900)
    await scroll_by(page, -520)
    await rec.hold(600)
    # The rail is sticky, so the record opens beside the card in view.
    await click(page, first.locator(".title-btn").first)
    box = evidence_box(page, rail=True)
    await need(page, "#rail-ev .rec-title", "the record in the evidence rail")
    await page.locator("#rail-ev .rec-title").scroll_into_view_if_needed()
    await rec.hold(500)
    await rec.focus(box, pad=10)
    await rec.hold(3200)
    rec.wide()
    await rec.hold(700)
    await rec.stop()
    return rec


async def awards(page: Page, base: str, o: argparse.Namespace) -> Recorder:
    await page.goto(base + "/#/")
    await need(page, ".landing h1", "the landing page")
    await settle(page, 600)
    rec = Recorder(page, "awards", RAW)
    await rec.start()
    await rec.hold(1000)
    await click(page, page.locator("[data-key=browse-awards]"))
    await need(page, ".award", "the award list", 30_000)
    await need(page, ".tag-chip", "the school chips")
    await rec.hold(1200)
    rec.wide()
    chips = page.locator(".tag-chip[data-key^='tag-s:']")
    if not await chips.count():
        raise SceneError("no school chip (data-key tag-s:...) on the award list")
    chip = chips.first
    await rec.focus(page.locator(".tag-row"), pad=24)
    await rec.hold(900)
    await click(page, chip)
    await settle(page, 1300)
    await rec.hold(1200)
    rec.wide()
    sort = page.locator("#list-sort")
    await need(page, "#list-sort", "the Sort by menu")
    await rec.focus(sort, pad=60)
    await click(page, sort)
    await sort.select_option("closing")
    await settle(page, 1200)
    await rec.hold(1000)
    rec.wide()
    await rec.hold(500)
    await scroll_by(page, 300, steps=5)
    await rec.hold(900)
    row = page.locator(".award").first
    await rec.focus(row, pad=20)
    await rec.hold(1000)
    await click(page, row.locator(".title-btn").first)
    await need(page, "#evidence-body .rec-title", "the award's evidence")
    await rec.hold(700)
    await rec.focus(evidence_box(page, rail=False), pad=10)
    await rec.hold(3200)
    rec.wide()
    await rec.hold(600)
    await rec.stop()
    return rec


async def researcher(page: Page, base: str, o: argparse.Namespace) -> Recorder:
    await page.goto(base + "/#/")
    await need(page, ".landing h1", "the landing page")
    await settle(page, 600)
    rec = Recorder(page, "researcher", RAW)
    await rec.start()
    await rec.hold(900)
    await click(page, page.locator("[data-key=seg-r]"))
    await rec.hold(700)
    await click(page, page.locator("[data-key=guest-start]"))
    await need(page, "[data-key=guest-banner]", "the guest banner")
    await rec.hold(500)
    await need(page, "#q", "the researcher search box")
    await pick_author(page, rec, o.author)
    rec.wide()
    await build_and_wait(page, rec, "[data-key=build]", speed=14)
    await rec.hold(900)
    await need(page, "[data-key=route-A]", "the Grants route button")
    await rec.focus(page.locator(".route-switch:not(.sort-switch)").first, pad=30)
    await rec.hold(1300)
    rec.wide()
    top = page.locator("#panel .leads > li").first
    await rec.focus(top, pad=20)
    await rec.hold(1800)
    if await page.locator("[data-key=route-T]").count():
        await click(page, page.locator("[data-key=route-T]"))
        await need(page, "#panel .leads > li", "the Temple internal leads")
        await rec.hold(900)
        await rec.focus(page.locator("#panel .leads > li").first, pad=20)
        await rec.hold(1800)
        await click(page, page.locator("[data-key=route-A]"))
        await need(page, "#panel .leads > li", "the Grants leads")
        await rec.hold(700)
        top = page.locator("#panel .leads > li").first
    rec.wide()
    await click(page, top.locator(".title-btn").first)
    await need(page, "#rail-ev .rec-title", "the lead's record in the evidence rail")
    await page.locator("#rail-ev .rec-title").scroll_into_view_if_needed()
    await rec.hold(500)
    await rec.focus(evidence_box(page, rail=True), pad=10)
    await rec.hold(3200)
    rec.wide()
    await rec.hold(600)
    await rec.stop()
    return rec


async def keep(page: Page, base: str, o: argparse.Namespace) -> Recorder:
    aud = await open_brief(page, base, o.author)
    rec = Recorder(page, "keep", RAW)
    await rec.start()
    await rec.hold(800)
    btns = page.locator("#panel .leads > li .btn.keep:not(.on)")
    for _ in range(2):
        if not await btns.count():
            break
        b = btns.first
        await rec.focus(b.locator("xpath=ancestor::li[1]"), pad=16)
        await click(page, b)
        await rec.hold(800)
    rec.wide()
    await need(page, "[data-key=sl-compare]:not([disabled])", "an enabled Compare and draft button")
    await rec.focus(page.locator(".shortlist"), pad=40)
    await rec.hold(1500)
    await click(page, page.locator("[data-key=sl-compare]"))
    table = await need(page, "#panel table", "the comparison table")
    await settle(page, 500)
    rec.wide(ease=0.4)
    await rec.hold(500)
    await rec.focus(table, pad=20)
    await rec.hold(3000)
    rec.wide()
    if aud == "student":
        # Code writes the note at once; there is no Draft button.
        await need(page, "#st-body", "the student's note to the office", 60_000)
        await page.locator("#st-body").scroll_into_view_if_needed()
        await rec.hold(500)
        await rec.focus(page.locator(".handoff"), pad=24)
        await rec.hold(3600)
    else:
        make = await need(page, "[data-key=handoff-make]", "the Draft the email button")
        await make.scroll_into_view_if_needed()
        await rec.focus(page.locator(".office-pick").first, pad=40)
        await rec.hold(2200)
        await click(page, make)
        subject = page.locator("[data-key=handoff-subject]")
        try:
            await rec.quickly(lambda: subject.wait_for(timeout=180_000), speed=10)
        except Exception as e:  # noqa: BLE001
            raise SceneError("the hand-off draft did not appear in 180 s") from e
        await subject.evaluate("e => window.scrollBy(0, e.getBoundingClientRect().top - 150)")
        await rec.hold(400)
        await rec.focus(page.locator("#handoff-body"), pad=30)
        await rec.hold(3600)
    rec.wide()
    await rec.hold(600)
    await rec.stop()
    return rec


async def myperch(page: Page, base: str, o: argparse.Namespace) -> Recorder:
    await page.goto(base + "/#/me")
    await need(page, ".my-perch", "My Perch")
    await need(page, ".brief-row, .home-briefs .empty-list", "the Briefs box")
    await settle(page, 800)
    rec = Recorder(page, "myperch", RAW)
    await rec.start()
    await rec.hold(1500)
    kept = page.locator(".home-kept")
    await rec.focus(kept, pad=20)
    await rec.hold(3200)
    brief = page.locator(".brief-row").first
    if not await brief.count():
        raise SceneError("no brief row on My Perch; film `keep` or build a brief first")
    await rec.focus(brief, pad=24)
    await rec.hold(2200)
    again = brief.locator("a.quiet-link")
    await need(page, ".brief-row a.quiet-link", "Change details and run again")
    await click(page, again.first)
    await need(page, "#st-title, .screen, #pick-title", "the form with the brief's details")
    await rec.hold(2600)
    rec.wide()
    await rec.hold(500)
    await rec.stop()
    return rec


async def scout(page: Page, base: str, o: argparse.Namespace) -> Recorder:
    await open_brief(page, base, o.author, tab="scout")
    chips = page.locator(".scout-try .chip")
    await need(page, ".scout-try .chip", "an example question chip")
    rec = Recorder(page, "scout", RAW)
    await rec.start()
    await rec.hold(1000)
    await rec.focus(page.locator(".scout-try"), pad=30)
    await rec.hold(2000)
    await click(page, chips.nth(min(o.chip, await chips.count() - 1)))
    rec.wide()
    answer = page.locator(".scout-answer").last
    try:
        await rec.quickly(lambda: answer.wait_for(timeout=240_000), speed=10)
    except Exception as e:  # noqa: BLE001
        raise SceneError("Scout gave no answer in 240 s") from e
    await settle(page, 1200)
    await rec.hold(700)
    await rec.focus(answer, pad=30)
    await rec.hold(3800)
    records = page.locator(".scout-x").last.locator(".scout-records")
    if await records.count():
        await records.first.scroll_into_view_if_needed()
        await rec.focus(records.first, pad=40)
        await rec.hold(2800)
    rec.wide()
    await rec.hold(600)
    await rec.stop()
    return rec


async def points(page: Page, base: str, o: argparse.Namespace) -> Recorder:
    await open_brief(page, base, o.author)
    btn = await need(page, "#panel [data-key^=cover-]", "a Cover-letter points button")
    card = btn.locator("xpath=ancestor::li[1]")
    rec = Recorder(page, "points", RAW)
    await rec.start()
    await rec.hold(800)
    await card.scroll_into_view_if_needed()
    await rec.focus(card, pad=20)
    await rec.hold(1500)
    block = card.locator(".scout-points")
    for attempt in range(3):  # a withheld answer is asked again, up to three tries
        await click(page, card.locator("[data-key^=cover-]").first)
        rec.wide()
        try:
            await rec.quickly(lambda: block.first.wait_for(timeout=240_000), speed=10)
        except Exception as e:  # noqa: BLE001
            raise SceneError("no cover-letter points in 240 s") from e
        await settle(page, 900)
        if not await block.first.locator(".notice.warn").count():
            break
        print(f"points: attempt {attempt + 1} withheld")
    else:
        raise SceneError("the points were withheld three times")
    await block.first.scroll_into_view_if_needed()
    await rec.focus(block.first, pad=24)
    await rec.hold(4500)
    miss = block.first.locator(".points-missing")
    if await miss.count():
        await rec.focus(miss.first, pad=40)
        await rec.hold(2200)
    rec.wide()
    await rec.hold(600)
    await rec.stop()
    return rec


SCENES = {"hero": hero, "awards": awards, "researcher": researcher, "keep": keep,
          "myperch": myperch, "scout": scout, "points": points}


async def main(a: argparse.Namespace) -> int:
    alias = aliases()
    out = Path(a.out)
    out = out if out.is_absolute() else ROOT / out
    exe = sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe[-1] if exe else None,
                                    args=["--no-sandbox"])
        for name in a.scenes:
            if name not in SCENES:
                print(f"{name}: unknown scene (have {', '.join(SCENES)})")
                failed += 1
                continue
            ctx = await b.new_context(viewport=VIEW, device_scale_factor=2, color_scheme="light")
            page = await ctx.new_page()
            page.set_default_timeout(20_000)
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            try:
                await Recorder.install(page)
                await alias_responses(page, alias)
                if name in SIGNED_IN:
                    await sign_in(page, a.base, a.login)
                await SCENES[name](page, a.base, a)
            except SceneError as e:
                print(f"{name}: FAILED - {e}")
                failed += 1
                await ctx.close()
                continue
            except Exception as e:  # noqa: BLE001 - a timeout or a closed page
                print(f"{name}: FAILED - {type(e).__name__}: {str(e).splitlines()[0][:160]}")
                failed += 1
                await ctx.close()
                continue
            await ctx.close()
            done = subprocess.run([sys.executable, str(Path(__file__).with_name("animate.py")),
                            str(RAW / name), str(out / f"{name}.webp"), "--width", str(a.width),
                            "--fps", str(a.fps), "--quality", str(a.quality)], check=True,
                capture_output=True, text=True)
            # animate.py prints "<file>: N frames, 22.4 s, 2.3 MB"; that is the clip's real length.
            m = re.search(r"([\d.]+) s,", done.stdout)
            print(f"{name}: filmed, {m.group(1) if m else '?'} s -> {out / (name + '.webp')}")
            if errors:
                print(f"{name}: page errors: {errors}")
        await b.close()
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:8191")
    ap.add_argument("--scenes", nargs="*", default=list(SCENES))
    ap.add_argument("--out", default="docs/tour", help="where the .webp files go")
    ap.add_argument("--author", default=AUTHOR, help="OpenAlex id for the researcher scenes")
    ap.add_argument("--login", default=None,
                    help="a helper .py with login(base), or 'env' for PERCH_TOUR_USER/PASSWORD")
    ap.add_argument("--chip", type=int, default=0, help="which Scout example chip (0-based)")
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--quality", type=int, default=70)
    sys.exit(asyncio.run(main(ap.parse_args())))
