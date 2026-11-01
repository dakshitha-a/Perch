"""Walk every screen of the running app for each audience, with automatic checks (S21).

  uv run --no-project --with playwright python scripts/ux_walk.py \\
      [--base http://127.0.0.1:8090] [--axe PATH/axe.min.js (axe-core 4.10.2, cdnjs)] [--out build/ux] [--only pi student private]

Audiences: the PI demo researcher (PI-4, by OpenAlex id), the three SYNTHETIC student
personas (persona-ug, persona-masters, persona-phd) and the SYNTHETIC researcher
persona-1 with private documents. Each flow is captured on a phone (390 px) and a laptop
(1280 px); the PI flow also in dark mode. Researchers appear by alias only, as in the
README clips (scripts/tour/film.py).

At every captured state the script records, in <out>/report-<groups>.json:
- axe-core violations (WCAG 2.0 to 2.2 A and AA), if --axe points at axe.min.js;
- interactive elements smaller than 44 px (the design's target) and 24 px (WCAG 2.2 AA);
- sideways scroll;
- whether the session frame shows (the Local / Cloud switch state, the frame line, and the
  body class that marks Cloud on). Since S23 every brief is a session; the PI flow also
  opens the cloud warning and dismisses it, so no cloud call is made.
It also tabs through Find and a brief and records the focus order and whether each focus
is visible. S25 reruns this script before the freeze.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import sys
from collections.abc import Awaitable
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Route, async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/tour"))
from film import alias_responses, aliases  # noqa: E402

SYN = ROOT / "data/synthetic"
AUTHOR = "A5026494099"  # PI-4, the demo researcher
PHONE = {"width": 390, "height": 844}
LAPTOP = {"width": 1280, "height": 860}
STUDENTS = ("persona-ug", "persona-masters", "persona-phd")

PROBE = """() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const name = (el) => (el.getAttribute('aria-label') || el.innerText || el.value || el.id || el.tagName)
    .trim().replace(/\\s+/g, ' ').slice(0, 50);
  const small = [];
  for (const el of document.querySelectorAll('a[href], button, input, select, textarea, summary, [role=switch], [role=tab], label.btn')) {
    if (!vis(el) || el.closest('[hidden]')) continue;
    if (el.type === 'checkbox' || el.type === 'radio') continue;  // the label is the target
    const r = el.getBoundingClientRect();
    const inline = el.tagName === 'A' && !el.classList.contains('btn') && getComputedStyle(el).display === 'inline';
    if (r.width < 44 || r.height < 44) small.push({ el: name(el), tag: el.tagName.toLowerCase(),
      w: Math.round(r.width), h: Math.round(r.height), inline, under24: r.width < 24 || r.height < 24 });
  }
  const chip = document.querySelector('#status-chip');
  return { small, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    session: { word: chip && chip.innerText.trim(), frame: Boolean(chip && vis(chip)),
      text: chip && chip.getAttribute('aria-label'),
      cloudBody: document.body.classList.contains('cloud-on') },
    title: document.title, hash: location.hash };
}"""

FOCUS = """() => {
  const el = document.activeElement; if (!el || el === document.body) return null;
  const s = getComputedStyle(el);
  const shown = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none';
  const r = el.getBoundingClientRect();
  return { el: (el.getAttribute('aria-label') || el.innerText || el.placeholder || el.id || el.tagName)
    .trim().replace(/\\s+/g, ' ').slice(0, 40), tag: el.tagName.toLowerCase(), role: el.getAttribute('role'),
    visible: shown, onscreen: r.bottom > 0 && r.top < innerHeight };
}"""


# Layout checks the screenshots alone missed (S27). A pill group is stretched when it is
# much wider than its buttons.
STRETCH = """() => [...document.querySelectorAll('.route-switch, .seg')].filter(g => g.offsetParent)
  .filter(g => getComputedStyle(g).display !== 'grid')
  .map(g => [g, [...g.children].reduce((w, c) => w + c.getBoundingClientRect().width, 0)])
  .filter(([g, inner]) => g.getBoundingClientRect().width > inner + 40)
  .map(([g, inner]) => `${g.className} is ${Math.round(g.getBoundingClientRect().width)} px wide `
       + `for ${Math.round(inner)} px of buttons`)"""
# With the page scrolled, the side rail and the Evidence box must end inside the window,
# and the shortlist must not be cut off.
RAIL = """() => {
  const out = [], vh = innerHeight, rail = document.querySelector('.cols > .rail');
  if (!rail || getComputedStyle(rail).position !== 'sticky') return out;
  for (const [sel, label] of [['.cols > .rail', 'rail'], ['.rail-evidence', 'Evidence box']]) {
    const el = document.querySelector(sel);
    if (el && el.getBoundingClientRect().bottom > vh + 1)
      out.push(`${label} ends ${Math.round(el.getBoundingClientRect().bottom - vh)} px below the window`);
  }
  const sl = document.querySelector('.rail .shortlist');
  if (sl && !sl.querySelector('li') && sl.scrollHeight > sl.clientHeight + 1)
    out.push('the empty shortlist is cut off');
  return out; }"""


# The open Evidence (rail or phone sheet): no text past its right edge, and no long
# text shown twice.
EVIDENCE = """() => {
  const out = [];
  for (const box of document.querySelectorAll('.rail-evidence, .sheet-body')) {
    if (!box.offsetParent && getComputedStyle(box).position !== 'fixed') continue;
    const r = box.getBoundingClientRect();
    if (!r.width) continue;
    const edge = r.right - parseFloat(getComputedStyle(box).paddingRight) + 1;
    const wide = [...box.querySelectorAll('p, dd, li, h2, h3, a')]
      .filter(el => el.getClientRects().length && el.getBoundingClientRect().right > edge);
    if (wide.length) out.push(`${wide.length} text blocks run ${Math.round(Math.max(...wide.map(
      el => el.getBoundingClientRect().right)) - edge)} px past the Evidence box's edge`);
    const longs = [...box.querySelectorAll('.long')].map(el => el.textContent.replace(/…$/, '').slice(0, 200));
    if (longs.some((t, i) => longs.findIndex(u => u.startsWith(t) || t.startsWith(u)) !== i))
      out.push('the same long text is shown twice');
  }
  return out; }"""


# Leftovers of the ask-first mode, gone since S27: no Approve or Skip, no "Waiting for you".
GATE = """() => [...document.querySelectorAll('.scout-card, .help, main')].some(el =>
  el.querySelector(':scope > .scout-actions') || /Waiting for you|\\bApprove\\b/.test(el.innerText))"""
# A MutationObserver counts loading placeholders put into an Evidence box that is already
# open; going from record to record must crossfade, not blank to the owl (S27).
WATCH_FLASH = """() => { window.__flash = 0; const seen = (n) => n.nodeType === 1 && (n.matches('.loading')
  || n.querySelector('.loading'));
  for (const box of document.querySelectorAll('#evidence-body, #rail-ev'))
    new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) if (seen(n)) window.__flash++; })
      .observe(box, { childList: true, subtree: true }); }"""


async def checks_flow(w: Walk, page: Page, base: str, tag: str) -> None:
    """Motion and chat checks the static screenshots missed (S27): opening Evidence must not
    move the page, going from paper to paper must not flash, Scout shows no approval gate
    while a step runs, and the question box stays in the window as the chat grows."""
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".cand", timeout=20000)
    await pick_and_build(page)
    await page.wait_for_selector("#tab-routes", timeout=60000)
    await w.step(tag, "built", wait_built(page))
    await page.click("#tab-profile")
    await page.wait_for_timeout(600)
    papers = page.locator("button.paper")
    before = await page.locator("#panel").bounding_box()
    await papers.nth(0).click()
    await page.wait_for_selector("#evidence .rec-title")
    await page.wait_for_timeout(500)
    after = await page.locator("#panel").bounding_box()
    if abs(before["x"] - after["x"]) > 1 or abs(before["width"] - after["width"]) > 1:
        w.errors.append(f"{tag}: evidence: motion: opening Evidence moved the page "
                        f"({round(before['width'])} -> {round(after['width'])} px wide)")
    await w.snap(page, tag, "evidence-open")
    await page.evaluate(WATCH_FLASH)
    for i in (1, 2):
        await papers.nth(i).click(force=True)
        await page.wait_for_timeout(700)
    if n := await page.evaluate("() => window.__flash"):
        w.errors.append(f"{tag}: evidence: motion: going from paper to paper blanked Evidence {n} times")
    # A click anywhere outside the Evidence card closes it (S27).
    await page.mouse.click(20, 40 if page.viewport_size["width"] < 700 else page.viewport_size["height"] // 2)
    await page.wait_for_timeout(500)
    if await page.evaluate("() => !document.querySelector('#evidence').hidden"):
        w.errors.append(f"{tag}: evidence: a click outside the Evidence card did not close it")
        await page.keyboard.press("Escape")
    # Open Scout from the top of the page, as a reader does straight after the brief loads.
    await page.evaluate("() => window.scrollTo(0, 0)")
    await page.wait_for_timeout(200)
    await page.click("#tab-scout")
    await page.wait_for_selector("#scout-q")
    if await page.evaluate("() => Boolean(document.querySelector('#panel aside'))"):
        w.errors.append(f"{tag}: scout: a side box sits beside the chat; its content belongs in the welcome")
    # The question box is on the bottom edge from the first view, before anything is asked (S27).
    await page.wait_for_timeout(400)
    box = await page.locator("#scout-q").bounding_box()
    vh = page.viewport_size["height"]
    if not box or box["y"] + box["height"] > vh or vh - (box["y"] + box["height"]) > 40:
        w.errors.append(f"{tag}: scout: chat: on first open the question box is not on the bottom edge of the window "
                        f"(bottom at {round(box['y'] + box['height']) if box else '?'} px, window {vh} px)")
    await w.snap(page, tag, "scout-welcome")
    # No scroll bar on the chat, and the page's bar shows only near the pointer (S27).
    if await page.evaluate("() => getComputedStyle(document.querySelector('.scout-scroll')).scrollbarWidth !== 'none'"):
        w.errors.append(f"{tag}: scout: chat: the conversation shows a scroll bar")
    vw = page.viewport_size["width"]
    await page.mouse.move(vw // 2, page.viewport_size["height"] // 2)
    if not await page.evaluate("() => /transparent|rgba\\(0, 0, 0, 0\\) rgba\\(0, 0, 0, 0\\)/.test(getComputedStyle(document.documentElement).scrollbarColor)"):
        w.errors.append(f"{tag}: page: the scroll bar shows while the pointer is away from it")
    await page.mouse.move(vw - 3, page.viewport_size["height"] // 2)
    if await page.evaluate("() => /rgba\\(0, 0, 0, 0\\) rgba\\(0, 0, 0, 0\\)/.test(getComputedStyle(document.documentElement).scrollbarColor)"):
        w.errors.append(f"{tag}: page: the scroll bar stays hidden with the pointer over it")
    await page.wait_for_selector("#scout-q")
    for q in ("Why does the top lead fit?", "Only R21 grants that close by 2027-03-01"):
        await page.fill("#scout-q", q)
        await page.click(".scout-ask button[type=submit]")
        gate = False
        for _ in range(900):  # up to 90 s per question
            gate = gate or await page.evaluate(GATE)
            if await page.evaluate("() => !document.querySelector('.scout-wait') && !document.querySelector('.scout-ask button[disabled]')"):
                break
            await page.wait_for_timeout(100)
        if gate:
            w.errors.append(f"{tag}: scout: an approval card or button showed while Scout ran")
        await page.wait_for_timeout(300)
        box = await page.locator("#scout-q").bounding_box()
        vh = page.viewport_size["height"]
        if not box or box["y"] + box["height"] > vh or box["y"] < 0:
            w.errors.append(f"{tag}: scout: chat: the question box is outside the window after {q!r}")
        elif vh - (box["y"] + box["height"]) > 40:
            w.errors.append(f"{tag}: scout: chat: the question box sits {round(vh - box['y'] - box['height'])} px "
                            "above the bottom of the window")
        seen = await page.evaluate("""() => { const box = document.querySelector('.scout-scroll');
          const qs = document.querySelectorAll('.scout-x > .scout-q'); if (!box || !qs.length) return false;
          const b = box.getBoundingClientRect(), r = qs[qs.length - 1].getBoundingClientRect();
          return box.scrollHeight - box.scrollTop - box.clientHeight < 32 || (r.top >= b.top - 1 && r.top < b.bottom); }""")
        if not seen:
            w.errors.append(f"{tag}: scout: chat: the newest reply is not in view after {q!r}")
        await w.snap(page, tag, "scout-chat")
    grow = await page.evaluate("() => document.documentElement.scrollHeight - innerHeight")
    if grow > 400 and page.viewport_size["width"] >= 700:
        w.errors.append(f"{tag}: scout: chat: the page grows {grow} px past the window; "
                        "older replies should scroll inside the chat")
    # S28: how Scout read the question sits above the answer, the step cards are folded under
    # it with where each step ran, and no step names a researcher (Scout is fixed to the brief).
    read = await page.evaluate("""() => { const xs = document.querySelectorAll('.scout-x');
      const x = xs[xs.length - 1]; if (!x) return null;
      const steps = x.querySelector('details.scout-steps');
      return {read: Boolean(x.querySelector('.scout-read li')), folded: Boolean(steps && !steps.open),
        where: x.querySelectorAll('.scout-where').length, cards: x.querySelectorAll('.scout-card').length,
        researcher: [...x.querySelectorAll('.chip')].some(c => /^Researcher:/.test(c.innerText))}; }""")
    if not read or not read["read"]:
        w.errors.append(f"{tag}: scout: no 'How Scout read your question' block above the answer")
    if not read or not read["folded"]:
        w.errors.append(f"{tag}: scout: the step cards are not folded under the answer")
    if read and read["where"] < read["cards"]:
        w.errors.append(f"{tag}: scout: {read['cards'] - read['where']} step cards do not say where they ran")
    if read and read["researcher"]:
        w.errors.append(f"{tag}: scout: a step names a researcher; Scout is fixed to the brief")
    await w.snap(page, tag, "scout-read")
    # Stop ends a question between steps; the page says so and a follow-up still works.
    await page.fill("#scout-q", "Compare my top three leads and explain why the first one fits")
    await page.click(".scout-ask button[type=submit]")
    try:
        await page.wait_for_selector(".scout-stop", timeout=15000)
        await page.click(".scout-stop")
    except Exception:  # noqa: BLE001 - reported as a finding
        w.errors.append(f"{tag}: scout: no Stop button while Scout works")
    for _ in range(900):
        if await page.evaluate("() => !document.querySelector('.scout-wait') && !document.querySelector('.scout-ask button[disabled]')"):
            break
        await page.wait_for_timeout(100)
    last = await page.evaluate("""() => { const xs = document.querySelectorAll('.scout-x'); const x = xs[xs.length - 1];
      return {stopped: Boolean(x.querySelector('.scout-stopped')), answer: Boolean(x.querySelector('.scout-answer')),
        warn: (x.querySelector('.notice') || {}).innerText || ''}; }""")
    if not (last["stopped"] or last["answer"]) or last["warn"]:
        w.errors.append(f"{tag}: scout: after Stop the page shows neither the stop note nor an answer {last['warn']!r}")
    await w.snap(page, tag, "scout-stopped")
    await page.goto(base + "/#/help")
    await page.wait_for_timeout(600)
    if await page.evaluate(GATE):
        w.errors.append(f"{tag}: help: the Scout picture still shows Approve or Waiting for you")


async def sort_stays(w: Walk, page: Page, tag: str) -> None:
    """The sort switch must stay put when the sort changes (S27)."""
    boxes = []
    for key in ("closing", "order"):
        btn = page.locator(f"[data-key=sort-{key}]")
        if await btn.count():
            await btn.click()
            await page.wait_for_timeout(150)
            boxes.append(await page.locator(".sort-switch").bounding_box())
    # At laptop width the sort switch shares the Grants | Industry (or Fellowships |
    # Scholarships) row, as Dakshitha asked.
    toggle = await page.locator(".route-row > .route-switch:not(.sort-switch)").bounding_box()
    if page.viewport_size["width"] >= 1024 and toggle and boxes and \
            abs(toggle["y"] - boxes[-1]["y"]) > 2:
        w.errors.append(f"{tag}: sort: layout: the sort switch is not on the toggle's row")
    if len(boxes) < 2:
        w.errors.append(f"{tag}: sort: no sort switch")
    elif any(abs(b["x"] - boxes[0]["x"]) > 1 or abs(b["y"] - boxes[0]["y"]) > 1 for b in boxes):
        w.errors.append(f"{tag}: sort: layout: the sort switch moves when the sort changes")


# Console errors the flows cause on purpose: the browser logs every 4xx answer as a failed
# resource load (a check that a session ended answers 401, a missing brief 404).
EXPECTED_CONSOLE = re.compile(r"^Failed to load resource: the server responded with a status "
                              r"of (401|404|409|422|429)")


async def html_export(w: Walk, page: Page, tag: str) -> None:
    """Print or save as PDF opens the export as a blob: page, which inherits the app's
    CSP. Its style and print script must run: no console error, the page styled, and the
    button calls print (review S11)."""
    async with page.context.expect_page() as got:
        await page.click(".export-pop button:has-text('Print or save as PDF')")
    pdf = await got.value
    w.watch(pdf, f"{tag}: html export")
    await pdf.wait_for_load_state()
    await pdf.wait_for_timeout(400)
    width = await pdf.evaluate("() => getComputedStyle(document.body).maxWidth")
    if width != "820px":
        w.errors.append(f"{tag}: html export: its style did not apply (body max-width {width})")
    await pdf.evaluate("() => { window.__printed = false; window.print = () => { window.__printed = true; }; }")
    await pdf.click("button.print")
    if not await pdf.evaluate("() => window.__printed"):
        w.errors.append(f"{tag}: html export: the print button did nothing")
    await w.snap(pdf, tag, "html-export")
    await pdf.close()


class Walk:
    def __init__(self, out: Path, axe: str | None) -> None:
        self.out = out
        self.axe = axe
        self.states: list[dict] = []
        self.errors: list[str] = []
        self.focus: dict[str, list] = {}

    async def snap(self, page: Page, tag: str, name: str, full: bool = False) -> None:
        await page.wait_for_timeout(250)
        path = self.out / f"{tag}-{len([s for s in self.states if s['tag'] == tag]) + 1:02d}-{name}.png"
        await page.screenshot(path=str(path), full_page=full)
        probe = await page.evaluate(PROBE)
        state = {"tag": tag, "name": name, "shot": path.name, **probe}
        for problem in await page.evaluate(STRETCH):
            self.errors.append(f"{tag}: {name}: layout: {problem}")
        if self.axe:
            if not await page.evaluate("() => Boolean(window.axe)"):
                # Evaluated through the debugger, not as a <script> tag: the app's CSP
                # (review S11) refuses inline scripts, and that refusal would be logged.
                await page.evaluate(Path(self.axe).read_text() + "\n;0")
            res = await page.evaluate("""async () => {
              const r = await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] });
              return r.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help, n: v.nodes.length,
                targets: v.nodes.slice(0, 4).map(x => x.target.join(' ')),
                summary: v.nodes[0] && v.nodes[0].failureSummary.slice(0, 240) })); }""")
            state["axe"] = res
        self.states.append(state)

    def watch(self, page: Page, tag: str) -> None:
        """Page errors and console errors are findings. A CSP refusal is only a console
        error, never a page error (review S11)."""
        page.on("pageerror", lambda e: self.errors.append(f"{tag}: page error: {e}"))
        page.on("console", lambda m: self.errors.append(f"{tag}: console error: {m.text[:200]}")
                if m.type == "error" and not EXPECTED_CONSOLE.search(m.text) else None)

    async def step(self, tag: str, what: str, coro: Awaitable) -> bool:
        try:
            await coro
            return True
        except Exception as e:  # noqa: BLE001 - a failed step is a finding, the walk goes on
            self.errors.append(f"{tag}: {what}: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
            return False

    async def tab_through(self, page: Page, key: str, n: int = 30) -> None:
        await page.evaluate("() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); }")
        seq = []
        for _ in range(n):
            await page.keyboard.press("Tab")
            seq.append(await page.evaluate(FOCUS))
        self.focus[key] = seq


async def new_page(browser: Browser, view: dict, names: dict, scheme: str = "light",
                   motion: str = "no-preference") -> tuple[BrowserContext, Page]:
    ctx = await browser.new_context(viewport=view, color_scheme=scheme, reduced_motion=motion,
                                    device_scale_factor=1, has_touch=view is PHONE, is_mobile=view is PHONE)
    page = await ctx.new_page()
    await alias_responses(page, names)
    await page.route("**/watch**", lambda route: alias_watch(route, names))
    return ctx, page


async def alias_watch(route: Route, names: dict) -> None:
    """The What changed screen names watched researchers; film.py's filter does not cover it."""
    try:
        r = await route.fetch()
    except Exception:  # noqa: BLE001 - the page closed mid-request
        return
    body = await r.text()
    for real, alias in names.items():
        body = body.replace(real, alias)
    await route.fulfill(response=r, body=body)


