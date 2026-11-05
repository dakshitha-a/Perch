# ruff: noqa: E501, ANN001, ANN202 - inline JavaScript probes and Playwright callbacks, as in scripts/ux_walk.py
"""S50 FE-A walk checks: base styles, the lead card, the list head, stopping a brief, the example
brief (docs/design/S50_DESIGN.md section 3.3).

Flows (loaded by scripts/ux_walk.py):
  s50a_styles    heading focus, control borders, disabled buttons and the form column (A1)
  s50a_cards     a guest on the stubbed PI-4 brief: the lead card, sort, the withheld note, the
                 ready chip, the open evidence rail, industry cards, the student compare cards
  s50a_building  a stubbed signed-in researcher whose brief is still building: Stop (A4)
  s50a_example   the static example page and its landing link (A5)

Every brief is the cached payload under build/s49_fe_a/cache (built by the s49a flows), served
from a stubbed GET /briefs/<id> with SYNTHETIC changes. Nothing here is sent anywhere.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

CACHE = Path(__file__).resolve().parents[2] / "build" / "s49_fe_a" / "cache"
RB = "aaaaaaaa-0000-4000-8000-0000000000b1"  # stub id for the researcher brief
SB = "aaaaaaaa-0000-4000-8000-0000000000b2"  # stub id for the student brief

# WCAG contrast of each visible control's top border against the first opaque background above it.
BORDERS = """() => {
  const rgb = (s) => { const m = s.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const c = rgb(getComputedStyle(e).backgroundColor); if (c && c.a > 0.5) return c; }
    return rgb(getComputedStyle(document.body).backgroundColor); };
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const els = [...document.querySelectorAll('.btn:not(.primary):not(.quiet), input, select, textarea, .searchbox')]
    .filter((el) => vis(el) && !['checkbox', 'radio', 'hidden', 'file'].includes(el.type))
    .filter((el) => parseFloat(getComputedStyle(el).borderTopWidth) > 0);
  return els.map((el) => { const c = rgb(getComputedStyle(el).borderTopColor);
    const r = c ? ratio(c, bgOf(el.parentElement)) : 0;
    return { el: (el.dataset.key || el.className || el.tagName).toString().slice(0, 30), r: Math.round(r * 100) / 100 }; }); }"""
CARDS = """() => { const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const cards = [...document.querySelectorAll('#panel ol.leads > li.card.lead')].filter((c) => vis(c) && !c.closest('details:not([open])'));
  return cards.map((c) => { const t = c.querySelector('.lead-title'); const k = c.querySelector('[data-key=keep]');
    const fx = c.querySelector('.facts-2'); const f2 = c.querySelectorAll('.facts-2 .fact')[1];
    return { id: c.dataset.id, titleW: t ? Math.round(t.getBoundingClientRect().width) : null,
      keepTop: k ? Math.round(k.getBoundingClientRect().top) : null, factsBottom: fx ? Math.round(fx.getBoundingClientRect().bottom) : null,
      fact2Left: f2 ? Math.round(f2.getBoundingClientRect().left * 10) / 10 : null,
      inFoot: Boolean(k && k.closest('.lead-foot > .actions')), withheld: Boolean(c.querySelector('.withheld-line')) }; }); }"""
MATCHES = """() => [...document.querySelectorAll('#panel ol.leads > li.card.lead')].filter((c) => c.offsetParent !== null)
  .map((c) => { const b = c.querySelector('.fit b'); return b ? Number(b.textContent) : null; })"""


def register(U) -> tuple[dict, list]:  # noqa: C901 - one walk module, flows as closures over U
    def cached() -> tuple[dict, dict]:
        rp, sp = CACHE / "researcher.json", CACHE / "student.json"
        if not (rp.is_file() and sp.is_file()):
            raise RuntimeError("run the s49a_brief flow once to build the cached briefs")
        return json.loads(rp.read_text()), json.loads(sp.read_text())

    def researcher(raw: dict, route_t: bool = False, flag_two: bool = False, instant: bool = False) -> dict:
        d = copy.deepcopy(raw)
        d["brief"]["id"] = RB
        d["brief"]["status"] = "done"
        a = sorted([x for x in d["leads"] if (x.get("route") or "A") == "A" and x.get("group") != "temple_internal"],
                   key=lambda x: x.get("rank", 0))
        if route_t and len(a) > 3:  # two leads moved to T with ranks 1 and 2 (the S49 stub)
            for i, x in enumerate(a[-2:], 1):
                x["group"] = "temple_internal"
                x["rank"] = i
                x["opportunity"]["title"] = "SYNTHETIC Temple internal call " + x["id"][-4:]
        if flag_two:
            for x in a[:3]:
                x.update(flagged=True, explanation=None, cited_ids=[])
            # S51 (D16): a stage skipped by the model budget shows the budget line instead, so
            # the withheld case runs with the explanations stage done.
            for s in d["brief"]["stages"]:
                if s["name"] == "explanations":
                    s.update(status="done", detail="SYNTHETIC: 3 withheld")
        if len(a) > 3:  # BE-G: a placeholder date reaches the page as null, with the record's own words
            o = a[3].setdefault("opportunity", {})
            o.update(close_date=None, close_date_note=None, deadline_quote=None, close_text="SYNTHETIC: proposals accepted at any time")
        if instant:  # a brief served from the cache: every step starts and ends at once
            for s in d["brief"]["stages"]:
                s["started_at"] = s["finished_at"] = "2026-11-05T04:42:55.852147Z"
        return d

    def student(raw: dict, kept: int = 0) -> dict:
        d = copy.deepcopy(raw)
        d["brief"]["id"] = SB
        n = 0
        for x in d["leads"]:
            if n < kept and x.get("verdict") in ("eligible", "may be eligible") and not x.get("sample"):
                x["status"] = "kept"
                n += 1
        return d

    async def serve(page, bid: str, payload) -> dict:
        hits = {"cancel": 0}

        async def handle(route) -> None:
            if route.request.url.rstrip("/").endswith("/cancel"):
                hits["cancel"] += 1
                return await route.fulfill(json={"id": bid, "cancelled": True})
            if route.request.method != "GET":
                return await route.fulfill(json={"status": "kept"})
            await route.fulfill(json=payload() if callable(payload) else payload)
        await page.unroute(re.compile(rf".*/briefs/{bid}(/cancel)?(\?.*)?$"))
        await page.route(re.compile(rf".*/briefs/{bid}(/cancel)?(\?.*)?$"), handle)
        return hits

    async def guest_page(w, browser, base, tag, view):
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/")
        await page.click("[data-key=seg-r]")
        await page.click("[data-key=guest-start]")
        await page.wait_for_selector("[data-key=guest-banner]")
        return page

    async def open_brief(page, bid: str, tab: str = "routes", ready: str = "#panel li.card.lead") -> bool:
        await page.evaluate("([id, t]) => { location.hash = '#/brief/' + id + '/' + t; }", [bid, tab])
        try:
            await page.wait_for_selector(ready, timeout=20_000)
        except Exception:  # noqa: BLE001 - a screen that never draws is a failed check, not a crash
            return False
        await page.wait_for_timeout(600)
        await page.evaluate("window.scrollTo(0, 0)")
        return True

    def example_stub(raw: dict):
        body = {"version": 2, "brief": researcher(raw), "candidates": [{"display_name": "PI-4"}], "records": {}}

        async def ok(route) -> None:
            await route.fulfill(json=body)

        async def missing(route) -> None:
            await route.fulfill(status=404, json={"detail": "not found"})
        return ok, missing

    # ---------- s50a_styles ----------

    async def flow_styles(w, browser, base, tag, view) -> None:
        wide = view["width"] >= 1280
        sch = w.scheme
        # control borders: the landing (both tabs) and the awards list
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/")
        await page.wait_for_selector(".landing h1")
        got = []
        for who in ("s", "r"):
            await page.click(f"[data-key=seg-{who}]")
            await page.wait_for_timeout(200)
            got += await page.evaluate(BORDERS)
        await U.go(page, base, "#/awards", ".tag-row")
        await page.wait_for_timeout(500)
        got += await page.evaluate(BORDERS)
        low = [x for x in got if x["r"] < 3.0]
        w.check(f"s50a_control_border_{sch}_{tag}", bool(got) and not low, f"{len(got)} controls; under 3:1: {low[:4]}")
        await page.context.close()
        # heading focus: a signed-in account that still owes the welcome screen
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": [], "consented": False, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)
        await page.goto(base + "/#/awards")
        await page.wait_for_selector(".tag-row", state="attached")
        await page.evaluate("location.hash = '#/welcome'")
        await page.wait_for_selector("#acct-title")
        await page.wait_for_timeout(300)
        ring = await page.evaluate("() => { const a = document.activeElement; return [a.tagName, getComputedStyle(a).outlineStyle]; }")
        w.check(f"s50a_heading_ring_{tag}", ring == ["H1", "none"], f"focus on {ring[0]}, outline {ring[1]}")
        edges = """() => { const s = document.querySelector('main > .screen'); if (!s) return null; const r = s.getBoundingClientRect();
          const cs = getComputedStyle(s); const right = r.right - parseFloat(cs.paddingRight) - parseFloat(cs.borderRightWidth);
          return [...document.querySelectorAll('main > .screen .box, main > .screen .welcome-go .btn.primary')].filter((e) => e.offsetParent !== null)
            .map((e) => Math.round((right - e.getBoundingClientRect().right) * 10) / 10); }"""
        off = {}
        off["welcome"] = await page.evaluate(edges)
        await w.snap(page, tag, "s50a-welcome")
        state.update(roles=["researcher"], consented=True)
        await page.evaluate("location.hash = '#/account'")
        await page.wait_for_selector("#acct-title")
        await page.wait_for_timeout(500)
        off["account"] = await page.evaluate(edges)
        await page.context.close()
        # the student start with no CV: the build button is disabled
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["student"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)

        async def no_docs(route) -> None:
            await route.fulfill(json=[])
        await page.route(re.compile(r".*/me/docs(\?.*)?$"), no_docs)
        await page.goto(base + "/#/student")
        await page.wait_for_selector("[data-key=st-build]")
        await page.wait_for_timeout(400)
        off["student"] = await page.evaluate(edges)
        dis = await page.evaluate("""() => { const b = document.querySelector('[data-key=st-build]'); const t = document.createElement('span');
          t.style.background = 'var(--chip)'; document.body.append(t); const chip = getComputedStyle(t).backgroundColor; t.remove();
          return [b.disabled, getComputedStyle(b).backgroundColor, chip, getComputedStyle(b).opacity]; }""")
        w.check(f"s50a_disabled_{sch}_{tag}", dis[0] and dis[1] == dis[2] and dis[3] == "1", f"disabled {dis[0]}, background {dis[1]}, chip {dis[2]}, opacity {dis[3]}")
        await w.snap(page, tag, "s50a-student-start")
        await page.context.close()
        if wide:
            bad = {k: [x for x in v if abs(x) > 1] for k, v in off.items() if v is None or any(abs(x) > 1 for x in v)}
            w.check("s50a_form_edges", all(off.values()) and not bad, f"right-edge gaps off by more than 1 px: {bad or 'none'}; counts {[len(v or []) for v in off.values()]}")

    # ---------- s50a_cards ----------

    async def flow_cards(w, browser, base, tag, view) -> None:
        raw_r, raw_s = cached()
        wide = view["width"] >= 1280
        page = await guest_page(w, browser, base, tag, view)
        await serve(page, RB, researcher(raw_r, instant=True))
        shown = await open_brief(page, RB)
        await w.snap(page, tag, "s50a-brief")
        cards = await page.evaluate(CARDS) if shown else []
        if wide:
            narrow = [(c["id"][-6:], c["titleW"]) for c in cards if c["titleW"] is None or c["titleW"] < 600]
            w.check("s50a_title_width", bool(cards) and not narrow, f"{len(cards)} cards; under 600 px: {narrow[:4]}")
            lefts = [c["fact2Left"] for c in cards if c["fact2Left"] is not None]
            w.check("s50a_facts_column", len(lefts) >= 3 and max(lefts) - min(lefts) <= 1,
                    f"second fact left edges {sorted(set(lefts))[:6]}")
        above = [c["id"][-6:] for c in cards if c["keepTop"] is None or c["factsBottom"] is None or c["keepTop"] < c["factsBottom"] or not c["inFoot"]]
        w.check(f"s50a_actions_footer_{tag}", bool(cards) and not above, f"{len(cards)} cards; Keep not in the footer under the facts on {above[:4]}")
        # the record's own date words stand in for a missing date (G8, BE-G close_text)
        words = await page.evaluate("() => [...document.querySelectorAll('#panel li.card.lead .fact.close dd')].map((d) => d.textContent)")
        w.check(f"s50a_close_text_{tag}", any("SYNTHETIC: proposals accepted at any time" in x for x in words), f"{words[:6]}")
        # what the rules left out, as a disclosure (Tier B, V44)
        hid = [x for x in (raw_r["brief"].get("hidden") or []) if x.get("label") and x.get("count")]
        fold = await page.evaluate("""() => { const d = document.querySelector('#panel details.hidden-fold'); if (!d) return null;
          return [d.querySelector('summary').textContent, [...d.querySelectorAll('li')].map((li) => li.textContent)]; }""")
        want = [f"{sum(x['count'] for x in hid)} hidden by the rules", [f"{x['label']}: {x['count']}" for x in hid]]
        w.check(f"s50a_hidden_fold_{tag}", bool(hid) and fold == want, f"got {fold}, want {want}"[:240])
        chip = await page.evaluate("() => { const c = document.querySelector('.ready-chip .ready-word'); return c ? c.textContent : null; }")
        if wide:
            w.check("s50a_ready_zero", chip == "Ready", f"chip text {chip!r}")
        # the sort select: a change redraws the list and keeps focus on the select
        if wide:
            sel = page.locator("#sort-pick")
            ok, detail = False, "no #sort-pick select"
            if await sel.count():
                await sel.select_option("closing")
                await page.wait_for_timeout(300)
                foc = await page.evaluate("() => document.activeElement && document.activeElement.id")
                ok, detail = foc == "sort-pick", f"focus on {foc!r} after the change"
                await sel.select_option("order")
                await page.wait_for_timeout(200)
            w.check("s50a_sort_select", ok, detail)
        # the open evidence rail (wide) or sheet (phone)
        first = page.locator("#panel li.card.lead .lead-title .title-btn").first
        ok, detail = False, "no card title"
        if await first.count():
            title = (await first.inner_text()).strip()
            await first.click()
            await page.wait_for_timeout(1200)
            if wide:
                got = await page.evaluate("""() => { const r = document.querySelector('#rail-ev'); const t = r && r.querySelector('#evidence-title');
                  const c = document.querySelector('#panel li.card.lead'); return [t ? t.textContent : null, r ? r.textContent.includes('Pick a card’s title') : null, c.classList.contains('selected')]; }""")
                ok = bool(got[0]) and got[0].strip() in title and got[1] is False and got[2]
                detail = f"rail title {got[0]!r}, placeholder still shown {got[1]}, card selected {got[2]}"
                await w.snap(page, tag, "evidence-rail-open", full=False)
            else:
                got = await page.evaluate("() => { const s = document.querySelector('#evidence'); const b = document.querySelector('#evidence-body'); return [s ? !s.hidden : false, b ? b.textContent.slice(0, 400) : ''] }")
                ok = got[0] and title[:30] in got[1]
                detail = f"sheet open {got[0]}, body holds the title {title[:30] in got[1]}"
                await w.snap(page, tag, "evidence-sheet-open", full=False)
                await page.keyboard.press("Escape")
        w.check(f"s50a_title_opens_evidence_{tag}", ok, detail)
        # industry cards draw, with Keep in the footer
        if await page.locator("[data-key=route-B]").count():
            await page.click("[data-key=route-B]")
            await page.wait_for_timeout(600)
            org = await page.evaluate("() => [...document.querySelectorAll('#panel li.card.lead.org')].map((c) => Boolean(c.querySelector('.lead-foot > .actions [data-key=keep]')))")
            w.check(f"s50a_industry_cards_{tag}", bool(org) and all(org), f"{len(org)} industry cards; Keep in the footer on {sum(org)}")
            # from the top, so the guest banner is not half under the sticky header (S51: the list
            # now starts lower, so the closed sheet's focus return leaves the page scrolled)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(200)
            await w.snap(page, tag, "s50a-industry")
            await page.click("[data-key=route-A]")
            await page.wait_for_timeout(300)
        # the withheld reason said once: three flagged cards, one list note and no card line
        await serve(page, RB, researcher(raw_r, flag_two=True, instant=True))
        await page.evaluate("location.hash = '#/'")
        await page.wait_for_selector(".landing h1, #acct-title")
        if await open_brief(page, RB):
            note = await page.evaluate("() => { const n = document.querySelector('#list-notices [data-withheld]'); return n ? [n.innerText, Boolean(n.querySelector('svg'))] : null; }")
            lines = sum(c["withheld"] for c in await page.evaluate(CARDS))
            w.check(f"s50a_withheld_once_{tag}", bool(note) and lines == 0 and "show no reason" in note[0],
                    f"list note {note}, card withheld lines {lines}")
            await w.snap(page, tag, "s50a-withheld")
        # route T in Match order
        await serve(page, RB, researcher(raw_r, route_t=True, instant=True))
        await page.evaluate("location.hash = '#/'")
        await page.wait_for_selector(".landing h1, #acct-title")
        ok, detail = False, "no Temple internal button"
        if await open_brief(page, RB) and await page.locator("[data-key=route-T]").count():
            await page.click("[data-key=route-T]")
            await page.wait_for_timeout(400)
            m = await page.evaluate(MATCHES)
            ok = len(m) >= 3 and all(a is not None and b is not None and a >= b for a, b in zip(m, m[1:], strict=False))
            detail = f"Match numbers top to bottom {m}"
            await w.snap(page, tag, "s50a-route-t")
        w.check(f"s50a_sort_order_{tag}", ok, detail)
        # research threads: "Thread 1 · 73 %" over the label's words as chips (Tier B, V48)
        await page.evaluate("(id) => { location.hash = '#/brief/' + id + '/profile'; }", RB)
        await page.wait_for_timeout(1000)
        th = await page.evaluate("""() => [...document.querySelectorAll('#panel li.thread:not(.said)')].map((t) => [t.querySelector('h3').textContent,
          t.querySelectorAll('.thread-words .chip').length])""")
        how = await page.locator("#panel details.threads-how").count()
        w.check(f"s50a_threads_{tag}", bool(th) and all(re.fullmatch(r"Thread \d+ · \d+ %", a) and n > 0 for a, n in th) and how == 1,
                f"threads {th}, How threads work {how}")
        await w.snap(page, tag, "s50a-threads")
        # the student compare, stacked into cards on a phone
        if not wide:
            await serve(page, SB, student(raw_s, kept=2))
            shown = await open_brief(page, SB, "compare", "table.compare")
            got = await page.evaluate("""() => [...document.querySelectorAll('table.compare.stack tbody td')].filter((td) => td.offsetParent !== null && td.dataset.label).map((td) => {
              const r = td.getBoundingClientRect(); const cs = getComputedStyle(td); const b = getComputedStyle(td, '::before');
              const lab = r.top + parseFloat(cs.borderTopWidth) + parseFloat(cs.paddingTop) + parseFloat(b.paddingTop);
              const rg = document.createRange(); rg.selectNodeContents(td); const rs = [...rg.getClientRects()].filter((x) => x.height > 0);
              const val = rs.length ? Math.min(...rs.map((x) => x.top)) : null;
              const kid = td.firstElementChild; const kv = kid ? kid.getBoundingClientRect().top : val;
              return Math.round(Math.abs(lab - (kv ?? lab)) * 10) / 10; })""") if shown else []
            off = [x for x in got if x > 2]
            w.check("s50a_stack_labels", bool(got) and not off, f"{len(got)} cells; label and value tops apart by more than 2 px: {off[:6]}")
            await w.snap(page, tag, "s50a-student-compare")
        await page.context.close()

    # ---------- s50a_building ----------

    async def flow_building(w, browser, base, tag, view) -> None:
        raw_r, _ = cached()
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["researcher"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)
        live = {"status": "running"}

        def payload() -> dict:
            d = researcher(raw_r)
            b = d["brief"]
            b["status"] = live["status"]
            after = False
            for s in b["stages"]:
                if s["name"] == "route_a":
                    s.update(status="running" if live["status"] == "running" else "failed", finished_at=None, detail=None)
                    after = True
                elif after:
                    s.update(status="pending", started_at=None, finished_at=None, detail=None)
            if live["status"] == "failed":
                b["error"] = "SYNTHETIC: the job was cancelled."
            return d
        hits = await serve(page, RB, payload)
        await page.goto(base + "/")
        await page.wait_for_selector("h1")
        await page.evaluate("(id) => { location.hash = '#/brief/' + id + '/routes'; }", RB)
        try:
            await page.wait_for_selector(".pcard", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(800)
        got = await page.evaluate("""() => [Boolean(document.querySelector('.pcard')),
          document.querySelector('#panel') ? document.querySelector('#panel').innerText.includes('Leads appear here when the search finishes.') : false,
          Boolean(document.querySelector('[data-key=stop-brief]'))]""")
        await w.snap(page, tag, "s50a-building")
        w.check(f"s50a_building_{tag}", all(got), f"progress card {got[0]}, leads skeleton {got[1]}, Stop {got[2]}")
        stopped = None
        if got[2]:
            await page.click("[data-key=stop-brief]")
            await page.wait_for_timeout(300)
            live["status"] = "failed"
            for _ in range(20):
                await page.wait_for_timeout(250)
                stopped = await page.evaluate("() => { const c = document.querySelector('.pcard'); return c ? c.innerText : null; }")
                if stopped and "Stopped" in stopped:
                    break
            await w.snap(page, tag, "s50a-stopped")
        ok = hits["cancel"] == 1 and bool(stopped) and "Stopped" in stopped and "You stopped this brief." in stopped
        w.check(f"s50a_stop_{tag}", ok, f"cancel posts {hits['cancel']}, card {(stopped or '')[:120]!r}")
        await page.context.close()

    # ---------- s50a_example ----------

    async def flow_example(w, browser, base, tag, view) -> None:
        raw_r, _ = cached()
        ok_stub, missing_stub = example_stub(raw_r)
        wide = view["width"] >= 1280
        # the example page plays the file back and calls nothing
        page = await U.new_page(browser, w, tag, view, base)
        await page.route("**/example/*.json", ok_stub)
        seen: list[str] = []
        page.on("request", lambda r: seen.append(r.url))
        await page.goto(base + "/example.html")
        try:
            await page.wait_for_selector("#panel li.card.lead", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(600)
        got = await page.evaluate("""() => { const b = document.querySelector('#banner'); return [b && !b.hidden ? b.innerText : '',
          document.querySelectorAll('#panel li.card.lead').length, document.title]; }""")
        calls = [u for u in seen if re.search(r"/(briefs|auth/session|session|me)(/|\?|$)", u)]
        w.check(f"s50a_example_{tag}", "Example" in got[0] and "PI-4" in got[0] and got[1] > 0 and not calls,
                f"banner {got[0][:90]!r}, {got[1]} cards, title {got[2]!r}, calls {calls[:3]}")
        await w.snap(page, tag, "s50a-example")
        await page.goto(base + "/example.html?tab=scout")
        await page.wait_for_timeout(1500)
        await w.snap(page, tag, "s50a-example-scout")
        await page.context.close()
        # the landing link, with and without the file
        page = await U.new_page(browser, w, tag, {"width": 1280, "height": 720} if wide else view, base)
        await page.route("**/example/*.json", ok_stub)
        await page.goto(base + "/")
        await page.wait_for_selector(".landing h1")
        vis, fits = {}, []
        for who in ("r", "s"):
            await page.click(f"[data-key=seg-{who}]")
            await page.wait_for_timeout(400)
            vis[who] = await page.evaluate("() => { const a = document.querySelector('[data-key=example-brief]'); return a ? [a.offsetParent !== null, a.getAttribute('href')] : null; }")
            if wide:
                sh = await page.evaluate("[document.documentElement.scrollHeight, innerHeight]")
                fits.append(sh[0] <= sh[1])
            await w.snap(page, tag, f"s50a-landing-example-{who}", full=False)
        await page.context.close()
        page = await U.new_page(browser, w, tag, view, base)
        await page.route("**/example/*.json", missing_stub)
        await page.goto(base + "/")
        await page.wait_for_selector(".landing h1")
        await page.click("[data-key=seg-r]")
        await page.wait_for_timeout(500)
        gone = await page.locator("[data-key=example-brief]").count()
        ok = (vis["r"] and vis["r"][0] and vis["r"][1] == "example.html" and vis["s"] and vis["s"][0]
              and vis["s"][1] == "example.html?side=student" and gone == 0 and all(fits))
        w.check(f"s50a_example_link_{tag}", ok, f"researcher {vis['r']}, student {vis['s']}, with the file missing {gone} links, fits 1280x720 {fits}")
        # the example page with no file on the server
        await page.goto(base + "/example.html")
        await page.wait_for_timeout(1500)
        txt = await page.evaluate("() => document.querySelector('main') ? document.querySelector('main').innerText : ''")
        w.check(f"s50a_example_missing_{tag}", "The example is not on this server." in txt, f"main {txt[:80]!r}")
        await w.snap(page, tag, "s50a-example-missing")
        await page.context.close()

    # ---------- s50a_pick (Tier B: Q19, Q31, V32, Q13) ----------

    async def flow_pick(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["researcher"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)  # /me/docs answers one stored CV, id d1
        await page.goto(base + "/#/start")
        await page.wait_for_selector("[data-key=seg-r]")
        await page.click("[data-key=seg-r]")
        await page.fill("#q", U.AUTHOR)
        await page.click(".searchbox button[type=submit]")
        await page.wait_for_selector("[data-key=build], .cand button", timeout=60_000)
        if not await page.locator("[data-key=build]").count():
            await page.click(".cand button")
        await page.wait_for_selector("[data-key=build]")
        await page.wait_for_timeout(800)
        got = await page.evaluate("""() => { const cv = document.querySelector('.cv-docs input[type=checkbox]');
          const ex = [...document.querySelectorAll('.explain-check input')];
          return { cvTicked: cv ? cv.checked : null, explainIn: ex.length === 1 && Boolean(ex[0].closest('details.more-panel')),
            explainOn: ex.length ? ex[0].checked : null, foot: document.querySelectorAll('[data-key=build-foot]').length,
            footText: (document.querySelector('[data-key=build-foot]') || {}).textContent || null }; }""")
        ok = got["cvTicked"] is True and got["explainIn"] and got["explainOn"] is True and got["foot"] == 1 and got["footText"] == "Build brief"
        w.check(f"s50a_pick_{tag}", ok, f"{got}")
        await w.snap(page, tag, "s50a-pick")
        await page.context.close()

    return {"s50a_styles": flow_styles, "s50a_cards": flow_cards, "s50a_building": flow_building, "s50a_example": flow_example,
            "s50a_pick": flow_pick}, []
