# ruff: noqa: E501, ANN001, ANN202 - inline JavaScript probes and Playwright callbacks, as in scripts/ux_walk.py
"""S49 FE-A walk checks: base styles, landing, header, routing, the researcher lead card, the brief
header, the CV card, rerun and the Temple internal route (docs/design/S49_DESIGN.md section 3.3).

Flows (loaded by scripts/ux_walk.py):
  s49a_landing  signed out at 1280x720 and 1366x768, both tabs: the landing fits; the scroll bar shows
  s49a_brief    a guest on #/awards and on the researcher and student briefs: left edges, one Sign in,
                the lead card, the ready chip, the tab names, Sort on the count row, route T
  s49a_mocked   a stubbed signed-in researcher: My Perch at #/, the CV card on the pick screen, rerun

The two briefs are built once by the walk server (a guest PI-4 brief and the SYNTHETIC sample student)
and cached under build/s49_fe_a/cache. Every later run serves the cached payload from a stubbed
GET /briefs/<id>, with SYNTHETIC changes: one lead with no agency, code or status, one explained card
with a citation, two leads moved to route T (only in the route T step), and a SYNTHETIC direction for
the rerun step. Nothing here is sent anywhere.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

CACHE = Path(__file__).resolve().parents[2] / "build" / "s49_fe_a" / "cache"
RB = "aaaaaaaa-0000-4000-8000-0000000000a1"  # stub id for the researcher brief
SB = "aaaaaaaa-0000-4000-8000-0000000000a2"  # stub id for the student brief
DIRECTION = "SYNTHETIC test direction"

LEFT = """() => {
  const edge = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return Math.round((r.left + parseFloat(s.paddingLeft) + parseFloat(s.borderLeftWidth)) * 10) / 10; };
  const b = document.querySelector('#banner');
  return { bar: edge(document.querySelector('.bar-in')), banner: b && !b.hidden ? edge(b.querySelector('p')) : null,
    screen: edge(document.querySelector('main > .screen')), foot: edge(document.querySelector('.foot p')) }; }"""
SIGNIN = """() => [...document.querySelectorAll('header a, header button, #banner a, #banner button')]
  .filter((el) => el.offsetParent !== null && el.innerText.trim() === 'Sign in').length"""
CARDS = """() => { const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const cards = [...document.querySelectorAll('#panel li.card.lead')].filter((c) => vis(c) && !c.closest('details:not([open])'));
  const firstText = (card) => { const w = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) { if (!n.textContent.trim()) continue;
      const el = n.parentElement; if (el.closest('.sr-only') || !vis(el)) continue; return el; } return null; };
  return cards.map((c) => { const t = c.querySelector('.lead-title'); const a = c.querySelector('.actions button, .actions a');
    const ft = firstText(c);
    return { id: c.dataset.id, gone: c.classList.contains('gone') || Boolean(c.closest('.dismissed')),
      h: Math.round(c.getBoundingClientRect().height),
      titleFirst: Boolean(ft && t && t.contains(ft)), first: ft ? ft.textContent.trim().slice(0, 30) : null,
      facts2: c.querySelectorAll('.facts-2 .fact').length,
      emptyTags: [...c.querySelectorAll('.tag, .lead-sub')].filter((x) => !x.textContent.trim()).length,
      titleTop: t ? Math.round(t.getBoundingClientRect().top) : null,
      actTop: a ? Math.round(a.getBoundingClientRect().top) : null }; }); }"""
CITES = """() => [...document.querySelectorAll('#panel .explain .cite')].filter((c) => c.offsetParent !== null).map((c) => {
  const p = c.closest('p') || c.parentElement; const fs = parseFloat(getComputedStyle(p).fontSize);
  return { d: getComputedStyle(c).display, h: Math.round(c.getBoundingClientRect().height * 10) / 10, max: Math.round(fs * 16) / 10 }; })"""
CENTRES = """() => { const c = (s) => { const el = document.querySelector(s); if (!el || el.offsetParent === null) return null;
  const r = el.getBoundingClientRect(); return Math.round(r.top + r.height / 2); };
  return { sort: c('#panel .sort-group'), title: c('#panel #routes-title') }; }"""
LIST_IDS = """() => [...document.querySelectorAll('#panel ol.leads > li.card.lead')]
  .filter((c) => !c.closest('.dismissed')).map((c) => c.dataset.id)"""


def register(U) -> tuple[dict, list]:  # noqa: C901 - one walk module, flows as closures over U
    async def build_payloads(browser, base: str) -> tuple[dict, dict]:
        """The two real briefs, built once and cached as JSON (public PI-4 data and the SYNTHETIC student)."""
        rp, sp = CACHE / "researcher.json", CACHE / "student.json"
        if rp.is_file() and sp.is_file():
            return json.loads(rp.read_text()), json.loads(sp.read_text())

        async def keep(page, path: Path) -> None:
            status = await U.build_wait(page)
            bid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
            got = await page.evaluate("(id) => fetch('/briefs/' + id).then(r => r.json())", bid)
            if status != "done" or "brief" not in got:
                raise RuntimeError(f"the brief for the cache did not build: {status} {str(got)[:120]}")
            path.write_text(json.dumps(got))
        CACHE.mkdir(parents=True, exist_ok=True)
        w = U.Walk(CACHE, Path(U.ROOT / "scripts/walk_assets/axe.min.js"), None)
        page = await U.new_page(browser, w, "cache", U.VIEWS[1280], base)
        await page.goto(base + "/")
        await page.click("[data-key=seg-r]")
        await page.fill("#q", U.AUTHOR)
        await page.click(".searchbox button[type=submit]")
        await page.wait_for_selector("[data-key=build], .cand button", timeout=60_000)
        if not await page.locator("[data-key=build]").count():
            await page.click(".cand button")
        await page.click("[data-key=build]")
        await keep(page, rp)
        await page.evaluate("location.hash = '#/'")
        await page.wait_for_selector("[data-key=seg-s]")
        await page.click("[data-key=seg-s]")
        await page.click("[data-key=fit]")
        await page.click("[data-key=st-build]", timeout=8000)
        await keep(page, sp)
        await page.context.close()
        return json.loads(rp.read_text()), json.loads(sp.read_text())

    def researcher_variant(raw: dict, route_t: bool = False, direction: str | None = None) -> dict:
        d = copy.deepcopy(raw)
        d["brief"]["id"] = RB
        d["brief"]["status"] = "done"
        a = sorted([x for x in d["leads"] if (x.get("route") or "A") == "A"], key=lambda x: x.get("rank", 0))
        if a:  # a lead whose record names no agency, code or status (M1)
            o = a[0].setdefault("opportunity", {})
            o.update(agency=None, parent_agency=None, activity_code=None, status="posted")
        if len(a) > 1:
            # an explained card with an inline citation chip in its sentence (M2); the fake model
            # writes "Cited work:" findings, which render as paper rows, not chips
            papers = list((d.get("papers") or {}).keys())
            wid = papers[0].rsplit("/", 1)[-1] if papers else None
            if wid:
                a[1]["explanation"] = f"SYNTHETIC: this call funds work close to your recent paper [{wid}]."
                a[1]["cited_ids"] = [wid]
                a[1]["flagged"] = False
        if route_t and len(a) > 3:
            # the back end's contract (95c8508): route "A", group "temple_internal", ranks from 1
            for i, x in enumerate(a[-2:], 1):
                x["group"] = "temple_internal"
                x["rank"] = i
                x["opportunity"]["title"] = "SYNTHETIC Temple internal call " + x["id"][-4:]
        # what the rules left out, as GET /briefs/<id> gives it (S49 F2)
        d["brief"]["hidden"] = [{"key": "synthetic", "label": "SYNTHETIC hidden reason", "count": 3, "record_ids": []}]
        if direction is not None:
            d["brief"]["options"]["direction"] = direction
        return d

    def student_variant(raw: dict) -> dict:
        d = copy.deepcopy(raw)
        d["brief"]["id"] = SB
        return d

    async def serve(page, bid: str, payload: dict) -> None:
        async def handle(route) -> None:
            if route.request.method != "GET":
                return await route.fulfill(json={"status": "kept"})
            await route.fulfill(json=payload)
        await page.unroute(re.compile(rf".*/briefs/{bid}(\?.*)?$"))
        await page.route(re.compile(rf".*/briefs/{bid}(\?.*)?$"), handle)

    async def guest_page(w, browser, base, tag, view):
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/")
        await page.click("[data-key=seg-r]")
        await page.click("[data-key=guest-start]")
        await page.wait_for_selector("[data-key=guest-banner]")
        return page

    async def open_brief(page, bid: str) -> None:
        await page.evaluate("(id) => { location.hash = '#/brief/' + id + '/routes'; }", bid)
        await page.wait_for_selector("#panel li.card.lead", timeout=20_000)
        await page.wait_for_timeout(600)
        await page.evaluate("window.scrollTo(0, 0)")

    # ---------- s49a_landing ----------

    async def flow_landing(w, browser, base, tag, view) -> None:
        if view["width"] != 1280:
            return
        bad = []
        for size in ({"width": 1280, "height": 720}, {"width": 1366, "height": 768}):
            page = await U.new_page(browser, w, tag, size, base)
            await page.goto(base + "/")
            await page.wait_for_selector(".landing h1")
            for who in ("s", "r"):
                await page.click(f"[data-key=seg-{who}]")
                await page.wait_for_timeout(200)
                sh = await page.evaluate("[document.documentElement.scrollHeight, innerHeight]")
                if sh[0] > sh[1]:
                    bad.append(f"{size['width']}x{size['height']} {who}: {sh[0]} > {sh[1]}")
                await w.snap(page, tag, f"s49a-landing-{size['width']}x{size['height']}-{who}", full=False)
            if size["width"] == 1280:
                col = await page.evaluate("getComputedStyle(document.documentElement).scrollbarColor")
                clear = re.fullmatch(r"(?:\s*(?:transparent|rgba\([^)]*,\s*0\))\s*){2}", col or "")
                w.check("s49_scrollbar_visible", not clear, f"scrollbar-color {col!r}")
            await page.context.close()
        w.check("s49_landing_no_scroll", not bad, "; ".join(bad) or "fits at 1280x720 and 1366x768, both tabs")

    # ---------- s49a_brief ----------

    async def flow_brief(w, browser, base, tag, view) -> None:
        raw_r, raw_s = await build_payloads(browser, base)
        wide = view["width"] >= 1280
        page = await guest_page(w, browser, base, tag, view)
        if wide:
            await U.go(page, base, "#/awards", ".tag-row")
            await page.wait_for_timeout(400)
            e1 = await page.evaluate(LEFT)
            await w.snap(page, tag, "s49a-awards")
        await serve(page, RB, researcher_variant(raw_r))
        await open_brief(page, RB)
        await w.snap(page, tag, "s49a-brief-researcher")
        n = await page.evaluate(SIGNIN)
        w.check(f"s49_guest_one_signin_{tag}", n == 1, f"{n} visible Sign in links in the header and banner")
        if wide:
            e2 = await page.evaluate(LEFT)
            def even(e: dict) -> bool:
                vals = [v for v in e.values() if v is not None]
                return len(vals) == 4 and max(vals) - min(vals) <= 1
            w.check("s49_left_edges_1280", even(e1) and even(e2), f"awards {e1}; brief {e2}")
            top = await page.evaluate("() => { const c = document.querySelector('#panel li.card.lead'); return c ? Math.round(c.getBoundingClientRect().top + scrollY) : null; }")
            w.check("s49_first_lead_top", top is not None and top <= 500, f"first lead top {top} px")
            c = await page.evaluate(CENTRES)
            w.check("s49_sort_on_count_row", c["sort"] is not None and c["title"] is not None and abs(c["sort"] - c["title"]) <= 12,
                    f"researcher: sort centre {c['sort']}, title centre {c['title']} (the student half is BE-S S3)")
        cards = await page.evaluate(CARDS)
        live = [c for c in cards if not c["gone"]]
        empty = [c["id"] for c in cards if c["emptyTags"]]
        w.check(f"s49_no_empty_tag_{tag}", bool(cards) and not empty, f"{len(cards)} cards; empty tag or sub line on {empty[:3]}")
        notfirst = [(c["id"][-6:], c["first"]) for c in live if not c["titleFirst"]]
        w.check(f"s49_title_first_{tag}", bool(live) and not notfirst, f"first text elsewhere on {notfirst[:3]}")
        two = [(c["id"][-6:], c["facts2"]) for c in live if c["facts2"] != 2]
        w.check(f"s49_two_facts_{tag}", bool(live) and not two, f"{len(live)} cards; not two facts: {two[:3]}")
        if wide:
            hs = sorted(c["h"] for c in live[:5])
            med = hs[len(hs) // 2] if hs else None
            w.check("s49_card_height", med is not None and med <= 260, f"first five heights {[c['h'] for c in live[:5]]}, median {med}")
        else:
            low = [(c["id"][-6:], c["titleTop"], c["actTop"]) for c in live if c["titleTop"] is None or c["actTop"] is None or c["titleTop"] >= c["actTop"]]
            w.check("s49_phone_title_top", bool(live) and not low, f"title not above the actions on {low[:3]}")
        cites = await page.evaluate(CITES)
        # a <button> set to display: inline computes inline-block in Chromium, so both pass; the
        # old chip was inline-flex and 44 px tall
        bad = [x for x in cites if x["d"] not in ("inline", "inline-block") or x["h"] > x["max"]]
        w.check(f"s49_cite_inline_{tag}", bool(cites) and not bad, f"{len(cites)} cites; off: {bad[:3]}")
        # the brief header once ready
        chip = page.locator(".ready-chip")
        pcard = await page.evaluate("() => [...document.querySelectorAll('.pcard')].some((p) => p.offsetParent !== null)")
        steps_ok = False
        if await chip.count():
            await page.click(".ready-chip > summary")
            await page.wait_for_timeout(200)
            steps_ok = await page.evaluate("() => { const o = document.querySelector('.ready-chip ol'); return Boolean(o && o.offsetParent !== null && o.children.length); }")
            await w.snap(page, tag, "s49a-ready-chip-open", full=False)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)
            back = await page.evaluate("() => document.activeElement && document.activeElement.matches('.ready-chip > summary') && !document.querySelector('.ready-chip').open")
            w.check(f"s49_ready_chip_escape_{tag}", back, "Escape closes the steps and returns focus to the chip")
        w.check(f"s49_ready_chip_{tag}", await chip.count() == 1 and not pcard and steps_ok,
                f"chip {await chip.count()}, progress card visible {pcard}, steps shown {steps_ok}")
        tr = await page.locator("#tab-profile").get_attribute("aria-label")
        hid = await page.evaluate("() => { const p = document.querySelector('#panel .hidden-line'); return p && p.offsetParent !== null ? p.innerText : null; }")
        w.check(f"s49_hidden_line_{tag}", bool(hid) and "SYNTHETIC hidden reason (3)" in hid, f"{hid!r}")
        # route T: two leads moved to T; the switch shows them apart from Grants
        await serve(page, RB, researcher_variant(raw_r, route_t=True))
        await page.evaluate("location.hash = '#/'")
        await page.wait_for_selector(".landing h1, #acct-title")
        await open_brief(page, RB)
        tids = {x["id"] for x in researcher_variant(raw_r, route_t=True)["leads"] if x.get("group") == "temple_internal"}
        ok, detail = False, "no Temple internal button"
        if await page.locator("[data-key=route-T]").count():
            await page.click("[data-key=route-T]")
            await page.wait_for_timeout(400)
            shown_t = set(await page.evaluate(LIST_IDS))
            head = await page.locator("#routes-title").inner_text()
            await w.snap(page, tag, "s49a-route-t")
            await page.click("[data-key=route-A]")
            await page.wait_for_timeout(400)
            shown_a = set(await page.evaluate(LIST_IDS))
            ok = bool(shown_t) and shown_t <= tids and not (shown_a & tids)
            detail = f"T list {len(shown_t)} ({head!r}), T ids under Grants {len(shown_a & tids)}"
        w.check(f"s49_route_t_apart_{tag}", ok, detail)
        # the student brief
        await serve(page, SB, student_variant(raw_s))
        await open_brief(page, SB)
        await w.snap(page, tag, "s49a-brief-student")
        ts = await page.locator("#tab-profile").get_attribute("aria-label")
        w.check(f"s49_tab_names_{tag}", tr == "What Perch read" and ts == "What Perch read", f"researcher {tr!r}, student {ts!r}")
        await page.context.close()

    # ---------- s49a_mocked ----------

    async def flow_mocked(w, browser, base, tag, view) -> None:
        raw_r, _ = await build_payloads(browser, base)
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["researcher"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)

        async def saved(route) -> None:
            await route.fulfill(json={"audience": "researcher", "total": 0, "items": []})
        await page.route(re.compile(r".*/me/saved(\?.*)?$"), saved)
        await page.goto(base + "/")
        await page.wait_for_selector("h1")
        await page.wait_for_timeout(800)
        h1 = (await page.locator("main h1").first.inner_text()).strip()
        link = await page.locator("#my-perch-link").count() and await page.locator("#my-perch-link").is_visible()
        wide = view["width"] >= 1280
        w.check(f"s49_signed_in_home_{tag}", h1 == "My Perch" and (bool(link) if wide else True),
                f"h1 {h1!r}, My Perch link visible {bool(link)}")
        await w.snap(page, tag, "s49a-home")
        # the pick screen, reached by a search, with the CV card
        await page.evaluate("location.hash = '#/start'")
        await page.wait_for_selector("[data-key=seg-r]")
        await page.click("[data-key=seg-r]")
        await page.fill("#q", U.AUTHOR)
        await page.click(".searchbox button[type=submit]")
        await page.wait_for_selector("[data-key=build], .cand button", timeout=60_000)
        if not await page.locator("[data-key=build]").count():
            await page.click(".cand button")
        await page.wait_for_selector("[data-key=build]")
        await page.wait_for_timeout(500)
        cv = await page.evaluate("() => { const i = document.querySelector('#r-cv-file'); return i ? !i.closest('details:not([open])') : null; }")
        w.check(f"s49_cv_card_visible_{tag}", cv is True, f"#r-cv-file present and not folded: {cv}")
        await w.snap(page, tag, "s49a-pick-cv")
        # rerun: the pick screen with the person and the options from the brief
        await serve(page, RB, researcher_variant(raw_r, direction=DIRECTION))
        await page.evaluate("(id) => { location.hash = '#/rerun/' + id; }", RB)
        got = None
        for _ in range(24):
            await page.wait_for_timeout(250)
            got = await page.evaluate("() => { const t = document.querySelector('#ctx-direction'); return t ? [location.hash, t.value] : null; }")
            if got:
                break
        w.check(f"s49_rerun_prefills_{tag}", bool(got) and got[0] == "#/find" and got[1] == DIRECTION, f"{got}")
        if got:
            await w.snap(page, tag, "s49a-rerun")
        await page.context.close()

    return {"s49a_landing": flow_landing, "s49a_brief": flow_brief, "s49a_mocked": flow_mocked}, []
