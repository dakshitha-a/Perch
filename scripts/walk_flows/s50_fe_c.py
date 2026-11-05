# ruff: noqa: ANN001, ANN202, E501  (walk flow: inline JavaScript probes, flows take the ux_walk objects)
"""S50 walk flows owned by package FE-C (docs/design/S50_DESIGN.md, section 3.5): the student cards.

Loaded by scripts/ux_walk.py. The student brief is the SYNTHETIC fixture of S49 with changes made
here in code (a copy, never the original). STUB: `checks` is a back-end field that may not be on
this branch, so the checks that read it (s50c_checks, s50c_compare_checks) feed it from the flow.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

FIXED = "The listing says who may apply; the award's own page sets the full rules. Read it before applying."
CANARY_TEXT = "SYNTHETIC interests note about stream ecology. Canary: PERCH-CANARY-UG-INT-6W1J"
STUB_CHECKS = [{"rule": "level", "outcome": "pass", "text": "Level: open to undergraduates; your CV says bachelor's."},
               {"rule": "deadline", "outcome": "unknown", "text": "Deadline: the listing does not state one."}]


def register(U):  # noqa: ANN001, ANN201, N803 - the ux_walk module, passed by its loader
    base_body = json.loads((Path(__file__).parent / "s49_student_brief.json").read_text())

    def variant(kind: str, kept: tuple = ()) -> dict:
        body = copy.deepcopy(base_body)
        leads = body["leads"]
        if kind == "plant":  # one sentence on every card, the GPA line stays on two
            for x in leads:
                x["verdict_lines"] = [FIXED, *x["verdict_lines"]]
        if kind == "checks":
            leads[0]["checks"] = STUB_CHECKS
        if kind == "extras":
            leads[1]["unsupported"] = ["Invented sentence the check could not match."]
            leads[4]["record"].update({"source": "temple_sdfa", "deadline": None, "deadline_quote": None,
                                       "amount_min": None, "amount_max": None})
            body["papers"] = {"user:interests": {"title": "Your interests", "text": CANARY_TEXT, "source": "user", "kind": "user"},
                              "user:achievement-a": {"title": "Poster", "text": "Presented a poster. Canary: PERCH-CANARY-UG-ACH-9K2T", "source": "user", "kind": "user"}}
        for x in leads:
            if x["id"] in kept:
                x["status"] = "kept"
        return body

    async def open_brief(w, browser, base, tag, view, state):
        page = await U.new_page(browser, w, tag, view, base)
        st = {"roles": ["student"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, st)

        async def brief(route):
            path = route.request.url.split("?")[0]
            if route.request.method == "GET" and path.endswith("/briefs/b1"):
                return await route.fulfill(json=variant(state["kind"], state.get("kept", ())))
            if "/briefs/b1/" in path:
                return await route.fulfill(status=404, json={"detail": "not in this walk"})
            await route.continue_()

        async def record(route):
            url = route.request.url.replace("%3A", ":")
            lead = next(x for x in base_body["leads"] if x["record_id"] in url)
            await route.fulfill(json=lead["record"])

        await page.route("**/briefs/b1**", brief)
        await page.route("**/records/**", record)
        await page.goto(base + "/")
        return page

    async def go(page, hash_, sel):
        await page.evaluate(f"location.hash = '{hash_}'")
        await page.reload()
        await page.wait_for_selector(sel, timeout=30_000)
        await page.wait_for_timeout(500)

    async def flow_student_cards(w, browser, base, tag, view):
        state = {"kind": "plain"}
        page = await open_brief(w, browser, base, tag, view, state)
        await go(page, "#/brief/b1/routes", "#panel .lead")
        await w.snap(page, tag, "s50c-student-list")
        widths = await page.evaluate("() => [...document.querySelectorAll('#panel ol.leads > li.lead .lead-title')].map((e) => Math.round(e.getBoundingClientRect().width))")
        wide = view["width"] >= 600
        w.check("s50c_title_width", bool(widths) and (not wide or min(widths) >= 600), f"{view['width']} px: titles {widths}")
        routes = await page.locator("#panel [data-key^=route-]").count()
        w.check("s50c_single_route", routes == 0, f"{routes} route buttons on a brief with route F only")
        mix = await page.locator("#panel .lead .lead-end").count() + await page.locator("#panel .lead .reason b", has_text="To check").count()
        w.check("s50c_no_verdict_label", mix == 0, f"{mix} old lead-end or 'To check:' labels")
        sel = await page.evaluate("() => { const s = document.querySelector('#sort-pick'); return s ? [s.tagName, [...s.options].map((o) => o.value).join()] : null; }")
        w.check("s50c_sort_select", sel == ["SELECT", "order,closing"], f"{sel}")
        notes = await page.locator("#panel [data-withheld]").count()
        lines = await page.locator("#panel .lead .withheld-line").count()
        w.check("s50c_withheld_once", notes == 1 and lines == 0, f"{notes} list notes, {lines} card lines")
        first = (await page.locator("#panel ol.leads > li.lead .title-btn").first.inner_text()).strip().split("\n")[0]
        await page.locator("#panel ol.leads > li.lead .title-btn").first.click()
        target = "#rail-ev" if wide else "#evidence"
        await page.wait_for_timeout(1500)
        shown = await page.inner_text(target)
        w.check("s50c_title_opens_evidence", first in shown, f"{target} shows {shown[:60]!r} for {first!r}")
        await page.context.close()

    async def flow_student_rules(w, browser, base, tag, view):
        state = {"kind": "plant"}
        page = await open_brief(w, browser, base, tag, view, state)
        await go(page, "#/brief/b1/routes", "#panel .lead")
        on_cards = await page.locator("#panel .lead", has_text=FIXED).count()
        in_notes = await page.locator("#list-notices", has_text=FIXED).count()
        shared = await page.locator("#list-notices [data-shared-rule]").count()
        gpa = await page.locator("#panel .lead", has_text="asks for a GPA").count()
        w.check("s50c_no_repeat", on_cards == 0 and in_notes == 1 and shared == 1 and gpa == 2,
                f"{on_cards} cards with the sentence, {in_notes} list note, {shared} shared notes, GPA line on {gpa} cards")
        await w.snap(page, tag, "s50c-student-shared-rule")
        state["kind"] = "checks"
        await go(page, "#/brief/b1/routes", "#panel .lead")
        got = await page.evaluate("""() => { const c = document.querySelector('#panel .lead[data-id="b1:1"]');
          return [...c.querySelectorAll('li.check')].map((li) => [li.dataset.outcome, li.innerText]); }""")
        ok = len(got) == 2 and got[0][0] == "unknown" and got[1][0] == "pass" and STUB_CHECKS[1]["text"] in got[0][1] and STUB_CHECKS[0]["text"] in got[1][1]
        w.check("s50c_checks", ok, f"{got}")
        chip_in = await page.locator("#panel .lead[data-id='b1:1'] .rules > .verdict").count()
        w.check("s50c_chip_in_rules", chip_in == 1, f"{chip_in} chips in the rule block")
        await w.snap(page, tag, "s50c-student-checks")
        await page.context.close()

    async def flow_student_card_says(w, browser, base, tag, view):
        state = {"kind": "extras"}
        page = await open_brief(w, browser, base, tag, view, state)
        await go(page, "#/brief/b1/routes", "#panel .lead")
        # S51 W19: a quiet closed fold that lists the sentence, not an amber box
        card = "#panel .lead[data-id='b1:2']"
        un = await page.locator(f"{card} details.unsupported-fold:not([open]) > summary", has_text="1 sentence could not be matched to its source").count()
        listed = await page.locator(f"{card} details.unsupported-fold li", has_text="Invented sentence the check could not match.").count()
        amber = await page.locator(f"{card} .notice.warn").count()
        w.check("s50c_unsupported", un == 1 and listed == 1 and amber == 0, f"{un} folds, {listed} sentences listed, {amber} amber boxes")
        facts = await page.locator("#panel .lead[data-id='b1:5'] .fact").count()
        wide = await page.locator("#panel .lead[data-id='b1:5'] .fact.fact-wide").count()
        stated = await page.locator("#panel .lead[data-id='b1:5']", has_text="Not stated").count()
        w.check("s50c_sdfa_facts", facts == 1 and wide == 1 and stated == 0, f"{facts} facts, {wide} wide, {stated} 'Not stated'")
        await w.snap(page, tag, "s50c-student-extras")
        await go(page, "#/brief/b1/profile", "#panel .prof-cols")
        text = await page.inner_text("#panel")
        w.check("s50c_no_canary", "PERCH-CANARY" not in text and "Canary:" not in text, "profile text")
        await w.snap(page, tag, "s50c-student-profile")
        await page.context.close()

    async def flow_student_compare_checks(w, browser, base, tag, view):
        state = {"kind": "checks", "kept": ("b1:1", "b1:2")}
        page = await open_brief(w, browser, base, tag, view, state)
        await go(page, "#/brief/b1/compare", "#panel .compare-group")
        cell = await page.evaluate("""() => { const r = document.querySelector('#panel .compare tbody tr');
          return [...r.querySelectorAll('li.check')].map((li) => li.dataset.outcome); }""")
        heading = await page.evaluate("() => [...document.querySelectorAll('#panel section.handoff h2')].map((h) => h.textContent)")
        order = await page.evaluate("""() => { const p = document.querySelector('#panel');
          const hint = [...p.querySelectorAll('p.hint')].find((x) => x.textContent.startsWith('Each cell is copied'));
          const s = p.querySelector('section.handoff'); return Boolean(hint && s && (hint.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING)); }""")
        w.check("s50c_compare_checks", cell == ["unknown", "pass"], f"first row check outcomes {cell}")
        w.check("s50c_compare_order", heading == ["Hand off"] and order, f"headings {heading}, note above hand-off {order}")
        await w.snap(page, tag, "s50c-student-compare")
        await page.context.close()

    async def flow_student_find(w, browser, base, tag, view):
        page = await U.new_page(browser, w, tag, view, base)
        st = {"roles": ["student"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, st)
        calls: list[str] = []

        async def docs(route):
            if route.request.method == "POST":
                calls.append("doc")
                return await route.fulfill(json={"id": f"d{len(calls)}", "kind": "cv", "label": "x", "chars": 10, "name": "x"})
            await route.fulfill(json=[])

        async def briefs(route):
            if route.request.method == "POST" and route.request.url.split("?")[0].endswith("/briefs"):
                calls.append("brief")
                return await route.fulfill(json={"id": "b1"})
            await route.continue_()

        await page.route("**/briefs", briefs)
        await page.route("**/me/docs**", docs)  # registered last, so it answers first
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/student'")
        await page.wait_for_selector("#cv-text", timeout=20_000)
        off = await page.locator("[data-key=st-build]").is_disabled()
        hint = await page.inner_text(".welcome-go")
        await page.click("[data-key=load-sample]")
        label = await page.inner_text("[data-key=st-build]")
        await w.snap(page, tag, "s50c-find-after-sample")
        w.check("s50c_find_button_state", off and "Paste or upload your CV first." in hint and label.strip() == "Save and find awards",
                f"disabled at start {off}, hint {hint.strip()!r}, label after sample {label.strip()!r}")
        await page.click("[data-key=st-build]")
        await page.wait_for_timeout(1500)
        w.check("s50c_load_sample_find", calls == ["doc", "doc", "doc", "brief"], f"{calls}")
        await page.context.close()

    flows = {"s50c_student_cards": flow_student_cards, "s50c_student_rules": flow_student_rules,
             "s50c_student_card_says": flow_student_card_says, "s50c_student_compare": flow_student_compare_checks,
             "s50c_student_find": flow_student_find}
    return flows, []
