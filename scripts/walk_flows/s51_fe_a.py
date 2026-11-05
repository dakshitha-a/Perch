# ruff: noqa: E501, ANN001, ANN202 - inline JavaScript probes and Playwright callbacks, as in scripts/ux_walk.py
"""S51 walk checks owned by package FE-A (docs/design/S51_DESIGN.md section 3.4).

Flows (loaded by scripts/ux_walk.py):
  s51a_example   the example page's banner on a phone (A1, W1) and the done progress card (W2)
  s51a_brief     a guest on the stubbed PI-4 brief: the chip row on a phone (W11), the centre
                 fold (H7 front end), the fit verdict on the card's face (W13), the unsupported
                 fold (W19) and the budget line (D16)
  s51a_stopped   a stubbed signed-in researcher whose brief builds, then stops: Run again once (W5)
  s51a_landing   a stubbed session with accounts closed (D4)

Every brief is the cached payload under build/s49_fe_a/cache (built by the s49a flows), served
from a stubbed GET /briefs/<id> with SYNTHETIC changes. Nothing here is sent anywhere.

Stubbed back-end contracts (S51 3.2): `group: "centre"` and its note, and `accounts_open` on
/auth/session. The checks s51a_centre_fold and s51a_accounts_closed rely on those stubs.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

CACHE = Path(__file__).resolve().parents[2] / "build" / "s49_fe_a" / "cache"
RB = "aaaaaaaa-0000-4000-8000-0000000000c1"  # stub id for the researcher brief
CENTRE_NOTE = ("Centre or programme grant (activity code P30). An institution applies for these for a centre or a group of projects, "
               "so Perch lists them below the single-lab grants.")
BUDGET = "withheld: the daily model budget is used"
# Visible buttons and links whose own text is exactly "Run again" (the hint sentence does not count).
RUN_AGAIN = """() => [...document.querySelectorAll('button, a')].filter((e) => {
  const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'
    && e.textContent.trim() === 'Run again'; }).length"""


def register(U) -> tuple[dict, list]:  # noqa: C901 - one walk module, flows as closures over U
    def cached() -> dict:
        rp = CACHE / "researcher.json"
        if not rp.is_file():
            raise RuntimeError("run the s49a_brief flow once to build the cached briefs")
        return json.loads(rp.read_text())

    def a_leads(d: dict) -> list:
        return sorted([x for x in d["leads"] if (x.get("route") or "A") == "A" and x.get("group") != "temple_internal"],
                      key=lambda x: x.get("rank", 0))

    def paper_ids(d: dict) -> list[str]:
        return [k.rsplit("/", 1)[-1] for k in (d.get("papers") or {}) if re.search(r"W\d+$", k)]

    def researcher(raw: dict, explained: bool = False, centre: bool = False, budget: bool = False) -> dict:
        d = copy.deepcopy(raw)
        d["brief"]["id"] = RB
        d["brief"]["status"] = "done"
        for s in d["brief"]["stages"]:
            s["started_at"] = s["finished_at"] = "2026-11-05T04:42:55.852147Z"
            if s["name"] == "explanations":
                s.update(status="skipped", detail=BUDGET) if budget else s.update(status="done", detail="SYNTHETIC: 3 explained")
        a = a_leads(d)
        for x in d["leads"]:
            x.update(explanation=None, inference=None, unsupported=[], flagged=False)
        if explained:  # SYNTHETIC reasons on the top three cards, the first with an unsupported sentence
            ws = paper_ids(d)[:2] or ["W1"]
            for i, x in enumerate(a[:3]):
                x["explanation"] = (f"SYNTHETIC: the call funds research on molecular simulation methods. Cited work: {ws[0]} reported "
                                    f"SYNTHETIC simulation results in its abstract; {ws[-1]} described SYNTHETIC methods in its abstract.")
                x["inference"] = f"SYNTHETIC: your simulation papers [{ws[0]}] sit close to what this call funds."
                x["cited_ids"] = list(dict.fromkeys(ws))
                x["match_score"] = max(x.get("match_score") or 0, 60 - i * 5)
            a[0]["unsupported"] = ["SYNTHETIC: this sentence could not be matched to its source."]
        if centre and len(a) > 2:  # the second lead is a centre grant (BE contract 3.2, stubbed)
            c = a[1]
            c["group"] = "centre"
            c["notes"] = [CENTRE_NOTE]
            c["opportunity"]["activity_code"] = "P30"
            c["opportunity"]["title"] = "SYNTHETIC Centre core grant " + c["id"][-4:]
        return d

    async def serve(page, payload) -> dict:
        hits = {"cancel": 0}

        async def handle(route) -> None:
            if route.request.url.rstrip("/").endswith("/cancel"):
                hits["cancel"] += 1
                return await route.fulfill(json={"id": RB, "cancelled": True})
            if route.request.method != "GET":
                return await route.fulfill(json={"status": "kept"})
            await route.fulfill(json=payload() if callable(payload) else payload)
        await page.unroute(re.compile(rf".*/briefs/{RB}(/cancel)?(\?.*)?$"))
        await page.route(re.compile(rf".*/briefs/{RB}(/cancel)?(\?.*)?$"), handle)
        return hits

    async def guest_page(w, browser, base, tag, view):
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/")
        await page.click("[data-key=seg-r]")
        await page.click("[data-key=guest-start]")
        await page.wait_for_selector("[data-key=guest-banner]")
        return page

    async def open_brief(page, ready: str = "#panel li.card.lead") -> bool:
        await page.evaluate("location.hash = '#/'")
        await page.wait_for_selector(".landing h1, #acct-title")
        await page.evaluate("(id) => { location.hash = '#/brief/' + id + '/routes'; }", RB)
        try:
            await page.wait_for_selector(ready, timeout=20_000)
        except Exception:  # noqa: BLE001 - a screen that never draws is a failed check, not a crash
            return False
        await page.wait_for_timeout(600)
        await page.evaluate("window.scrollTo(0, 0)")
        return True

    # ---------- s51a_example ----------

    async def flow_example(w, browser, base, tag, view) -> None:
        body = {"version": 2, "brief": researcher(cached()), "candidates": [{"display_name": "PI-4"}], "records": {}}

        async def ok(route) -> None:
            await route.fulfill(json=body)
        page = await U.new_page(browser, w, tag, view, base)
        await page.route("**/example/*.json", ok)
        await page.goto(base + "/example.html")
        try:
            await page.wait_for_selector("#panel li.card.lead", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(600)
        if view["width"] < 600:
            got = await page.evaluate("""() => { const s = document.querySelector('[data-key=example-banner] > span:not(.tag)');
              return s ? Math.round(s.getBoundingClientRect().width) : null; }""")
            w.check("s51a_example_banner_w360", got is not None and got >= 300, f"banner text width {got} px")
        await w.snap(page, tag, "s51a-example", full=False)
        await page.context.close()

    # ---------- s51a_brief ----------

    async def flow_brief(w, browser, base, tag, view) -> None:
        raw = cached()
        phone = view["width"] < 600
        page = await guest_page(w, browser, base, tag, view)
        # the budget line (D16): the explanations stage was skipped by the model budget
        await serve(page, researcher(raw, budget=True))
        await open_brief(page)
        await w.snap(page, tag, "s51a-budget", full=False)
        if phone:
            tops = await page.evaluate("() => [...document.querySelectorAll('.filter-box .filter-chips > *')].filter((c) => c.offsetParent !== null).map((c) => c.offsetTop)")
            w.check("s51a_brief_chips_one_row_w360", len(tops) >= 3 and len(set(tops)) == 1, f"{len(tops)} chips, offsetTop values {sorted(set(tops))}")
        # the verdict on the face (W13), the unsupported fold (W19) and the centre fold (H7)
        await serve(page, researcher(raw, explained=True, centre=True))
        shown = await open_brief(page)
        face = await page.evaluate("""() => { const c = document.querySelector('#panel ol.leads > li.card.lead'); if (!c) return null;
          const f = c.querySelector('.fit-why'); const d = c.querySelector('details.why');
          return [Boolean(f && f.getBoundingClientRect().height > 0), d ? d.open : null, f ? f.textContent.slice(0, 60) : null]; }""") if shown else None
        w.check(f"s51a_fit_on_face_{tag}", bool(face) and face[0] and face[1] is False and face[2].startswith("Why it fits:"),
                f"fit line visible, details open, text: {face}")
        await w.snap(page, tag, "s51a-fit-face", full=False)
        top = await page.evaluate("() => [...document.querySelectorAll('#panel > ol.leads > li.card.lead')].map((c) => c.textContent.includes('SYNTHETIC Centre core grant'))")
        fold = await page.evaluate("""() => { const d = document.querySelector('#panel details.centre-fold'); if (!d) return null;
          return [d.querySelector('summary').textContent.trim(), d.open, d.querySelectorAll('li.card.lead').length]; }""")
        note = None
        if fold:
            await page.click("#panel details.centre-fold > summary")
            await page.wait_for_timeout(300)
            note = await page.evaluate("""() => { const c = document.querySelector('#panel details.centre-fold li.card.lead');
              const n = c && c.querySelector('.lead-notes'); return n ? [n.textContent, n.getBoundingClientRect().height > 0] : null; }""")
            await page.evaluate("() => { const n = document.querySelector('#panel details.centre-fold .lead-notes'); if (n) n.scrollIntoView({ block: 'center' }); }")
            await page.wait_for_timeout(200)
            await w.snap(page, tag, "s51a-centre-fold", full=False)
        ok = (bool(top) and not any(top) and bool(fold) and fold[0] == "Centre and programme grants (1)" and fold[1] is False
              and fold[2] == 1 and bool(note) and "Centre or programme grant (activity code P30)" in note[0] and note[1])
        w.check(f"s51a_centre_fold_{tag}", ok, f"centre card in the top list {any(top) if top else None}, fold {fold}, note {(note or [''])[0][:50]!r}")
        # the unsupported fold on the first card, opened
        if await page.locator("#panel ol.leads > li.card.lead details.why > summary").count():
            await page.locator("#panel ol.leads > li.card.lead details.why > summary").first.click()
            await page.wait_for_timeout(300)
            uf = page.locator("#panel details.unsupported-fold > summary").first
            if await uf.count():
                await uf.click()
                await page.wait_for_timeout(200)
                await uf.scroll_into_view_if_needed()
            await w.snap(page, tag, "s51a-card-open", full=False)
        await w.snap(page, tag, "s51a-brief")
        await page.context.close()

    # ---------- s51a_stopped ----------

    async def flow_stopped(w, browser, base, tag, view) -> None:
        raw = cached()
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["researcher"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)
        live = {"status": "running"}

        def payload() -> dict:
            d = researcher(raw)
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
        await serve(page, payload)
        await page.goto(base + "/")
        await page.wait_for_selector("h1")
        await page.evaluate("(id) => { location.hash = '#/brief/' + id + '/routes'; }", RB)
        try:
            await page.wait_for_selector("[data-key=stop-brief]", timeout=15_000)
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(800)
        building = await page.evaluate(RUN_AGAIN)
        await w.snap(page, tag, "s51a-building", full=False)
        stopped, skel = None, None
        if await page.locator("[data-key=stop-brief]").count():
            await page.click("[data-key=stop-brief]")
            live["status"] = "failed"
            for _ in range(20):
                await page.wait_for_timeout(250)
                txt = await page.evaluate("() => { const c = document.querySelector('.pcard'); return c ? c.innerText : ''; }")
                if "Stopped" in txt:
                    break
            await page.wait_for_timeout(300)
            stopped = await page.evaluate(RUN_AGAIN)
            skel = await page.locator("#panel .skeleton").count()
            await w.snap(page, tag, "s51a-stopped", full=False)
        w.check(f"s51a_stopped_once_{tag}", building == 0 and stopped == 1 and skel == 0,
                f"Run again while building {building}, after the stop {stopped}; skeletons in the panel after the stop {skel}")
        await page.context.close()

    # ---------- s51a_landing ----------

    async def flow_landing(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)

        async def closed(route) -> None:
            await route.fulfill(json={"signed_in": False, "accounts_open": False})
        await page.route("**/auth/session", closed)
        await page.goto(base + "/")
        await page.wait_for_selector(".landing h1")
        await page.click("[data-key=seg-s]")
        await page.wait_for_timeout(400)
        got = await page.evaluate("""() => { const b = document.querySelector('[data-key=fit]'); const s = document.querySelector('#sign-in');
          return [b ? b.tagName : null, b ? b.textContent.trim() : null, Boolean(s && s.getBoundingClientRect().width > 0),
            document.querySelectorAll('[data-key=guest-start]').length]; }""")
        w.check(f"s51a_accounts_closed_{tag}", got[0] == "BUTTON" and got[1] == "Try a sample student" and got[2] and got[3] == 0,
                f"fit {got[0]} {got[1]!r}, header Sign in visible {got[2]}, guest lines {got[3]}")
        await w.snap(page, tag, "s51a-landing-closed", full=False)
        await page.click("[data-key=seg-r]")
        await page.wait_for_timeout(300)
        await w.snap(page, tag, "s51a-landing-closed-r", full=False)
        await page.context.close()

    return {"s51a_example": flow_example, "s51a_brief": flow_brief, "s51a_stopped": flow_stopped, "s51a_landing": flow_landing}, []
