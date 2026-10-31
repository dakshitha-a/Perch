"""Measure the user's paths through the running app: the baseline for UI simplification.

  uv run --no-project --with playwright python scripts/path_measure.py \\
      [--base http://127.0.0.1:8091] [--out build/paths] [--shots build/review/workflow] \\
      [--only pi pi-live student private]

Each task is one person's path, driven the way scripts/ux_walk.py drives it (that file is
the map of the UI). For every task the script records:
- screens: each change of view the person sees (the hash route, including the brief's tab);
- clicks: every press of a button, link, tab or summary the task needs;
- typed: fields the person fills in;
- waits: every time the person waits for the app, with its seconds (a wait under 1 s is
  kept in the JSON but not counted in the table);
- scrolls: clicks whose target was outside the window, so the page had to scroll first;
- network: requests and bytes, split by path, and the brief polls during the build.

Tasks:
- pi: PI-4 (A5026494099) finds their brief (the default request, which a warm server
  answers from memory), reads why the top lead fits, opens its record, keeps two leads,
  compares them, drafts and copies a hand-off, asks Scout one question and exports.
- pi-live: the same, with "Career stage" set so the brief is built live (is_default()
  is false), to measure the build a non-demo researcher gets.
- student: the SYNTHETIC persona-ug through the Student door: fellowships and sample
  scholarships, the code-written note, one Scout question, an export.
- private: the SYNTHETIC persona-1 builds a private brief from one document (the draft
  aims) with no OpenAlex id, as its README requires.

Researchers appear by alias only (scripts/tour/film.py). Writes <out>/paths.json and
screenshots to <shots>; prints a Markdown table. Every session is ended after its task.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Page, async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/tour"))
from film import alias_responses, aliases  # noqa: E402

SYN = ROOT / "data/synthetic"
AUTHOR = "A5026494099"  # PI-4
LAPTOP = {"width": 1280, "height": 860}
WAIT_COUNTED = 1.0  # seconds: a shorter wait is recorded but not counted in the table

VIEW = """() => `${document.body.dataset.screen || ''}|${location.hash.split('?')[0]}`"""
SCOUT_IDLE = """() => !document.querySelector('.scout-wait')
  && !document.querySelector('.scout-ask button[disabled]')"""
BUILT = """() => { const p = document.querySelector('#progress');
  return p && /ready|finished|failed|stopped/i.test(p.innerText)
    && !/Building|Searching/i.test(p.innerText.split('\\n')[0]); }"""


def bucket(url: str) -> str:
    u = urlsplit(url)
    if u.hostname and u.hostname not in ("127.0.0.1", "localhost"):
        return "third-party"
    p = u.path
    for prefix in ("/private/brief", "/private/records", "/private/scout", "/private/compare",
                   "/private/handoff", "/private/export", "/private/documents",
                   "/private/session", "/private/samples", "/authors/resolve"):
        if p.startswith(prefix):
            return prefix
    if p == "/private":
        return "/private (info)"
    if p.endswith((".js", ".css", ".svg", ".html")) or p == "/":
        return "static"
    return p


@dataclass
class Task:
    name: str
    label: str
    screens: int = 0
    clicks: int = 0
    typed: int = 0
    scrolls: int = 0
    waits: list[tuple[str, float]] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    net: list[dict] = field(default_factory=list)
    phase: str = ""
    errors: list[str] = field(default_factory=list)
    started: float = 0.0
    wall: float = 0.0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        counted = [(w, s) for w, s in self.waits if s >= WAIT_COUNTED]
        by: dict[str, dict] = {}
        for r in self.net:
            b = by.setdefault(r["bucket"], {"requests": 0, "bytes": 0})
            b["requests"] += 1
            b["bytes"] += r["bytes"]
        polls = [r for r in self.net if r["bucket"] == "/private/brief" and r["method"] == "GET"
                 and r["phase"] == "build"]
        return {"task": self.name, "label": self.label, "screens": self.screens,
                "clicks": self.clicks, "typed": self.typed, "scrolls": self.scrolls,
                "waits": len(counted), "wait_s": round(sum(s for _, s in counted), 1),
                "wait_detail": [{"what": w, "s": round(s, 2)} for w, s in self.waits],
                "wall_s": round(self.wall, 1), "requests": len(self.net),
                "kb": round(sum(r["bytes"] for r in self.net) / 1000, 1),
                "build_polls": len(polls),
                "build_poll_kb": round(sum(r["bytes"] for r in polls) / 1000, 1),
                "network": by, "steps": self.steps, "notes": self.notes,
                "errors": self.errors}


class Driver:
    def __init__(self, page: Page, task: Task, shots: Path) -> None:
        self.page, self.t, self.shots = page, task, shots
        self.view = None
        self.n = 0
        page.on("response", self._response)

    def _response(self, r) -> None:  # noqa: ANN001 - a playwright Response
        try:
            size = int(r.headers.get("content-length") or 0)
        except ValueError:
            size = 0
        self.t.net.append({"url": urlsplit(r.url).path, "bucket": bucket(r.url),
                           "method": r.request.method, "status": r.status, "bytes": size,
                           "phase": self.t.phase,
                           "at": round(time.perf_counter() - self.t.started, 2)})

    async def _seen(self, why: str) -> None:
        v = await self.page.evaluate(VIEW)
        if v != self.view:
            self.view = v
            self.t.screens += 1
            self.t.steps.append({"screen": v.split("|", 1)[1] or "#/", "after": why})

    async def goto(self, url: str) -> None:
        await self.page.goto(url)
        await self.page.wait_for_selector(".landing")
        await self._seen("open the app")

    async def click(self, selector: str, what: str, *, nth: int = 0) -> None:
        loc = self.page.locator(selector).nth(nth)
        await loc.wait_for(state="visible", timeout=30000)
        box = await loc.bounding_box()
        vh = self.page.viewport_size["height"]
        if box and (box["y"] < 0 or box["y"] + box["height"] > vh):
            self.t.scrolls += 1
            self.t.steps.append({"scroll": what})
        await loc.click()
        self.t.clicks += 1
        self.t.steps.append({"click": what})
        await self.page.wait_for_timeout(150)
        await self._seen(what)

    async def type(self, selector: str, text: str, what: str) -> None:
        loc = self.page.locator(selector)
        box = await loc.bounding_box()
        vh = self.page.viewport_size["height"]
        if box and (box["y"] < 0 or box["y"] + box["height"] > vh):
            self.t.scrolls += 1
            self.t.steps.append({"scroll": what})
        await loc.fill(text)
        self.t.typed += 1
        self.t.steps.append({"type": what, "chars": len(text)})

    async def select(self, selector: str, value: str, what: str) -> None:
        await self.page.select_option(selector, value)
        self.t.clicks += 1
        self.t.steps.append({"select": what})

    async def wait(self, what: str, js: str | None = None, selector: str | None = None,
                   timeout: int = 300_000, phase: str = "") -> None:
        self.t.phase = phase or what
        t0 = time.perf_counter()
        if selector:
            await self.page.wait_for_selector(selector, timeout=timeout)
        else:
            await self.page.wait_for_function(js, timeout=timeout, polling=100)
        s = time.perf_counter() - t0
        self.t.phase = ""
        self.t.waits.append((what, s))
        self.t.steps.append({"wait": what, "s": round(s, 2)})
        await self._seen(what)

    async def snap(self, name: str) -> None:
        self.n += 1
        path = self.shots / f"{self.t.name}-{self.n:02d}-{name}.png"
        await self.page.screenshot(path=str(path))
        self.t.steps.append({"shot": str(path.relative_to(ROOT))})

    async def step(self, what: str, coro) -> bool:  # noqa: ANN001 - an awaitable
        try:
            await coro
            return True
        except Exception as e:  # noqa: BLE001 - a failed step is recorded, the task goes on
            self.t.errors.append(f"{what}: {type(e).__name__}: {str(e).splitlines()[0][:160]}")
            return False


async def ask_scout(d: Driver, question: str) -> None:
    await d.click("#tab-scout", "Ask Scout tab")
    await d.page.wait_for_selector("#scout-q")
    await d.type("#scout-q", question, "Scout question")
    await d.click(".scout-ask button[type=submit]", "Ask")
    await d.page.wait_for_timeout(300)
    await d.wait("Scout answer", SCOUT_IDLE, timeout=180_000)
    await d.snap("scout")


async def export_md(d: Driver, private: bool = True) -> None:
    await d.page.evaluate("() => window.scrollTo(0, 0)")
    await d.click("[data-key=export]", "Export menu")
    async with d.page.expect_download(timeout=30000) as dl:
        await d.click(".export-pop button:has-text('Markdown'), .export-pop a:has-text('Markdown')",
                      "Markdown")
    got = await dl.value
    d.t.notes.append(f"export downloaded as {got.suggested_filename}")


async def end_session(page: Page) -> None:
    try:
        if await page.locator("#end-session").is_visible():
            await page.click("#end-session")
            await page.wait_for_selector("#models-dialog[open]")
            await page.click("[data-key=end-ok]")
            await page.wait_for_timeout(500)
    except Exception:  # noqa: BLE001 - the session ends on idle anyway
        pass


async def pi_task(d: Driver, base: str, live: bool) -> None:
    await d.goto(base + "/#/")
    await d.type("#q", AUTHOR, "researcher id")
    await d.click(".searchbox button[type=submit]", "Find")
    await d.wait("search results", selector=".cand", timeout=30000)
    if await d.page.locator(".cand button.btn.outline").count():  # an exact id picks itself (W1)
        await d.click(".cand button.btn.outline", "This is the one")
    if live:  # any context makes the request non-default, so it is built live
        await d.click("[data-key=more-ctx]", "Tell Perch more")  # folded since W1
        await d.select("#ctx-stage", "established", "Career stage")
    await d.click("[data-key=build]", "Build brief")
    await d.page.wait_for_selector("#tab-routes", timeout=60000)
    await d.wait("brief build", BUILT, phase="build")
    await d.snap("built")
    lead = ".leads > li"
    await d.step("why", d.click(f"{lead} summary[data-key=why]", "Why it fits"))
    await d.snap("why")
    await d.click(f"{lead} .title-btn", "lead title (Evidence)")
    await d.wait("evidence record", selector="#rail-ev .rec-title, #evidence-body .rec-title",
                 timeout=30000)
    await d.snap("evidence")
    for i in (0, 1):
        if not await d.page.locator(f"{lead} .btn.keep").nth(i).is_visible():
            await d.click("details.weak-fold > summary", "Weaker matches")  # U24's fold
        await d.click(f"{lead} .btn.keep", f"Keep lead {i + 1}", nth=i)
        await d.page.wait_for_timeout(300)
    await d.click("#tab-compare", "Compare tab")
    await d.wait("comparison", selector="table.compare", timeout=30000)
    await d.click("[data-key=handoff-make]", "Draft the email")
    await d.wait("hand-off draft", selector="#handoff-body", timeout=180_000)
    await d.click("[data-key=handoff-copy]", "Copy the draft")
    await d.snap("handoff")
    await ask_scout(d, "Why does the top lead fit?")
    await export_md(d)


async def student_task(d: Driver, base: str) -> None:
    await d.goto(base + "/#/")
    await d.click("[data-key=seg-s]", "Student")
    await d.click("[data-key=student]", "Start with your CV or résumé")
    await d.wait("student form (session opens)", selector="#st-cv", timeout=30000)
    for kind in ("cv", "interests", "achievements"):
        await d.type(f"#st-{kind}", (SYN / "persona-ug" / f"{kind}.md").read_text(), kind)
    await d.click("[data-key=st-build]", "Find fellowships and scholarships")
    await d.page.wait_for_selector("#progress", timeout=30000)
    await d.wait("brief build", BUILT, phase="build")
    await d.snap("built")
    first = ".leads > li"
    if not await d.page.evaluate(
            "() => Boolean(document.querySelector('.leads > li details.why[open]'))"):
        await d.step("why", d.click(f"{first} details.why > summary", "Why it may fit"))
    else:
        d.t.notes.append("the first card's reasons were already open: no click")
    await d.click(f"{first} .title-btn", "option title (Evidence)")
    await d.wait("evidence record", selector="#rail-ev .rec-title, #evidence-body .rec-title",
                 timeout=30000)
    await d.click(f"{first} .btn.keep", "Keep a fellowship")
    await d.page.wait_for_timeout(300)
    await d.click("[data-key=route-S]", "Scholarships")
    await d.page.wait_for_timeout(300)
    await d.click(f"{first} .btn.keep", "Keep a sample scholarship")
    await d.page.wait_for_timeout(300)
    await d.snap("kept")
    await d.click("#tab-compare", "Compare tab")
    await d.page.wait_for_selector("table.compare", timeout=30000)
    if await d.page.locator("[data-key=st-draft]").count():  # shows at once since W8
        await d.click("[data-key=st-draft]", "Draft the note")
    await d.page.wait_for_selector(".draft textarea", timeout=10000)
    await d.click(".draft .actions button:has-text('Copy')", "Copy")
    await d.snap("note")
    await ask_scout(d, "What do my kept options still need?")
    await export_md(d)


async def private_task(d: Driver, base: str) -> None:
    await d.goto(base + "/#/")
    await d.click("[data-key=more-opts]", "More options")
    await d.click("[data-key=docs-link]", "No public papers yet? link")
    await d.click("button:has-text('Start a session')", "Start a session")
    await d.wait("session opens", selector="#doc-proposal", timeout=30000)
    await d.type("#doc-proposal", (SYN / "persona-1/specific_aims_draft.md").read_text(),
                 "draft proposal")
    await d.click("#doc-proposal ~ .doc-actions button:has-text('Add text')", "Add text")
    await d.wait("document added", js="() => !document.querySelector('#doc-proposal')",
                 timeout=30000)
    await d.click("button:has-text('Build brief')", "Build brief")
    await d.page.wait_for_selector("#progress", timeout=30000)
    await d.wait("brief build", BUILT, phase="build")
    await d.snap("built")
    if not d.page.url.endswith("/routes"):  # lands on Routes since W11
        await d.click("#tab-routes", "Routes tab")
    await d.page.wait_for_timeout(500)
    await d.snap("routes")


TASKS = {
    "pi": ("PI-4 (A5026494099): warm default brief, why, evidence, keep 2, compare, hand-off, "
           "Scout, export", lambda d, b: pi_task(d, b, live=False)),
    "pi-live": ("PI-4 (A5026494099): same path, brief built live (career stage set)",
                lambda d, b: pi_task(d, b, live=True)),
    "student": ("SYNTHETIC persona-ug: fellowships and sample scholarships, note, Scout, export",
                student_task),
    "private": ("SYNTHETIC persona-1: private brief from one document, no OpenAlex id",
                private_task),
}


def table(rows: list[dict]) -> str:
    out = ["| Task | Screens | Clicks | Typed | Waits ≥1 s (s) | Scrolls | Wall s | "
           "Requests | KB | Build polls (KB) |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['task']}: {r['label']} | {r['screens']} | {r['clicks']} | {r['typed']} | "
                   f"{r['waits']} ({r['wait_s']}) | {r['scrolls']} | {r['wall_s']} | "
                   f"{r['requests']} | {r['kb']} | {r['build_polls']} ({r['build_poll_kb']}) |")
    return "\n".join(out)


async def main(base: str, out: Path, shots: Path, only: list[str]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    shots.mkdir(parents=True, exist_ok=True)
    names = aliases()
    exe = sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))[-1]
    rows = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        for key in only:
            label, run = TASKS[key]
            ctx = await browser.new_context(viewport=LAPTOP, accept_downloads=True,
                                            device_scale_factor=1)
            await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
            page = await ctx.new_page()
            await alias_responses(page, names)
            t = Task(key, label)
            page.on("pageerror", lambda e, t=t: t.errors.append(f"page error: {e}"))
            d = Driver(page, t, shots)
            t.started = time.perf_counter()
            await d.step("task", run(d, base))
            t.wall = time.perf_counter() - t.started
            await end_session(page)
            await ctx.close()
            rows.append(t.summary())
            print(f"{key}: {len(t.errors)} errors", *t.errors, sep="\n  ", file=sys.stderr)
        await browser.close()
    text = json.dumps({"base": "dev server", "viewport": LAPTOP, "wait_counted_s": WAIT_COUNTED,
                       "tasks": rows}, indent=1)
    for real, alias in names.items():
        text = text.replace(real, alias)
    (out / "paths.json").write_text(text)
    print(table(rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8091")
    ap.add_argument("--out", type=Path, default=ROOT / "build/paths")
    ap.add_argument("--shots", type=Path, default=ROOT / "build/review/workflow")
    ap.add_argument("--only", nargs="+", default=list(TASKS), choices=list(TASKS))
    a = ap.parse_args()
    asyncio.run(main(a.base, a.out, a.shots, a.only))