async def pi_flow(w: Walk, page: Page, base: str, tag: str) -> None:
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await w.snap(page, tag, "find")
    if tag == "pi-laptop":
        await w.tab_through(page, "find")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await w.step(tag, "candidate", page.wait_for_selector(".cand", timeout=20000))
    await w.snap(page, tag, "candidate")
    if await page.locator(".cand button.btn.outline").count():  # an exact id picks itself (W1)
        await page.locator(".cand button.btn.outline").first.click()
        await page.wait_for_timeout(500)
    await page.click("[data-key=more-ctx]")  # Tell Perch more starts folded (W1)
    await page.wait_for_timeout(300)
    await w.snap(page, tag, "context", full=True)
    if tag == "pi-laptop":
        await w.tab_through(page, "context", 30)
    await page.click("[data-key=build]")
    await page.wait_for_selector("#tab-routes", timeout=60000)
    await w.step(tag, "built", wait_built(page))  # a live run: briefs are never reused (S23)
    await page.wait_for_timeout(1000)
    await page.click("#tab-profile")
    await w.snap(page, tag, "profile", full=True)
    await page.click("#tab-routes")
    await page.wait_for_timeout(800)
    await w.snap(page, tag, "routes-grants")
    await w.snap(page, tag, "routes-grants-full", full=True)
    await sort_stays(w, page, tag)
    lead = page.locator(".leads > li").first
    await w.step(tag, "why", lead.locator("summary[data-key=why]").click())
    await lead.scroll_into_view_if_needed()
    await w.snap(page, tag, "lead-why")
    if await w.step(tag, "evidence", lead.locator(".title-btn").click()):
        await page.wait_for_selector(".rec-title")
        await page.wait_for_timeout(400)
        await w.snap(page, tag, "evidence-opportunity")
        for problem in await page.evaluate(EVIDENCE):
            w.errors.append(f"{tag}: evidence: layout: {problem}")
        more = page.locator(".rail-evidence .more-btn, .sheet-body .more-btn").first
        if await more.count() and await more.is_visible():
            para = page.locator(".rail-evidence .long, .sheet-body .long").first
            before = (await para.bounding_box() or {}).get("height", 0)
            await more.click()
            await page.wait_for_timeout(200)
            after = (await para.bounding_box() or {}).get("height", 0)
            if after <= before:
                w.errors.append(f"{tag}: evidence: Show the full text did not open the text")
            await more.scroll_into_view_if_needed()
            await w.snap(page, tag, "evidence-expanded")
        await page.evaluate("() => window.scrollBy(0, 600)")
        await page.wait_for_timeout(300)
        for problem in await page.evaluate(RAIL):
            w.errors.append(f"{tag}: evidence scrolled: layout: {problem}")
        await w.snap(page, tag, "evidence-scrolled")
        await page.evaluate("() => window.scrollTo(0, 0)")
        await page.keyboard.press("Escape")
    if await w.step(tag, "export", page.click("[data-key=export]")):
        await page.wait_for_timeout(300)
        await w.snap(page, tag, "export-menu")
        if tag == "pi-laptop":
            await w.step(tag, "html export", html_export(w, page, tag))
            await page.click("[data-key=export]")
        await page.keyboard.press("Escape")
    if tag == "pi-laptop":
        await w.tab_through(page, "routes", 40)
    await w.step(tag, "industry", page.click("[data-key=route-B]"))
    await page.wait_for_timeout(600)
    await w.snap(page, tag, "routes-industry", full=True)
    await page.click("[data-key=route-A]")
    await page.wait_for_timeout(400)
    leads = page.locator(".leads > li")
    await page.evaluate(OPEN_WEAK)
    for i in (0, 1):
        await w.step(tag, f"keep {i}", leads.nth(i).locator(".btn.keep").click())
        await page.wait_for_timeout(300)
    await w.snap(page, tag, "shortlist")
    await page.click("#tab-compare")
    await page.wait_for_timeout(1200)
    await w.snap(page, tag, "compare", full=True)
    if await w.step(tag, "handoff", page.locator("[data-key=handoff-make]").click()):
        await w.step(tag, "handoff draft", page.wait_for_selector("#handoff-body", timeout=90000))
        await w.snap(page, tag, "handoff", full=True)
    await page.click("#tab-scout")
    await page.wait_for_timeout(800)
    await w.snap(page, tag, "scout", full=True)
    # The Local / Cloud dialog: the warning is shown and read, then cancelled; no cloud call.
    await page.click("#status-chip")
    await page.wait_for_selector("#models-dialog[open]")
    await w.snap(page, tag, "models-dialog")
    cloud = page.locator("#models-dialog input[value=cloud]")
    if await cloud.count() and not await cloud.is_disabled():
        await cloud.check()
        await page.wait_for_timeout(300)
        warn = await page.locator("#models-dialog .warn-box").first.inner_text()
        if "Anthropic" not in warn:
            w.errors.append(f"{tag}: no cloud warning naming the provider: {warn[:80]}")
        await w.snap(page, tag, "cloud-warning")
    await page.click("#models-dialog button:has-text('Cancel')")
    await page.wait_for_timeout(300)
    await page.goto(base + "/#/help")
    await page.wait_for_timeout(800)
    await w.snap(page, tag, "help", full=True)


