"""Film the four Demo Day films in the running v1 app (S53, S54): researcher, student, scout, quick.

Films (each 45 to 90 seconds once slow waits are played back quickly):
  researcher  a researcher's brief, shown by alias: Ready, the top individual-lab grant with
              Match and Why it fits, its Evidence, the Temple internal and Industry tabs,
              Compare, and the hand-off draft that Perch never sends
  student     a SYNTHETIC Temple student (data/synthetic/persona-demo): paste the CV, the two
              optional picks, Save and find awards, what the rules read from the CV, a lead's
              check marks and question marks, the note that names where a rule was found, the
              sample data badge
  quick       (30 s or less, played at 1.5x) the student path for a new user: Load sample,
              Save and find awards, one card with its check marks, Evidence, Keep, the other tabs
  scout       the same student's brief: cover-letter points with their citations, one question
              to Scout with the glow while it works, and a crisis message answered by a fixed
              reply from code with its help links

It reuses scripts/tour/film.py (sign-in, the alias swap, the helpers) and recorder.py. New here:
one-line captions, a name check, and a renderer that draws the captions and writes a WebP (the
README clips' format) and an MP4.

Researchers appear by alias only. Every JSON answer is swapped before the page sees it, a
leak check fails the film when a real name is still in an answer, and the text of the screen is
checked for every real name at each pause and at the end.

Accounts: each film signs in as a SYNTHETIC deploy account whose user name and password come
from the environment (PERCH_TOUR_USER, PERCH_TOUR_PASSWORD); the password is never printed.
Run `scripts/demo_reset.py --apply` first (docs/DEMO.md) and check the spend ledger.

  PERCH_TOUR_USER=... PERCH_TOUR_PASSWORD=... uv run --no-project --with playwright \\
      --with pillow --with imageio-ffmpeg python scripts/tour/demo_films.py \\
      --base https://<the deploy> --films researcher --out build/films --dry
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import subprocess
import sys
import time
from bisect import bisect_right
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import Page, Route, async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import film  # noqa: E402
from animate import camera  # noqa: E402
from names import _loose, swap_names  # noqa: E402
from recorder import Recorder, click, glide  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "build/films_raw"
PERSONA = ROOT / "data/synthetic/persona-demo"
VIEW = {"width": 1280, "height": 720}
AUTHOR = film.AUTHOR  # PI-1, the PI S52's tour used
LONG = film.LONG
need, settle, scroll_by, session = film.need, film.settle, film.scroll_by, film.session
SceneError = film.SceneError

# The persona's three texts as a person pastes them: the file's Markdown title line is left out,
# so each text opens with the SYNTHETIC label and carries its canary token.
DISTRESS_MESSAGE = "I feel overwhelmed and hopeless about money and I can't go on like this."
QUESTION = "What does the top award ask for that my CV does not show yet?"


def persona_text(name: str) -> str:
    t = (PERSONA / name).read_text(encoding="utf-8")
    if t.startswith("# "):
        t = t.split("\n", 2)[2]
    return t.strip()


# ---------- the name check ----------

def pi_parts(openalex_id: str) -> tuple[list[str], str]:
    """The given and middle names of the PI behind an OpenAlex id, from the alias table (kept
    in memory only). The shared swap replaces a full name and a surname; a model's sign-off can
    use the given name alone, so the film also swaps these."""
    import csv
    with (ROOT / "data/overrides/pi_aliases.csv").open() as f:
        for r in csv.DictReader(f):
            if r.get("openalex_id") == openalex_id:
                return r["name"].split()[:-1], r["alias"]
    return [], ""


def swap_given(body: str, parts: list[str], alias: str) -> str:
    """"<given> [middle] <alias>" becomes the alias; a given or middle name left on its own
    (three letters or more, as a whole word, accents allowed) becomes the alias too."""
    toks = [_loose(t) for t in parts if t]
    if not toks:
        return body
    seq = r"(?:" + r"\s+".join(f"(?:{t})" for t in toks) + r")"
    body = re.sub(rf"(?<!\w){seq}\s+{re.escape(alias)}(?!\w)", alias, body, flags=re.I)
    for t, raw in zip(toks, parts):
        if len(raw.strip(".")) >= 3:
            body = re.sub(rf"(?<!\w){t}(?!\w)", alias, body)
    return body


class NameCheck:
    """Whether a real researcher name is on the screen or in an answer. Full names, in every
    accented and escaped form, always; surnames of five letters or more when `surnames`."""

    def __init__(self, names: dict[str, str], surnames: bool, given: list[str] | None = None) -> None:
        pats = [_loose(n) for n in names]
        if surnames:
            pats += [_loose(n.split()[-1]) for n in names if len(n.split()[-1]) >= 5]
        # The film's own PI: the given and middle names count on their own too.
        pats += [_loose(g) for g in (given or []) if len(g.strip(".")) >= 3]
        self.rx = re.compile(r"(?<!\w)(?:" + "|".join(pats) + r")(?!\w)", re.I)
        self.hits: list[str] = []
        self.looks = 0

    def text(self, where: str, s: str) -> None:
        for m in self.rx.finditer(s):
            self.hits.append(f"{where}: {m.group(0)[:3]}... ({len(m.group(0))} letters)")
            if os.environ.get("FILM_DEBUG"):
                print("DEBUG context:", repr(s[max(0, m.start() - 50):m.end() + 30]).replace(m.group(0), "<NAME>"))
            break

    async def screen(self, page: Page, where: str) -> None:
        self.looks += 1
        try:
            s = await page.evaluate(
                "() => document.title + ' ' + document.body.innerText + ' ' + "
                "[...document.querySelectorAll('input,textarea')].map(e => e.value).join(' ')")
        except Exception:  # noqa: BLE001 - mid-navigation
            return
        self.text(where, s)

    def report(self) -> str:
        return f"{self.looks} screen looks, {len(self.hits)} hits" + (
            "; " + "; ".join(self.hits[:5]) if self.hits else "")


async def alias_checked(page: Page, names: dict[str, str], check: NameCheck,
                        given: list[str] | None = None, alias: str = "") -> None:
    """film.alias_responses plus a check that no real name survives in a JSON answer."""
    async def handle(route: Route) -> None:
        try:
            if route.request.resource_type not in ("fetch", "xhr"):
                await route.continue_()
                return
            r = await route.fetch()
            if "json" not in r.headers.get("content-type", ""):
                if os.environ.get("FILM_DEBUG"):
                    print("DEBUG non-json", route.request.url.split("?")[0][-50:], r.headers.get("content-type"))
                await route.fulfill(response=r)
                return
            body = await r.text()

            def swap(t: str) -> str:
                t = swap_names(t, names)
                return swap_given(t, given, alias) if given and alias else t

            def walk(v):  # noqa: ANN001, ANN202 - every string value, so "\\nName" has a real line break
                if isinstance(v, str):
                    return swap(v)
                if isinstance(v, list):
                    return [walk(x) for x in v]
                if isinstance(v, dict):
                    return {swap(k): walk(x) for k, x in v.items()}
                return v

            try:
                body = json.dumps(walk(json.loads(body)), ensure_ascii=False, separators=(",", ":"))
            except ValueError:
                body = swap(body)
            body = re.sub(r'"orcid":\s*"[^"]*"', '"orcid": null', body)
            if os.environ.get("FILM_DEBUG") and "Best regards" in body:
                i = body.index("Best regards")
                print("DEBUG after swap:", repr(body[i:i + 40]), "given", given, "alias", alias)
            check.text("answer " + route.request.url.split("?")[0][-40:], body.replace("\\n", " "))
            await route.fulfill(response=r, body=body)
        except Exception:  # noqa: BLE001 - the page closed mid-request
            return

    await page.route("**/*", handle)


# ---------- a recorder with captions and the name check ----------

class Film(Recorder):
    def __init__(self, page: Page, name: str, check: NameCheck) -> None:
        super().__init__(page, name, RAW)
        self.caps: list[dict] = []
        self.check = check

    def cap(self, text: str) -> None:
        """One line of plain words, shown from now until the next caption (or "" to clear)."""
        self.caps.append({"t": self.now(), "text": text})

    async def hold(self, ms: int) -> None:
        await super().hold(ms)
        await self.check.screen(self.page, f"{self.name} hold@{self.now():.0f}s")

    async def stop(self) -> None:
        await self.check.screen(self.page, f"{self.name} end")
        await super().stop()
        path = self.dir / "scene.json"
        scene = json.loads(path.read_text())
        scene["captions"] = self.caps
        path.write_text(json.dumps(scene, indent=1))


# ---------- the renderer: the camera of animate.py, plus captions, to WebP and MP4 ----------

FONTS = ["/usr/share/fonts/truetype/lato/Lato-Semibold.ttf", "/usr/share/fonts/truetype/lato/Lato-Medium.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def caption_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for f in FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def with_caption(im: Image.Image, text: str, font) -> Image.Image:  # noqa: ANN001
    if not text:
        return im
    base = im.convert("RGBA")
    over = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    left, t, r, b = d.textbbox((0, 0), text, font=font)
    tw, th = r - left, b - t
    padx, pady = round(base.width * 0.018), round(base.height * 0.016)
    x0 = (base.width - tw) // 2 - padx
    y1 = round(base.height * 0.045) + th + 2 * pady  # the caption sits at the top, clear of the bottom controls
    d.rounded_rectangle((x0, y1 - th - 2 * pady, x0 + tw + 2 * padx, y1), radius=round(th * 0.6),
                        fill=(20, 28, 24, 214))
    d.text((x0 + padx - left, y1 - pady - th - t), text, font=font, fill=(255, 255, 255, 255))
    return Image.alpha_composite(base, over).convert("RGB")


def render(scene_dir: Path, out_stem: Path, webp_width: int, mp4_width: int, fps: int,
           quality: int, tail: float = 1.5, speed: float = 1.0) -> dict:
    """WebP at `webp_width` (the README clips' settings: fps and quality as passed) and, when
    imageio-ffmpeg is installed, an MP4 at `mp4_width`. Returns the lengths and sizes."""
    scene = json.loads((scene_dir / "scene.json").read_text())
    frames, view = scene["frames"], scene["viewport"]
    times = [f["t"] for f in frames]
    at = camera(scene)
    fast = scene.get("fast", [])
    caps = sorted(scene.get("captions", []), key=lambda c: c["t"])
    cap_times = [c["t"] for c in caps]
    cache: dict[str, Image.Image] = {}

    def frame_at(t: float) -> Image.Image:
        i = max(0, bisect_right(times, t) - 1)
        name = frames[i]["file"]
        if name not in cache:
            cache.clear()
            cache[name] = Image.open(scene_dir / name).convert("RGB")
        return cache[name]

    def speed_at(t: float) -> float:
        return next((f["speed"] for f in fast if f["from"] <= t < f["to"]), 1.0)

    def text_at(t: float) -> str:
        i = bisect_right(cap_times, t) - 1
        return caps[i]["text"] if i >= 0 else ""

    def shot(t: float, width: int, font) -> Image.Image:  # noqa: ANN001
        full = frame_at(t)
        sx = full.width / view["width"]
        x, y, w, h = at(t)
        height = round(width * view["height"] / view["width"])
        im = full.crop((round(x * sx), round(y * sx), round((x + w) * sx), round((y + h) * sx)))
        return with_caption(im.resize((width, height), Image.LANCZOS), text_at(t), font)

    end, step = scene["end"], 1 / fps
    ts: list[float] = []
    t = 0.0
    while t <= end:
        ts.append(t)
        t += step * speed * speed_at(t)
    out: dict = {"seconds": len(ts) / fps + tail}

    # WebP: identical neighbours become one frame held longer, as animate.py does.
    font = caption_font(round(webp_width * 0.024))
    shots, durs, last = [], [], None
    for t in ts:
        im = shot(t, webp_width, font)
        raw = im.tobytes()
        if raw == last:
            durs[-1] += round(1000 / fps)
            continue
        shots.append(im)
        durs.append(round(1000 / fps))
        last = raw
    durs[-1] += round(tail * 1000)
    webp = out_stem.with_suffix(".webp")
    shots[0].save(webp, format="WEBP", save_all=True, append_images=shots[1:], duration=durs,
                  loop=0, quality=quality, method=4, allow_mixed=True, minimize_size=True)
    out["webp"] = (str(webp), webp.stat().st_size / 1e6, webp_width)
    del shots

    try:
        import imageio_ffmpeg
    except ImportError:
        return out
    if not mp4_width:
        return out
    height = round(mp4_width * view["height"] / view["width"])
    mp4 = out_stem.with_suffix(".mp4")
    font = caption_font(round(mp4_width * 0.024))
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo",
           "-pix_fmt", "rgb24", "-s", f"{mp4_width}x{height}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(mp4)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for t in ts:
        pr.stdin.write(shot(t, mp4_width, font).tobytes())
    last_frame = shot(ts[-1], mp4_width, font).tobytes()
    for _ in range(round(tail * fps)):
        pr.stdin.write(last_frame)
    pr.stdin.close()
    pr.wait()
    out["mp4"] = (str(mp4), mp4.stat().st_size / 1e6, mp4_width)
    return out


# ---------- off-camera preparation ----------

async def fetch_json(page: Page, method: str, path: str, body: dict | None = None):  # noqa: ANN201
    """A call to the app's own API from the page, with the session's CSRF token."""
    return await page.evaluate(
        """async ([method, path, body]) => {
            const s = await fetch('/auth/session').then(r => r.json());
            const r = await fetch(path, {method, headers: {'Content-Type': 'application/json',
              ...(method !== 'GET' ? {'X-CSRF-Token': s.csrf} : {})}, body: body ? JSON.stringify(body) : undefined});
            const t = await r.text();
            try { return {status: r.status, json: JSON.parse(t)}; } catch { return {status: r.status, json: null}; }
        }""", [method, path, body])


async def ready_account(page: Page, base: str, side: str) -> None:
    """Signed in, consent given and the side chosen (a new account sees the welcome step)."""
    s = await session(page)
    c = s.get("consent") or {}
    if c.get("accepted_version", 0) < c.get("current_version", 1) or side not in s.get("roles", []):
        await page.goto(base + "/#/welcome")
        await need(page, "[data-key=agree]", "the consent checkbox")
        if not await page.locator(f"[data-key=role-{side}]").is_checked():
            await page.check(f"[data-key=role-{side}]")
        if not await page.locator("[data-key=agree]").is_checked():
            await page.check("[data-key=agree]")
        await page.click("[data-key=continue]")
        await page.wait_for_selector("#acct-btn", timeout=30_000)
    r = await fetch_json(page, "PUT", "/me/audience", {"audience": side})
    if r["status"] >= 400:  # not every build has this route; the brief build sets the side too
        print(f"(audience call answered {r['status']}; the build sets the side)")


async def reset_student(page: Page) -> None:
    """Off camera: the student side's stored CV, entries and picks are removed, so the film
    starts at an empty form. SYNTHETIC test account only."""
    docs = await fetch_json(page, "GET", "/me/docs?audience=student")
    for d in (docs["json"] or []):
        await fetch_json(page, "DELETE", f"/me/docs/{d['id']}")
    await fetch_json(page, "PUT", "/me/profile?audience=student",
                     {"citizenship": None, "residency_state": None})


async def newest_brief(page: Page, base: str, side: str) -> str | None:
    """The hash of the newest brief of a side on My Perch, or None."""
    await page.goto(base + "/#/me")
    await need(page, ".my-perch", "My Perch")
    await need(page, ".brief-row, .home-briefs .empty-list", "the Briefs box")
    await settle(page, 700)
    return await page.evaluate("""(side) => {
        const rows = [...document.querySelectorAll('.brief-row')];
        const a = rows.map(r => r.querySelector('a.btn')).filter(Boolean)[0];
        return a ? a.getAttribute('href') : null; }""", side)


async def ensure_two_kept(page: Page) -> None:
    btns = page.locator("#panel .leads > li .btn.keep:not(.on)")
    for _ in range(2):
        if await page.locator("#panel .leads > li .btn.keep.on").count() >= 2:
            break
        if not await btns.count():
            break
        await btns.first.click()
        await settle(page, 700)


# ---------- the films ----------

async def researcher(page: Page, base: str, o: argparse.Namespace, check: NameCheck) -> Film:
    await ready_account(page, base, "researcher")
    # A fresh brief for the aliased PI: an older brief on the account may be for someone else.
    await page.goto(base + "/#/start")
    await film.pick_author(page, None, o.author)
    await page.click("[data-key=build]")
    await need(page, "#panel .leads > li", "a brief with leads", LONG)
    await page.locator("#progress .pcard").wait_for(state="detached", timeout=180_000)
    await settle(page, 800)
    # Off camera: two kept leads. The draft itself is written on camera (the button glows).
    href = await page.evaluate("location.hash")
    title = await page.evaluate("document.querySelector('h1').innerText")
    if not re.match(r"PI-\d+", title):
        raise SceneError(f"the brief's title is not an alias: {title[:3]}...")
    await ensure_two_kept(page)
    await page.click("#tab-compare")
    await need(page, "[data-key=handoff-make]", "the Draft the email button")
    await page.goto(base + "/" + href)  # the saved state is what the film shows
    await need(page, "#panel .leads > li", "the brief again")
    await settle(page, 1200)
    await page.evaluate("window.scrollTo(0, 0)")

    rec = Film(page, "researcher", check)
    await rec.start()
    rec.cap("A researcher's brief, shown here as PI-1")
    await rec.hold(3200)
    chip = page.locator("[data-key=progress-chip], .progress-chip, #progress").first
    if await chip.count() and await chip.is_visible():
        await rec.focus(chip, pad=40)
        await rec.hold(1200)
        rec.wide()
    top = page.locator("#panel .leads > li").first
    rec.cap("Top lead: a grant for an individual lab")
    await top.scroll_into_view_if_needed()
    await scroll_by(page, -80, steps=3)
    await rec.hold(500)
    await rec.focus(top, pad=20)
    await rec.hold(4100)
    why = top.locator("summary[data-key=why]").first
    if await why.count():
        rec.cap("Match, and why it fits, in plain words")
        await click(page, why)
        await rec.hold(500)
        await rec.focus(top, pad=20)
        await rec.hold(4300)
    rec.wide()
    rec.cap("Every date and amount is copied from the public record")
    await click(page, top.locator(".title-btn").first)
    await need(page, "#rail-ev .rec-title", "the lead's record in the evidence rail")
    await page.locator("#rail-ev .rec-title").scroll_into_view_if_needed()
    await rec.hold(600)
    await rec.focus(film.evidence_box(page, rail=True), pad=10)
    await rec.hold(4900)
    rec.wide()
    await page.evaluate("window.scrollTo(0, 0)")
    await rec.hold(500)
    if await page.locator("[data-key=route-T]").count():
        rec.cap("Temple's own funding calls")
        await click(page, page.locator("[data-key=route-T]"))
        await need(page, "#panel .leads > li", "the Temple internal leads")
        await rec.hold(3000)
    rec.cap("Industry leads: inferred from public signals, not verified")
    await click(page, page.locator("[data-key=route-B]"))
    await need(page, "#panel .leads > li, #panel .empty-list, #panel .hint", "the industry leads")
    await rec.hold(3800)
    rec.wide()
    rec.cap("Compare the leads you kept")
    await click(page, page.locator("#tab-compare"))
    table = await need(page, "#panel table", "the comparison table")
    await settle(page, 500)
    await rec.focus(table, pad=20)
    await rec.hold(4300)
    rec.wide()
    make = await need(page, "[data-key=handoff-make]", "the Draft the email button")
    await make.scroll_into_view_if_needed()
    rec.cap("The button glows while a model writes the draft")
    await rec.hold(500)
    await rec.focus(make, pad=160)
    await rec.hold(900)
    await click(page, make)
    await rec.hold(3600)  # the glow, at full speed
    try:
        await rec.quickly(lambda: page.locator(
            "[data-key=handoff-make]:not([aria-busy=true])").wait_for(timeout=240_000), speed=12)
    except Exception as e:  # noqa: BLE001
        raise SceneError("the hand-off draft took longer than 240 s") from e
    rec.wide()
    subject = await need(page, "[data-key=handoff-subject]", "the drafted hand-off")
    await settle(page, 600)
    rec.cap("A draft to a Temple office. Perch never sends it.")
    await subject.evaluate("e => window.scrollBy(0, e.getBoundingClientRect().top - 110)")
    await rec.hold(700)
    await rec.focus(page.locator(".handoff").first, pad=14)
    await rec.hold(5700)
    await scroll_by(page, 420, steps=8)
    await rec.hold(3200)
    rec.wide()
    rec.cap("")
    await rec.hold(800)
    await rec.stop()
    return rec


async def student(page: Page, base: str, o: argparse.Namespace, check: NameCheck) -> Film:
    await ready_account(page, base, "student")
    await reset_student(page)
    await page.goto(base + "/#/student")
    await need(page, "#cv-text", "the CV box")
    await settle(page, 1000)

    rec = Film(page, "student", check)
    await rec.start()
    rec.cap("A Temple student pastes a CV (invented for this film)")
    await rec.hold(1200)
    cv = page.locator("#cv-text")
    await click(page, cv)
    await cv.fill(persona_text("cv.md"))
    await cv.evaluate("e => { e.scrollTop = 0; }")
    await rec.focus(cv, pad=30)
    await rec.hold(4300)
    for _ in range(12):  # a calm scroll through the pasted text
        await cv.evaluate("e => { e.scrollTop += 28; }")
        await rec.hold(110)
    await rec.hold(1600)
    rec.wide()
    await click(page, page.locator("#st-interests"))
    await page.locator("#st-interests").fill(persona_text("interests.md"))
    await rec.hold(1200)
    await click(page, page.locator("#st-ach"))
    first_ach = persona_text("achievements.md").split("\n")
    await page.locator("#st-ach").fill("\n".join(first_ach))
    await rec.hold(1200)
    picks = page.locator(".profile-picks")
    await need(page, ".profile-picks", "the optional picks")
    await picks.scroll_into_view_if_needed()
    rec.cap("Two optional picks: citizenship and state")
    await rec.hold(500)
    await rec.focus(picks, pad=30)
    await click(page, page.locator("#st-pick-citizenship"))
    await page.select_option("#st-pick-citizenship", o.citizenship)
    await rec.hold(1300)
    await click(page, page.locator("#st-pick-state"))
    await page.select_option("#st-pick-state", o.state)
    await rec.hold(3000)
    rec.wide()
    rec.cap("Save and find awards")
    await film.build_and_wait(page, rec, "[data-key=st-build]", speed=14)
    await page.evaluate("window.scrollTo(0, 0)")
    await rec.hold(1200)

    rec.cap("What Perch read from the CV, by rule, not by a model")
    await click(page, page.locator("#tab-profile"))
    await need(page, ".prof-cols .fields .field", "the CV panel")
    await rec.hold(500)
    await rec.focus(page.locator(".prof-cols .left").first, pad=30)
    await rec.hold(5700)
    await rec.focus(page.locator(".prof-cols .right").first, pad=30)
    await rec.hold(3800)
    rec.wide()
    rec.cap("Awards that may fit, each checked against the CV")
    await click(page, page.locator("#tab-routes"))
    await need(page, "#panel .leads > li", "the leads")
    await rec.hold(600)
    ruled = page.locator("#panel .leads > li:has(.check[data-rule=citizenship] .pick-source), "
                         "#panel .leads > li:has(.pick-source)").first
    if not await ruled.count():
        raise SceneError("no lead shows a rule with a Source page link; "
                         "try other picks (--citizenship, --state)")
    top = page.locator("#panel .leads > li").first
    await rec.focus(top, pad=20)
    await rec.hold(4900)
    rec.cap("A check mark means met. A question mark means you decide.")
    await rec.focus(ruled.locator(".rules").first, pad=30)
    await rec.hold(4300)
    link = ruled.locator(".pick-source").first
    rec.cap("The note says where the rule was found, with a link to the page")
    await link.scroll_into_view_if_needed()
    await click_hover(page, link)
    await rec.focus(ruled.locator(".check:has(.pick-source)").first, pad=60)
    await rec.hold(5700)
    rec.wide()
    second = page.locator("#panel .leads > li").nth(1)
    if await second.count():
        rec.cap("Each award shows what is still needed, in plain words")
        await second.scroll_into_view_if_needed()
        await rec.hold(500)
        await rec.focus(second, pad=20)
        await rec.hold(4900)
        rec.wide()
    if await page.locator("[data-key=route-S]").count():
        rec.cap("Sample scholarships carry a Sample data badge")
        await page.evaluate("window.scrollTo(0, 0)")
        await click(page, page.locator("[data-key=route-S]"))
        await need(page, "#panel .leads > li", "the sample list")
        await rec.hold(600)
        badge = page.locator("#panel .tag.sample, #panel .sample").first
        if await badge.count():
            await rec.focus(page.locator("#panel .leads > li").first, pad=20)
        await rec.hold(4100)
        rec.wide()
    rec.cap("")
    await rec.hold(700)
    await rec.stop()
    return rec


async def quick(page: Page, base: str, o: argparse.Namespace, check: NameCheck) -> Film:
    """A 30-second tour of the student path. Holds are in real time; the render plays at 1.5x,
    so a beat of N final seconds holds 1.5 N real seconds."""
    await ready_account(page, base, "student")
    await reset_student(page)
    # Off camera: one full build, so the filmed build is quick and nothing slow is filmed.
    await page.goto(base + "/#/student")
    await need(page, "#cv-text", "the CV box")
    await page.click("[data-key=load-sample]")
    await page.select_option("#st-pick-citizenship", "")  # Load sample ticks International: back to Not stated
    await page.click("[data-key=st-build]")
    await need(page, "#panel .leads > li", "a brief with leads", LONG)
    await page.locator("#progress .pcard").wait_for(state="detached", timeout=180_000)
    await settle(page, 800)
    # Off camera, on this first brief: cover-letter points on the top card, and one Scout answer
    # in a fresh thread, so no wait is filmed. The film's own brief is built after this one.
    old_href = await page.evaluate("location.hash")
    btn = await need(page, "#panel .leads > li:first-child [data-key^=cover-]", "a Cover-letter points button")
    block = page.locator("#panel .leads > li").first.locator(".scout-points")
    for attempt in range(3):
        if not await block.count():
            await btn.click()
            await block.first.wait_for(timeout=240_000)
        if not await block.first.locator(":scope > p.notice.warn").count():
            break
        print(f"quick: points attempt {attempt + 1} withheld")
    await page.click("#tab-scout")
    await need(page, "#scout-q", "the Scout box")
    clear = page.locator("[data-key=scout-clear]")
    if await clear.count() and await clear.is_enabled():
        await clear.click()
        await settle(page, 800)
    await page.fill("#scout-q", QUESTION)
    await page.click(".scout-ask button[type=submit]")
    await page.locator(".scout-answer").last.wait_for(timeout=240_000)
    await settle(page, 1000)
    await page.click("#tab-routes")
    await reset_student(page)
    await page.goto(base + "/#/student")
    await need(page, "#cv-text", "the CV box")
    await settle(page, 1000)

    def fin(s: float) -> int:  # final seconds to real milliseconds
        return round(s * 1.5 * 1000)

    rec = Film(page, "quick", check)
    await rec.start()
    rec.cap("Start here: your CV, interests and achievements")
    await rec.hold(fin(2.2))
    rec.cap("Load sample fills all three boxes")
    await click(page, page.locator("[data-key=load-sample]"))
    # Load sample ticks International; the pick is set back to Not stated, so no card shows a rule
    # about an answer the viewer never saw. The select is below the fold here, so nothing shows.
    await page.select_option("#st-pick-citizenship", "")
    await rec.hold(fin(1.0))
    await page.evaluate("window.scrollTo({top: 470, behavior: 'smooth'})")  # one move down
    await rec.hold(fin(1.2))
    rec.cap("Perch checks every award against your CV")
    await click(page, page.locator("[data-key=st-build]"))
    await rec.hold(fin(1.8))
    wait = page.locator("#panel .leads > li").first.wait_for(timeout=LONG)
    await rec.quickly(lambda: wait, speed=40)
    done = page.locator("#progress .pcard").wait_for(state="detached", timeout=120_000)
    await rec.quickly(lambda: done, speed=40)
    await settle(page, 900)
    await page.evaluate("window.scrollTo(0, 0)")
    top = page.locator("#panel .leads > li").first
    keep = top.locator("[data-key^=keep-]").first
    if "on" in ((await keep.get_attribute("class")) or "").split():
        await keep.click()  # off camera: start from not kept
        await settle(page, 700)
    rec.cap("A check means you meet it. A question mark means check it yourself.")
    await page.evaluate("window.scrollTo({top: 150, behavior: 'smooth'})")  # the whole card in view
    await settle(page, 500)
    rec.wide()
    await rec.hold(fin(3.5))
    rec.cap("Every date and amount is copied from the record")
    await click(page, top.locator(".title-btn").first)
    await need(page, "#rail-ev .rec-title", "the record in the evidence rail")
    rec.wide()
    await rec.hold(fin(2.6))
    rec.cap("Keep the awards you like")
    await click(page, keep)
    await rec.hold(fin(1.0))
    for tab, text in (("profile", "What Perch read from your CV"), ("compare", "Compare and draft")):
        rec.cap(text)
        await click(page, page.locator(f"#tab-{tab}"))
        await rec.hold(fin(0.9))
    # The Scout part runs on the first brief, which already holds the points and the answer.
    await page.evaluate("(h) => { location.hash = h; }", old_href)
    await need(page, "#panel .leads > li", "the first brief")
    await settle(page, 800)
    rec.cap("Ask Scout about your options. Every answer cites its records")
    await click(page, page.locator("#tab-scout"))
    answer = await need(page, ".scout-answer", "the stored Scout answer")
    await answer.last.scroll_into_view_if_needed()
    await rec.hold(fin(2.9))
    rec.cap("Cover-letter points, from your own CV")
    await click(page, page.locator("#tab-routes"))
    block = page.locator("#panel .leads > li").first.locator(".scout-points").first
    await need(page, "#panel .leads > li:first-child .scout-points", "the stored cover-letter points")
    await block.scroll_into_view_if_needed()
    await rec.hold(fin(2.4))
    rec.cap("If you are struggling, Scout stops and shows where to get help")
    await click(page, page.locator("#tab-scout"))
    q = await need(page, "#scout-q", "the Scout box")
    await click(page, q)
    await q.press_sequentially(DISTRESS_MESSAGE, delay=12)
    await click(page, page.locator(".scout-ask button[type=submit]"))
    await need(page, "#panel :text('Tuttleman Counseling')", "the help links in the reply", 60_000)
    await settle(page, 600)
    await page.locator(".scout-x").last.scroll_into_view_if_needed()
    await rec.hold(fin(2.0))
    await rec.stop()
    return rec


async def click_hover(page: Page, target) -> None:  # noqa: ANN001
    """Point at a link without following it (it opens another tab)."""
    await glide(page, target)


async def scout(page: Page, base: str, o: argparse.Namespace, check: NameCheck) -> Film:
    await ready_account(page, base, "student")
    href = await newest_brief(page, base, "student")
    if not href:
        raise SceneError("no student brief on My Perch; film `student` first")
    await page.goto(base + "/" + href)
    await need(page, "#panel .leads > li", "the brief's leads", LONG)
    await page.locator("#progress .pcard").wait_for(state="detached", timeout=180_000)
    await settle(page, 800)
    # Off camera: a fresh Scout thread, so the crisis reply is not suppressed as a repeat.
    await page.click("#tab-scout")
    await need(page, "#scout-q", "the Scout box")
    clear = page.locator("[data-key=scout-clear]")
    if await clear.count() and await clear.is_enabled():
        await clear.click()
        await settle(page, 800)
    await page.goto(base + "/" + href)  # reload: the stored points come back with the card
    await need(page, "#panel .leads > li", "the brief again")
    await settle(page, 1500)
    await page.evaluate("window.scrollTo(0, 0)")

    rec = Film(page, "scout", check)
    await rec.start()
    rec.cap("Scout, the student's helper. Cover-letter points for one award")
    await rec.hold(2000)
    top = page.locator("#panel .leads > li").first
    block = top.locator(".scout-points").first
    btn = await need(page, "#panel .leads > li:first-child [data-key^=cover-]", "a Cover-letter points button")
    await btn.scroll_into_view_if_needed()
    rec.cap("The button glows while a model reads the CV and writes the points")
    await rec.hold(500)
    await rec.focus(btn, pad=200)
    await rec.hold(900)
    await click(page, btn)
    await rec.hold(3600)  # the glow, at full speed
    try:
        await rec.quickly(lambda: top.locator(
            "[data-key^=cover-]:not([aria-busy=true])").wait_for(timeout=240_000), speed=14)
    except Exception as e:  # noqa: BLE001
        raise SceneError("the cover-letter points took longer than 240 s") from e
    await need(page, "#panel .leads > li:first-child .scout-points", "the cover-letter points")
    if await block.locator(":scope > p.notice.warn").count():
        raise SceneError("the cover-letter points were withheld; run again")
    rec.wide()
    rec.cap("Scout, the student's helper. Cover-letter points for one award")
    await block.scroll_into_view_if_needed()
    await rec.hold(500)
    await rec.focus(block, pad=24)
    await rec.hold(4000)
    cites = block.locator("button.cite")
    if await cites.count():
        rec.cap("Every point cites the student's own CV or the award's record")
        await click(page, cites.first)
        await rec.hold(500)
        await rec.hold(2800)
    rec.wide()
    rec.cap("Ask Scout a question")
    await page.evaluate("window.scrollTo(0, 0)")
    await click(page, page.locator("#tab-scout"))
    q = await need(page, "#scout-q", "the Scout box")
    await rec.hold(700)
    await rec.focus(page.locator(".scout-ask-row").first, pad=60)
    await rec.hold(1800)
    await click(page, q)
    await q.press_sequentially(QUESTION, delay=45)
    await rec.hold(500)
    await click(page, page.locator(".scout-ask button[type=submit]"))
    rec.cap("The box glows while Scout works")
    await rec.hold(4200)  # the glow, at full speed
    answer = page.locator(".scout-answer").last
    try:
        await rec.quickly(lambda: answer.wait_for(timeout=240_000), speed=10)
    except Exception as e:  # noqa: BLE001
        raise SceneError("Scout gave no answer in 240 s") from e
    await settle(page, 1000)
    rec.wide()
    rec.cap("A cited answer")
    await rec.focus(answer, pad=30)
    await rec.hold(3800)
    rec.wide()
    rec.cap("Clear starts over")
    clear = page.locator("[data-key=scout-clear]")
    await need(page, "[data-key=scout-clear]", "the Clear button")
    await rec.focus(page.locator(".scout-ask-row").first, pad=60)
    await rec.hold(1500)
    await click(page, clear)
    await settle(page, 900)
    q = await need(page, "#scout-q", "the Scout box")
    rec.cap("A message about distress")
    await click(page, q)
    await q.press_sequentially(DISTRESS_MESSAGE, delay=40)
    await rec.hold(700)
    await click(page, page.locator(".scout-ask button[type=submit]"))
    reply = page.locator(".scout-answer, .scout-msg").last
    await need(page, "#panel :text('Tuttleman Counseling')", "the help links in the reply", 60_000)
    await settle(page, 800)
    rec.cap("Scout stops and shows help. The reply is fixed text written by code.")
    box = page.locator(".scout-x").last
    await rec.focus(box, pad=40)
    await rec.hold(5200)
    rec.wide()
    rec.cap("")
    await rec.hold(700)
    await rec.stop()
    del reply
    return rec


FILMS = {"researcher": researcher, "student": student, "quick": quick, "scout": scout}
STEM = {"quick": "quick-student"}
SPEED = {"quick": 1.5}
ACCOUNT = {"researcher": "RESEARCHER", "student": "STUDENT", "quick": "STUDENT", "scout": "STUDENT"}


async def main(a: argparse.Namespace) -> int:
    names = film.aliases()
    out = Path(a.out)
    out = out if out.is_absolute() else ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    exe = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    failed = 0
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe[-1] if exe else None, args=["--no-sandbox"])
        for name in a.films:
            user = os.environ.get(f"DEMO_{ACCOUNT[name]}_USERNAME")
            pw = os.environ.get(f"DEMO_{ACCOUNT[name]}_PASSWORD")
            if user and pw:  # the account for this film, from the deploy's env file
                os.environ["PERCH_TOUR_USER"], os.environ["PERCH_TOUR_PASSWORD"] = user, pw
            ctx = await b.new_context(viewport=VIEW, device_scale_factor=2, color_scheme="light")
            page = await ctx.new_page()
            page.set_default_timeout(20_000)
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            given, alias = pi_parts(a.author) if name == "researcher" else ([], "")
            check = NameCheck(names, surnames=(name == "researcher"), given=given)
            t0 = time.time()
            try:
                await Recorder.install(page)
                if name == "researcher":
                    await alias_checked(page, names, check, given, alias)
                await film.sign_in(page, a.base, None)
                await FILMS[name](page, a.base, a, check)
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                print(f"{name}: FAILED - {msg}")
                failed += 1
                await ctx.close()
                continue
            await ctx.close()
            if check.hits:
                print(f"{name}: NAME CHECK FAILED - {check.report()}")
                failed += 1
                continue
            res = render(RAW / name, out / STEM.get(name, name), 640 if a.dry else a.webp_width,
                         0 if a.dry else a.mp4_width, a.fps, a.quality,
                         tail=0.7 if name in SPEED else 1.5, speed=SPEED.get(name, 1.0))
            sizes = ", ".join(f"{k} {v[1]:.1f} MB" for k, v in res.items() if k != "seconds")
            print(f"{name}: filmed in {time.time() - t0:.0f} s of work, film length "
                  f"{res['seconds']:.1f} s, {sizes}; name check: {check.report()}")
            if errors:
                print(f"{name}: page errors: {errors}")
        await b.close()
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--films", nargs="*", default=list(FILMS), choices=list(FILMS))
    ap.add_argument("--out", default="build/films")
    ap.add_argument("--author", default=AUTHOR)
    ap.add_argument("--citizenship", default="us_citizen")
    ap.add_argument("--state", default="PA")
    ap.add_argument("--webp-width", type=int, default=1280)
    ap.add_argument("--mp4-width", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--quality", type=int, default=70)
    ap.add_argument("--dry", action="store_true", help="a timing check: a small WebP, no MP4")
    sys.exit(asyncio.run(main(ap.parse_args())))
