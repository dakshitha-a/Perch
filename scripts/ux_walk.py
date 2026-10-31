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
    await page.wait_for_timeout(600)
    await page.click("button:has-text('Start a session')")
    await page.wait_for_timeout(1000)
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
    if not await page.evaluate("() => [...document.querySelectorAll('.leads > li .lead-title')]"
                               ".every(t => /Evidence/.test(t.innerText))"):
        w.errors.append(f"{tag}: W4: a lead title has no visible Evidence marker")
    # W2: Keep sits in the card head, not under the explanation.
    gap = await page.evaluate("""() => { const c = document.querySelector('.leads > li');
      const k = c && c.querySelector('.btn.keep'); if (!k) return null;
      return Math.round(k.getBoundingClientRect().top - c.getBoundingClientRect().top); }""")
    if gap is None or gap > 120:
        w.errors.append(f"{tag}: W2: Keep sits {gap} px below the top of its card")
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
    mask = page.locator(".handoff input[type=checkbox]")
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
    await w.snap(page, tag, "w6-compare", full=True)
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
    # W8: the note shows at once, has no dead To box, and Open in mail sends the edited text.
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
    mail = page.locator(".draft .actions a:has-text('Open in mail')")
    if await mail.count():
        await mail.click()
        got = await page.evaluate("() => decodeURIComponent(window.__mail || '')")
        if "EDITED-W8" not in got:
            w.errors.append(f"{tag}: W8: Open in mail sends the note as first drawn, not as edited")
    else:
        w.errors.append(f"{tag}: W8: no Open in mail button on a note about public fellowships")
    await w.snap(page, tag, "w8-note", full=True)
    await end_session(page)


async def workflow_private(w: Walk, page: Page, base: str, tag: str) -> None:
    await page.goto(base + "/#/")
    await page.wait_for_selector(".landing")
    await page.click("[data-key=more-opts]")
    await page.click("[data-key=docs-link]")
    await page.click("button:has-text('Start a session')")
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


async def main(base: str, axe: str | None, out: Path, only: list[str]) -> None:
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
                            ("workflow-private", workflow_private)):
                ctx, page = await new_page(b, LAPTOP, names)
                w.watch(page, tag)
                await w.step(tag, "flow", fn(w, page, base, tag))
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
    ap.add_argument("--only", nargs="+", default=["pi", "checks", "student", "private", "workflow"])
    a = ap.parse_args()
    asyncio.run(main(a.base, a.axe, a.out, a.only))