# Weak matches fold under "Weaker matches (N)" (U24); flows that keep the second lead
# open the fold first, as a reader would.
OPEN_WEAK = "() => document.querySelectorAll('details.weak-fold').forEach(d => { d.open = true; })"


async def end_session(page: Page) -> None:
    await page.click("#end-session")
    await page.wait_for_selector("#models-dialog[open]")
    await page.click("[data-key=end-ok]")


async def reasons_open(w: Walk, page: Page, tag: str, sel: str) -> None:
    """With a CV or current research given, each card's reasons start open (S27, Dakshitha)."""
    n, shut = await page.evaluate(f"""() => {{ const d = [...document.querySelectorAll('{sel}')];
      return [d.length, d.filter((x) => !x.open).length]; }}""")
    if not n:
        w.errors.append(f"{tag}: reasons: no reason blocks found ({sel})")
    elif shut:
        w.errors.append(f"{tag}: reasons: {shut} of {n} reason blocks start closed")


async def wait_built(page: Page, timeout: int = 300_000) -> None:
    await page.wait_for_function("""() => { const p = document.querySelector('#progress');
      return p && /ready|finished|failed/i.test(p.innerText) && !/Building|Searching/i.test(p.innerText.split('\\n')[0]); }""",
                                 timeout=timeout)


async def student_flow(w: Walk, page: Page, base: str, persona: str, views: list[tuple[str, dict]]) -> None:
    tag = f"{persona}"
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.click("[data-key=seg-s]")
    await page.click("[data-key=student]")
    await page.wait_for_selector("#st-cv", timeout=20000)
    await w.snap(page, tag, "student-form", full=True)
    for kind in ("cv", "interests", "achievements"):
        await page.fill(f"#st-{kind}", (SYN / persona / f"{kind}.md").read_text())
    await w.snap(page, tag, "student-added", full=True)
    await page.click("[data-key=st-build]")
    await page.wait_for_selector("#progress", timeout=20000)
    await page.wait_for_timeout(4000)
    await w.snap(page, tag, "student-building")
    await w.step(tag, "built", wait_built(page))
    await page.wait_for_timeout(1000)
    for vtag, view in views:
        await page.set_viewport_size(view)
        t = f"{tag}-{vtag}"
        await page.click("#tab-profile")
        await w.snap(page, t, "profile", full=True)
        await page.click("#tab-routes")
        await page.wait_for_timeout(500)
        await w.snap(page, t, "fellowships", full=True)
        await reasons_open(w, page, t, "details.why.explain")
        await page.click("[data-key=route-S]")
        await page.wait_for_timeout(500)
        await w.snap(page, t, "scholarships")
        await sort_stays(w, page, t)
        await w.snap(page, t, "scholarships-full", full=True)
        if await w.step(t, "evidence", page.locator(".leads > li .title-btn").first.click()):
            await page.wait_for_selector(".rec-title")
            await page.wait_for_timeout(400)
            await w.snap(page, t, "evidence-sample")
            await page.keyboard.press("Escape")
        if vtag == views[0][0]:
            for i in (0, 1):
                await w.step(t, f"keep {i}", page.locator(".leads > li").nth(i).locator(".btn.keep").click())
                await page.wait_for_timeout(300)
        await page.click("#tab-compare")
        await page.wait_for_timeout(800)
        await w.snap(page, t, "compare", full=True)
        if vtag == views[0][0]:
            await w.tab_through(page, f"{persona}-compare", 25)
            await page.click("#tab-scout")
            await page.wait_for_timeout(500)
            await w.snap(page, t, "scout", full=True)
            if persona == STUDENTS[0]:  # student Scout answers on its own tools (S28)
                await page.fill("#scout-q", "Only options with a deadline after 2027-03-01")
                await page.click(".scout-ask button[type=submit]")
                await page.wait_for_timeout(500)
                for _ in range(1200):
                    if await page.evaluate("() => !document.querySelector('.scout-wait') && !document.querySelector('.scout-ask button[disabled]')"):
                        break
                    await page.wait_for_timeout(100)
                got = await page.evaluate("""() => ({read: Boolean(document.querySelector('.scout-read li')),
                  warn: (document.querySelector('.scout-x .notice') || {}).innerText || '',
                  code: [...document.querySelectorAll('.scout-where')].every(x => x.textContent === 'Code, no model'),
                  raw: [...document.querySelectorAll('.scout-read .chip')].some(x => /^[a-z]+_[a-z_]+:/.test(x.textContent))})""")
                if not got["read"] or got["warn"] or not got["code"] or got["raw"]:
                    w.errors.append(f"{t}: scout: a student question did not finish cleanly {got}")
                await w.snap(page, t, "scout-answer", full=True)
    await w.step(tag, "end", end_session(page))
    await page.wait_for_timeout(1200)
    await w.snap(page, tag, "after-end")


async def private_flow(w: Walk, page: Page, base: str) -> None:
    tag = "persona-1"
    files = {"cv": "cv.md", "proposal": "specific_aims_draft.md", "manuscript": "unpublished_manuscript.md"}
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.click("[data-key=more-opts]")
    await page.click("[data-key=docs-link]")
    await page.wait_for_selector("#doc-cv", timeout=20000)  # the session opens on arrival (U41)
    await page.wait_for_timeout(500)
    await w.snap(page, tag, "private-start", full=True)
    for kind, name in files.items():
        await page.fill(f"#doc-{kind}", (SYN / "persona-1" / name).read_text())
        await page.locator(f"#doc-{kind} ~ .doc-actions button:has-text('Add text')").click()
        await page.wait_for_timeout(500)
    await w.snap(page, tag, "private-added", full=True)
    await page.click("button:has-text('Build brief')")
    await page.wait_for_timeout(5000)
    await w.snap(page, tag, "private-building")
    await w.step(tag, "built", wait_built(page))
    await page.click("#tab-profile")
    await w.snap(page, tag, "private-profile", full=True)
    await page.click("#tab-routes")
    await page.wait_for_timeout(500)
    await w.snap(page, tag, "private-routes", full=True)
    await reasons_open(w, page, tag, ".explain > details.why")
    await page.goto(base + "/#/help")
    await page.wait_for_timeout(600)
    await w.snap(page, tag, "private-on-help")
    await w.step(tag, "end", end_session(page))
    await page.wait_for_timeout(1000)


# ---------- the workflow review's findings (S30, docs/design/WORKFLOW_REVIEW.md W1 to W18) ----------
# Each check names its finding. Every one failed on the build before its fix.

BUILD_BUTTONS = """() => [...document.querySelectorAll('[data-key=build], [data-key=build-top]')]
  .filter(b => b.offsetParent).length"""


async def doc_click_listeners(page: Page) -> int:
    """Click listeners on document, read through the debugger (W17)."""
    cdp = await page.context.new_cdp_session(page)
    doc = await cdp.send("Runtime.evaluate", {"expression": "document"})
    got = await cdp.send("DOMDebugger.getEventListeners", {"objectId": doc["result"]["objectId"]})
    await cdp.detach()
    return sum(1 for x in got["listeners"] if x["type"] == "click")


async def pick_and_build(page: Page) -> None:
    """From the pick screen to a running brief, whichever presses the screen still needs."""
    if await page.locator(".cand button.btn.outline").count():
        await page.locator(".cand button.btn.outline").first.click()
        await page.wait_for_timeout(300)
    await page.locator("[data-key=build], [data-key=build-top]").first.click()


# Counts each landing drawn into #main from the first script on (W17).
COUNT_LANDINGS = """new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes)
  if (n.nodeType === 1 && n.classList.contains('landing')) window.__landings = (window.__landings || 0) + 1; })
  .observe(document, { childList: true, subtree: true });"""


async def workflow_pi(w: Walk, page: Page, base: str, tag: str) -> None:
    await page.add_init_script(COUNT_LANDINGS)
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.wait_for_timeout(1000)
    if (n := await page.evaluate("() => window.__landings")) != 1:  # W17
        w.errors.append(f"{tag}: W17: the landing was drawn {n} times on one load")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_function("() => { const t = document.querySelector('#pick-title');"
                                 " return t && !/Searching/.test(t.innerText); }", timeout=20000)
    # W1: an exact id with one match opens Ready to build, with one Build button.
    title = await page.locator("#pick-title").inner_text()
    if not title.startswith("Ready to build"):
        w.errors.append(f"{tag}: W1: an exact OpenAlex id with one match still asks {title!r}")
    if await page.locator(".cand button.btn.outline").count():
        await page.locator(".cand button.btn.outline").first.click()
        await page.wait_for_timeout(300)
    if (n := await page.evaluate(BUILD_BUTTONS)) != 1:
        w.errors.append(f"{tag}: W1: the ready screen shows {n} Build brief buttons")
    await w.snap(page, tag, "w1-ready", full=True)
    await page.locator("[data-key=build], [data-key=build-top]").first.click()
    await page.wait_for_selector("#tab-routes", timeout=60000)
    await wait_built(page)
    await page.wait_for_timeout(600)
    # W4: the title is the one control that opens Evidence; a marker beside it says so.
    n_ev = await page.locator(".leads > li [data-key=evidence]").count()
    if n_ev:
        w.errors.append(f"{tag}: W4: {n_ev} lead cards carry an Evidence button beside the title that opens the same record")
    if not await page.evaluate("() => [...document.querySelectorAll('.leads > li .lead-title')].filter(t => t.checkVisibility())"
                               ".every(t => /Evidence/.test(t.innerText))"):  # folded weak matches are not shown (U24)
        w.errors.append(f"{tag}: W4: a lead title has no visible Evidence marker")
    # W2: Keep sits in the card head, not under the explanation.
    gap = await page.evaluate("""() => { const c = document.querySelector('.leads > li');
      const k = c && c.querySelector('.btn.keep'); if (!k) return null;
      return Math.round(k.getBoundingClientRect().top - c.getBoundingClientRect().top); }""")
    if gap is None or gap > 120:
        w.errors.append(f"{tag}: W2: Keep sits {gap} px below the top of its card")
    await page.evaluate(OPEN_WEAK)
    for i in (0, 1):
        await page.locator(".leads > li .btn.keep").nth(i).click()
        await page.wait_for_timeout(250)
        live = await page.locator("#live").inner_text()
        if "bar at the bottom" in live:  # W7
            w.errors.append(f"{tag}: W7: after Keep the screen reader hears {live!r}")
    await page.wait_for_timeout(300)
    # W3: the kept count is not repeated in the subtitle or as a Kept tag.
    sub = await page.evaluate("() => (document.querySelector('.routes-sub') || {}).innerText || ''")
    if "kept" in sub:
        w.errors.append(f"{tag}: W3: the routes subtitle repeats the kept count: {sub!r}")
    if n := await page.evaluate("() => [...document.querySelectorAll('.leads .tag')].filter(t => t.innerText.trim() === 'Kept').length"):
        w.errors.append(f"{tag}: W3: {n} cards carry a Kept tag beside a Kept button")
    await w.snap(page, tag, "w2-kept")
    # W5: the Evidence panel links the source once.
    await page.locator(".leads > li .title-btn").first.click()
    await page.wait_for_selector("#rail-ev .rec-title, #evidence-body .rec-title")
    await page.wait_for_timeout(300)
    dup = await page.evaluate("""() => { const box = document.querySelector('#rail-ev');
      const top = box && box.querySelector('.source-top a'); if (!top) return 0;
      return [...box.querySelectorAll('a[href]')].filter(a => a.href === top.href).length; }""")
    if dup > 1:
        w.errors.append(f"{tag}: W5: the Evidence panel links the same source URL {dup} times")
    await w.snap(page, tag, "w5-evidence")
    # W17: rendering the brief again does not add a document click listener.
    n0 = await doc_click_listeners(page)
    for _ in range(3):
        await page.goto(base + "/#/help")
        await page.wait_for_timeout(300)
        await page.goto(base + "/#/brief/private/routes")
        await page.wait_for_selector("#tab-routes")
        await page.wait_for_timeout(400)
    if (n1 := await doc_click_listeners(page)) > n0:
        w.errors.append(f"{tag}: W17: three more brief renders left {n1 - n0} more click listeners on document")
    # W6: the hand-off shows the mask setting it uses, and both toggles are one state.
    await page.click("#tab-compare")
    await page.wait_for_selector("table.compare", timeout=30000)
    await page.wait_for_timeout(500)
    ho, tb = await page.evaluate("""() => [document.querySelector('.handoff'), document.querySelector('table.compare')]
      .map(x => x ? Math.round(x.getBoundingClientRect().top) : null)""")
    if ho is None or tb is None or ho > tb:
        w.errors.append(f"{tag}: W2: the hand-off box sits below the comparison table ({ho} against {tb} px)")
    await w.step(tag, "W6", mask_follows(w, page, tag))
    await w.snap(page, tag, "w6-compare", full=True)
    await w18_reload(w, page, base, tag)


