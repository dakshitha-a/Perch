# ruff: noqa: E501, ANN001, ANN201, ANN202, ANN003  - walk flows hold inline JavaScript probes, like ux_walk.py
"""S50 walk flows owned by package FE-B (docs/design/S50_DESIGN.md section 3.4).

register(U) -> (flows, plants). `U` is the ux_walk module. Checks marked [mock] stub a route or call
a module directly with SYNTHETIC input, because the back-end fields they need (a failed brief, the
G8 words) may not be on the branch; QA re-runs them against the real routes after the merge.
"""

from __future__ import annotations

import json
import re

OFFICES = [{"key": "research_development", "name": "Research Development", "route": "A", "url": "https://example.invalid/rd"},
           {"key": "industry", "name": "SYNTHETIC Industry Office", "route": "B", "url": "https://example.invalid/ind"}]


async def ev(page, js, arg=None):
    """Run a module probe; a failure (a missing export, say) is a failed check, not a crashed flow."""
    try:
        return await page.evaluate(js, arg) if arg is not None else await page.evaluate(js)
    except Exception as e:  # noqa: BLE001
        return {"err": str(e)[:120]}


def register(U):  # noqa: N803 - the module handed in by the loader
    async def opp_stub(page) -> None:
        """Funding list: the first row gets a far-off date with a note, the second only page words."""
        async def route(r) -> None:
            resp = await r.fetch()
            data = await resp.json()
            items = data["groups"][0]["items"]
            if len(items) > 1:
                items[0].update(close_date="2076-10-05", close_date_note="SYNTHETIC proposals accepted anytime")
                items[1].update(close_date=None, close_date_note="SYNTHETIC rolling review by the sponsor")
            await r.fulfill(json=data)
        await page.route(re.compile(r".*/opportunities\?.*"), route)

    # ---------- lists, as a guest ----------
    async def flow_lists(w, browser, base, tag, view) -> None:
        phone = view["width"] < 600
        tops = {}
        for side, path in (("awards", "#/awards"), ("funding", "#/funding")):
            page = await U.new_page(browser, w, tag, view, base)
            if side == "funding":
                await opp_stub(page)
            await page.goto(base + "/" + path)
            await page.wait_for_selector("li.award-row", timeout=30_000)
            await page.wait_for_timeout(400)
            tops[side] = await page.evaluate("document.querySelector('.award-row').getBoundingClientRect().top")
            if phone:
                tog = page.locator("[data-key=filters]")
                if await tog.count():
                    await tog.click()
                    await page.wait_for_timeout(200)
                rows = await page.evaluate("[...new Set([...document.querySelectorAll('.tag-chip')].filter(e => e.offsetParent !== null).map(e => Math.round(e.getBoundingClientRect().top)))]")
                w.check(f"s50b_filters_one_row_{side}", await tog.count() == 1 and len(rows) == 1, f"toggle {await tog.count()}, distinct chip tops {rows}")
            sb = await page.evaluate("""() => { const b = document.querySelector('.searchbox'); const btn = b.querySelector('button[type=submit]');
              const r = b.getBoundingClientRect(), q = btn.getBoundingClientRect();
              const inside = q.left >= r.left - .5 && q.right <= r.right + .5 && q.top >= r.top - .5 && q.bottom <= r.bottom + .5;
              return { border: getComputedStyle(b).borderTopWidth, inside }; }""")
            w.check(f"s50b_search_button_{side}", sb["border"] == "0px" or not sb["inside"], f"searchbox border {sb['border']}, button inside box {sb['inside']}")
            lines = await page.evaluate("""() => [...document.querySelectorAll('.ar-facts dl')].map(dl => {
              const dt = [...dl.querySelectorAll('dt')].find(e => e.textContent === 'Amount'); const dd = dt && dt.nextElementSibling;
              if (!dd) return 0; const lh = parseFloat(getComputedStyle(dd).lineHeight) || 20; return dd.getBoundingClientRect().height / lh; })""")
            bad = [round(x, 1) for x in lines if x >= 1.6]
            w.check(f"s50b_amount_one_line_{side}", bool(lines) and not bad, f"{len(lines)} amounts, over one line: {bad[:4]}")
            # the title opens the record (regression for 5abe151)
            first_title = (await page.locator(".ar-title .title-btn span").first.inner_text()).strip()
            await page.locator(".ar-title .title-btn").first.click()
            ok = True
            try:
                await page.wait_for_selector("#evidence:not([hidden])", timeout=5000)
                body = await page.locator("#evidence-body").inner_text()
                ok = first_title in body
            except Exception:  # noqa: BLE001
                ok = False
            w.check(f"s50b_title_opens_evidence_{side}", ok, f"title {first_title[:50]!r}")
            if side == "funding":
                await page.keyboard.press("Escape")
                texts = await page.evaluate("[...document.querySelectorAll('.award-row')].slice(0, 2).map(e => e.querySelector('.ar-facts').textContent)")
                w.check("s50b_far_date", len(texts) > 1 and "SYNTHETIC proposals accepted anytime" in texts[0] and "2076" not in texts[0],
                        f"[mock] {texts[0][:90] if texts else ''!r}")
                w.check("s50b_page_words", len(texts) > 1 and "The page says: “SYNTHETIC rolling review by the sponsor”" in texts[1]
                        and await page.locator(".award-row .quote-date").count() >= 1, f"[mock] {texts[1][:120] if len(texts) > 1 else ''!r}")
                lv = await page.locator("#list-level").count()
                w.check("s50b_no_level_on_funding", lv == 0, f"{lv} level selects")
            await w.snap(page, tag, f"s50b-{side}")
            await page.context.close()
        if phone:
            w.check("s50b_phone_first_row", all(t < 640 for t in tops.values()), f"first row tops {tops} (limit 640)")

    # ---------- My Perch: a busy row can be stopped ----------
    async def flow_stop(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["researcher"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)
        row = {"record_id": "x", "id": "b2", "status": "running", "researcher_id": "you", "created_at": "2026-11-04T12:00:00", "leads": 3,
               "topics": ["SYNTHETIC topic"], "sample_leads": 0, "kept": 0, "sample_kept": 0}
        seen = {"cancels": 0}

        async def briefs(route) -> None:
            await route.fulfill(json=[row])

        async def cancel(route) -> None:
            seen["cancels"] += 1
            row["status"] = "failed"
            await route.fulfill(json={"id": "b2", "cancelled": True})

        async def saved(route) -> None:
            await route.fulfill(json={"audience": "researcher", "total": 0, "items": []})
        await page.route(re.compile(r".*/me/briefs(\?.*)?$"), briefs)
        await page.route(re.compile(r".*/briefs/b2/cancel$"), cancel)
        await page.route(re.compile(r".*/me/saved(\?.*)?$"), saved)
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/me'")
        await page.wait_for_selector(".brief-row", timeout=20_000)
        stop = page.locator("[data-key=stop-b2]")
        shown = await stop.count()
        before = (await page.locator(".brief-row").inner_text()) if shown else ""
        await w.snap(page, tag, "s50b-my-perch-busy")
        if shown:
            await stop.click()
            await page.wait_for_timeout(700)
        after = await page.locator(".brief-row").inner_text()
        w.check("s50b_stop_row", shown == 1 and "Still building" in before and seen["cancels"] == 1 and "Stopped" in after
                and await page.locator("[data-key=stop-b2]").count() == 0, f"[mock] stop shown {shown}, cancels {seen['cancels']}, after {after[:80]!r}")
        await w.snap(page, tag, "s50b-my-perch-stopped")
        await page.context.close()

    # ---------- module-level checks with SYNTHETIC input ----------
    async def flow_modules(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/")
        await page.wait_for_selector(".welcome, #app, main", timeout=30_000)
        # hand-off: Temple's own calls are not federal grants
        res = await ev(page, """async (offices) => {
          const { renderHandoff } = await import('/handoff.js');
          const box = document.createElement('div'); document.body.append(box);
          const lead = { id: 'T1', route: 'A', group: 'temple_internal', title: 'SYNTHETIC Temple call' };
          renderHandoff(box, { api: { exampleAvailable: async () => true }, briefId: 'bt', kept: [lead], offices, announce() {}, redraw() {}, guest: false, signIn: '#/' });
          const rd = box.querySelector('[data-key=office-research_development]');
          const line = box.querySelector('[data-key=temple-line]');
          const out = { disabled: rd ? rd.disabled : null, line: line ? line.textContent : null, vis: line ? line.offsetParent !== null : false,
            make: Boolean(box.querySelector('[data-key=handoff-make]')) };
          box.remove(); return out; }""", OFFICES)
        w.check("s50b_temple_handoff", res.get("disabled") is True and res.get("vis") and "Temple’s own calls name their contact on each call’s page." in (res.get("line") or ""), f"[mock] {res}")
        # hand-off: a guest's example link, only when the example exists
        ex = await ev(page, """async (offices) => {
          const { renderHandoff } = await import('/handoff.js');
          const mk = async (avail) => { const box = document.createElement('div'); document.body.append(box);
            renderHandoff(box, { api: { exampleAvailable: async () => avail }, briefId: 'bg', kept: [{ id: 'F1', route: 'A', title: 'SYNTHETIC grant' }], offices, announce() {}, redraw() {}, guest: true, signIn: '#/' });
            await new Promise((r) => setTimeout(r, 50));
            const a = box.querySelector('[data-key=example-draft]'); const o = { href: a ? a.getAttribute('href') : null, text: a ? a.textContent : null }; box.remove(); return o; };
          return { yes: await mk(true), no: await mk(false) }; }""", OFFICES)
        w.check("s50b_example_draft_link", (ex.get("yes") or {}).get("href") == "example.html?tab=compare" and ex["yes"]["text"] == "Or see an example draft" and ex["no"]["href"] is None, f"[mock] {ex}")
        # cover points: one hint above the list, none on the cards
        hint = await ev(page, """async () => {
          const { coverBlock, coverListLine, resetCover } = await import('/cover.js'); resetCover();
          const api = { mode: 'live', coverStart() {}, coverGet() {}, usage: async () => ({}) };
          const ctx = { api, announce() {}, openEvidence() {}, guest: false, signIn: '#/', audience: 'student', stored: [] };
          const box = document.createElement('div'); document.body.append(box);
          const line = coverListLine(ctx); if (line) box.append(line);
          for (const id of ['a', 'b', 'c']) box.append(coverBlock(ctx, 'bc', id));
          const n = (box.textContent.match(/A model writes these/g) || []).length; box.remove(); return n; }""")
        w.check("s50b_cover_hint_once", hint == 1, f"[mock] 'A model writes these' appears {hint} times")
        # cover points: consent is a step, not an error
        cons = await ev(page, """async () => {
          const { coverBlock, resetCover } = await import('/cover.js'); resetCover();
          const err = Object.assign(new Error('x'), { status: 403, code: 'consent_required' });
          const api = { mode: 'live', coverStart: async () => { throw err; }, coverGet() {}, usage: async () => ({}) };
          const ctx = { api, announce() {}, openEvidence() {}, guest: false, signIn: '#/', audience: 'student', stored: [] };
          const box = document.createElement('div'); document.body.append(box);
          box.append(coverBlock(ctx, 'bc', 'a')); box.querySelector('button').click();
          await new Promise((r) => setTimeout(r, 2600));
          const n = box.querySelector('.notice'); const o = { cls: n ? n.className : '', text: n ? n.textContent : '', link: n && n.querySelector('a.btn') ? n.querySelector('a.btn').textContent : '' };
          box.remove(); return o; }""")
        w.check("s50b_cover_consent_step", "info" in cons.get("cls", "") and "error" not in cons.get("cls", "") and "need your consent first" in cons.get("text", "") and cons.get("link") == "Read and agree", f"[mock] {cons}")
        # scout: record chips read by title, never by one shared word
        chips = await ev(page, """async () => {
          const { scoutAnswer } = await import('/scout.js');
          const ids = ['nih:1', 'nih:2', 'nih:3'];
          const ctx = { openEvidence() {}, announce() {}, label: (id) => ({ text: 'Evidence', full: 'SYNTHETIC Program number ' + id.slice(-1) + ' with a long title that runs past the limit', name: 'x' }) };
          const x = { status: 'done', cards: [], answer: 'SYNTHETIC answer', message: { flagged: true, withheld_all: true, read: ids } };
          const node = scoutAnswer(x, ctx, false); document.body.append(node);
          const labels = [...node.querySelectorAll('.scout-records .cite')].map((b) => b.textContent); node.remove(); return labels; }""")
        w.check("s50b_scout_chips", isinstance(chips, list) and len(chips) == 3 and len(set(chips)) == 3 and not any(c.strip() == "Evidence" for c in chips) and all(len(c) <= 33 for c in chips), f"[mock] {chips}")
        # scout: the guest's example link
        sc = await ev(page, """async () => {
          const { renderScout } = await import('/scout.js');
          const mk = async (avail) => { const panel = document.createElement('div'); document.body.append(panel);
            const api = { scoutStart() {}, exampleAvailable: async () => avail };
            renderScout(panel, { api, briefId: 'sg', done: true, student: false, signedIn: false, signIn: '#/', openEvidence() {}, announce() {}, label: () => null });
            await new Promise((r) => setTimeout(r, 50));
            const a = panel.querySelector('[data-key=example-scout]'); const o = { href: a ? a.getAttribute('href') : null, text: a ? a.textContent : null }; panel.remove(); return o; };
          return { yes: await mk(true), no: await mk(false) }; }""")
        w.check("s50b_example_scout_link", (sc.get("yes") or {}).get("href") == "example.html?tab=scout" and sc["yes"]["text"] == "Or see an example answer" and sc["no"]["href"] is None, f"[mock] {sc}")
        await page.context.close()

    # ---------- Help ----------
    async def flow_help(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/#/help")
        await page.wait_for_selector("article.help h1", timeout=20_000)
        await page.wait_for_timeout(300)
        text = await page.locator("article.help").inner_text()
        figs = await page.locator("article.help .anatomy figure").count()
        need = ["Keep, Dismiss and Cover-letter points sit in the card’s bottom row.", "A check mark means the rule was met", "Closing soonest puts the nearest date first",
                "See an example brief opens a saved brief", "press Stop", "On a phone, Filters opens the level, sort and school choices.",
                "A note to Research Development lists kept federal grants only.", "One line above the list says how points are written.",
                "one note above the list says so, and those cards show no reason."]
        missing = [n for n in need if n not in text.replace("\n", " ")]
        w.check("s50b_help", figs == 1 and not missing and "Ready · 0 s" not in text, f"anatomy figures {figs}, missing {[m[:30] for m in missing]}")
        s = await w.snap(page, tag, "s50b-help")
        w.check("s50b_help_axe", not s["axe"], f"axe {str(s['axe'])[:80]}")
        await page.context.close()

    flows = {"s50b_lists": flow_lists, "s50b_stop": flow_stop, "s50b_modules": flow_modules, "s50b_help": flow_help}
    return flows, []
