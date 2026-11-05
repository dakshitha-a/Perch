"""Take the repo screenshots in docs/screenshots/ from the running v1 app.

  uv run --no-project --with playwright --with pillow python scripts/screenshots.py \\
      --base https://<host> --env-file <file> [--only 5 6] [--view wide phone] [--scheme light dark]

Each screen is saved as <view>-<scheme>-<n>-<name>.png, where the view is wide (1280 by 800)
or phone (390 by 844 at 2x). Guest screens need no account. Signed-in screens use the
SYNTHETIC demo student and researcher accounts (DEMO_STUDENT_* and DEMO_RESEARCHER_* in the
environment; the passwords are never printed) and reuse the newest brief that already
exists on each account; nothing is built or changed. Researchers appear by alias only: every
JSON answer has real names swapped for the alias in data/overrides/pi_aliases.csv, and the
text of every screen is checked for a real name before it is saved (a hit fails the run and
the image is removed). Playwright is a dev-only tool, not a project dependency.

The transient Scout states are staged: the "working" glow holds the Scout request open
before it reaches the server, and "Conversation cleared. Undo" is the app's own line.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import os
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/tour"))
import film  # noqa: E402
from demo_films import NameCheck, alias_checked  # noqa: E402

VIEWS = {"wide": ({"width": 1280, "height": 800}, 1), "phone": ({"width": 390, "height": 844}, 2)}
STUDENT_PICK_BRIEF = "3d7c9535-c66f-43b9-bc2f-5d6cd399f2d1"  # a U.S. citizen pick, the Gilman card
RESEARCHER_BRIEF = None  # set from My Perch: the first brief on the account


class Shots:
    def __init__(self, out: Path, view: str, scheme: str, check: NameCheck, only: set[int]) -> None:
        self.out, self.view, self.scheme, self.check, self.only = out, view, scheme, check, only
        self.made: list[str] = []

    def want(self, n: int) -> bool:
        return not self.only or n in self.only

    async def snap(self, page: Page, n: int, name: str) -> None:
        await page.wait_for_timeout(350)
        before = len(self.check.hits)
        await self.check.screen(page, f"{self.view}-{self.scheme}-{n}")
        if len(self.check.hits) > before:
            return  # never save a screen with a real name on it
        path = self.out / f"{self.view}-{self.scheme}-{n}-{name}.png"
        await page.screenshot(path=str(path), animations="disabled")
        self.made.append(path.name)


def find_chrome() -> str | None:
    hits = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    return hits[-1] if hits else None


async def top(page: Page, locator, offset: int = 70) -> None:  # noqa: ANN001
    """Scroll an element to the top of the window, below the sticky bars."""
    await locator.evaluate("e => e.scrollIntoView({block: 'start'})")
    await page.evaluate(f"window.scrollBy(0, -{offset})")
    await page.wait_for_timeout(250)


async def sign_in_as(page: Page, base: str, side: str) -> None:
    os.environ["PERCH_TOUR_USER"] = os.environ[f"DEMO_{side}_USERNAME"]
    os.environ["PERCH_TOUR_PASSWORD"] = os.environ[f"DEMO_{side}_PASSWORD"]
    await film.sign_in(page, base, None)


async def open_brief(page: Page, base: str, brief: str | None, tab: str = "routes") -> None:
    if brief is None:
        await page.goto(base + "/#/me")
        await film.need(page, ".brief-row a.btn", "a brief on My Perch", 30_000)
        await page.wait_for_timeout(800)
        brief_href = await page.evaluate("document.querySelector('.brief-row a.btn').getAttribute('href')")
        await page.goto(base + "/" + brief_href.replace("/routes", f"/{tab}"))
    else:
        await page.goto(f"{base}/#/brief/{brief}/{tab}")
    await film.need(page, "#panel .leads > li, #panel .scout-ask-row, .prof-cols", "the brief", 60_000)
    await page.locator("#progress .pcard").wait_for(state="detached", timeout=120_000)
    await page.wait_for_timeout(1500)


async def guest_screens(page: Page, base: str, s: Shots) -> None:
    await page.goto(base + "/#/")
    await film.need(page, ".landing h1", "the landing page")
    await page.wait_for_timeout(600)
    if s.want(1):
        await s.snap(page, 1, "landing")
    if s.want(2):
        await page.goto(base + "/#/awards")
        await film.need(page, ".award", "the award list", 30_000)
        await s.snap(page, 2, "awards")
    if s.want(3):
        await page.goto(base + "/#/funding")
        await film.need(page, ".award, .lead, .funding-list li", "the funding list", 30_000)
        await s.snap(page, 3, "funding")
    if s.want(4):
        await page.goto(base + "/#/help")
        await film.need(page, "#h-researcher", "the Help page")
        await page.emulate_media(reduced_motion="reduce", color_scheme=s.scheme)  # figures complete
        await s.snap(page, 4, "help")
        await page.emulate_media(reduced_motion="no-preference", color_scheme=s.scheme)


async def researcher_screens(page: Page, base: str, s: Shots) -> None:
    await film.need(page, "#acct-btn", "the signed-in header")
    await open_brief(page, base, RESEARCHER_BRIEF)
    if s.want(14):
        await page.goto(base + "/#/start")
        await film.pick_author(page, None, film.AUTHOR)  # PI-1; the picks appear after the pick
        await film.need(page, "[data-key=picks-fold]", "the folded picks")
        await page.locator("[data-key=picks-fold] summary").scroll_into_view_if_needed()
        await page.evaluate("window.scrollBy(0, 160)")
        await s.snap(page, 14, "researcher-start-picks")
        await open_brief(page, base, RESEARCHER_BRIEF)
    if s.want(5):
        await page.evaluate("window.scrollTo(0, 0)")
        await s.snap(page, 5, "researcher-brief")
    if s.want(6):
        summ = page.locator(".lead .why summary").first
        await film.need(page, ".lead .why summary", "a Why it fits fold")
        if not await page.locator(".lead .why[open]").count():
            await summ.click()
        await page.wait_for_timeout(300)
        await top(page, page.locator(".lead").first, 80)
        await s.snap(page, 6, "researcher-why")
    if s.want(7):
        await page.locator(".lead .title-btn").first.click()
        await film.need(page, ".rec-title", "the evidence panel")
        await page.wait_for_timeout(400)
        await s.snap(page, 7, "researcher-evidence")
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
    if s.want(8):
        await page.evaluate("window.scrollTo(0, 0)")
        t = page.locator("[data-key=route-T]")
        if await t.count():
            await t.click()
            await film.need(page, "#panel .leads > li", "the Temple internal list")
            await s.snap(page, 8, "researcher-temple")
            await page.locator("[data-key=route-A]").click()
    if s.want(9):
        await page.evaluate("window.scrollTo(0, 0)")
        await page.click("#tab-compare")
        await page.wait_for_timeout(900)
        await s.snap(page, 9, "researcher-compare")
    if s.want(10):
        await page.click("#tab-scout")
        await film.need(page, "#scout-q", "the Scout box")
        await page.evaluate("window.scrollTo(0, 0)")
        await s.snap(page, 10, "researcher-scout")


async def stage_picks(page: Page) -> None:
    """The brief's own answer carries the account's current picks as words; a reset account
    has none, so the "You chose" line is staged with the pick the brief's cards were checked
    against (U.S. citizen), as the app writes it."""
    async def handler(route) -> None:  # noqa: ANN001
        r = await route.fetch()
        try:
            body = await r.json()
        except ValueError:
            await route.fulfill(response=r)
            return
        if isinstance(body, dict) and body.get("student") is not None:
            body["student_picks"] = {"citizenship": "U.S. citizen", "residency": None}
        await route.fulfill(response=r, json=body)

    await page.route(f"**/briefs/{STUDENT_PICK_BRIEF}", handler)


async def student_screens(page: Page, base: str, s: Shots) -> None:
    await film.need(page, "#acct-btn", "the signed-in header")
    await stage_picks(page)
    if s.want(13):  # the form with a CV stored; the picks fieldset sits under the notes boxes
        await page.goto(base + "/#/student")
        await film.need(page, ".profile-picks", "the picks on the student start")
        await page.wait_for_timeout(800)
        await top(page, page.locator(".profile-picks"), 150 if s.view == "wide" else 120)
        await s.snap(page, 13, "student-start-picks")
    await open_brief(page, base, STUDENT_PICK_BRIEF)
    if s.want(11):
        await page.evaluate("window.scrollTo(0, 0)")
        await s.snap(page, 11, "student-brief")
    rules = page.locator("#panel .leads > li:has(.rules)").nth(1)  # not the Gilman card, shown in 16
    if s.want(12):
        await top(page, rules, 80)
        await s.snap(page, 12, "student-rules")
    if s.want(16):
        card = page.locator("#panel .leads > li:has(.pick-source)").first
        await film.need(page, "#panel .leads > li .pick-source", "a card with a citizenship note")
        await top(page, card, 80)
        await card.locator(".check:has(.pick-source)").first.scroll_into_view_if_needed()
        await top(page, card.locator(".check:has(.pick-source)").first, 260 if s.view == "wide" else 300)
        await s.snap(page, 16, "student-card-citizenship")
    if s.want(15):
        await page.evaluate("window.scrollTo(0, 0)")
        await page.click("#tab-profile")
        await film.need(page, ".prof-cols .fields .field", "the CV panel")
        await page.wait_for_timeout(600)
        note = page.locator("#panel p.notice:has-text('You chose')")
        await film.need(page, "#panel p.notice:has-text('You chose')", "the You chose line")
        await note.evaluate("e => e.scrollIntoView({block: 'end'})")
        await s.snap(page, 15, "student-cv-panel")
    if any(s.want(n) for n in (17, 18, 19)):
        await scout_screens(page, base, s)


async def scout_screens(page: Page, base: str, s: Shots) -> None:
    await page.evaluate("window.scrollTo(0, 0)")
    await page.click("#tab-scout")
    await film.need(page, "#scout-q", "the Scout box")
    await page.wait_for_timeout(600)
    clear = page.locator("[data-key=scout-clear]")
    if not await page.locator(".scout-answer").count():  # one real question when the thread is empty
        await page.fill("#scout-q", "Which award closes soonest, and what does it ask for?")
        await page.click(".scout-ask button[type=submit]")
        await film.need(page, ".scout-answer", "Scout's answer", 240_000)
        await page.wait_for_timeout(1500)
    await page.evaluate("window.scrollTo(0, 0)")
    if s.want(17):
        await s.snap(page, 17, "scout-ask-clear")
    if s.want(19):
        await clear.click()
        await film.need(page, "text=Conversation cleared.", "the Undo line")
        await page.wait_for_timeout(400)
        await s.snap(page, 19, "scout-cleared-undo")
        await page.get_by_role("button", name="Undo").click()  # the thread is back for the next view
        await page.wait_for_timeout(800)
    if s.want(18):
        gate = asyncio.Event()

        async def hold(route) -> None:  # noqa: ANN001 - the request waits, so the box keeps glowing
            await gate.wait()
            await route.abort()

        await page.route("**/scout", hold, times=1)
        await page.fill("#scout-q", "Which of these awards ask for a letter of recommendation?")
        await page.click(".scout-ask button[type=submit]")
        await film.need(page, ".scout-ask-row.working", "the working glow")
        await page.wait_for_timeout(700)
        await s.snap(page, 18, "scout-working")
        gate.set()
        await page.wait_for_timeout(500)
        await page.unroute("**/scout")


def load_env(path: str | None) -> None:
    """Read DEMO_* credentials from an env file into this process only; nothing is printed."""
    if not path:
        return
    for line in Path(path).read_text().splitlines():
        k, _, v = line.strip().partition("=")
        if k.startswith("DEMO_") and v:
            os.environ.setdefault(k, v.strip("\"'"))


async def main(a: argparse.Namespace) -> int:
    load_env(a.env_file)
    names = film.aliases()
    out = ROOT / a.out
    out.mkdir(parents=True, exist_ok=True)
    only = set(a.only or [])
    made = 0
    failed = 0
    hits: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=find_chrome(), args=["--no-sandbox"])
        for view in a.view:
            size, scale = VIEWS[view]
            for scheme in a.scheme:
                for kind, fn, wanted in (("guest", guest_screens, {1, 2, 3, 4}),
                                         ("researcher", researcher_screens, {5, 6, 7, 8, 9, 10, 14}),
                                         ("student", student_screens, {11, 12, 13, 15, 16, 17, 18, 19})):
                    if only and not (only & wanted):
                        continue
                    check = NameCheck(names, surnames=True)
                    s = Shots(out, view, scheme, check, only)
                    ctx = await browser.new_context(viewport=size, device_scale_factor=scale,
                                                    color_scheme=scheme, has_touch=view == "phone",
                                                    is_mobile=view == "phone")
                    page = await ctx.new_page()
                    page.set_default_timeout(30_000)
                    errs: list[str] = []
                    page.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
                    try:
                        await alias_checked(page, names, check)
                        if kind != "guest":
                            await sign_in_as(page, a.base, kind.upper())
                        await fn(page, a.base, s)
                    except Exception as e:  # noqa: BLE001
                        failed += 1
                        print(f"{view}-{scheme}-{kind}: FAILED {type(e).__name__}: {str(e).splitlines()[0][:200]}")
                    await ctx.close()
                    made += len(s.made)
                    hits += check.hits
                    print(f"{view}-{scheme}-{kind}: {len(s.made)} saved; name check: {check.report()}"
                          + (f"; page errors: {errs[:2]}" if errs else ""))
        await browser.close()
    print(f"{made} screenshots in {out}; name hits: {len(hits)}; failed groups: {failed}")
    return 1 if (hits or failed) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--env-file", help="a file with the DEMO_*_USERNAME and _PASSWORD lines")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--only", type=int, nargs="*", help="screen numbers")
    ap.add_argument("--view", nargs="*", default=["wide", "phone"], choices=list(VIEWS))
    ap.add_argument("--scheme", nargs="*", default=["light", "dark"], choices=["light", "dark"])
    sys.exit(asyncio.run(main(ap.parse_args())))