async def mask_follows(w: Walk, page: Page, tag: str) -> None:
    """W6, in a session that holds documents: the hand-off shows the mask setting it
    uses, and both boxes are one state. Without documents neither shows (U12)."""
    held = await page.evaluate("""async () => { const t = sessionStorage.getItem('perch.session');
      const r = await fetch('/private/session', {headers: {'X-Perch-Private': t}}); return (await r.json()).documents.length; }""")
    mask = page.locator(".handoff input[type=checkbox]")
    if not held:
        if await mask.count():
            w.errors.append(f"{tag}: U12: a mask box beside Draft the email in a session with no documents")
        return
    if not await mask.count():
        w.errors.append(f"{tag}: W6: no mask setting beside Draft the email; it hides in the Export menu")
    else:
        await mask.check()
        await page.click("[data-key=export]")
        await page.wait_for_timeout(200)
        if not await page.locator(".export-pop input[type=checkbox]").is_checked():
            w.errors.append(f"{tag}: W6: the Export menu's mask box does not follow the hand-off's")
        await page.locator(".export-pop input[type=checkbox]").uncheck()
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        if await mask.is_checked():
            w.errors.append(f"{tag}: W6: the hand-off's mask box does not follow the Export menu's")


async def w18_reload(w: Walk, page: Page, base: str, tag: str) -> None:
    # W18: a reload asks first, then resumes the brief; a new tab does not share it.
    await page.click("#tab-routes")
    await page.wait_for_timeout(300)
    seen: list[str] = []

    async def on_dialog(d) -> None:  # noqa: ANN001 - a playwright Dialog
        seen.append(d.type)
        await d.accept()
    page.on("dialog", on_dialog)
    await page.reload()
    page.remove_listener("dialog", on_dialog)
    if "beforeunload" not in seen:
        w.errors.append(f"{tag}: W18: reloading a brief gave no beforeunload prompt")
    try:
        await page.wait_for_selector("#tab-routes", timeout=15000)
        await wait_built(page, 30000)
        label = await page.locator("#tab-compare").get_attribute("aria-label")
        if label != "Compare, 2 kept":
            w.errors.append(f"{tag}: W18: after a reload the brief came back without its kept leads ({label!r})")
    except Exception:  # noqa: BLE001 - reported as a finding
        w.errors.append(f"{tag}: W18: a reload lost the brief (landed on {page.url.split('#')[-1]!r})")
    await w.snap(page, tag, "w18-reloaded")
    other = await page.context.new_page()
    await other.goto(base + "/#/brief/private/routes")
    await other.wait_for_timeout(1500)
    if await other.locator("#tab-routes").count():
        w.errors.append(f"{tag}: W18: a new tab opened the first tab's session")
    await other.close()
    token = await page.evaluate("() => { try { return sessionStorage.getItem('perch.session'); } catch { return null; } }")
    if token:
        await page.evaluate("""(t) => fetch('/private/end', {method: 'POST', headers: {'X-Perch-Private': t}})""", token)
        page.on("dialog", on_dialog)
        await page.reload()
        page.remove_listener("dialog", on_dialog)
        try:
            await page.wait_for_selector(".session-ended", timeout=15000)
        except Exception:  # noqa: BLE001 - reported as a finding
            w.errors.append(f"{tag}: W18: after the server ended the session, a reload did not land on the start with the notice")
        await w.snap(page, tag, "w18-expired")


async def workflow_sample(w: Walk, page: Page, base: str, tag: str) -> None:
    """W18 and rule 11: a brief steered by the SYNTHETIC sample keeps its Sample data banner
    after a reload."""
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".cand", timeout=20000)
    if await page.locator(".cand button.btn.outline").count():
        await page.locator(".cand button.btn.outline").first.click()
    await page.click("[data-key=more-ctx]")
    await page.click("[data-key=fill-sample]")
    await page.wait_for_selector(".sample-status")
    await page.click("[data-key=build]")
    await page.wait_for_selector("#tab-routes", timeout=60000)
    await wait_built(page)
    if not await page.locator(".sample-note").count():
        w.errors.append(f"{tag}: rule 11: a brief steered by the sample has no Sample data banner")
    await page.locator(".leads > li .btn.keep").first.click()  # the sample's draft aims are a document
    await page.click("#tab-compare")
    await page.wait_for_selector(".handoff", timeout=30000)
    await page.wait_for_timeout(500)
    await w.step(tag, "W6", mask_follows(w, page, tag))
    await page.click("#tab-routes")
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await page.reload()
    await page.wait_for_selector("#tab-routes", timeout=20000)
    await page.wait_for_timeout(800)
    if not await page.locator(".sample-note").count():
        w.errors.append(f"{tag}: W18: after a reload the sample-steered brief lost its Sample data banner")
    await w.snap(page, tag, "w18-sample-reloaded")
    await end_session(page)


async def workflow_student(w: Walk, page: Page, base: str, tag: str) -> None:
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.click("[data-key=seg-s]")
    await page.click("[data-key=student]")
    await page.wait_for_selector("#st-cv", timeout=20000)
    for kind in ("cv", "interests", "achievements"):
        await page.fill(f"#st-{kind}", (SYN / "persona-ug" / f"{kind}.md").read_text())
    await page.click("[data-key=st-build]")
    await page.wait_for_selector("#progress", timeout=20000)
    await wait_built(page)
    await page.wait_for_timeout(500)
    if n := await page.locator(".leads > li [data-key^=evidence-]").count():
        w.errors.append(f"{tag}: W4: {n} option cards carry an Evidence button beside the title")
    await page.locator(".leads > li .btn.keep").first.click()
    await page.wait_for_timeout(300)
    await page.click("#tab-compare")
    await page.wait_for_selector("table.compare", timeout=30000)
    await page.wait_for_timeout(800)
    # W8: the note shows at once, has no dead To box, and Open in my mail app sends the edited text.
    if not await page.locator(".draft textarea").count():
        w.errors.append(f"{tag}: W8: the code-written note needs a Draft the note press")
        if await page.locator("[data-key=st-draft]").count():
            await page.click("[data-key=st-draft]")
            await page.wait_for_selector(".draft textarea")
    if await page.locator("#st-to").count():
        w.errors.append(f"{tag}: W8: the note has a To box that nothing reads")
    ho, tb = await page.evaluate("""() => [document.querySelector('.handoff'), document.querySelector('table.compare')]
      .map(x => x ? Math.round(x.getBoundingClientRect().top) : null)""")
    if ho is None or tb is None or ho > tb:
        w.errors.append(f"{tag}: W2: the note sits below the comparison table ({ho} against {tb} px)")
    await page.locator(".draft textarea").fill((await page.locator(".draft textarea").input_value()) + "\nEDITED-W8")
    await page.evaluate("""() => window.addEventListener('click', (e) => {
      const a = e.target.closest('a[href^="mailto"], [data-key=st-mail]');
      if (a) { window.__mail = a.getAttribute('href'); e.preventDefault(); } })""")
    mail = page.locator(".draft .actions a:has-text('Open in my mail app')")
    if await mail.count():
        await mail.click()
        got = await page.evaluate("() => decodeURIComponent(window.__mail || '')")
        if "EDITED-W8" not in got:
            w.errors.append(f"{tag}: W8: Open in my mail app sends the note as first drawn, not as edited")
    else:
        w.errors.append(f"{tag}: W8: no Open in my mail app button on a note about public fellowships")
    await w.snap(page, tag, "w8-note", full=True)
    await end_session(page)


async def workflow_private(w: Walk, page: Page, base: str, tag: str) -> None:
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.click("[data-key=more-opts]")
    await page.click("[data-key=docs-link]")
    await page.wait_for_selector("#doc-proposal", timeout=20000)
    await page.fill("#doc-proposal", (SYN / "persona-1/specific_aims_draft.md").read_text())
    await page.locator("#doc-proposal ~ .doc-actions button:has-text('Add text')").click()
    await page.wait_for_function("() => !document.querySelector('#doc-proposal')", timeout=20000)
    await page.click(".private button:has-text('Build brief')")
    await page.wait_for_selector("#progress", timeout=20000)
    await page.wait_for_timeout(500)
    if not page.url.endswith("/routes"):  # W11
        w.errors.append(f"{tag}: W11: a private brief lands on {page.url.split('#')[-1]!r}, not on Routes")
    await wait_built(page)
    # W10: End session on Your documents asks first, as the header's does.
    await page.goto(base + "/#/private")
    await page.wait_for_selector(".private")
    await page.click(".private .doc-actions button:has-text('End session')")
    try:
        await page.wait_for_selector("#models-dialog[open]", timeout=3000)
        await w.snap(page, tag, "w10-confirm")
        await page.click("#models-dialog button:has-text('Keep working')")
        await end_session(page)
    except Exception:  # noqa: BLE001 - reported as a finding
        w.errors.append(f"{tag}: W10: End session on Your documents ended the session without asking")


# ---------- the UX review's findings (S30, docs/design/UX_REVIEW_S29.md U1 to U28) ----------
# Each check names its finding. Every one failed on the build before its fix.

YEAR_NOW = 2026


SECURITY = ("Companies outside the United States may need a research-security review before any "
            "contact; the office makes that check.")  # Q13's fixed line


def far_years(text: str) -> list[str]:
    """Years more than ten years out: a placeholder close date shown as if real (U3)."""
    return [y for y in re.findall(r"\b(2\d{3})\b", text) if int(y) > YEAR_NOW + 10]


