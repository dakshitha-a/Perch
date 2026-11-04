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
from pathlib import Path

from playwright.async_api import Browser, Page, Route, async_playwright

ROOT = Path(__file__).resolve().parents[1]
AUTHOR = "A5026494099"  # PI-4, the demo researcher (a public OpenAlex id)
VIEWS = {1280: {"width": 1280, "height": 860}, 360: {"width": 360, "height": 780}}
OLD_COPY = ("Nothing about you is stored", "Local · nothing stored")
PLANTS = ["guest_banner", "no_sample_public", "badge_on_samples", "tag_row_360", "tag_row_contained",
          "counts_from_server", "focus_order", "delete_keyboard", "delete_guard", "old_copy",
          "no_dead_modules", "header_height", "scroll_padding", "retry_filters", "small_target"]
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
    const inline = (el.tagName === 'A' && !el.classList.contains('btn') && getComputedStyle(el).display === 'inline')
      || el.classList.contains('linkish') || el.classList.contains('title-btn');
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
  return { sw: row.scrollWidth, cw: row.clientWidth, ox: getComputedStyle(row).overflowX,
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


async def go(page: Page, base: str, hash_: str, ready: str) -> None:
    if not page.url.startswith(base):
        await page.goto(base + "/")
    await page.evaluate("(h) => { location.hash = h; }", hash_)
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
    await page.wait_for_selector(".tag-row")
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
        await page.evaluate("document.querySelector('.tag-row').style.overflowX = 'visible'")
        tags = await page.evaluate(TAGS)
    low = [c for c in tags["chips"] if c["h"] < 44]
    w.check("tag_row_chips_44", not low and tags["pageOver"] <= 0, f"{len(tags['chips'])} chips, shortest {min(c['h'] for c in tags['chips'])} px, page overflow {tags['pageOver']}")
    if view["width"] < 600:
        w.check("tag_row_contained", tags["sw"] > tags["cw"] and tags["pageOver"] <= 0 and tags["ox"] == "auto",
                f"row scroll {tags['sw']} > client {tags['cw']}, page overflow {tags['pageOver']}")
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
    await page.fill("#list-q", "zzzzqqxx")
    await page.wait_for_selector(".empty-list")
    await w.snap(page, tag, "awards-empty")
    await page.click("[data-key=clear]")
    await page.wait_for_selector(".award")
    w.check("clear_filters", True, "cards return")
    await page.context.close()


async def tab_order(page: Page) -> list[str]:
    await page.focus("#list-title")
    seq = []
    for _ in range(9):
        await page.keyboard.press("Tab")
        seq.append(await page.evaluate("""() => { const e = document.activeElement;
          if (e.matches('[data-key=temple]')) return 'toggle'; if (e.id === 'list-q') return 'search';
          if (e.closest('form[role=search]')) return 'search'; if (e.id === 'list-level') return 'level';
          if (e.matches('.tag-chip')) return 'tag'; if (e.closest('.award')) return 'card'; return e.tagName; }"""))
    return seq


async def flow_funding(w: Walk, browser: Browser, base: str, tag: str, view: dict) -> None:
    page = await new_page(browser, w, tag, view, base)
    await page.goto(base + "/#/funding")
    await page.wait_for_selector(".award")
    w.check("funding_toggle_off", await page.locator("[data-key=temple]").get_attribute("aria-checked") == "false", "off by default")
    await w.snap(page, tag, "funding")
    await page.click("[data-key=temple]")
    await until(page, "() => document.querySelector('[data-key=temple]').getAttribute('aria-checked') === 'true'")
    await page.wait_for_selector(".award")
    await w.snap(page, tag, "funding-temple")
    if w.plant == "focus_order":
        await page.evaluate("""() => { const row = document.querySelector('.filter-row'); row.append(row.firstElementChild); }""")
    seq = await tab_order(page)
    order = ["toggle", "search", "level", "tag", "card"]
    firsts = [seq.index(k) for k in order if k in seq]
    w.check("focus_order_lists", [k for k in order if k in seq] == order and firsts == sorted(firsts), " > ".join(dict.fromkeys(seq)))
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
    await page.wait_for_timeout(1500)
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
    await page.wait_for_timeout(1500)
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
    await page.wait_for_selector(".tag-row")
    w.check("public_lists_open_without_welcome", "#/awards" in page.url, page.url)
    await page.evaluate("location.hash = '#/welcome'")
    await page.wait_for_selector(".welcome")
    await page.check("[data-key=role-student]")
    await page.check("[data-key=agree]")
    w.check("welcome_continue_enabled", await go_btn.is_enabled(), "enabled after both steps")
    await go_btn.click()
    await page.wait_for_selector(".landing h1")
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
    await page.wait_for_selector(".landing h1")
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

        async def flaky(route: Route) -> None:
            calls["n"] += 1
            if calls["n"] == 1 or w.plant == "retry_filters":
                return await route.abort()
            await route.continue_()
        await page.route(re.compile(r".*/filters\?.*"), flaky)
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
    for path, want in (("/auth/login", "not available"), ("/auth/callback?code=x&state=y", "available")):
        page = await new_page(browser, w, tag, view, base)
        await page.goto(base + path)
        await page.wait_for_selector(".landing h1")
        await page.wait_for_selector("[data-key=flash-banner]")
        text = await page.evaluate("document.body.innerText")
        raw = text.strip().startswith("{") or '"detail"' in text or '"error"' in text
        w.check(f"signin_failure_lands_on_app {path.split('?')[0]}", not raw and want in text and "?signin" not in page.url,
                f"hash {await page.evaluate('location.hash')!r}; banner: {(await page.locator('[data-key=flash-banner]').inner_text()).strip()}")
        if path == "/auth/login":
            await w.snap(page, tag, "signin-unavailable")
        await page.context.close()


FLOWS = {"landing": flow_landing, "awards": flow_awards, "funding": flow_funding, "samples": flow_samples,
         "briefs": flow_briefs, "mocked": flow_mocked, "retry": flow_retry, "header": flow_header,
         "signinfail": flow_signinfail}


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


if __name__ == "__main__":
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
