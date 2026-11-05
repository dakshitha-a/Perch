"""Walk the v1 student-first UI with automatic checks (S43; replaces the S21 private-mode walk).

  scripts/walk_server.py                      # a dev server on 127.0.0.1:8191 (see its docstring)
  uv run --no-project --with playwright --with httpx python scripts/ux_walk.py \\
      [--base http://127.0.0.1:8191] [--out build/s43_walk] [--widths 1280 360] \\
      [--only landing guest awards funding samples briefs mocked] \\
      [--login-helper scripts/e2e_oidc_login.py]   # adds the real sign-in flow
      [--scheme light|dark]                        # colour scheme of the browser (default light)
      [--plant NAME]                               # break one thing on purpose (see PLANTS)

Flows, each at every width:
  landing   signed-out landing, old copy gone, no dead modules, guest start and the banner on every
            guest screen
  awards    the Temple awards list: toggle rule, school tags (counts, geometry), two groups, level,
            search, empty state, Show more, no sample record in a public list
  funding   the funding list: Temple toggle, tags, focus order
  samples   the sample screen: a badge on every card
  briefs    a guest brief for a public author id and for the SYNTHETIC sample persona, keep and compare
  retry     the list error state: /filters fails once, Retry brings the list and the filter bar back
  header    the guest header stays on one row on a phone; a focused control is not under it
  scoutmarks  Ask Scout with a stubbed, SYNTHETIC answer in four states (clean; two unsupported sentences and
            General advice; flagged with a body; withheld in full): the marks, notices and checked line
  cover     Cover-letter points on every lead card: the guest sign-in link; with a stubbed session and routes,
            the busy status and focus, a SYNTHETIC result (Model text tag, Copy), Points again sending `again`,
            a sample record's Sample data badge, a consent 403, a 429 alert, one stored card restored by one GET,
            a redraw; then a researcher lead card
  signinfail  /auth/login and /auth/callback land on the app with a message, never on JSON
  mocked    welcome, account page, withdraw consent, delete dialog and My Perch against a stubbed signed-in session
            (the stubs are in this file; no sign-in service is needed, and the walk says so)
  signin    with --login-helper only: the real sign-in through the dev Keycloak, then welcome,
            account, My Perch and delete. `login(base)` of the helper returns an httpx client whose
            session cookie is copied into the browser.

Every captured state records axe-core violations (WCAG 2.0 to 2.2 A and AA), targets smaller than
44 px and sideways scroll. Page errors and console errors are findings. `--plant` applies one
deliberate fault with Playwright (no source edits), so a check is shown to FAIL before it is
trusted; each plant is expected to make exactly its named check fail.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
import urllib.parse
from pathlib import Path

from playwright.async_api import Browser, Page, Route, async_playwright

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = "A5026494099"  # PI-4, the demo researcher (a public OpenAlex id)
VIEWS = {1280: {"width": 1280, "height": 860}, 360: {"width": 360, "height": 780}}
OLD_COPY = ("Nothing about you is stored", "Local · nothing stored")
PLANTS = ["guest_banner", "no_sample_public", "badge_on_samples", "tag_row_360", "tag_row_contained",
          "counts_from_server", "focus_order", "delete_keyboard", "delete_guard", "old_copy",
          "no_dead_modules", "header_height", "scroll_padding", "retry_filters", "small_target", "mark_sr_text", "cover_no_tag", "cover_sample_badge"]
PROBE = """() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const name = (el) => (el.getAttribute('aria-label') || el.innerText || el.value || el.id || el.tagName)
    .trim().replace(/\\s+/g, ' ').slice(0, 50);
  const small = [];
  for (const el of document.querySelectorAll('a[href], button, input, select, textarea, summary, [role=switch], [role=radio]')) {
    if (!vis(el) || el.closest('[hidden]') || el.closest('dialog:not([open])')) continue;
    if (el.type === 'file') continue;
    // a checkbox is pressed through its label, so the label is the target (S43 M5)
    const box = (el.type === 'checkbox' || el.type === 'radio') && el.closest('label') ? el.closest('label') : el;
    if ((el.type === 'checkbox' || el.type === 'radio') && !vis(box)) continue;
    const r = box.getBoundingClientRect();
    // exempt: a link or the guest link inside a sentence, and a card title button (a text link, 25 px
    // tall, which meets WCAG 2.2's 24 px minimum); both are counted in `under24` only if smaller
    const inline = el.classList.contains('cite') || (el.tagName === 'A' && !el.classList.contains('btn') && getComputedStyle(el).display === 'inline')
      || el.classList.contains('linkish') || el.classList.contains('title-btn');
    // WCAG 2.5.8's inline exception: a link or citation chip inside a sentence is exempt outright when its
    // block holds other words; a standalone inline link (nothing else in its block) still needs 24 px (S49 QA)
    let blk = el.parentElement;
    while (blk && ['inline', 'inline-block', 'inline-flex', 'contents'].includes(getComputedStyle(blk).display)) blk = blk.parentElement;
    const words = blk ? blk.textContent.replace(el.textContent, '').replace(/[^A-Za-z0-9]/g, '').length : 0;
    const inSentence = !el.classList.contains('title-btn') && !el.classList.contains('linkish') && words >= 3;
    if (inline && inSentence) continue;
    if (inline) { if (r.height < 24 && !el.classList.contains('linkish')) small.push({ el: name(el), w: Math.round(r.width), h: Math.round(r.height), under24: true }); continue; }
    if (r.width < 44 || r.height < 44) small.push({ el: name(el) || name(box), w: Math.round(r.width), h: Math.round(r.height) });
  }
  return { small, overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    title: document.title, hash: location.hash };
}"""
AXE = """async () => { const r = await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21a',
  'wcag21aa', 'wcag22aa', 'best-practice'] });
  return r.violations.map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length,
    targets: v.nodes.slice(0, 3).map(x => x.target.join(' ')) })); }"""
TAGS = """() => { const row = document.querySelector('.tag-row'); if (!row) return null;
  const chips = [...row.querySelectorAll('.tag-chip')];
  const rr = row.getBoundingClientRect();
  return { sw: row.scrollWidth, cw: row.clientWidth, ox: getComputedStyle(row).overflowX,
    lines: new Set(chips.map(c => Math.round(c.getBoundingClientRect().top))).size,
    outside: chips.filter(c => { const r = c.getBoundingClientRect(); return r.left < rr.left - 1 || r.right > rr.right + 1; }).length,
    pageOver: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    chips: chips.map(c => ({ label: c.querySelector('span').textContent,
      count: c.querySelector('.n') ? Number(c.querySelector('.n').textContent) : null,
      h: Math.round(c.getBoundingClientRect().height) })) }; }"""


class Walk:
    def __init__(self, out: Path, axe: Path, plant: str | None, scheme: str = "light") -> None:
        self.out, self.axe, self.plant, self.scheme = out, axe, plant, scheme
        self.states: list[dict] = []
        self.errors: list[str] = []
        self.checks: list[tuple[str, bool, str]] = []
        self.requests: list[str] = []

    def errors_since(self, tag: str) -> list[str]:
        return [e for e in self.errors if e.startswith(f"{tag}:")]

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, bool(ok), detail))

    async def snap(self, page: Page, tag: str, name: str, full: bool = True) -> dict:
        await page.wait_for_timeout(300)
        shot = self.out / f"{tag}-{name}.png"
        height = await page.evaluate("document.documentElement.scrollHeight")
        # a long list is cut at 2000 px so the picture can be read
        clip = {"x": 0, "y": 0, "width": page.viewport_size["width"], "height": min(height, 2000)}
        await page.screenshot(path=str(shot), full_page=full, clip=clip if full else None)
        state = {"tag": tag, "name": name, "shot": shot.name, **await page.evaluate(PROBE)}
        if not await page.evaluate("() => Boolean(window.axe)"):
            await page.evaluate(self.axe.read_text() + "\n;0")  # not a <script>: the CSP refuses those
        state["axe"] = await page.evaluate(AXE)
        self.states.append(state)
        return state

    def watch(self, page: Page, tag: str) -> None:
        page.on("pageerror", lambda e: self.errors.append(f"{tag}: page error: {e}"))
        page.on("console", lambda m: self.errors.append(f"{tag}: console error: {m.text[:160]}")
                if m.type == "error" and "Failed to load resource" not in m.text else None)
        page.on("request", lambda r: self.requests.append(r.url))


async def new_page(browser: Browser, w: Walk, tag: str, view: dict, base: str) -> Page:
    ctx = await browser.new_context(viewport=view, reduced_motion="reduce", device_scale_factor=1, color_scheme=w.scheme,
                                    has_touch=view["width"] < 600, is_mobile=view["width"] < 600)
    page = await ctx.new_page()
    w.watch(page, tag)
    if w.plant == "no_dead_modules":
        await page.add_init_script("addEventListener('DOMContentLoaded', () => import('/mode.js').catch(() => 0))")
    if w.plant == "delete_keyboard":  # open the dialog without moving focus into it
        await page.add_init_script("HTMLDialogElement.prototype.showModal = function () {"
                                   " this.setAttribute('open', ''); setTimeout(() => document.activeElement.blur(), 0); }")
    return page


async def until(page: Page, expr: str, arg: object = None, secs: float = 30, every: float = 0.25) -> None:
    """Poll a page expression. Playwright's own wait_for_function evaluates a string, which the
    app's CSP refuses, so this evaluates through the debugger as everything else does."""
    end = asyncio.get_event_loop().time() + secs
    while asyncio.get_event_loop().time() < end:
        if await page.evaluate(expr, arg):
            return
        await asyncio.sleep(every)
    raise TimeoutError(f"waited {secs:.0f} s for: {expr[:80]}")