async def ux_pi(w: Walk, page: Page, base: str, tag: str) -> None:
    phone = page.viewport_size["width"] < 700
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    x_landing = (await page.locator(".wordmark").bounding_box())["x"]
    if not phone:  # U17: the paste nudge clears when the field changes
        cv = (SYN / "persona-1/cv.md").read_text()
        await page.evaluate("""(t) => { const q = document.querySelector('#q'); const dt = new DataTransfer();
          dt.setData('text/plain', t); q.value = t; q.dispatchEvent(new InputEvent('input', {bubbles: true}));
          q.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})); }""", cv)
        await page.wait_for_selector(".nudge", timeout=3000)
        await page.fill("#q", AUTHOR)
        await page.wait_for_timeout(200)
        if await page.locator(".nudge").count() or await page.locator(".searchbox button[type=submit]").is_disabled():
            w.errors.append(f"{tag}: U17: after the field is cleared and an ID typed, the paste offer stays and Find is disabled")
            await page.click(".nudge button:has-text('Keep it here')")
        await page.goto(base + "/#/help")
        await page.wait_for_timeout(500)
        x_help = (await page.locator(".wordmark").bounding_box())["x"]
        await page.goto(base + "/#/")
        await page.wait_for_selector(".landing")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".cand", timeout=20000)
    if await page.locator(".cand button.btn.outline").count():
        await page.locator(".cand button.btn.outline").first.click()
        await page.wait_for_timeout(300)
    near = await page.evaluate("""() => { const c = [...document.querySelectorAll('label.check')].find(l => /Explain each lead/.test(l.innerText));
      const b = document.querySelector('[data-key=build]'); if (!c || !b) return null;
      const r = c.getBoundingClientRect(), k = b.getBoundingClientRect();
      return { inBox: Boolean(c.closest('.box, .more-panel')), gap: Math.max(0, r.top - k.bottom, k.top - r.bottom) }; }""")
    if near is None or near["inBox"] or near["gap"] > 60:  # U42
        w.errors.append(f"{tag}: U42: Explain each lead is not beside Build brief {near}")
    await w.snap(page, tag, "u-pick")
    await pick_and_build(page)
    await page.wait_for_selector("#tab-routes", timeout=60000)
    await wait_built(page)
    await page.wait_for_timeout(800)
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]
    if not phone:  # U18: one header on every screen
        x_brief = (await page.locator(".wordmark").bounding_box())["x"]
        if len({round(x_landing), round(x_help), round(x_brief)}) > 1:
            w.errors.append(f"{tag}: U18: the wordmark moves between screens (landing {x_landing:.0f}, "
                            f"help {x_help:.0f}, brief {x_brief:.0f} px)")
    await w.snap(page, tag, "u-routes", full=not phone)
    if phone:  # U5: the first lead shows in the first view
        top = await page.evaluate("() => document.querySelector('.leads > li').getBoundingClientRect().top + scrollY")
        if top + 140 > vh:
            w.errors.append(f"{tag}: U5: the first lead starts at y = {top:.0f} px on a {vh} px screen")
        await page.click(".pcard .steps summary")  # opened, the steps take the card's width
        await page.wait_for_timeout(200)
        wide = await page.evaluate("() => document.querySelector('.pcard .steps ol').getBoundingClientRect().width")
        if wide < vw * 0.7:
            w.errors.append(f"{tag}: U5: the opened steps are squeezed into {wide:.0f} px")
        await w.snap(page, tag, "u-steps-open")
        await page.click(".pcard .steps summary")
    dup = await page.evaluate("""() => [...document.querySelectorAll('#panel details.why')].filter(d => {
      const inf = [...d.querySelectorAll('.inference .paper-cite')].map(b => b.dataset.key);
      const own = new Set([...d.querySelectorAll('.findings .paper-ref')].map(b => b.dataset.key));
      return inf.length && inf.every(k => own.has(k)); }).length""")
    if dup:  # U35
        w.errors.append(f"{tag}: U35: {dup} Inference boxes repeat the paper chips listed just above them")
    lab = await page.evaluate("""() => { const sw = document.querySelector('#panel .route-row .sort-switch'); const l = document.querySelector('#panel .route-row .sort-label');
      return { label: l ? l.innerText.trim() : null, before: Boolean(l && sw && (l.compareDocumentPosition(sw) & Node.DOCUMENT_POSITION_FOLLOWING)) }; }""")
    if lab["label"] != "Sort" or not lab["before"]:  # U36
        w.errors.append(f"{tag}: U36: the sort switch has no visible Sort label {lab}")
    # U24 as Q6 decided: the first five cards always show open, whatever their band; the
    # fold holds only weak cards after the fifth, with its count
    weak = await page.evaluate("""() => {
      const top = [...document.querySelectorAll('#panel .leads > li')].filter(li => !li.closest('details'));
      const inFold = [...document.querySelectorAll('#panel details.weak-fold .leads > li')];
      const fold = document.querySelector('#panel details.weak-fold > summary');
      return { open: top.length, weakAfter: top.slice(5).filter(li => li.querySelector('.fit.weak')).length,
               foldNotWeak: inFold.filter(li => !li.querySelector('.fit.weak')).length, inFold: inFold.length,
               fold: fold ? fold.innerText : null }; }""")
    if weak["open"] < min(5, weak["open"] + weak["inFold"]):
        w.errors.append(f"{tag}: Q6: only {weak['open']} cards show open before the Weaker matches fold")
    if weak["weakAfter"] or weak["foldNotWeak"]:
        w.errors.append(f"{tag}: Q6: weak cards after the fifth sit open, or the fold holds a stronger card {weak}")
    elif weak["fold"] is not None and not re.search(r"\d", weak["fold"]):
        w.errors.append(f"{tag}: U24: the weak-match fold does not state its count ({weak['fold']!r})")
    # Q3: a placeholder close date never shows on a card; the record's words do
    cards = await page.evaluate("() => [...document.querySelectorAll('#panel .leads > li .fact.close')].map(x => x.innerText)")
    if far := [c for c in cards if far_years(c)]:
        w.errors.append(f"{tag}: Q3: a card shows a placeholder close date as real ({far[0]!r})")
    # Q27: Home and End move along the tabs (WAI-ARIA tabs)
    await page.focus("#tab-routes")
    await page.keyboard.press("End")
    await page.wait_for_timeout(300)
    last = await page.evaluate("() => document.activeElement && document.activeElement.id")
    await page.keyboard.press("Home")
    await page.wait_for_timeout(300)
    first = await page.evaluate("() => [document.activeElement && document.activeElement.id, location.hash]")
    tabs = await page.evaluate("() => [...document.querySelectorAll('[role=tab]')].map(t => t.id)")
    if last != tabs[-1] or first[0] != tabs[0] or not first[1].endswith("/routes"):
        w.errors.append(f"{tag}: Q27: End went to {last!r} and Home to {first[0]!r}; the tabs are {tabs}")
    await page.wait_for_timeout(300)
    # U25: filter chips from the leads' own agency and activity-code values
    chips = await page.evaluate("""() => [...document.querySelectorAll('#panel .filter-chips button')].map(b => b.innerText.trim())""")
    if not chips:
        w.errors.append(f"{tag}: U25: no filter chips on Routes")
    else:
        vals = await page.evaluate("""() => [...document.querySelectorAll('#panel .leads > li .tags .tag')].map(t => t.textContent.trim())""")
        stray = [c for c in chips if re.sub(r"\s*\d+$", "", c) not in vals and not c.startswith("All")]
        if stray:
            w.errors.append(f"{tag}: U25: filter chips not built from the leads' own values: {stray}")
        await page.locator("#panel .filter-chips button").nth(1).click()  # the largest agency
        await page.wait_for_timeout(300)
        want = re.sub(r"\s*\d+$", "", chips[1])
        got = await page.evaluate("""(v) => [...document.querySelectorAll('#panel .leads > li')].map(li =>
          [...li.querySelectorAll('.tags .tag')].some(t => t.textContent.trim() === v))""", want)
        if not got or not all(got):
            w.errors.append(f"{tag}: U25: the {want} chip left other agencies in the list")
        await w.snap(page, tag, "u-filtered")
        await page.locator("#panel .filter-chips button").first.click()
        await page.wait_for_timeout(300)
    # U9 and U27: the rail (laptop only)
    if not phone:
        await page.locator(".leads > li .title-btn").first.click()
        await page.wait_for_selector("#rail-ev .rec-title")
        await page.wait_for_timeout(400)
        fade = await page.evaluate("""() => { const b = document.querySelector('#rail-ev'); const s = getComputedStyle(b);
          const a = getComputedStyle(b, '::after');
          return { over: b.scrollHeight > b.clientHeight + 2, bar: s.scrollbarColor, width: s.scrollbarWidth,
                   fade: (s.maskImage && s.maskImage !== 'none') || (s.webkitMaskImage && s.webkitMaskImage !== 'none')
                     || (a.content !== 'none' && /gradient/.test(a.backgroundImage)) }; }""")
        if fade["over"] and (re.match(r"transparent|rgba\(0, 0, 0, 0\)", fade["bar"] or "")  # the thumb's colour
                             or fade["width"] == "none" or not fade["fade"]):
            w.errors.append(f"{tag}: U27: the Evidence rail is cut with no visible scroll bar or fade {fade}")
        await w.snap(page, tag, "u-rail")
        await page.click("[data-key=route-B]")
        await page.wait_for_timeout(500)
        if not await page.locator("#rail-ev .empty-ev").count():
            w.errors.append(f"{tag}: U9: after a switch to Industry the rail still shows the grant record")
        await page.locator(".leads > li .title-btn").first.click()
        await page.wait_for_selector("#rail-ev .rec-title")
        await page.click("[data-key=route-A]")
        await page.wait_for_timeout(400)
        if not await page.locator("#rail-ev .empty-ev").count():
            w.errors.append(f"{tag}: U9: after a switch back to Grants the rail still shows the company record")
        await page.wait_for_timeout(300)
        await page.keyboard.press("Escape")
    # U12: no mask block in the Export menu while the session holds no documents
    await page.click("[data-key=export]")
    await page.wait_for_timeout(300)
    if phone:  # U1: the menu stays on screen
        r = await page.locator(".export-pop").bounding_box()
        if r["x"] < 0 or r["x"] + r["width"] > vw:
            w.errors.append(f"{tag}: U1: the Export menu runs from x = {r['x']:.0f} to {r['x'] + r['width']:.0f} on a {vw} px screen")
    if await page.locator(".export-pop input[type=checkbox]").count() or \
            "Unmask" in await page.locator(".export-pop").inner_text():
        w.errors.append(f"{tag}: U12: the Export menu shows the mask controls in a session with no documents")
    await w.snap(page, tag, "u-export")
    await page.keyboard.press("Escape")
    # U13 and U14: Industry
    await page.click("[data-key=route-B]")
    await page.wait_for_timeout(600)
    names = await page.evaluate("() => [...document.querySelectorAll('#panel .leads > li .title-btn > span:first-child')].map(s => s.innerText)")
    keys = [(n.split()[0].lower(), (re.search(r"\(([^)]*)\)\s*$", n) or [None, ""])[1]) for n in names]
    dup = [n for n, k in zip(names, keys, strict=False) if keys.count(k) > 1]
    if dup:
        w.errors.append(f"{tag}: U13: one company shows as separate industry leads: {dup}")
    iso = await page.evaluate(r"() => [...document.querySelectorAll('#panel .signals p')].map(p => p.innerText).filter(t => /\d{4}-\d{2}-\d{2}/.test(t))")
    if iso:
        w.errors.append(f"{tag}: U14: industry sentences write dates as {iso[0][:90]!r}")
    gone = await page.evaluate(r"""() => [...document.querySelectorAll('#panel .signals > li')].map(li => {
      const n = parseInt((li.querySelector('p') || {}).innerText, 10); const m = li.querySelector('.hint');
      return m && /more in the export/.test(m.innerText) ? [n, m.innerText] : null; }).filter(x => x && x[0] <= 25)""")
    if gone:  # U38
        w.errors.append(f"{tag}: U38: {gone[0][1]!r} on a signal with only {gone[0][0]} records")
    if SECURITY not in await page.locator("#panel").inner_text():  # Q13
        w.errors.append(f"{tag}: Q13: the Industry tab does not carry the research-security line")
    await w.snap(page, tag, "u-industry", full=not phone)
    if phone:  # U16: the kept pill stays off the Industry warning
        await page.click("[data-key=route-A]")
        await page.wait_for_timeout(300)
        await page.evaluate(OPEN_WEAK)
        for i in (0, 1):
            await page.locator(".leads > li .btn.keep").nth(i).click()
            await page.wait_for_timeout(250)
        await page.evaluate("() => window.scrollTo(0, 0)")
        await page.click("[data-key=route-B]")
        await page.wait_for_timeout(600)
        hit = await page.evaluate("""() => { const p = document.querySelector('.keep-float'), n = document.querySelector('.infer-note');
          if (!p || !n || getComputedStyle(p).visibility === 'hidden') return false;
          const a = p.getBoundingClientRect(), b = n.getBoundingClientRect();
          return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top; }""")
        if hit:
            w.errors.append(f"{tag}: U16: the kept pill covers the Industry warning")
        await w.snap(page, tag, "u-industry-pill")
        await page.evaluate("() => window.scrollBy(0, 900)")  # past the warning the pill comes back
        await page.wait_for_timeout(400)
        if await page.evaluate("() => { const p = document.querySelector('.keep-float'); return !p || getComputedStyle(p).visibility === 'hidden'; }"):
            w.errors.append(f"{tag}: U16: the kept pill stays hidden once the warning has scrolled away")
        await page.evaluate("() => window.scrollTo(0, 0)")
    await page.click("[data-key=route-A]")
    await page.wait_for_timeout(300)
    # U23: the profile says how its paper counts relate
    await page.click("#tab-profile")
    await page.wait_for_timeout(600)
    twice = await page.evaluate("""() => [...document.querySelectorAll('#panel .block')].filter(b => /^Summary/.test(b.innerText))
      .filter(b => b.querySelector('h2 .hint') && b.querySelector('.tag.model')).length""")
    if twice:  # U35
        w.errors.append(f"{tag}: U35: the Summary says it is model text in its header and in its tag line")
    if not phone:
        note = await page.evaluate("() => (document.querySelector('.threads-note') || {}).innerText || ''")
        if not re.search(r"\d", note):
            w.errors.append(f"{tag}: U23: Research threads give no note on how the paper counts relate")
        await w.snap(page, tag, "u-profile", full=True)
    await page.click("#tab-routes")
    await page.wait_for_timeout(400)
    if not phone:
        # Keep the first two grants (the review's U3 steps), then Compare and the email
        await page.evaluate(OPEN_WEAK)
        kept = await page.locator(".leads > li .btn.keep.on").count()
        for _i in range(kept, 2):
            await page.locator(".leads > li .btn.keep:not(.on)").first.click()
            await page.wait_for_timeout(250)
    await page.click("#tab-compare")
    await page.wait_for_selector("table.compare", timeout=30000)
    await page.wait_for_timeout(600)
    table = await page.locator("table.compare").inner_text()
    if far := far_years(table):  # U3
        w.errors.append(f"{tag}: U3: Compare shows a placeholder close date as real ({far[0]})")
    if re.search(r"\d{4,} days after", table):
        w.errors.append(f"{tag}: U3: Compare counts tens of thousands of days to a close date")
    if "Perch’s order" in table or "Match" not in table:  # U6
        w.errors.append(f"{tag}: U6: Compare shows Perch's order, not the card's Match")
    sub = await page.evaluate("() => [...document.querySelectorAll('#panel .hint')].map(x => x.innerText).join(' ')")
    marks = await page.evaluate("""() => [...document.querySelectorAll('table.compare thead th')].map(th =>
      ({ text: th.innerText.trim(), btn: Boolean(th.querySelector('button')), mark: (th.querySelector('.sort-mark') || {}).textContent || '',
         top: Math.round((th.querySelector('button, span') || th).getBoundingClientRect().top),
         shown: th.getBoundingClientRect().height > 2 }))""")
    if phone:  # U15
        if "Press a column name to sort" in sub and not await page.locator("#panel select.compare-sort").count():
            w.errors.append(f"{tag}: U15: on a phone the table has no column names, but the hint says to press one")
        if await page.evaluate("() => [...document.querySelectorAll('table.compare td')].some(td => /[↕▲▼]/.test(td.dataset.label || ''))"):
            w.errors.append(f"{tag}: U15: the stacked cells' labels carry the sort mark")
    else:
        if any(not m["mark"].strip() for m in marks if m["btn"]):
            w.errors.append(f"{tag}: U15: sortable headers carry no sort mark until pressed")
        if len({m["top"] for m in marks}) > 1:
            w.errors.append(f"{tag}: U15: the header labels do not line up ({sorted({m['top'] for m in marks})})")
    await w.snap(page, tag, "u-compare", full=True)
    if not phone:
        await page.locator("[data-key=handoff-make]").click()
        await page.wait_for_selector("#handoff-body", timeout=90000)
        body = await page.locator("#handoff-body").input_value()
        ui = await page.evaluate("""() => ({ tag: (document.querySelector('.draft .model-note .tag') || {}).innerText || null,
          btns: [...document.querySelectorAll('.draft .actions .btn')].map(b => b.innerText.trim()) })""")
        if ui["tag"] not in (None, "Model text") or ui["btns"] != ["Copy the draft", "Open in my mail app"]:
            w.errors.append(f"{tag}: U34: the researcher's note reads {ui}")
        if far := far_years(body):
            w.errors.append(f"{tag}: U3: the email says a placeholder close date as real ({far[0]})")
        if re.search(r"\b\d{4}-\d{2}-\d{2}\b", body):
            w.errors.append(f"{tag}: U14: the email writes dates as 2026-09-29")
        await w.snap(page, tag, "u-handoff", full=True)
    # U22: at 320 px the tabs fit
    if phone:
        await page.set_viewport_size({"width": 320, "height": 640})
        await page.click("#tab-scout")
        await page.wait_for_timeout(500)
        clip = await page.evaluate("""() => { const t = document.querySelector('.tabs');
          const cut = [...t.querySelectorAll('.tab')].filter(b => { const r = b.getBoundingClientRect(), p = t.getBoundingClientRect();
            return r.left < p.left - 1 || r.right > p.right + 1 || b.scrollWidth > b.clientWidth + 1; }).map(b => b.innerText);
          const chip = document.querySelector('#status-chip .chip-word');
          return { cut, scroll: t.scrollWidth > t.clientWidth + 1,
                   chipLines: Math.round(chip.getBoundingClientRect().height / parseFloat(getComputedStyle(chip).lineHeight || 20)) }; }""")
        if clip["cut"] or clip["scroll"]:
            w.errors.append(f"{tag}: U22: at 320 px the tabs are clipped {clip['cut']}")
        if clip["chipLines"] > 1:
            w.errors.append(f"{tag}: U22: at 320 px the status chip wraps to {clip['chipLines']} lines")
        await w.snap(page, tag, "u-320")
        await page.set_viewport_size(PHONE)
    await end_session(page)


