# ruff: noqa: E501, ANN001, ANN201, ANN202, ANN003  - walk flows hold inline JavaScript probes, like ux_walk.py
"""S51 walk flows owned by package FE-B (docs/design/S51_DESIGN.md section 3.5).

register(U) -> (flows, plants). `U` is the ux_walk module. Checks marked [mock] stub a route or call
a module directly with SYNTHETIC input, because the back-end fields they need (accounts_open, the
budget stage detail) may not be on the branch; QA re-runs them against the real routes after the merge.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BUDGET = {"name": "student_explanations", "status": "skipped", "detail": "withheld: the daily model budget is used"}


async def ev(page, js, arg=None):
    """Run a module probe; a failure is a failed check, not a crashed flow."""
    try:
        return await page.evaluate(js, arg) if arg is not None else await page.evaluate(js)
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)[:160]}


def register(U):  # noqa: N803 - the module handed in by the loader
    # ---------- B1: Load sample leaves the canary out of the boxes; Save puts it back ----------
    async def flow_sample_canary(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["student"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)
        posted: list[dict] = []

        async def docs(route) -> None:
            if route.request.method == "POST":
                posted.append(json.loads(route.request.post_data or "{}"))
                return await route.fulfill(status=201, json={"id": f"d{len(posted)}", "kind": "x", "label": "x", "chars": 9})
            await route.fulfill(json=[])

        await page.route(re.compile(r".*/me/docs(\?.*)?$"), docs)
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/student'")
        await page.wait_for_selector("#cv-text", timeout=20_000)
        await page.click("[data-key=load-sample]")
        vals = [await page.input_value(s) for s in ("#cv-text", "#st-interests", "#st-ach")]
        await w.snap(page, tag, "s51b-sample-no-canary")
        await page.click("[data-key=cv-save]")
        await page.wait_for_timeout(600)
        cv = next((p for p in posted if p.get("kind") == "cv"), {})
        ok = (not any("PERCH-CANARY" in v for v in vals) and all(v.startswith("SYNTHETIC example student (invented).") for v in vals)
              and "SYNTHETIC example student (invented). Canary: PERCH-CANARY-UG-CV-3R8D" in (cv.get("text") or ""))
        w.check("s51b_sample_no_canary", ok, f"[mock] boxes hold a canary {[('PERCH-CANARY' in v) for v in vals]}, saved text starts {(cv.get('text') or '')[:90]!r}")
        await page.context.close()

    # ---------- B2: while accounts are closed the walls lead with the example ----------
    async def flow_walls_closed(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/#/help")
        await page.wait_for_selector("article.help h1", timeout=20_000)
        res = await ev(page, """async () => {
          const { renderScout } = await import('/scout.js');
          const { renderHandoff } = await import('/handoff.js');
          const { coverListLine } = await import('/cover.js');
          const offices = [{ key: 'research_development', name: 'Research Development', route: 'A', url: 'https://example.invalid/rd' }];
          const wait = () => new Promise((r) => setTimeout(r, 80));
          const first = (el) => { const b = el.querySelector('.btn.primary'); return b ? b.getAttribute('data-key') : null; };
          const out = {};
          const panel = document.createElement('div'); panel.id = 'wall-s'; document.body.append(panel);
          renderScout(panel, { api: { scoutStart() {}, exampleAvailable: async () => true }, briefId: 'w1', done: true, student: false, signedIn: false, signIn: '#/signin', accountsOpen: false, openEvidence() {}, announce() {}, label: () => null });
          await wait();
          out.scout = { primary: first(panel), href: (panel.querySelector('[data-key=example-scout]') || {}).href, signinPrimary: Boolean(panel.querySelector('a.btn.primary[href="#/signin"]')) };
          const box = document.createElement('div'); box.id = 'wall-h'; document.body.append(box);
          renderHandoff(box, { api: { exampleAvailable: async () => true }, briefId: 'w2', kept: [{ id: 'F1', route: 'A', title: 'SYNTHETIC grant' }], offices, announce() {}, redraw() {}, guest: true, signIn: '#/signin', accountsOpen: false });
          await wait();
          out.hand = { primary: first(box), signinPrimary: Boolean(box.querySelector('a.btn.primary[href="#/signin"]')) };
          const line = coverListLine({ api: { mode: 'live', coverStart() {} }, guest: true, signIn: '#/signin', audience: 'student', accountsOpen: false });
          out.cover = line ? line.textContent : null;
          const open = document.createElement('div'); open.id = 'wall-o'; document.body.append(open);
          renderScout(open, { api: { scoutStart() {}, exampleAvailable: async () => true }, briefId: 'w3', done: true, student: false, signedIn: false, signIn: '#/signin', openEvidence() {}, announce() {}, label: () => null });
          out.open = first(open);
          return out; }""")
        s, hd = res.get("scout") or {}, res.get("hand") or {}
        ok = (s.get("primary") == "example-scout" and (s.get("href") or "").endswith("example.html?tab=scout") and not s.get("signinPrimary")
              and hd.get("primary") == "example-draft" and not hd.get("signinPrimary")
              and res.get("cover") == "Cover-letter points need an account, and accounts are not open yet." and res.get("open") == "scout-signin")
        w.check("s51b_walls_closed", ok, f"[mock] {json.dumps(res)[:300]}")
        await ev(page, "() => { document.getElementById('wall-h').scrollIntoView(); }")
        await w.snap(page, tag, "s51b-walls-closed")
        await page.context.close()

    # ---------- B3: the student list: budget line, unsupported fold, entry labels ----------
    async def student_page(w, browser, base, tag, view, budget, text):
        body = json.loads((Path(__file__).parent / "s49_student_brief.json").read_text())
        if budget:
            body["brief"]["stages"].append(dict(BUDGET))
        for x in body["leads"]:
            x["flagged"] = bool(x["flagged"]) and not budget
        if text:
            body["leads"][0]["flagged"] = False
            body["leads"][0].update(explanation="SYNTHETIC listing text. Matches user:achievement-a and user:interests.", inference="SYNTHETIC reading of the fit.",
                                    unsupported=["SYNTHETIC unsupported sentence one.", "SYNTHETIC unsupported sentence two."])
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["student"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)

        async def brief(route) -> None:
            path = route.request.url.split("?")[0]
            if route.request.method == "GET" and path.endswith("/briefs/b1"):
                return await route.fulfill(json=body)
            if "/briefs/b1/" in path:
                return await route.fulfill(status=404, json={"detail": "not in this walk"})
            await route.continue_()

        await page.route("**/briefs/b1**", brief)
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/brief/b1/routes'")
        await page.wait_for_selector("#panel .lead", timeout=30_000)
        await page.wait_for_timeout(500)
        return page

    async def flow_student_budget(w, browser, base, tag, view) -> None:
        page = await student_page(w, browser, base, tag, view, True, None)
        b = await page.locator("#panel [data-budget]").count()
        n = await page.locator("#panel [data-withheld]").count()
        first = await page.evaluate("() => { const n = document.getElementById('list-notices'); return n && n.firstElementChild ? n.firstElementChild.hasAttribute('data-budget') : null; }")
        w.check("s51b_student_budget", b == 1 and n == 0 and first is True, f"[mock] {b} budget lines, {n} withheld notes, budget first {first}")
        await w.snap(page, tag, "s51b-student-budget")
        await page.context.close()

    async def flow_student_fold(w, browser, base, tag, view) -> None:
        page = await student_page(w, browser, base, tag, view, False, "plain")
        fold = page.locator("#panel .lead details.unsupported-fold")
        n = await fold.count()
        label = (await fold.first.locator("summary[data-key=unsupported]").inner_text()).strip() if n else ""
        amber = await page.locator("#panel .lead .notice.warn").count()
        opened = await page.locator("#panel .lead details.unsupported-fold[open]").count()
        why = (await page.locator("#panel .lead").first.inner_text()) if await page.locator("#panel .lead").count() else ""
        w.check("s51b_student_fold", n == 1 and label == "2 sentences could not be matched to their source" and amber == 0 and opened == 0
                and "one of your entries" in why.lower() and "your achievement A" not in why, f"[mock] folds {n}, label {label!r}, amber {amber}")
        await w.snap(page, tag, "s51b-student-fold")
        await page.context.close()

    # ---------- B5: Run again sits in the same place on a busy row and on a done row ----------
    async def flow_myperch_order(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["researcher"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)

        def mk(i, status):
            return {"record_id": "x", "id": i, "status": status, "researcher_id": "you", "created_at": "2026-11-04T12:00:00", "leads": 3,
                    "topics": ["SYNTHETIC topic"], "sample_leads": 0, "kept": 0, "sample_kept": 0}

        async def briefs(route) -> None:
            await route.fulfill(json=[mk("b-busy", "running"), mk("b-done", "done")])

        async def saved(route) -> None:
            await route.fulfill(json={"audience": "researcher", "total": 0, "items": []})
        await page.route(re.compile(r".*/me/briefs(\?.*)?$"), briefs)
        await page.route(re.compile(r".*/me/saved(\?.*)?$"), saved)
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/me'")
        await page.wait_for_selector(".brief-row", timeout=20_000)
        pos = await page.evaluate("""() => [...document.querySelectorAll('.brief-row')].map((r) => {
          const a = [...r.querySelectorAll('.brief-acts > *')]; const run = r.querySelector('a.quiet-link'); const stop = r.querySelector('[data-key^=stop-]');
          return { id: r.dataset.id, x: run ? Math.round(run.getBoundingClientRect().x) : null, text: run ? run.textContent.trim() : null, aria: run ? run.getAttribute('aria-label') : null,
                   order: a.map((e) => e.textContent.trim().split(' ')[0]), stopAfter: stop ? a.indexOf(run) < a.indexOf(stop) : null }; })""")
        busy = next((p for p in pos if p["id"] == "b-busy"), {})
        done = next((p for p in pos if p["id"] == "b-done"), {})
        phone = view["width"] < 600
        same = True if phone else busy.get("x") == done.get("x")  # on a phone the row wraps; the order still holds
        ok = (same and busy.get("text") == "Run again" and busy.get("aria") == "Change details and run again" and busy.get("stopAfter") is True
              and busy.get("order", [])[:3] == ["Open", "Run", "Stop"])
        w.check("s51b_myperch_order", ok, f"[mock] busy {busy}, done {done}")
        await w.snap(page, tag, "s51b-my-perch-order")
        await page.context.close()

    # ---------- B4: the cover list lines ----------
    async def flow_cover_lines(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/#/help")
        await page.wait_for_selector("article.help h1", timeout=20_000)
        res = await ev(page, """async () => {
          const { coverListLine } = await import('/cover.js');
          const api = { mode: 'live', coverStart() {} };
          const t = (ctx) => { const l = coverListLine(ctx); return l ? l.textContent : null; };
          return { sample: t({ api, guest: false, signIn: '#/', audience: 'student', sample: true }),
                   own: t({ api, guest: false, signIn: '#/', audience: 'student', sample: false }) }; }""")
        w.check("s51b_cover_sample_line", res.get("sample") == "A model writes these from the sample student's CV and entries. You put them in your own words."
                and res.get("own") == "A model writes these from your CV and entries. You put them in your own words.", f"[mock] {res}")
        await page.context.close()

    flows = {"s51b_sample_canary": flow_sample_canary, "s51b_walls_closed": flow_walls_closed, "s51b_student_budget": flow_student_budget,
             "s51b_student_fold": flow_student_fold, "s51b_myperch_order": flow_myperch_order, "s51b_cover_lines": flow_cover_lines}
    return flows, []