async def open_filters(page: Page) -> None:
    """S50 (FE-B): on a phone the list filters fold behind a Filters button; open them."""
    t = page.locator("[data-key=filters]")
    if await t.count() and await t.is_visible() and await t.get_attribute("aria-expanded") == "false":
        await t.click()
        await page.wait_for_timeout(150)


async def wait_filters(page: Page, sel: str = ".tag-row", timeout: int = 30_000) -> None:
    """Wait for a filter-bar element, opening the folded phone filters first."""
    await page.wait_for_selector(sel, state="attached", timeout=timeout)
    await open_filters(page)
    await page.wait_for_selector(sel, timeout=10_000)


async def go(page: Page, base: str, hash_: str, ready: str) -> None:
    if not page.url.startswith(base):
        await page.goto(base + "/")
    await page.evaluate("(h) => { location.hash = h; }", hash_)
    if ready == ".tag-row":
        await wait_filters(page)
        return
    await page.wait_for_selector(ready, timeout=30_000)


# ---------- flows ----------

async def flow_landing(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/")
    await page.wait_for_selector(".landing h1")
    await w.snap(page, tag, "landing")
    if w.plant == "old_copy":
        await page.evaluate("document.querySelector('.promises li:nth-child(2)').append(' Nothing about you is stored')")
    text = await page.evaluate("document.body.innerText + ' ' + document.querySelector('meta[name=description]').content")
    w.check("old_copy_gone", not any(s in text for s in OLD_COPY), "landing")
    w.check("landing_student_first", await page.locator("[data-key=seg-s]").get_attribute("aria-checked") == "true"
            and await page.locator("[data-key=browse-awards]").count() == 1, "Student chosen, Browse Temple awards present")
    await page.click("[data-key=guest-start]")
    await page.wait_for_selector("[data-key=guest-banner]")
    notice = await page.evaluate("fetch('/auth/session').then(r => r.json()).then(j => j.notice)")
    shots = {"#/": ".landing h1", "#/awards": ".tag-row", "#/funding": ".award", "#/samples/student": ".award",
             "#/student": ".student-start"}
    bad = []
    for h, ready in shots.items():
        await go(page, base, h, ready)
        if w.plant == "guest_banner" and h == "#/funding":
            await page.evaluate("document.querySelector('#banner').hidden = true")
        banner = await page.evaluate("(() => { const b = document.querySelector('#banner'); return b.hidden ? '' : b.innerText; })()")
        if not (notice and notice in banner):
            bad.append(h)
        if h == "#/":
            await w.snap(page, tag, "landing-guest")
    w.check("guest_banner", not bad, f"missing on {bad}" if bad else "on every guest screen, with the server's notice")
    # a guest session from here on, for the list flows
    body = await page.evaluate("document.body.innerText")
    w.check("old_copy_gone_guest", not any(s in body for s in OLD_COPY), "guest")
    await page.context.close()


async def sample_leak(page: Page) -> list[str]:
    return await page.evaluate("""() => [...document.querySelectorAll('.award')]
      .filter(c => String(c.dataset.id).startsWith('sample:') || c.dataset.sample === 'true' || c.querySelector('.tag.sample'))
      .map(c => c.dataset.id)""")


async def flow_awards(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    page = await new_page(browser, w, tag, view, base)
    calls = {"filters": 0}
    if w.plant == "no_sample_public":
        async def leak(route: Route) -> None:
            r = await route.fetch()
            data = await r.json()
            if data["groups"][0]["items"]:  # an empty search answer is left alone
                item = dict(data["groups"][0]["items"][0])
                item.update(id="sample:sch-0001", sample=True, source="synthetic", name="Planted sample")
                data["groups"][0]["items"].insert(0, item)
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        await page.route(re.compile(r".*/awards\?.*"), leak)
    if w.plant == "counts_from_server":
        async def skew(route: Route) -> None:
            calls["filters"] += 1
            r = await route.fetch()
            data = await r.json()
            if calls["filters"] > 1:  # the chips were drawn from the first answer
                for s in data["schools"]:
                    s["count"] += 1
            await route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        await page.route(re.compile(r".*/filters\?.*"), skew)
    await page.goto(base + "/#/awards")
    await wait_filters(page)
    await page.wait_for_selector(".award")
    await w.snap(page, tag, "awards")
    flt = await page.evaluate("fetch('/filters?audience=student').then(r => r.json())")
    w.check("awards_toggle_rule", (await page.locator("[data-key=temple]").count() == 0) == (flt["total"] == flt["temple_total"])
            and "Temple awards" in await page.locator("h1.page").inner_text(),
            f"total {flt['total']}, temple_total {flt['temple_total']}: toggle hidden and the title says Temple awards")
    tags = await page.evaluate(TAGS)
    if w.plant == "tag_row_360":
        await page.evaluate("""() => { const c = document.querySelectorAll('.tag-chip')[3];
          c.style.height = '30px'; c.style.minHeight = '0'; c.querySelector('span').textContent += ' with a very long label added'; }""")
        tags = await page.evaluate(TAGS)
    if w.plant == "tag_row_contained":
        await page.evaluate("document.querySelector('.tag-row').style.flexWrap = 'wrap'")
        tags = await page.evaluate(TAGS)
    low = [c for c in tags["chips"] if c["h"] < 44]
    w.check("tag_row_chips_44", not low and tags["pageOver"] <= 0, f"{len(tags['chips'])} chips, shortest {min(c['h'] for c in tags['chips'])} px, page overflow {tags['pageOver']}")
    if view["width"] < 600:
        # S50 (decided, V9/V40/Q14): on a phone the school chips are one row that scrolls sideways inside
        # itself; the page never scrolls sideways, and the row can reach every chip
        w.check("tag_row_contained", tags["lines"] == 1 and (tags["sw"] <= tags["cw"] or tags["ox"] in ("auto", "scroll"))
                and tags["pageOver"] <= 0,
                f"{tags['lines']} chip lines, row scroll {tags['sw']} vs client {tags['cw']}, {tags['outside']} chips outside, page overflow {tags['pageOver']}")
    flt2 = await page.evaluate("fetch('/filters?audience=student').then(r => r.json())")
    shown = {c["label"]: c["count"] for c in tags["chips"] if c["count"] is not None}
    want = {s["name"]: s["count"] for s in flt2["schools"]}
    w.check("counts_from_server", shown == want, f"{len(shown)} chips; differ: {[k for k in want if shown.get(k) != want[k]][:3]}")
    leak = await sample_leak(page)
    w.check("no_sample_in_awards", not leak, f"cards with a sample id or badge: {leak}")
    await page.click("[data-key=tag-s\\:CST]")
    await page.wait_for_selector(".group-title:nth-of-type(1)")
    await until(page, "() => document.querySelectorAll('.group-title').length === 2")
    heads = await page.locator(".group-title").all_inner_texts()
    w.check("school_two_groups", len(heads) == 2 and heads[0].startswith("CST (") and heads[1].startswith("Open across Temple ("), str(heads))
    await w.snap(page, tag, "awards-school")
    await page.select_option("#list-level", "undergraduate")
    await page.wait_for_timeout(600)
    await page.click("[data-key=tag-a]")
    await page.wait_for_selector("[data-key^=more-]")
    before = await page.locator(".award").count()
    await page.click("[data-key^=more-]")
    await until(page, "(n) => document.querySelectorAll('.award').length > n", before)
    w.check("show_more", True, f"{before} cards, then more")
    # focus as a user does (the browser honours scroll-padding under the sticky bar); Playwright's
    # fill scrolls the box to the very top, under the bar, which axe then reports as covered (S50 QA)
    await page.locator("#list-q").focus()
    await page.keyboard.type("zzzzqqxx")
    await page.wait_for_selector(".empty-list")
    await w.snap(page, tag, "awards-empty")
    await page.click("[data-key=clear]")
    await page.wait_for_selector(".award")
    w.check("clear_filters", True, "cards return")
    await page.context.close()


async def tab_order(page: Page) -> list[str]:
    await page.focus("#list-title")
    seq = []
    for _ in range(12):
        await page.keyboard.press("Tab")
        seq.append(await page.evaluate("""() => { const e = document.activeElement;
          if (e.matches('[data-key=temple]')) return 'toggle'; if (e.id === 'list-q') return 'search';
          if (e.matches('[data-key=show-closed]')) return 'closed'; if (e.id === 'list-sort') return 'sort';
          if (e.closest('.keep-line')) return 'keepline';
          if (e.closest('form[role=search]')) return 'search'; if (e.id === 'list-level') return 'level';
          if (e.matches('.tag-chip')) return 'tag'; if (e.closest('.award')) return 'card'; return e.tagName; }"""))
    return seq


async def flow_funding(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/#/funding")
    await page.wait_for_selector(".award")
    w.check("funding_toggle_off", await page.locator("[data-key=temple]").get_attribute("aria-checked") == "false", "off by default")
    await w.snap(page, tag, "funding")
    await open_filters(page)
    await page.click("[data-key=temple]")
    await until(page, "() => document.querySelector('[data-key=temple]').getAttribute('aria-checked') === 'true'")
    await page.wait_for_selector(".award")
    await w.snap(page, tag, "funding-temple")
    if w.plant == "focus_order":
        await page.evaluate("""() => { const row = document.querySelector('.filter-row'); row.append(row.firstElementChild); }""")
    seq = await tab_order(page)
    # S49 filter bar: row 1 search, sort; then the two switches (the school chips need Temple only on,
    # so they follow it); then the chips, the guest keep line and the list. S50 (FE-B): the funding
    # list has no level select, so "level" must not appear.
    order = ["search", "sort", "toggle", "closed", "tag", "keepline", "card"]
    firsts = [seq.index(k) for k in order if k in seq]
    w.check("focus_order_lists", [k for k in order if k in seq] == order and firsts == sorted(firsts) and "level" not in seq,
            " > ".join(dict.fromkeys(seq)))
    leak = await sample_leak(page)
    w.check("no_sample_in_funding", not leak, f"{leak}")
    await page.context.close()


async def flow_samples(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/#/samples/student")
    await page.wait_for_selector(".award")
    if w.plant == "badge_on_samples":
        await page.evaluate("document.querySelector('.award .tag.sample').remove()")
    cards = await page.evaluate("[...document.querySelectorAll('.award')].map(c => Boolean(c.querySelector('.tag.sample')))")
    w.check("badge_on_every_sample", bool(cards) and all(cards), f"{sum(cards)} of {len(cards)} cards badged")
    w.check("samples_note", await page.locator(".sample-note").count() == 1, "sample note present")
    await w.snap(page, tag, "samples")
    await page.context.close()


async def build_wait(page: Page, secs: int = 420) -> str:
    await until(page, "() => location.hash.startsWith('#/brief/')", secs=60)
    bid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
    one = """(id) => fetch('/briefs/' + id).then(r => r.json()).then(j => j.brief ? j.brief.status
      : 'answer: ' + JSON.stringify(j).slice(0, 100))"""
    await until(page, "(id) => (" + one + ")(id).then(s => !['queued', 'running'].includes(s))", bid, secs=secs, every=3)
    status = await page.evaluate(one, bid)
    await page.wait_for_timeout(1500)
    return status


async def keep_two(page: Page) -> int:
    btns = page.locator("#panel .btn.keep")
    n = min(2, await btns.count())
    for i in range(n):
        await btns.nth(i).click()
        await page.wait_for_timeout(500)
    return n


async def export_open(w: Walk, page: Page, tag: str, name: str) -> None:
    """The Export menu open, so its rows are measured."""
    await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/routes')")
    await page.wait_for_selector("details.export-menu > summary")
    await page.click("details.export-menu > summary")
    await page.wait_for_selector(".export-pop")
    if w.plant == "small_target":
        await page.evaluate("document.querySelectorAll('.export-pop .check, .export-pop .btn, .filter-chip, .route-btn').forEach((c) => { c.style.minHeight = '30px'; c.style.height = '30px'; })")
    await w.snap(page, tag, name, full=False)
    await page.keyboard.press("Escape")
    if await page.locator("details.export-menu[open]").count():
        await page.click("details.export-menu > summary")


async def other_tabs(w: Walk, page: Page, tag: str, side: str) -> None:
    """The brief's Profile and Scout tabs, each measured."""
    base_hash = await page.evaluate("location.hash.replace(/\\/[a-z]+$/, '')")
    for tab in ("profile", "scout"):
        await page.evaluate("(h) => { location.hash = h; }", f"{base_hash}/{tab}")
        await page.wait_for_timeout(1200)
        await w.snap(page, tag, f"brief-{side}-{tab}")


async def flow_briefs(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/")
    await page.click("[data-key=seg-r]")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector("[data-key=build], .cand button", timeout=60_000)
    if not await page.locator("[data-key=build]").count():
        await page.click(".cand button")
    await page.click("[data-key=build]")
    status = await build_wait(page)
    w.check("guest_researcher_brief", status == "done", f"status {status}")
    await w.snap(page, tag, "brief-researcher")
    await export_open(w, page, tag, "brief-researcher-export")
    await other_tabs(w, page, tag, "researcher")
    await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/routes')")
    await page.wait_for_selector("#panel .btn.keep")
    kept = await keep_two(page)
    await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/compare')")
    await page.wait_for_selector("#panel table, #panel .compare, [data-key=handoff-signin], [data-key=note-signin]", timeout=20_000)
    await page.wait_for_timeout(1000)
    await w.snap(page, tag, "brief-researcher-compare")
    w.check("guest_keep_compare_researcher", kept > 0 and await page.locator("#panel table, #panel .compare").count() > 0, f"{kept} kept")
    w.check("guest_researcher_draft_is_signin",
            await page.locator("[data-key=handoff-make]").count() == 0 and await page.locator("[data-key=handoff-signin]").count() == 1,
            "a guest sees Sign in to draft a note to the office, not a Draft the email button")
    # the sample persona, as a guest
    await page.evaluate("location.hash = '#/'")
    await page.wait_for_selector("[data-key=seg-s]")
    await page.click("[data-key=seg-s]")
    await page.click("[data-key=fit]")
    try:
        await page.click("[data-key=st-build]", timeout=8000)
    except Exception:
        await w.snap(page, tag, "debug-student-start")
        raise
    status = await build_wait(page)
    w.check("guest_sample_persona_brief", status == "done", f"status {status}")
    await w.snap(page, tag, "brief-student")
    bid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
    got = await page.evaluate("(id) => fetch('/briefs/' + id).then(r => r.json())", bid)
    fell = next((s for s in got["brief"]["stages"] if s["name"] == "fellowships"), {})
    srcs = sorted({x["record"]["source"] for x in got["leads"] if x["route"] == "F"})
    w.check("student_fellowship_sources", bool(srcs), f"stage says: {fell.get('summary')!r}; F leads come from {srcs}")
    body = await page.locator("#main").inner_text()
    w.check("sample_brief_not_your_cv", "your CV" not in body and "sample student's CV" in body,
            "the sample brief names the sample student's CV, not yours")
    await export_open(w, page, tag, "brief-student-export")
    await other_tabs(w, page, tag, "student")
    await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/routes')")
    await page.wait_for_selector("#panel .btn.keep")
    kept = await keep_two(page)
    await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/compare')")
    await page.wait_for_selector("#panel table, #panel .compare, [data-key=handoff-signin], [data-key=note-signin]", timeout=20_000)
    await page.wait_for_timeout(1000)
    await w.snap(page, tag, "brief-student-compare")
    w.check("guest_keep_compare_student", kept > 0 and await page.locator("#panel table, #panel .compare").count() > 0, f"{kept} kept")
    w.check("guest_student_note_is_signin",
            await page.locator("[data-key=note-signin]").count() == 1 and await page.locator("#st-body").count() == 0,
            "a guest sees Sign in to draft a note to the office, and no note")
    await page.context.close()


# ---------- the stubbed signed-in session ----------

CONSENT = "SYNTHETIC consent text for the walk. Perch may send the text of your CV to SYNTHETIC Provider. You can delete your data at any time."


async def stub_signed_in(page: Page, state: dict) -> None:
    def session() -> dict:
        if state["gone"]:
            return {"signed_in": False}
        return {"signed_in": True, "guest": False, "roles": state["roles"], "audience": (state["roles"] or ["student"])[0],
                "csrf": "walk-csrf", "display_name": "Sam Example Walker", "expires_at": 9999999999,
                "consent": {"required": not state["consented"], "current_version": 1,
                            "accepted_version": 1 if state["consented"] else 0, "provider_name": "SYNTHETIC Provider", "text": CONSENT},
                "needs_welcome": not (state["roles"] and state["consented"])}

    async def handle(route: Route) -> None:
        url = route.request.url
        if "/auth/session" in url:
            return await route.fulfill(json=session())
        if "/me/roles" in url:
            state["roles"] = json.loads(route.request.post_data or "{}").get("roles", [])
            return await route.fulfill(json={"roles": state["roles"]})
        if "/me/consent/withdraw" in url:
            state["consented"] = False
            state["withdrawn"] = True
            return await route.fulfill(json={"consent_version": 0})
        if "/me/consent" in url:
            state["consented"] = True
            return await route.fulfill(json={"consent_version": 1})
        if "/me/delete" in url and state.get("fail_delete"):
            state["fail_delete"] = False
            return await route.fulfill(status=500, json={"detail": {"error": "delete_incomplete"}})
        if "/me/delete" in url:
            state["deleted_with"] = route.request.post_data
            state["gone"] = True
            return await route.fulfill(status=202, json={"ok": True})
        if "/me/docs" in url:
            return await route.fulfill(json=[{"id": "d1", "kind": "cv", "label": "CV", "chars": 900, "name": "cv.md"}])
        if "/me/saved" in url:  # S49: lists and My Perch read the saved list; an empty one here
            if route.request.method == "GET":
                return await route.fulfill(json={"audience": state["roles"][0] if state["roles"] else "student", "total": 0, "items": []})
            return await route.fulfill(status=201, json={"saved_id": "sv-walk", "record_id": "", "saved_at": "2026-11-04T21:10:00+00:00"})
        if "/me/briefs" in url:
            return await route.fulfill(json=[{"id": "b1", "status": "done", "researcher_id": "you", "created_at": "2026-11-03T12:00:00",
                                              "leads": 12, "topics": []}])
        await route.continue_()
    for pat in ("**/auth/session", "**/me/**"):
        await page.route(pat, handle)


async def flow_mocked(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    page = await new_page(browser, w, tag, view, base)
    state = {"roles": [], "consented": False, "gone": False, "deleted_with": None}
    await stub_signed_in(page, state)
    await page.goto(base + "/")
    await page.wait_for_selector(".welcome")
    w.check("signed_in_new_goes_to_welcome", "#/welcome" in page.url, page.url)
    go_btn = page.locator("[data-key=continue]")
    await w.snap(page, tag, "welcome")
    w.check("welcome_continue_guarded", await go_btn.is_disabled(), "disabled before both steps")
    clip = await page.evaluate("() => { const t = document.querySelector('.consent-text'); return t.scrollHeight - t.clientHeight; }")
    w.check("consent_text_not_clipped", clip <= 0, f"scrollable overflow {clip} px")
    await page.evaluate("location.hash = '#/awards'")
    await page.wait_for_selector(".tag-row", state="attached")
    w.check("public_lists_open_without_welcome", "#/awards" in page.url, page.url)
    await page.evaluate("location.hash = '#/welcome'")
    await page.wait_for_selector(".welcome")
    await page.check("[data-key=role-student]")
    await page.check("[data-key=agree]")
    w.check("welcome_continue_enabled", await go_btn.is_enabled(), "enabled after both steps")
    await go_btn.click()
    # S49: a signed-in user's home is My Perch (its h1 shares #acct-title with the welcome, so wait on the text)
    await page.wait_for_selector("h1#acct-title:text-is('My Perch')")
    w.check("welcome_lands_on_my_perch", page.url.endswith("#/"), page.url)
    await w.snap(page, tag, "after-welcome")
    await page.evaluate("location.hash = '#/me'")
    await page.wait_for_selector(".brief-row")
    await w.snap(page, tag, "my-perch")
    await page.evaluate("location.hash = '#/account'")
    await page.wait_for_selector("#del-open")
    await w.snap(page, tag, "account")
    await page.click("#wd-open")
    await page.wait_for_timeout(200)
    await w.snap(page, tag, "withdraw-dialog", full=False)
    await page.click("#wd-go")
    await page.wait_for_selector("[data-key=consent-again]")
    w.check("withdraw_consent", state.get("withdrawn") and await page.locator("#acct-title").count() == 1,
            "the account page stays and offers Agree again")
    await page.evaluate("location.hash = '#/funding'")
    await page.wait_for_selector(".award, .tag-row, .filter-bar")
    w.check("withdrawn_can_browse", "#/funding" in page.url, page.url)
    await page.evaluate("location.hash = '#/account'")
    await page.wait_for_selector("#del-open")
    await w.snap(page, tag, "account-withdrawn")
    await page.evaluate("location.hash = '#/welcome'")
    await page.wait_for_selector("[data-key=agree]")
    await page.check("[data-key=agree]")
    await page.click("[data-key=continue]")
    await page.wait_for_selector("h1#acct-title:text-is('My Perch')")
    w.check("consent_again", state["consented"], "agreeing again works")
    await page.evaluate("location.hash = '#/account'")
    await page.wait_for_selector("#del-open")
    state["fail_delete"] = True
    await page.click("#del-open")
    await page.fill("#del-word", "delete")
    await page.click("#del-go")
    await page.wait_for_selector(".del-dialog:has(#del-word) .notice.error:not([hidden])")
    msg = await page.locator(".del-dialog:has(#del-word) .notice.error").inner_text()
    w.check("delete_failure_words", "Press Delete again" in msg and "500" not in msg, msg)
    await w.snap(page, tag, "delete-failed", full=False)
    await page.keyboard.press("Escape")
    await page.click("#del-open")
    await page.wait_for_timeout(200)
    focused = await page.evaluate("document.activeElement.id + '|' + Boolean(document.activeElement.closest('dialog'))")
    w.check("delete_takes_focus", focused == "del-word|true", focused)
    if w.plant == "delete_guard":
        await page.evaluate("document.querySelector('#del-go').disabled = false")
    off0 = await page.locator("#del-go").is_disabled()
    await page.fill("#del-word", "delet")
    off1 = await page.locator("#del-go").is_disabled()
    await page.fill("#del-word", "delete")
    on = await page.locator("#del-go").is_enabled()
    w.check("delete_guard", off0 and off1 and on, f"empty disabled {off0}, 'delet' disabled {off1}, 'delete' enabled {on}")
    await w.snap(page, tag, "delete-dialog", full=False)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    back = await page.evaluate("document.activeElement.id")
    w.check("delete_escape_returns_focus", back == "del-open", f"focus on {back}")
    await page.click("#del-open")
    await page.fill("#del-word", "delete")
    await page.click("#del-go")
    await page.wait_for_selector("[data-key=flash-banner]")
    banner = await page.locator("[data-key=flash-banner]").inner_text()
    w.check("delete_sends_confirm_and_ends", json.loads(state["deleted_with"] or "{}") == {"confirm": "delete"}
            and "deleted" in banner and await page.locator("#sign-in").count() == 1, banner.strip())
    await w.snap(page, tag, "after-delete")
    await page.context.close()


async def flow_signin(w: Walk, browser: Browser, base: str, tag: str, view: dict, helper: str) -> None:
    spec = importlib.util.spec_from_file_location("e2e_oidc_login", helper)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    client = mod.login(base)
    page = await new_page(browser, w, tag, view, base)
    await page.context.add_cookies([{"name": c.name, "value": c.value, "url": base} for c in client.cookies.jar])
    await page.goto(base + "/")
    await page.wait_for_selector("#acct-btn, .welcome", timeout=30_000)
    if await page.locator(".welcome").count() or "#/welcome" in page.url:
        await page.wait_for_selector(".welcome")
        await w.snap(page, tag, "welcome")
        for key in ("role-student", "agree"):
            if not await page.locator(f"[data-key={key}]").is_checked():
                await page.check(f"[data-key={key}]")
        await page.click("[data-key=continue]")
        await page.wait_for_selector("#acct-btn")
    await w.snap(page, tag, "signed-in-landing")
    for hash_, ready, name in (("#/student", ".student-start", "student-start"), ("#/me", ".my-perch", "my-perch"),
                               ("#/account", "#del-open", "account")):
        await go(page, base, hash_, ready)
        await w.snap(page, tag, name)
    await page.click("#del-open")
    await page.fill("#del-word", "delete")
    await page.click("#del-go")
    await page.wait_for_selector("[data-key=flash-banner]")
    await w.snap(page, tag, "after-delete")
    w.check("signin_flow", True, "welcome, account, My Perch and delete ran")
    await page.context.close()


async def flow_retry(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    """M7: /filters fails once; Retry brings the list and its filter bar back."""
    for aud, hash_ in (("student", "#/awards"), ("researcher", "#/funding")):
        page = await new_page(browser, w, tag, view, base)
        calls = {"n": 0}
        n_err = len(w.errors)

        def flake(calls: dict):  # noqa: ANN202 - a handler of one argument, bound to this page's counter
            async def flaky(route: Route) -> None:
                calls["n"] += 1
                if calls["n"] == 1 or w.plant == "retry_filters":
                    return await route.abort()
                await route.continue_()
            return flaky
        await page.route(re.compile(r".*/filters\?.*"), flake(calls))
        await page.goto(base + "/" + hash_)
        await page.wait_for_selector("[data-key=retry]")
        await w.snap(page, tag, f"{aud}-list-error")
        await page.click("[data-key=retry]")
        try:
            await page.wait_for_selector(".award", timeout=8000)
            ok = await page.locator(".filter-bar .tag-chip, .filter-bar [data-key=temple]").count() > 0
        except Exception:  # noqa: BLE001
            ok = False
        w.check(f"retry_after_failed_filters_{aud}", ok and len(w.errors) == n_err, f"{calls['n']} /filters calls; list and bar back: {ok}")
        await page.context.close()


async def flow_header(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    """S2 and S3: one-row header on a phone; focus never under the sticky header."""
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/")
    await page.wait_for_selector(".landing h1")
    await page.click("[data-key=guest-start]")
    await page.wait_for_selector("[data-key=guest-banner]")
    if w.plant == "header_height" and view["width"] < 480:
        await page.evaluate("document.querySelector('#acct-slot').style.gridRow = '2'")
    hgt = await page.evaluate("document.querySelector('.bar').getBoundingClientRect().height")
    w.check("header_one_row", hgt < 64 if view["width"] < 480 else True, f"header {hgt:.0f} px at {view['width']} px")
    await go(page, base, "#/awards", ".award")
    if w.plant == "scroll_padding":
        await page.evaluate("document.documentElement.style.scrollPaddingTop = '0px'")
    await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    last = page.locator(".award .title-btn").last
    await last.focus()
    hidden = []
    for _ in range(14):
        await page.keyboard.press("Shift+Tab")
        await page.wait_for_timeout(120)
        top, bar = await page.evaluate("[document.activeElement.getBoundingClientRect().top, document.querySelector('.bar').getBoundingClientRect().bottom]")
        if top < bar - 1:
            hidden.append(round(top))
    w.check("focus_not_under_header", not hidden, f"focus tops under the header: {hidden}")
    await page.context.close()


async def flow_signinfail(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    """M1: a sign-in that cannot start or finish lands on the app, with a message."""
    # the callback with a made-up code: "did not finish" with a provider set (the walk server), "not available" without
    for path, want in (("/auth/login", ("not available",)), ("/auth/callback?code=x&state=y", ("did not finish", "not available"))):
        page = await new_page(browser, w, tag, view, base)
        if path == "/auth/login":
            # The walk server has sign-in on (for the real sign-in flow), so /auth/login would go to the
            # identity provider. Answer it as perch/auth/routes.py does when no provider is set.
            async def unavailable(route: Route) -> None:
                await route.fulfill(status=302, headers={"Location": "/#/?signin=unavailable", "Cache-Control": "no-store"})
            await page.route(re.compile(r".*/auth/login(\?.*)?$"), unavailable)
        await page.goto(base + path)
        await page.wait_for_selector(".landing h1")
        await page.wait_for_selector("[data-key=flash-banner]")
        text = await page.evaluate("document.body.innerText")
        raw = text.strip().startswith("{") or '"detail"' in text or '"error"' in text
        w.check(f"signin_failure_lands_on_app {path.split('?')[0]}", not raw and any(x in text for x in want) and "?signin" not in page.url,
                f"hash {await page.evaluate('location.hash')!r}; banner: {(await page.locator('[data-key=flash-banner]').inner_text()).strip()}")
        if path == "/auth/login":
            fit = (await page.locator("[data-key=fit]").inner_text()).strip()
            links = await page.locator("#sign-in").count()
            w.check("signin_unavailable_offers_sample", fit == "Try a sample student" and links == 0,
                    f"fit button {fit!r}; header sign-in links {links}")
            await w.snap(page, tag, "signin-unavailable")
        await page.context.close()


# ---------- Scout's answer marks (S45) ----------

WITHHELD = "Scout's answer did not pass the citation check twice, so none of it is shown."
CHECKED_OK = "Written by a model; checked against the records it cites."
CHECKED_MARKED = "Written by a model. Some sentences could not be confirmed; they are marked."
CHECKED_FLAGGED = "Written by a model."
SENT_IN = "SYNTHETIC sample claim that the sample award covers travel costs."
SENT_OUT = "SYNTHETIC sample claim that was cut from the text and cannot be found in it."
GENERAL = "SYNTHETIC general tip: ask the sample office what a good next step looks like."


def scout_states(a: str, b: str) -> dict[str, dict]:
    """Four SYNTHETIC answer messages in the shape perch/scout/turn.py stores (a and b are record ids)."""
    base = {"role": "assistant", "kind": "answer", "flagged": False, "withheld": 0, "withheld_all": False,
            "unsupported": [], "general": None, "records": [a, b]}
    return {
        "clean": {**base, "text": f"SYNTHETIC sample answer. The first sample option fits the sample field [{a}]. "
                                  f"A second sample option accepts the same class years [{b}]."},
        "unsupported": {**base, "text": f"SYNTHETIC sample answer. The first sample option fits the sample field [{a}]. {SENT_IN} "
                                        f"The second sample option is open to the same class years [{b}].",
                        "unsupported": [SENT_IN, SENT_OUT], "general": GENERAL},
        "flagged": {**base, "text": f"SYNTHETIC sample answer. The first sample option fits the sample field [{a}].",
                    "flagged": True, "withheld": 2},
        "withheld_all": {**base, "text": WITHHELD, "flagged": True, "withheld": 3, "withheld_all": True, "records": [],
                         "read": [a, b, "user:brief"]},
    }


def scout_session(sid: str, brief: str, question: str, msg: dict | None) -> dict:
    ex = {"id": "m1", "question": question, "kind": "question", "intent": None, "status": "running", "answer": None,
          "answer_by": None, "flagged": False, "errors": [], "cards": [], "message": None, "job_id": None}
    if msg:
        ex |= {"status": "done", "answer": msg["text"], "answer_by": "model", "flagged": msg["flagged"], "message": msg}
    return {"id": sid, "brief_id": brief, "audience": "student", "status": "done", "busy": False, "error": None,
            "model": "fake:fake-1", "policy": "cloud", "tokens": 0, "usd": 0.0, "exchanges": [ex] if msg else [],
            "messages": [], "buttons": [], "usage": {}, "scope": "", "examples": []}


MARKS = """() => {
  const scope = document.querySelector('.scout-x');
  const note = [...scope.querySelectorAll('.notice.warn')].map(n => n.innerText.replace(/\\s+/g, ' ').trim());
  const marks = [...scope.querySelectorAll('mark.unsupported')].map(m => {
    const q = m.querySelector('.unsupported-q'); const sr = m.querySelector('.sr-only'); const cs = getComputedStyle(m);
    return { text: m.textContent, sr: sr ? sr.textContent.trim() : '', glyph: q ? q.textContent : '', glyphHidden: q ? q.getAttribute('aria-hidden') : null,
      line: cs.textDecorationLine, style: cs.textDecorationStyle };
  });
  const prov = scope.querySelector('.scout-answer .provenance');
  const gen = scope.querySelector('.scout-general');
  return { notes: note, marks, listItems: [...scope.querySelectorAll('.notice.warn li')].map(l => l.textContent),
    checked: prov ? prov.innerText.replace(/\\s+/g, ' ').trim() : null, modelTag: Boolean(scope.querySelector('.scout-answer .tag.model')),
    general: gen ? gen.querySelector('b').textContent : null, generalTag: gen ? gen.querySelector('.tag').textContent : null,
    generalHint: gen ? gen.querySelector('.hint').textContent : null,
    answerBox: Boolean(scope.querySelector('.scout-answer')), cites: scope.querySelectorAll('.cite').length };
}"""


async def flow_scoutmarks(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    """S45: Scout's answer marks, with the answer stubbed (a SYNTHETIC message in the stored shape)."""
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/")
    await page.click("[data-key=guest-start]")
    await page.wait_for_selector("[data-key=guest-banner]")
    await page.click("[data-key=seg-s]")
    await page.click("[data-key=fit]")
    await page.click("[data-key=st-build]", timeout=8000)
    status = await build_wait(page)
    w.check("scoutmarks_brief_built", status == "done", f"status {status}")
    bid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
    got = await page.evaluate("(id) => fetch('/briefs/' + id).then(r => r.json())", bid)
    ids = [x.get("record_id") or x["record"]["id"] for x in got["leads"]][:2]
    states = scout_states(*ids)
    cur: dict = {"msg": None, "q": "SYNTHETIC question about the sample options"}

    async def stub(route: Route) -> None:
        if route.request.method not in ("GET", "POST"):
            return await route.continue_()
        body = scout_session("11111111-1111-1111-1111-111111111111", bid, cur["q"], cur["msg"])
        await route.fulfill(json=body)
    await page.route(re.compile(r".*/(briefs/[^/?]+/scout|scout/[^/?]+(/[a-z]+)?)(\?.*)?$"), stub)
    # S46: a guest gets the sign-in prompt, not a question box that cannot send.
    await page.goto(base + f"/#/brief/{bid}/scout")
    await page.wait_for_selector("[data-key=scout-signin], #scout-q")
    w.check("scout_guest_sees_signin", await page.locator("[data-key=scout-signin]").count() == 1
            and await page.locator("#scout-q").count() == 0, "guest Scout panel")
    await w.snap(page, tag, "scout-guest")
    # Then the UI is told it is signed in (the brief stays the guest's), so the answer states show.
    signed = {"signed_in": True, "guest": False, "roles": ["student"], "audience": "student",
              "csrf": "walk-csrf", "display_name": "Sam Example Walker", "expires_at": 9999999999,
              "consent": {"required": False, "current_version": 1, "accepted_version": 1,
                          "provider_name": "SYNTHETIC Provider", "text": CONSENT},
              "needs_welcome": False}

    async def session_stub(route: Route) -> None:
        await route.fulfill(json=signed)
    await page.route("**/auth/session", session_stub)
    res: dict[str, dict] = {}
    chips: list[str] = []
    for name, msg in states.items():
        cur["msg"] = None
        await page.goto(base + f"/#/brief/{bid}/scout")
        await page.reload()
        await page.wait_for_selector("#scout-q")
        cur["msg"] = msg
        await page.fill("#scout-q", cur["q"])
        await page.click(".scout-ask button[type=submit]")
        await page.wait_for_selector(".scout-x .notice.warn, .scout-x .scout-answer")
        if w.plant == "mark_sr_text" and name == "unsupported":
            await page.evaluate("document.querySelectorAll('mark.unsupported .sr-only').forEach((e) => e.remove())")
        await w.snap(page, tag, f"scout-{name}")
        res[name] = await page.evaluate(MARKS)
        if name == "clean":
            chips = await page.locator(".scout-x .scout-answer .cite").all_inner_texts()
    # S50 QA: a student answer's chip reads as the option's name, never "Record <source:id>"
    bad = [t for t in chips if t.startswith("Record ") or re.search(r"[a-z_]+:[\w.-]+", t)]
    w.check("scout_cites_are_names", len(chips) == 2 and not bad, f"chips {chips}")
    c, u, f, a = res["clean"], res["unsupported"], res["flagged"], res["withheld_all"]
    w.check("scout_clean_nothing_flagged", not c["marks"] and not c["notes"] and not c["general"] and c["cites"] == 2
            and c["checked"].endswith(CHECKED_OK), f"cites {c['cites']}, notes {c['notes']}, checked {c['checked']!r}")
    m = u["marks"][0] if len(u["marks"]) == 1 else {}
    w.check("scout_mark_screen_reader_text", bool(m) and m["sr"] == "(not confirmed by the cited record)", f"{u['marks']}")
    w.check("scout_mark_not_colour_only", bool(m) and m["glyph"] == "?" and m["glyphHidden"] == "true"
            and "underline" in m["line"] and m["style"] == "dotted", f"glyph {m.get('glyph')!r}, underline {m.get('line')} {m.get('style')}")
    w.check("scout_mark_only_matched_sentence", len(u["marks"]) == 1 and SENT_IN in m["text"], f"{len(u['marks'])} mark")
    n2 = u["notes"][0] if u["notes"] else ""
    w.check("scout_notice_unsupported", n2.startswith("Scout could not confirm 2 sentences against the cited records. 1 underlined above, 1 listed here.")
            and n2.rstrip().endswith(SENT_OUT) and u["listItems"] == [SENT_OUT],
            f"{n2[:120]!r}; list {u['listItems']}")
    w.check("scout_checked_marked", u["checked"].endswith(CHECKED_MARKED), repr(u["checked"]))
    w.check("scout_general_only_in_unsupported", u["general"] == "General advice, not from records" and u["generalTag"] == "Uncited"
            and u["generalHint"].startswith("General guidance from the model. It cites no record")
            and not (c["general"] or f["general"] or a["general"]), f"{u['general']!r}")
    nf = f["notes"][0] if f["notes"] else ""
    w.check("scout_notice_flagged", nf == "This answer did not pass the citation check twice. 2 sentences were removed. "
            "What remains is shown, but check each claim against its record." and f["checked"].endswith(CHECKED_FLAGGED)
            and not f["marks"] and f["answerBox"], f"{nf[:100]!r}; checked {f['checked']!r}")
    w.check("scout_withheld_all", len(a["notes"]) == 1 and a["notes"][0].startswith(WITHHELD)
            and "Records Scout read:" in a["notes"][0] and a["cites"] == 2
            and "user:" not in a["notes"][0] and not a["answerBox"] and not a["modelTag"] and not a["marks"],
            f"notes {a['notes']}, cites {a['cites']}, model tag {a['modelTag']}")
    await page.context.close()


async def flow_cover(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    """S46: the Cover-letter points button on every lead card. A guest sees the sign-in link; a stubbed
    signed-in session sees the button, and the cover-points routes are stubbed with SYNTHETIC sets in the
    CoverPointSet shape: busy state and focus, a result, "Points again" sending `again`, a sample record's
    badge, a consent 403, a 429, one stored card restored by a single GET; then a researcher lead card."""
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/")
    await page.click("[data-key=guest-start]")
    await page.wait_for_selector("[data-key=guest-banner]")
    await page.click("[data-key=seg-s]")
    await page.click("[data-key=fit]")
    await page.click("[data-key=st-build]", timeout=8000)
    status = await build_wait(page)
    w.check("cover_brief_built", status == "done", f"status {status}")
    bid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
    await page.evaluate("(id) => { location.hash = '#/brief/' + encodeURIComponent(id) + '/routes'; }", bid)
    await page.wait_for_selector("#panel li.card.lead")
    await page.evaluate("document.querySelectorAll('#panel details.dismissed').forEach((d) => { d.open = true; })")
    cards = await page.locator("#panel li.card.lead").count()
    # S49 (U16): a guest is told once, in one line above the list, not on every card
    links = await page.locator("#panel li.card.lead [data-cover] a, #panel li.card.lead a[data-key^=cover-]").count()
    btns = await page.locator("#panel li.card.lead button[data-key^=cover-]").count()
    line = page.locator("#list-notices [data-cover-line]")
    lines = await line.count()
    text = (await line.first.inner_text()).strip() if lines else ""
    signin = await line.locator("a:text-is('Sign in')").count() if lines else 0
    w.check("cover_guest_sees_signin_link", cards > 0 and lines == 1 and signin == 1 and links == 0 and btns == 0
            and text.startswith("Cover-letter points need an account."),
            f"{cards} cards, {lines} list lines {text!r}, {signin} Sign in links in it, {links} card links, {btns} buttons")
    await w.snap(page, tag, "cover-guest")
    # a dismissed card has no sign-in link or button (done as the guest: the stub below has no real session)
    gone = await page.locator("#panel li.card.lead:has([data-key^=dismiss])").last.get_attribute("data-id")
    await page.locator(f"#panel li.card.lead[data-id='{gone}'] [data-key^=dismiss]").click()
    await page.wait_for_timeout(600)
    card = page.locator(f"#panel li.card.lead[data-id='{gone}']")
    w.check("cover_hidden_on_dismissed", await card.count() == 1 and "Restore" in (await card.text_content() or "")
            and await card.locator("[data-key^=cover-]").count() == 0, f"card {gone}")
    got = await page.evaluate("(id) => fetch('/briefs/' + id).then(r => r.json())", bid)
    titles = {x["record_id"]: (x["record"].get("name") or x["record"].get("title") or x["record_id"]) for x in got["leads"]}
    seen = await stub_cover(page, bid, titles, "student")
    # the brief payload names one stored record; only that card makes a GET
    stored_rid: dict = {"id": None}

    async def with_stored(route: Route) -> None:
        resp = await route.fetch()
        if resp.status != 200:
            return await route.fulfill(response=resp)
        body = await resp.json()
        if stored_rid["id"] and isinstance(body, dict) and "leads" in body:
            body["cover_points"] = [stored_rid["id"]]
        await route.fulfill(response=resp, json=body)
    await page.route(re.compile(r".*/briefs/[^/?]+$"), with_stored)
    await page.goto(base + "/")  # a plain load first, to read the ids the screen shows
    await page.evaluate("(id) => { location.hash = '#/brief/' + encodeURIComponent(id) + '/routes'; }", bid)
    await page.wait_for_selector("#panel li.card.lead button[data-key^=cover-]")
    ids = []
    for el in await page.locator("#panel [data-cover]").all():
        if await el.is_visible():
            ids.append(await el.get_attribute("data-cover"))
    plain = [i for i in ids if not i.startswith("sample:")]
    w.check("cover_walk_has_cards", len(plain) >= 5, f"{len(plain)} public cards")
    first, quota_rid, consent_rid, restored_rid = plain[0], plain[1], plain[2], plain[3]
    stored_rid["id"] = restored_rid
    seen["refuse"].update({quota_rid: "quota", consent_rid: "consent"})
    seen["gets"].clear()
    await page.reload()
    await page.wait_for_selector("#panel li.card.lead button[data-key^=cover-]")
    await page.wait_for_timeout(600)
    cards = await page.locator("#panel li.card.lead:not(:has([data-key^=restore]))").count()
    btns = await page.locator("#panel li.card.lead button[data-key^=cover-]").count()
    # S50 B4: the hint is said once above the list, never on a card
    hint0 = await page.locator("#panel [data-cover-line]").first.inner_text() if await page.locator("#panel [data-cover-line]").count() else ""
    card_hints = await page.locator("#panel [data-cover] :text('A model writes these')").count()
    w.check("cover_button_on_every_card", cards > 0 and btns == cards
            and (await page.locator(f"button[data-key='cover-{first}']").inner_text()) == "Cover-letter points",
            f"{cards} cards not dismissed, {btns} buttons")
    # S51 W9: this brief is the sample student's, so the line names the sample student's CV
    w.check("cover_student_hint", hint0.strip() == "A model writes these from the sample student's CV and entries. You put them in your own words."
            and await page.locator("#panel [data-cover-line]").count() == 1 and card_hints == 0,
            f"list line {hint0!r}; {card_hints} card hints")
    w.check("cover_restore_is_one_get", seen["gets"] == [{"record_id": restored_rid}]
            and await page.locator(f"[data-cover='{restored_rid}'] .scout-points").count() == 1
            and await page.locator(f"button[data-key='cover-{restored_rid}']").inner_text() == "Points again"
            and await page.locator(f"[data-cover='{restored_rid}'] > .hint").count() == 0
            and await page.locator("#panel .scout-points").count() == 1, f"{seen['gets']}")
    await w.snap(page, tag, "cover-button")
    one = page.locator(f"button[data-key='cover-{first}']")
    await one.click()
    await page.wait_for_timeout(150)
    live = await page.locator("#live").inner_text()
    wait_line = await page.locator(f"[data-cover='{first}'] [data-cover-wait]").inner_text()
    state = await page.evaluate("""(r) => { const b = document.querySelector(`button[data-key='cover-${r}']`);
      return { focus: document.activeElement === b, disabledAttr: b.disabled, aria: b.getAttribute('aria-disabled'),
        busy: b.getAttribute('aria-busy') }; }""", first)
    w.check("cover_busy_status", wait_line.startswith("A model is reading the record and your CV.")
            and live == wait_line and state["busy"] == "true" and state["aria"] == "true" and not state["disabledAttr"]
            and state["focus"], f"{wait_line!r} live {live!r} {state}")
    await page.wait_for_selector(f"[data-cover='{first}'] .scout-points", timeout=15_000)
    await page.wait_for_timeout(400)
    if w.plant == "cover_no_tag":
        await page.evaluate("document.querySelectorAll('.scout-points .tag.model').forEach((e) => e.remove())")
    res = await page.evaluate("""(rid) => { const c = document.querySelector(`[data-cover='${rid}']`);
      const a = document.activeElement; return { tag: c.querySelector('.scout-points .tag.model')?.textContent || '',
        copy: Boolean(c.querySelector('.points-copy')), items: c.querySelectorAll('.points-list > li').length,
        focusSummary: a.tagName === 'SUMMARY' && c.contains(a), label: c.querySelector('button[data-key^=cover-]').textContent.trim(),
        hints: [...c.querySelectorAll(':scope > .hint')].map((e) => e.textContent), live: document.querySelector('#live').textContent }; }""", first)
    w.check("cover_result_card", res["tag"] == "Model text" and res["copy"] and res["items"] == 3
            and res["label"] == "Points again", f"{res}")
    # the owner's bug (S49): an evidence chip reads as the record's title, never as a record id
    ids_shown = await page.evaluate("""(rid) => [...document.querySelectorAll(`[data-cover='${rid}'] .scout-points .cite`)]
      .flatMap((c) => [c.textContent.trim(), (c.getAttribute('aria-label') || '').replace(/^Evidence: /, '')])
      .filter((t) => /^[a-z_]+:[\\w.-]+$/i.test(t) || t === rid)""", first)
    w.check("cover_cites_are_titles", not ids_shown, f"chips showing an id: {ids_shown[:3]}")
    w.check("cover_result_focus_and_announce", res["focusSummary"] and res["live"] == "The points are ready below.", f"{res}")
    after = await page.locator("#panel [data-cover] :text('A model writes these')").count()
    w.check("cover_hint_hidden_with_result", not any(x.startswith("A model writes these") for x in res["hints"]) and after == 0
            and await page.locator("#panel [data-cover-line]").count() == 1, f"{res['hints']}; {after} card hints")
    w.check("cover_post_sends_csrf", bool(seen["posts"]) and seen["posts"][0][:2] == (first, "walk-csrf"), f"{seen['posts']}")
    await show(page, f"[data-cover='{first}']")
    await w.snap(page, tag, "cover-result", full=False)
    # "Points again" asks for a fresh set: the POST carries `again`, and the second set replaces the first
    await one.click()
    await page.wait_for_selector(f"[data-cover='{first}'] :text('SYNTHETIC: second set')", timeout=15_000)
    w.check("cover_again_sends_again", [p[2] for p in seen["posts"]] == [False, True] and seen["posts"][1][0] == first
            and await page.locator(f"[data-cover='{first}'] .points-list > li").count() == 3, f"{seen['posts']}")
    # a sample record's result carries the Sample data badge (rule 11); the samples sit on their own route
    await page.click("[data-key=route-S]")
    await page.wait_for_selector("#panel li.card.lead button[data-key^=cover-]")
    sample_rid = await page.locator("#panel [data-cover]").first.get_attribute("data-cover")
    await page.locator(f"button[data-key='cover-{sample_rid}']").click()
    await page.wait_for_selector(f"[data-cover='{sample_rid}'] .scout-points", timeout=15_000)
    if w.plant == "cover_sample_badge":
        await page.evaluate("document.querySelectorAll('.scout-points .sample-badge').forEach((e) => e.remove())")
    badge = await page.locator(f"[data-cover='{sample_rid}'] .scout-points .sample-badge").all_inner_texts()
    w.check("cover_sample_result_badge", sample_rid.startswith("sample:") and badge == ["Sample data"], f"{sample_rid} {badge}")
    await show(page, f"[data-cover='{sample_rid}']")
    await w.snap(page, tag, "cover-sample", full=False)
    await page.click("[data-key=route-F]")
    await page.wait_for_selector(f"button[data-key='cover-{consent_rid}']")
    # a 403 for consent names the consent, not the sign-in
    await page.locator(f"button[data-key='cover-{consent_rid}']").click()
    # S50 (FE-B): consent is a step, not an error: an info status with a Read and agree link
    await page.wait_for_selector(f"[data-cover='{consent_rid}'] .notice.info[role=status]", timeout=10_000)
    alert = await page.locator(f"[data-cover='{consent_rid}'] .notice.info[role=status]").inner_text()
    href = await page.locator(f"[data-cover='{consent_rid}'] a.btn").get_attribute("href")
    errs = await page.locator(f"[data-cover='{consent_rid}'] [role=alert], [data-cover='{consent_rid}'] .notice.error").count()
    w.check("cover_consent_403_wording", "need your consent first" in alert and "Sign in" not in alert and errs == 0
            and href == "#/welcome", f"{alert!r} {href}; {errs} error notes")
    await show(page, f"[data-cover='{consent_rid}']")
    await w.snap(page, tag, "cover-consent", full=False)
    # S49 (U6): the allowance is said once, in a status line above the list; the card points to it
    await page.locator(f"button[data-key='cover-{quota_rid}']").click()
    await page.wait_for_selector("#list-notices [data-cover-line][role=status]", timeout=10_000)
    await page.wait_for_selector(f"[data-cover='{quota_rid}'] .quota-hint", timeout=10_000)
    alert = await page.locator("#list-notices [data-cover-line][role=status]").inner_text()
    hint = await page.locator(f"[data-cover='{quota_rid}'] .quota-hint").inner_text()
    card_alerts = await page.locator(f"[data-cover='{quota_rid}'] [role=alert]").count()
    second = page.locator(f"button[data-key='cover-{quota_rid}']")
    w.check("cover_quota_alert", alert.strip().startswith("SYNTHETIC: you have used today's allowance.")
            and hint.strip() == "Today’s allowance is used. See the note above the list." and card_alerts == 0
            and not await second.is_disabled() and await page.evaluate(
                "(r) => document.activeElement === document.querySelector(`button[data-key='cover-${r}']`)", quota_rid),
            f"line {alert.strip()!r}; card {hint.strip()!r}; {card_alerts} card alerts"),
    await show(page, f"[data-cover='{quota_rid}']")
    await w.snap(page, tag, "cover-error", full=False)
    # a redraw (the sort switch) keeps the result: the state is held outside the card
    await page.locator("#sort-pick").select_option("closing")
    await page.wait_for_timeout(500)
    w.check("cover_result_survives_redraw", await page.locator(f"[data-cover='{first}'] .scout-points").count() == 1
            and await page.locator(f"[data-cover='{quota_rid}'] .quota-hint").count() == 1
            and await page.locator("#list-notices [data-cover-line][role=status]").count() == 1, "result, card pointer and list line kept")
    await page.context.close()

    # the researcher lead card: a guest brief for the public author id, a stubbed signed-in session
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/")
    await page.click("[data-key=guest-start]")
    await page.wait_for_selector("[data-key=guest-banner]")
    await page.click("[data-key=seg-r]")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector("[data-key=build], .cand button", timeout=60_000)
    if not await page.locator("[data-key=build]").count():
        await page.click(".cand button")
    await page.click("[data-key=build]")
    status = await build_wait(page)
    w.check("cover_researcher_brief_built", status == "done", f"status {status}")
    rbid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
    got = await page.evaluate("(id) => fetch('/briefs/' + id).then(r => r.json())", rbid)
    # a researcher lead carries its record as `opportunity`, a student lead as `record`; the server's
    # sources map gives the record's title (perch/scout/job.py), so the stub does too
    rtitles = {x["record_id"]: ((x.get("record") or x.get("opportunity") or {}).get("name")
                                or (x.get("record") or x.get("opportunity") or {}).get("title")
                                or x.get("title") or x["record_id"]) for x in got["leads"]}
    rseen = await stub_cover(page, rbid, rtitles, "researcher")
    await page.goto(base + "/")
    await page.evaluate("(id) => { location.hash = '#/brief/' + encodeURIComponent(id) + '/routes'; }", rbid)
    await page.wait_for_selector("#panel li.card.lead button[data-key^=cover-]", timeout=20_000)
    rid = await page.locator("#panel [data-cover]").first.get_attribute("data-cover")
    rhint = (await page.locator("#panel [data-cover-line]").first.inner_text()).strip() if await page.locator("#panel [data-cover-line]").count() else ""
    rcard = await page.locator("#panel [data-cover] :text('A model writes these')").count()
    w.check("cover_researcher_hint", rhint == "A model writes these from your CV, entries and the papers the record cites. You put them in your own words."
            and rcard == 0 and not rseen["gets"], f"{rhint!r}; {rcard} card hints; gets {rseen['gets']}")
    await show(page, f"[data-cover='{rid}']")
    await w.snap(page, tag, "cover-researcher-button", full=False)
    await page.locator(f"button[data-key='cover-{rid}']").click()
    await page.wait_for_selector(f"[data-cover='{rid}'] .scout-points", timeout=15_000)
    w.check("cover_researcher_result", await page.locator(f"[data-cover='{rid}'] .points-list > li").count() == 3
            and rseen["posts"][0][0] == rid, f"{rseen['posts']}")
    await show(page, f"[data-cover='{rid}']")
    await w.snap(page, tag, "cover-researcher-result", full=False)
    await page.context.close()


async def flow_handoff(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    """S48: the researcher hand-off as a worker job. A guest brief with two kept leads, a stubbed signed-in
    session, and the hand-off routes stubbed: POST answers 202 with a poll, the first poll is pending and the
    second brings a SYNTHETIC draft; a second Draft again gets a 429. Checks the busy status (role=status),
    the draft with its "never sends it" line and the error (role=alert); targets and axe come from the walk's totals."""
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/")
    await page.click("[data-key=guest-start]")
    await page.wait_for_selector("[data-key=guest-banner]")
    await page.click("[data-key=seg-r]")
    await page.fill("#q", AUTHOR)
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector("[data-key=build], .cand button", timeout=60_000)
    if not await page.locator("[data-key=build]").count():
        await page.click(".cand button")
    await page.click("[data-key=build]")
    status = await build_wait(page)
    w.check("handoff_brief_built", status == "done", f"status {status}")
    bid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
    await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/routes')")
    await page.wait_for_selector("#panel .btn.keep")
    kept = await keep_two(page)
    seen: dict = {"posts": [], "gets": [], "fail": False}
    jid = "44444444-4444-4444-4444-444444444444"

    async def session(route: Route) -> None:
        await route.fulfill(json={"signed_in": True, "guest": False, "roles": ["researcher"], "audience": "researcher",
                                  "csrf": "walk-csrf", "display_name": "Sam Example Walker", "expires_at": 9999999999,
                                  "consent": {"required": False, "current_version": 1, "accepted_version": 1,
                                              "provider_name": "SYNTHETIC Provider", "text": CONSENT},
                                  "needs_welcome": False})

    async def handoff(route: Route) -> None:
        req = route.request
        if req.method == "POST":
            body = json.loads(req.post_data or "{}")
            seen["posts"].append((body.get("office"), req.headers.get("x-csrf-token")))
            if seen["fail"]:
                return await route.fulfill(status=429, json={"detail": {"error": "quota_exceeded",
                                           "message": "SYNTHETIC: you have used today's allowance.", "usage": {}}})
            return await route.fulfill(status=202, json={"job_id": jid, "status": "queued", "poll": "x"})
        seen["gets"].append(req.url)
        if len(seen["gets"]) % 2 == 1:
            return await route.fulfill(json={"result": None, "job": {"id": jid, "state": "running"}})
        office = dict(urllib.parse.parse_qsl(req.url.split("?", 1)[1])).get("office")
        draft = {"office": {"key": office, "name": "SYNTHETIC Office", "url": "https://example.invalid/"}, "to": "",
                 "subject": "SYNTHETIC: leads to discuss", "flagged": False, "model": "SYNTHETIC model", "lead_ids": ["x1", "x2"],
                 "cited_ids": [], "opening_by": "model",
                 "body": "SYNTHETIC opening paragraph.\n\n- SYNTHETIC lead one\n- SYNTHETIC lead two\n\nThis draft is a sample."}
        await route.fulfill(json={"result": draft, "job": {"id": jid, "state": "succeeded"}})
    await page.route("**/auth/session", session)
    await page.route(re.compile(r".*/briefs/[^/?]+/handoff(\?.*)?$"), handoff)
    await page.goto(base + "/")
    await page.evaluate("(id) => { location.hash = '#/brief/' + encodeURIComponent(id) + '/compare'; }", bid)
    await page.wait_for_selector("[data-key=handoff-make]", timeout=20_000)
    w.check("handoff_button_for_signed_in", kept > 0 and await page.locator("[data-key=handoff-signin]").count() == 0, f"{kept} kept")
    await w.snap(page, tag, "handoff-ready")
    await page.locator("[data-key=handoff-make]").click()
    await page.wait_for_selector(".handoff [role=status]", timeout=5000)
    busy = await page.locator(".handoff [role=status]").inner_text()
    w.check("handoff_busy_status", busy.startswith("A model is writing the opening paragraph. This can take up to two minutes")
            and await page.locator("[data-key=handoff-make]").is_disabled(), busy)
    # The snapshot shows the hand-off from its heading; a compare row half under the sticky tabs
    # is a scroll position, not a target (S51 QA: W7 removed a compare row, which moved it there).
    top = "() => document.getElementById('handoff-title').scrollIntoView({ block: 'start' })"
    await page.evaluate(top)
    await w.snap(page, tag, "handoff-busy", full=False)
    await page.wait_for_selector("[data-key=handoff-subject]", timeout=20_000)
    sent = await page.locator(".handoff").inner_text()
    w.check("handoff_draft_rendered", "Perch never sends it" in sent and len(seen["gets"]) == 2
            and await page.locator("[data-key=handoff-body]").input_value() != "" and seen["posts"][0][1] == "walk-csrf",
            f"posts {seen['posts']}, polls {len(seen['gets'])}")
    await page.evaluate(top)
    await w.snap(page, tag, "handoff-draft")
    seen["fail"] = True
    await page.locator("[data-key=handoff-make]").click()
    await page.wait_for_selector(".handoff [role=alert]", timeout=10_000)
    alert = await page.locator(".handoff [role=alert]").inner_text()
    w.check("handoff_error_alert", "The draft could not be made" in alert, repr(alert))
    await w.snap(page, tag, "handoff-error", full=False)
    await page.context.close()


async def show(page: Page, selector: str) -> None:
    """Scroll a card to the top of the view, so the picture shows it and not the top of the page."""
    await page.evaluate("(s) => document.querySelector(s).closest('li.card').scrollIntoView({ block: 'start' })", selector)
    await page.wait_for_timeout(200)


async def stub_cover(page: Page, bid: str, titles: dict, audience: str) -> dict:
    """A SYNTHETIC signed-in session and the cover-points routes for one page. A POST gets the first job id,
    or the second with `again`, which gives a second set. A record id in `seen["refuse"]` gets a 429
    ("quota") or a 403 consent_required ("consent")."""
    seen: dict = {"posts": [], "gets": [], "refuse": {}}  # refuse: record id -> "quota" or "consent"

    def points_for(rid: str, second: bool) -> dict:
        def pt(asks: str, you: str) -> dict:
            return {"asks": asks, "asks_ids": [rid], "you": you, "you_ids": ["user:interests"]}
        lead = "SYNTHETIC: second set. " if second else "SYNTHETIC: "
        return {"brief_id": bid, "record_id": rid, "title": titles.get(rid, rid), "sample": rid.startswith("sample:"),
                "status": "done", "created_at": "2026-11-04T12:00:00", "missing": ["SYNTHETIC: a letter of support"],
                "unsupported": [], "sources": {rid: titles.get(rid, rid), "user:interests": "SYNTHETIC interests note"},
                "points": [pt(f"{lead}the record asks for a short research plan.", "SYNTHETIC: your interests note describes a plan."),
                           pt("SYNTHETIC: it asks for a named mentor.", "SYNTHETIC: your interests note names a mentor."),
                           pt("SYNTHETIC: it asks for service to the community.", "SYNTHETIC: your interests note lists service.")],
                "note": "SYNTHETIC note"}

    async def session(route: Route) -> None:
        await route.fulfill(json={"signed_in": True, "guest": False, "roles": [audience], "audience": audience,
                                  "csrf": "walk-csrf", "display_name": "Sam Example Walker", "expires_at": 9999999999,
                                  "consent": {"required": False, "current_version": 1, "accepted_version": 1,
                                              "provider_name": "SYNTHETIC Provider", "text": CONSENT},
                                  "needs_welcome": False})

    async def cover(route: Route) -> None:
        req = route.request
        if req.method == "POST":
            body = json.loads(req.post_data or "{}")
            rid = body.get("record_id")
            seen["posts"].append((rid, req.headers.get("x-csrf-token"), bool(body.get("again"))))
            kind = seen["refuse"].get(rid)
            if kind == "consent":
                return await route.fulfill(status=403, json={"detail": "consent_required"})
            if kind == "quota":
                return await route.fulfill(status=429, json={"detail": {"error": "quota_exceeded",
                                           "message": "SYNTHETIC: you have used today's allowance.", "usage": {}}})
            job = "33333333-3333-3333-3333-333333333333" if body.get("again") else "22222222-2222-2222-2222-222222222222"
            return await route.fulfill(status=202, json={"job_id": job, "status": "queued", "poll": "x"})
        q = dict(urllib.parse.parse_qsl(req.url.split("?", 1)[1]))
        seen["gets"].append(q)
        if "job_id" in q:
            return await route.fulfill(json={"result": points_for(q["record_id"], q["job_id"].startswith("3333")),
                                             "job": {"id": q["job_id"], "state": "succeeded"}})
        await route.fulfill(json={"result": points_for(q["record_id"], False), "job": None})
    await page.route("**/auth/session", session)
    await page.route(re.compile(r".*/briefs/[^/?]+/cover-points(\?.*)?$"), cover)
    return seen


FLOWS = {"landing": flow_landing, "awards": flow_awards, "funding": flow_funding, "samples": flow_samples,
         "briefs": flow_briefs, "mocked": flow_mocked, "retry": flow_retry, "header": flow_header,
         "signinfail": flow_signinfail, "scoutmarks": flow_scoutmarks, "cover": flow_cover,
         "handoff": flow_handoff}


async def main(a: argparse.Namespace) -> int:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w = Walk(out, Path(a.axe), a.plant, a.scheme)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for width in a.widths:
            tag = f"w{width}"
            for name in a.only:
                before = len(w.checks)
                try:
                    await FLOWS[name](w, browser, a.base, tag, VIEWS[width])
                except Exception as e:  # noqa: BLE001 - a failed flow is a finding; the walk goes on
                    line = e.__traceback__.tb_next.tb_lineno if e.__traceback__ and e.__traceback__.tb_next else "?"
                    w.errors.append(f"{tag}: {name} (line {line}): {type(e).__name__}: {str(e).splitlines()[0][:200]}")
                print(f"{tag} {name}: {len(w.checks) - before} checks", flush=True)
            if a.login_helper:
                try:
                    await flow_signin(w, browser, a.base, tag, VIEWS[width], a.login_helper)
                except Exception as e:  # noqa: BLE001
                    w.errors.append(f"{tag}: signin: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
        await browser.close()
    dead = [u for u in w.requests if re.search(r"/(mode|private)\.js", u)]
    w.check("no_dead_modules", not dead, f"requests: {dead}")
    under = [(s["tag"], s["name"], c["el"][:30], c["w"], c["h"]) for s in w.states for c in s["small"] if not c.get("under24")]
    w.check("targets_44_every_state", not under, f"{len(under)} targets under 44 px: {under[:6]}")
    sideways = [(s["tag"], s["name"]) for s in w.states if s["overflow"] > 0]
    w.check("no_sideways_scroll", not sideways, f"{sideways[:6]}")
    axe_bad = [(s["tag"], s["name"], v["id"]) for s in w.states for v in s["axe"]]
    w.check("axe_clean_every_state", not axe_bad, f"{axe_bad[:6]}")
    report = {"checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in w.checks],
              "errors": w.errors, "states": w.states, "plant": a.plant}
    (out / f"report{'-' + a.plant if a.plant else ''}.json").write_text(json.dumps(report, indent=1))
    for n, ok, d in w.checks:
        print(f"{'PASS' if ok else 'FAIL'}  {n}  {d}")
    axe = [(s["tag"], s["name"], v["id"], v["n"]) for s in w.states for v in s["axe"]]
    side = [(s["tag"], s["name"], s["overflow"]) for s in w.states if s["overflow"] > 0]
    small = [(s["tag"], s["name"], len(s["small"])) for s in w.states if s["small"]]
    print(f"\n{len(w.states)} states; {len(w.errors)} errors; {len(axe)} axe violations; "
          f"{len(side)} states with sideways scroll; {len(small)} states with targets under 44 px")
    for e in w.errors:
        print("ERROR", e)
    for x in axe:
        print("AXE", *x)
    for x in side:
        print("SIDEWAYS", *x)
    for st in w.states:
        for v in st["axe"]:
            print("AXE-DETAIL", st["tag"], st["name"], v["id"], v["targets"])
        if st["small"]:
            print("SMALL", st["tag"], st["name"], [f"{c['el'][:24]} {c['w']}x{c['h']}" for c in st["small"][:6]])
    return 1 if any(not ok for _, ok, _ in w.checks) else 0



def _load_walk_flows() -> None:
    """S49: each build package keeps its flows in scripts/walk_flows/<name>.py, defining
    register(U) -> (flows: dict, plants: list). They are merged before argparse reads them."""
    import importlib.util
    me = sys.modules[__name__]
    for f in sorted((Path(__file__).resolve().parent / "walk_flows").glob("*.py")):
        if f.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"walk_flows.{f.stem}", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        flows, plants = mod.register(me)
        FLOWS.update(flows)
        PLANTS.extend(p for p in plants if p not in PLANTS)


if __name__ == "__main__":
    _load_walk_flows()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8191")
    ap.add_argument("--out", default="build/s43_walk")
    ap.add_argument("--axe", default=str(ROOT / "scripts/walk_assets/axe.min.js"))
    ap.add_argument("--widths", nargs="+", type=int, default=[1280, 360], choices=list(VIEWS))
    ap.add_argument("--only", nargs="+", default=list(FLOWS), choices=list(FLOWS))
    ap.add_argument("--login-helper", default=None)
    ap.add_argument("--scheme", default="light", choices=["light", "dark"])
    ap.add_argument("--plant", default=None, choices=PLANTS)
    sys.exit(asyncio.run(main(ap.parse_args())))