async def scout_ask(page: Page, q: str) -> None:
    await page.fill("#scout-q", q)
    await page.click(".scout-ask button[type=submit]")
    await page.wait_for_timeout(500)
    for _ in range(1500):  # up to 150 s
        if await page.evaluate("() => !document.querySelector('.scout-wait') && !document.querySelector('.scout-ask button[disabled]')"):
            break
        await page.wait_for_timeout(100)


SCOUT_FACTS = r"""() => { const xs = document.querySelectorAll('.scout-x'); const x = xs[xs.length - 1];
  const a = x && x.querySelector('.scout-answer');
  return { answer: Boolean(a), tagged: Boolean(a && a.querySelector('.tag.model')),
    text: a ? a.innerText : '', bullets: a ? /(^|\n)\s*[*-] /.test(a.innerText) : false,
    money: a ? (a.innerText.match(/\$\d[\d,]*\.\d\b/) || [null])[0] : null,
    raw: [...x.querySelectorAll('.scout-read .chip, .scout-answer .cite')].map(c => c.innerText)
      .filter(t => /(^|\W)(grants_gov|sample|nih_reporter|openalex):|\bsample:/.test(t)),
    results: [...x.querySelectorAll('.scout-read-result')].map(r => r.innerText) }; }"""


async def ux_scout(w: Walk, page: Page, base: str, tag: str) -> None:
    """U6, U7 and U8 on a researcher brief: Scout's numbers, model tag and raw ids."""
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".cand", timeout=20000)
    await pick_and_build(page)
    await page.wait_for_selector("#tab-routes", timeout=60000)
    await wait_built(page)
    await page.click("#tab-scout")
    await page.wait_for_selector("#scout-q")
    await scout_ask(page, "When is the next NSF deadline, and why does the top lead fit?")
    got = await page.evaluate(SCOUT_FACTS)
    if got["answer"] and not got["tagged"]:
        w.errors.append(f"{tag}: U7: Scout's answer carries no Model text tag")
    if any(re.match(r"→ fit \d+$", r) for r in got["results"]):
        w.errors.append(f"{tag}: U6: Scout's step shows a fit number unlike the card's Match: {got['results']}")
    if got["raw"]:
        w.errors.append(f"{tag}: U8: Scout shows raw record keys: {got['raw'][:3]}")
    if got["bullets"]:
        w.errors.append(f"{tag}: U8: Scout's answer shows literal markdown bullets")
    if got["money"]:
        w.errors.append(f"{tag}: U8: Scout's answer shows an amount as {got['money']}")
    if not got["answer"]:
        w.errors.append(f"{tag}: scout: no answer to check ({got['results']})")
    if re.search(r"\b20\d\d-\d\d-\d\d\b", got["text"]):  # Q22: dates as on the cards
        w.errors.append(f"{tag}: Q22: Scout's answer writes an ISO date: {got['text'][:120]!r}")
    meta = await page.evaluate("""() => ({ line: (document.querySelector('.scout-meta') || {}).innerText || '',
      steps: [...document.querySelectorAll('.scout-steps')].map(d => d.textContent).join(' ') })""")
    if re.search(r"tokens|Model \w+:", meta["line"]) or not re.search(r"Local model|Cloud", meta["line"]):  # U32
        w.errors.append(f"{tag}: U32: the line under the chat reads {meta['line']!r}, not just where the model runs")
    if "tokens" not in meta["steps"]:
        w.errors.append(f"{tag}: U32: the Steps disclosure does not hold the model and token count")
    # after U32: a follow-up answered from earlier results has no Steps list of its own
    await scout_ask(page, "Why does the top lead fit?")
    papers = await page.evaluate(r"""() => { const xs = document.querySelectorAll('.scout-x'); const x = xs[xs.length - 1];
      const all = [...x.querySelectorAll('.scout-answer .cite')].map(c => [c.innerText.trim(), c.getAttribute('aria-label') || '']);
      return { all: all.length, raw: all.filter(([t, l]) => /^W\d{5,}$/.test(t) || /W\d{5,}/.test(l)) }; }""")
    if papers["raw"]:  # Q8: papers named by title and year, not by OpenAlex work id
        w.errors.append(f"{tag}: Q8: Scout cites papers by raw work id {papers['raw'][:2]}")
    await w.snap(page, tag, "u-scout", full=True)
    await end_session(page)


async def ux_student(w: Walk, page: Page, base: str, tag: str) -> None:
    """U4, U10, U20, U21 and U8 on the SYNTHETIC student path."""
    phone = page.viewport_size["width"] < 700
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.click("[data-key=seg-s]")
    await page.click("[data-key=student]")
    await page.wait_for_selector("#st-cv", timeout=20000)
    if phone:  # U4: an empty submit says so where the button is
        await page.click("[data-key=st-build]")
        await page.wait_for_timeout(500)
        got = await page.evaluate("""() => { const e = document.querySelector('.student-start .notice.error, [role=alert]');
          const r = e && e.getBoundingClientRect(); const a = document.activeElement;
          return { err: Boolean(e), seen: Boolean(r && r.top >= 0 && r.bottom <= innerHeight),
                   focus: Boolean(a && e && (e.contains(a) || a.id === 'st-cv')),
                   invalid: (document.querySelector('#st-cv') || {}).getAttribute('aria-invalid') }; }""")
        if not got["err"] or not got["seen"]:
            w.errors.append(f"{tag}: U4: an empty submit shows no error in view {got}")
        if got["invalid"] != "true":
            w.errors.append(f"{tag}: U4: the CV box is not marked aria-invalid after an empty submit")
        await w.snap(page, tag, "u-empty")
    for kind in ("cv", "interests", "achievements"):
        await page.fill(f"#st-{kind}", (SYN / "persona-masters" / f"{kind}.md").read_text())
    await page.click("[data-key=st-build]")
    await page.wait_for_selector("#progress", timeout=20000)
    await wait_built(page)
    await page.wait_for_timeout(800)
    chip = await page.evaluate("() => [document.querySelector('#status-chip').innerText.trim(), document.querySelector('#status-chip').getAttribute('aria-label')]")
    if not chip[0].startswith("Local only") or "only" not in (chip[1] or ""):  # Q7, as U37 on the documents page
        w.errors.append(f"{tag}: Q7: with the CV held the chip reads {chip[0]!r}")
    # Q17: below the good band the model's sentence is labelled as how it relates, not why it fits
    why = await page.evaluate("""() => [...document.querySelectorAll('#panel .leads > li')].filter(li => {
        const m = li.querySelector('.fit'); const n = m ? parseInt((m.innerText.match(/\\d+/) || [100])[0], 10) : 100;
        return n < 60 && /Why it may fit/.test((li.querySelector('.fit-reason') || {}).innerText || ''); }).length""")
    if why:
        w.errors.append(f"{tag}: Q17: {why} options below the good band say Why it may fit")
    # U20: no rule line or empty-facts line repeated on most cards
    rep = await page.evaluate("""() => { const cards = [...document.querySelectorAll('#panel .leads > li')].filter(li => !li.closest('details'));
      const seen = {}; for (const c of cards) for (const p of new Set([...c.querySelectorAll('.reason, .no-size')].map(x => x.innerText.trim()).filter(t => t.length > 30)))
        seen[p] = (seen[p] || 0) + 1;
      return { n: cards.length, rep: Object.entries(seen).filter(([, k]) => k >= Math.max(3, 0.6 * cards.length)).map(([t]) => t.slice(0, 70)) }; }""")
    if rep["n"] >= 3 and rep["rep"]:
        w.errors.append(f"{tag}: U20: most option cards repeat the same text: {rep['rep'][:3]}")
    await w.snap(page, tag, "u-fellowships", full=True)
    wording = await page.evaluate("""() => ({ tags: [...new Set([...document.querySelectorAll('#panel .leads .tag.model')].map(t => t.innerText.trim()))],
      based: [...document.querySelectorAll('#panel .leads summary')].filter(x => /based on/.test(x.innerText)).length,
      sort: (document.querySelector('#panel .route-row .sort-label') || {}).innerText || null })""")
    if wording["tags"] not in ([], ["Model text"]) or wording["based"]:  # U34
        w.errors.append(f"{tag}: U34: student cards use other words than the researcher's {wording}")
    if wording["sort"] != "Sort":  # U36
        w.errors.append(f"{tag}: U36: the student sort switch has no visible Sort label")
    # U33: a sample's Evidence keeps the canary out of Purpose, in a muted Test marker row
    await page.click("[data-key=route-S]")
    await page.wait_for_timeout(500)
    await page.locator(".leads > li .title-btn").first.click()
    await page.wait_for_selector(".rec-title", timeout=10000)
    await page.wait_for_timeout(500)
    rows = await page.evaluate("""() => { const box = document.querySelector('#evidence-body .rec-title') && document.querySelector('#evidence').hidden === false
      ? document.querySelector('#evidence-body') : document.querySelector('#rail-ev');
      return Object.fromEntries([...box.querySelectorAll('.fields .field')].map(f => [f.querySelector('dt').innerText.trim(), f.querySelector('dd').innerText.trim()])); }""")
    if "canary" in rows.get("Purpose", "").lower() or "SYNTHETIC sample record" in rows.get("Purpose", ""):
        w.errors.append(f"{tag}: U33: the Purpose row carries the canary text: {rows['Purpose'][-70:]!r}")
    if not re.fullmatch(r"PERCH-CANARY-SCH-\d+", rows.get("Test marker", "")):
        w.errors.append(f"{tag}: U33: no Test marker row with the canary (rows: {sorted(rows)})")
    raw = [f"{k}={rows[k]!r}" for k in ("Type", "Level", "Field", "Enrolment") if rows.get(k) and rows[k][0].islower()]
    if raw:
        w.errors.append(f"{tag}: U33: raw lowercase values in Evidence: {raw}")
    await w.snap(page, tag, "u-sample-evidence")
    if phone:
        await page.click("#evidence-close")
        await page.wait_for_timeout(400)
    await page.click("[data-key=route-F]")
    await page.wait_for_timeout(400)
    if not phone:
        await page.locator(".leads > li .btn.keep").first.click()
        await page.wait_for_timeout(300)
        await page.click("[data-key=route-S]")
        await page.wait_for_timeout(500)
        for _i in (0, 1):
            await page.locator(".leads > li .btn.keep:not(.on)").first.click()
            await page.wait_for_timeout(300)
        sl = await page.evaluate("""() => ({ head: document.querySelector('.shortlist-head span').innerText,
          lists: [...document.querySelectorAll('.shortlist ul')].map(u => [...u.querySelectorAll('.kind-short')].map(k => k.innerText)) })""")
        if "sample" not in sl["head"] or any(len(set(x)) > 1 for x in sl["lists"]):
            w.errors.append(f"{tag}: U10: the shortlist mixes public and sample options under one count {sl}")
        await w.snap(page, tag, "u-shortlist")
        await page.click("#tab-compare")
        await page.wait_for_selector("table.compare", timeout=30000)
        await page.wait_for_timeout(800)
        got = await page.evaluate("""() => ({ tables: [...document.querySelectorAll('#panel table.compare')].map(t =>
            ({ sample: t.querySelectorAll('tbody tr .tag.sample, tbody tr .sample-badge').length, rows: t.querySelectorAll('tbody tr').length })),
          label: document.querySelector('#tab-compare').getAttribute('aria-label'),
          sl: (document.querySelector('.shortlist-head span') || {}).innerText || '' })""")
        mixed = [t for t in got["tables"] if 0 < t["sample"] < t["rows"]]
        if mixed or len(got["tables"]) < 2:
            w.errors.append(f"{tag}: U10: one Compare table mixes public fellowships and sample scholarships {got['tables']}")
        if "sample" not in (got["label"] or ""):
            w.errors.append(f"{tag}: U10: the kept count does not split public from sample ({got['label']!r})")
        note = await page.evaluate("""() => ({ subject: Boolean(document.querySelector('.draft input.input')),
          btns: [...document.querySelectorAll('.draft .actions .btn')].map(b => b.innerText.trim()),
          bare: [...document.querySelectorAll('table.compare td')].filter(td => td.innerText.trim() === 'Not stated').length })""")
        if not note["subject"] or note["btns"] not in (["Copy the draft", "Open in my mail app"], ["Copy the draft"]) or note["bare"]:  # U34
            w.errors.append(f"{tag}: U34: the student's note reads {note}")
        await w.snap(page, tag, "u-compare", full=True)
        await page.click("#tab-scout")
        await page.wait_for_selector("#scout-q")
        await scout_ask(page, "List all my options, fellowships and scholarships, with a deadline after 2026-11-01")
        got = await page.evaluate(SCOUT_FACTS)
        if got["raw"]:
            w.errors.append(f"{tag}: U8: Scout shows raw record keys: {got['raw'][:3]}")
        mix = await page.evaluate("""() => { const xs = document.querySelectorAll('.scout-x'); const x = xs[xs.length - 1];
          const a = x && x.querySelector('.scout-answer'); if (!a) return null;
          const lists = [...a.querySelectorAll('ul, ol, p')];
          return lists.some(l => /sample/i.test(l.innerText) && l.querySelector(".cite:not(.sample)") && l.querySelector(".cite.sample")); }""")
        if mix:
            w.errors.append(f"{tag}: U10: Scout lists sample scholarships with public fellowships under one heading")
        await w.snap(page, tag, "u-scout", full=True)
    # U21: back to the documents: a held document shows no empty paste box
    await page.click(".brief .back")
    await page.wait_for_selector("#st-cv, .added", timeout=10000)
    await page.wait_for_timeout(400)
    both = await page.evaluate("""() => [...document.querySelectorAll('.box')].filter(b => b.querySelector('.added')
      && [...b.querySelectorAll('textarea')].some(t => t.offsetParent)).length""")
    if both:
        w.errors.append(f"{tag}: U21: {both} boxes show a held document and an empty paste box together")
    await w.snap(page, tag, "u-back-docs", full=True)
    await end_session(page)


async def ux_sample(w: Walk, page: Page, base: str, tag: str) -> None:
    """U11: a researcher card steered by the SYNTHETIC sample says the cited item is a document."""
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".cand", timeout=20000)
    if await page.locator(".cand button.btn.outline").count():
        await page.locator(".cand button.btn.outline").first.click()
    await page.click("[data-key=more-ctx]")
    await page.click("[data-key=fill-sample]")
    await page.wait_for_selector(".sample-status")
    await page.click("[data-key=build]")
    await page.wait_for_selector("#tab-routes", timeout=60000)
    await wait_built(page)
    await page.wait_for_timeout(800)
    bad = await page.evaluate("""() => [...document.querySelectorAll('#panel details.why')].filter(d => d.querySelector('.paper-ref.private'))
      .map(d => ({ head: (d.querySelector('h4.mini') || {}).innerText || '',
                   badge: [...d.querySelectorAll('.paper-ref.private')].every(p => p.querySelector('.sample-badge')) }))
      .filter(x => !/document/.test(x.head) || !x.badge)""")
    if bad:
        w.errors.append(f"{tag}: U11: a card cites the sample document under {bad[0]['head']!r} (badge: {bad[0]['badge']})")
    await w.snap(page, tag, "u-sample-cite", full=True)
    await end_session(page)


async def ux_queued(w: Walk, page: Page, base: str, tag: str) -> None:
    """U19: while a brief waits for another, the headline says it waits. The first brief
    poll is answered as queued, as the server answers while another brief runs."""
    async def queued(route: Route) -> None:
        r = await route.fetch()
        if r.status != 200:
            await route.fulfill(response=r)
            return
        d = await r.json()
        d["brief"]["status"] = "queued"
        for s in d["brief"]["stages"]:
            s["status"], s["started_at"], s["finished_at"] = "pending", None, None
        body = json.dumps(d)
        for real, alias in aliases().items():  # this handler replaces film.py's alias filter
            body = body.replace(real, alias)
        await route.fulfill(response=r, body=body, headers={**r.headers, "etag": "", "content-encoding": ""})
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".cand", timeout=20000)
    await page.route("**/private/brief", queued)
    await pick_and_build(page)
    await page.wait_for_selector("#progress .p-head", timeout=20000)
    await page.wait_for_timeout(500)
    head = await page.locator("#progress .p-head").inner_text()
    if not head.startswith("Waiting"):
        w.errors.append(f"{tag}: U19: a queued brief's headline reads {head!r}")
    await w.snap(page, tag, "u-queued")
    await page.unroute("**/private/brief")
    await end_session(page)


async def ux_landing(w: Walk, page: Page, base: str, tag: str) -> None:
    """U29, U30, U31 and U41: the landing screen, the no-match screen and the documents path."""
    phone = page.viewport_size["width"] < 700
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    if phone:  # U29: the search placeholder is not cut, at 390 and at 320 px
        for width in (390, 320):
            await page.set_viewport_size({"width": width, "height": 844})
            await page.reload()
            await page.wait_for_selector(".landing")
            fit = await page.evaluate("""() => { const q = document.querySelector('#q'), s = getComputedStyle(q);
              const c = document.createElement('canvas').getContext('2d'); c.font = `${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
              return { text: q.placeholder, need: c.measureText(q.placeholder).width,
                       room: q.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight) }; }""")
            if fit["need"] > fit["room"]:
                w.errors.append(f"{tag}: U29: at {width} px the placeholder {fit['text']!r} needs {fit['need']:.0f} px "
                                f"and the box has {fit['room']:.0f}")
            if width == 390:
                await w.snap(page, tag, "u-landing")
        await page.set_viewport_size(PHONE)
        await page.reload()
        await page.wait_for_selector(".landing")
    summary = await page.locator("[data-key=more-opts]").inner_text()  # U31
    if re.search(r"more options", summary, re.I):
        w.errors.append(f"{tag}: U31: the fold holds a description and a link but is named {summary!r}")
    await page.click("[data-key=more-opts]")
    await w.snap(page, tag, "u-more-opts")
    await page.fill("#q", "zzqxw florbington")  # U30: the example id stays on one line
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".page-sub", timeout=20000)
    await page.wait_for_timeout(300)
    lines = await page.evaluate("""() => { const sub = document.querySelector('.page-sub');
      const tw = document.createTreeWalker(sub, NodeFilter.SHOW_TEXT); const id = '0000-0002-1825-0097';
      for (let n = tw.nextNode(); n; n = tw.nextNode()) { const i = n.data.indexOf(id); if (i < 0) continue;
        const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + id.length); return r.getClientRects().length; }
      return -1; }""")
    if lines != 1:
        w.errors.append(f"{tag}: U30: the example ORCID iD is drawn on {lines} lines")
    await w.snap(page, tag, "u-no-match")
    if not phone:
        await page.goto(base + "/#/")  # Q18: a placeholder ORCID iD fails its checksum
        await page.wait_for_selector(".landing")
        await page.fill("#q", "0000-0000-0000-0000")
        await page.click(".searchbox button[type=submit]")
        await page.wait_for_selector("#pick-title", timeout=20000)
        await page.wait_for_timeout(500)
        got = await page.evaluate("() => [document.querySelector('#pick-title').innerText, (document.querySelector('.notice.error') || {}).innerText || '', document.querySelectorAll('[data-key=build]').length]")
        if got[2] or "not a valid ORCID" not in got[1]:
            w.errors.append(f"{tag}: Q18: the all-zero ORCID iD gives {got[0]!r} {got[1]!r} and {got[2]} Build buttons")
        await page.goto(base + "/#/")  # Q19: a lower-case OpenAlex id finds the same person
        await page.wait_for_selector(".landing")
        await page.fill("#q", AUTHOR.lower())
        await page.click(".searchbox button[type=submit]")
        await page.wait_for_selector("#pick-title", timeout=20000)
        await page.wait_for_timeout(500)
        title = await page.locator("#pick-title").inner_text()
        if not title.startswith("Ready to build"):
            w.errors.append(f"{tag}: Q19: {AUTHOR.lower()!r} gives {title!r}")
    await page.goto(base + "/#/")  # U40: the owl keeps no "say hello" invitation
    await page.wait_for_selector(".landing")
    owls = await page.evaluate("() => [...document.querySelectorAll('button.owl, .owl[role=button], [aria-label*=Scout]')].map(o => o.getAttribute('aria-label'))")
    if any(re.search(r"hello", x or "", re.I) for x in owls):
        w.errors.append(f"{tag}: U40: the owl's label still invites a hello {owls}")
    await page.goto(base + "/#/help")  # U39: five questions at the top of Help
    await page.wait_for_selector(".help")
    await page.wait_for_timeout(400)
    qa = await page.evaluate("""() => { const q = document.querySelector('.help-quick'); const first = document.querySelector('#h-use');
      return { n: q ? q.querySelectorAll('li').length : 0, links: q ? q.querySelectorAll('button, a').length : 0,
               top: q ? Math.round(q.getBoundingClientRect().top + scrollY) : null,
               above: Boolean(q && first && q.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING),
               hello: /hello/i.test(document.querySelector('.help').innerText) }; }""")
    if qa["n"] != 5 or qa["links"] < 5 or not qa["above"] or (qa["top"] or 9999) > 700:
        w.errors.append(f"{tag}: U39: Help has no five-question block at the top {qa}")
    if qa["hello"]:
        w.errors.append(f"{tag}: U40: Help still says hello")
    await w.snap(page, tag, "u-help-top")
    if qa["links"]:
        await page.locator(".help-quick button, .help-quick a").first.click()
        await page.wait_for_timeout(600)
        if await page.evaluate("() => scrollY") < 200:
            w.errors.append(f"{tag}: U39: the first question's link did not move the page")
    if phone:
        return
    await page.goto(base + "/#/")  # U41: the documents path opens its session on arrival
    await page.wait_for_selector(".landing")
    await page.click("[data-key=more-opts]")
    await page.click("[data-key=docs-link]")
    try:
        await page.wait_for_selector("#p-author", timeout=10000)
    except Exception:  # noqa: BLE001 - reported as a finding
        w.errors.append(f"{tag}: U41: the documents path does not open its form without a press on Start a session")
        return
    top = await page.evaluate("""() => { const t = document.querySelector('.private-statement, .private .plain');
      const f = document.querySelector('.private-docs'); return t && f ? t.getBoundingClientRect().bottom <= f.getBoundingClientRect().top : false; }""")
    if not top:
        w.errors.append(f"{tag}: U41: the privacy text does not sit above the documents form")
    await w.snap(page, tag, "u-docs-arrival")
    await end_session(page)


async def ux_docs(w: Walk, page: Page, base: str, tag: str) -> None:
    """U28: the documents-only path shows no real researcher's id as an example."""
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.click("[data-key=more-opts]")
    await page.click("[data-key=docs-link]")
    await page.wait_for_selector("#p-author", timeout=20000)
    ph = await page.locator("#p-author").get_attribute("placeholder") or ""
    if re.search(r"A\d{6,}", ph):
        w.errors.append(f"{tag}: U28: the OpenAlex ID box's example is a real id ({ph!r})")
    chip = lambda: page.evaluate("() => document.querySelector('#status-chip').innerText.trim()")  # noqa: E731
    await page.fill("#doc-proposal", (SYN / "persona-1/specific_aims_draft.md").read_text())
    await page.locator("#doc-proposal ~ .doc-actions button:has-text('Add text')").click()
    await page.wait_for_function("() => !document.querySelector('#doc-proposal')", timeout=20000)
    if not (await chip()).startswith("Local only"):  # U37
        w.errors.append(f"{tag}: U37: the chip reads {await chip()!r} with a document held")
    label = await page.get_attribute("#status-chip", "aria-label")
    if "only" not in (label or ""):
        w.errors.append(f"{tag}: U37: the chip's label does not explain 'only' ({label!r})")
    await w.snap(page, tag, "u-docs")
    await page.locator(".private-docs button:has-text('Remove')").first.click()
    await page.wait_for_selector("#doc-proposal", timeout=10000)
    if (await chip()).startswith("Local only"):
        w.errors.append(f"{tag}: U37: the chip still says Local only after the document was removed")
    text = await page.locator(".private").inner_text()
    if "closing this tab" in text or "30 minutes without use" not in text:  # Q16
        w.errors.append(f"{tag}: Q16: Your documents does not say the session ends after 30 minutes without use")
    # Q25 and Q26: a documents-only brief's hand-off
    for kind, name in (("cv", "cv.md"), ("proposal", "specific_aims_draft.md")):
        await page.fill(f"#doc-{kind}", (SYN / "persona-1" / name).read_text())
        await page.locator(f"#doc-{kind} ~ .doc-actions button:has-text('Add text')").click()
        await page.wait_for_function(f"() => !document.querySelector('#doc-{kind}')", timeout=20000)
    await page.click(".private button:has-text('Build brief')")
    await page.wait_for_selector("#progress", timeout=20000)
    await wait_built(page)
    await page.evaluate(OPEN_WEAK)
    for _i in (0, 1):
        await page.locator(".leads > li .btn.keep:not(.on)").first.click()
        await page.wait_for_timeout(300)
    await page.click("#tab-compare")
    await page.wait_for_selector("[data-key=handoff-make]", timeout=30000)
    await page.locator("[data-key=handoff-make]").click()
    await page.wait_for_selector("#handoff-body", timeout=90000)
    body = await page.locator("#handoff-body").input_value()
    if "(private)" in body.splitlines()[-1] or not body.rstrip().endswith("Best regards,"):
        w.errors.append(f"{tag}: Q26: the email signs off as {body.splitlines()[-1]!r}")
    await page.locator(".handoff input[type=checkbox]").check()
    try:
        await page.wait_for_function("""() => { const n = document.querySelector('.draft .notice, .draft .model-note');
          return !document.querySelector('.handoff [role=status]') && n && !/Choose masking/.test(n.innerText); }""", timeout=90000)
    except Exception:  # noqa: BLE001 - reported as a finding
        note = await page.evaluate("() => (document.querySelector('.draft .notice, .draft .model-note') || {}).innerText || ''")
        w.errors.append(f"{tag}: Q25: after Mask private text the draft still reads {note[:90]!r}")
    await w.snap(page, tag, "q-handoff-masked", full=True)
    await end_session(page)


async def ux_zoom(w: Walk, page: Page, base: str, tag: str) -> None:
    """Q9: laptop at 400% (320 x 215 CSS px): the focused question box is not hidden under
    the header, and the kept pill does not cover the tabs."""
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".cand", timeout=20000)
    await pick_and_build(page)
    await page.wait_for_selector("#tab-routes", timeout=60000)
    await wait_built(page)
    await page.evaluate(OPEN_WEAK)
    for i in (0, 1):
        await page.locator(".leads > li .btn.keep").nth(i).click()
        await page.wait_for_timeout(250)
    await page.set_viewport_size({"width": 320, "height": 215})
    await page.wait_for_timeout(400)
    for y in (0, 400, 1200):
        await page.evaluate(f"() => window.scrollTo(0, {y})")
        await page.wait_for_timeout(300)
        hit = await page.evaluate("""() => { const p = document.querySelector('.keep-float'), t = document.querySelector('.tabs-wrap');
          if (!p || !t || getComputedStyle(p).visibility === 'hidden' || getComputedStyle(p).display === 'none') return false;
          const a = p.getBoundingClientRect(), b = t.getBoundingClientRect();
          return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top; }""")
        if hit:
            w.errors.append(f"{tag}: Q9: at 400% the kept pill covers the tabs (scrolled to {y} px)")
            break
    await w.snap(page, tag, "q-zoom-routes")
    await page.click("#tab-scout")
    await page.wait_for_selector("#scout-q")
    await page.focus("#scout-q")
    await page.wait_for_timeout(400)
    got = await page.evaluate("""() => { const q = document.querySelector('#scout-q').getBoundingClientRect();
      let cover = 0; for (const el of document.querySelectorAll('.bar, .tabs-wrap')) {
        const s = getComputedStyle(el); if (s.position !== 'sticky' && s.position !== 'fixed') continue;
        const r = el.getBoundingClientRect(); if (r.bottom > cover) cover = r.bottom; }
      return { top: q.top, bottom: q.bottom, cover, vh: innerHeight }; }""")
    if got["top"] < got["cover"] or got["bottom"] > got["vh"] or got["top"] < 0:
        w.errors.append(f"{tag}: Q9: at 400% the focused question box sits at {got['top']:.0f} to {got['bottom']:.0f} px "
                        f"under a header that ends at {got['cover']:.0f} px of {got['vh']} px")
    await w.snap(page, tag, "q-zoom-scout")
    await page.set_viewport_size(LAPTOP)
    await end_session(page)


UX_FLOWS = (("ux-laptop", "LAPTOP", "ux_pi"), ("ux-phone", "PHONE", "ux_pi"), ("ux-scout", "LAPTOP", "ux_scout"),
            ("ux-student", "LAPTOP", "ux_student"), ("ux-student-phone", "PHONE", "ux_student"),
            ("ux-sample", "LAPTOP", "ux_sample"), ("ux-queued", "LAPTOP", "ux_queued"), ("ux-docs", "LAPTOP", "ux_docs"),
            ("ux-landing", "LAPTOP", "ux_landing"), ("ux-landing-phone", "PHONE", "ux_landing"),
            ("ux-zoom", "LAPTOP", "ux_zoom"))


async def main(base: str, axe: str | None, out: Path, only: list[str], ux: list[str] | None = None) -> None:
    out.mkdir(parents=True, exist_ok=True)
    names = aliases()
    exe = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))[-1]
    w = Walk(out, axe)
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        if "pi" in only:
            for tag, view, scheme in (("pi-laptop", LAPTOP, "light"), ("pi-phone", PHONE, "light"),
                                      ("pi-laptop-dark", LAPTOP, "dark"), ("pi-phone-dark", PHONE, "dark")):
                ctx, page = await new_page(b, view, names, scheme)
                w.watch(page, tag)
                await w.step(tag, "flow", pi_flow(w, page, base, tag))
                await ctx.close()
            ctx, page = await new_page(b, PHONE, names, motion="reduce")
            await page.goto(base + "/#/")
            await page.wait_for_selector(".landing")
            w.focus["reduced-motion-animations"] = await page.evaluate("""() => [...document.querySelectorAll('*')]
              .map(el => getComputedStyle(el)).filter(s => s.animationName !== 'none' && parseFloat(s.animationDuration) > 0.01
              && s.animationIterationCount !== '1').length""")
            await ctx.close()
        if "checks" in only:
            for tag, view in (("checks", LAPTOP), ("checks-phone", PHONE)):
                ctx, page = await new_page(b, view, names)
                w.watch(page, tag)
                await w.step(tag, "flow", checks_flow(w, page, base, tag))
                await ctx.close()
        if "student" in only:
            for i, persona in enumerate(STUDENTS):
                first = ("phone", PHONE) if i != 1 else ("laptop", LAPTOP)
                second = ("laptop", LAPTOP) if i != 1 else ("phone", PHONE)
                ctx, page = await new_page(b, first[1], names, "dark" if i == 2 else "light")
                w.watch(page, persona)
                await w.step(persona, "flow", student_flow(w, page, base, persona, [first, second]))
                await ctx.close()
        if "private" in only:
            ctx, page = await new_page(b, LAPTOP, names)
            w.watch(page, "persona-1")
            await w.step("persona-1", "flow", private_flow(w, page, base))
            await ctx.close()
        if "workflow" in only:
            for tag, fn in (("workflow-pi", workflow_pi), ("workflow-student", workflow_student),
                            ("workflow-private", workflow_private), ("workflow-sample", workflow_sample)):
                ctx, page = await new_page(b, LAPTOP, names)
                w.watch(page, tag)
                await w.step(tag, "flow", fn(w, page, base, tag))
                await ctx.close()
        if "ux" in only:
            for tag, view, fn in UX_FLOWS:
                if ux and tag not in ux:
                    continue
                ctx, page = await new_page(b, globals()[view], names)
                w.watch(page, tag)
                await w.step(tag, "flow", globals()[fn](w, page, base, tag))
                await ctx.close()
        await b.close()
    report = out / f"report-{'-'.join(only)}.json"
    report.write_text(json.dumps({"states": w.states, "errors": w.errors, "focus": w.focus}, indent=1))
    print(f"{len(w.states)} states, {len(w.errors)} errors -> {report}")
    for e in w.errors:
        print(" ", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8090")
    ap.add_argument("--axe", default=None)
    ap.add_argument("--out", type=Path, default=ROOT / "build/ux")
    ap.add_argument("--only", nargs="+", default=["pi", "checks", "student", "private", "workflow", "ux"])
    ap.add_argument("--ux", nargs="+", default=None, help="with --only ux: just these flows, e.g. ux-phone")
    a = ap.parse_args()
    asyncio.run(main(a.base, a.axe, a.out, a.only, a.ux))
