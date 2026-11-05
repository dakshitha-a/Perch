# ruff: noqa: ANN001, ANN202, E501  (walk flow: inline JavaScript probes, flows take the ux_walk objects)
"""S49 BE-S walk flows: the student list head and the signed-in "Load sample" button.

Loaded by scripts/ux_walk.py (see _load_walk_flows). Each check was written before the code it
checks and failed on the untouched build (the base commit is in the commit message).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FLAGGED_COUNT = 3  # leads the flow marks as withheld, to see the list say it once


def register(U):  # noqa: ANN001, ANN201 - U is the ux_walk module
    async def sample_brief(w, browser, base, tag, view):
        """A signed-in student's stored brief (a SYNTHETIC fixture built from the real models,
        scripts/walk_flows/s49_student_brief.json) with three flagged fellowship leads. The
        walk server cannot build a brief here, so the brief view is answered by the flow."""
        body = json.loads((Path(__file__).parent / "s49_student_brief.json").read_text())
        flagged = [x["id"] for x in body["leads"] if x["flagged"]]
        flag = {"on": True, "kept": set()}  # off: no withheld reasons; kept: lead ids shown as kept
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["student"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)

        async def brief(route):
            path = route.request.url.split("?")[0]
            if route.request.method == "GET" and path.endswith("/briefs/b1"):
                shown = {**body, "leads": [{**x, "flagged": x["flagged"] and flag["on"],
                                            "status": "kept" if x["id"] in flag["kept"] else x["status"]} for x in body["leads"]]}
                return await route.fulfill(json=shown)
            if "/briefs/b1/" in path:
                return await route.fulfill(status=404, json={"detail": "not in this walk"})
            await route.continue_()

        await page.route("**/briefs/b1**", brief)
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/brief/b1/routes'")
        await page.wait_for_selector("#panel .lead", timeout=30_000)
        await page.wait_for_timeout(500)
        return page, flagged, flag

    async def flow_student_list(w, browser, base, tag, view):
        page, flagged, flag = await sample_brief(w, browser, base, tag, view)
        flag["on"] = False  # the preamble is measured with no list notice in the way
        await page.reload()
        await page.wait_for_selector("#panel .lead", timeout=30_000)
        await page.wait_for_timeout(800)  # fonts and the card's late lines settle first
        gap = await page.evaluate("""() => {
          const t = document.querySelector('#routes-title').getBoundingClientRect();
          const l = document.querySelector('#panel .lead').getBoundingClientRect();
          return Math.round(l.top - t.bottom); }""")
        limit = 120 if view["width"] >= 600 else 160  # at 360 the Sort switch wraps under the heading
        w.check("s49_student_preamble_folded", gap <= limit, f"first card starts {gap} px under the heading (limit {limit})")
        await w.snap(page, tag, "s49-student-list-clean")
        flag["on"] = True
        await page.reload()
        await page.wait_for_selector("#panel .lead", timeout=30_000)
        await w.snap(page, tag, "s49-student-list")
        notes = await page.locator("#panel .list-note").count()
        amber = await page.locator("#panel .lead .notice.warn").count()
        lines = await page.locator("#panel .lead .withheld-line").count()
        # S50 V5: with the list note up, the flagged cards carry no line of their own (their missing reason is the sign)
        w.check("s49_student_withheld_once", notes == 1 and amber == 0 and lines == 0 and len(flagged) >= 2,
                f"{notes} list notes, {amber} amber boxes on cards, {lines} withheld lines for {len(flagged)} flagged")
        more = await page.locator("#panel details.about-list").count()
        opened = await page.locator("#panel details.about-list[open]").count()
        w.check("s49_student_about_list_closed", more == 1 and opened == 0, f"{more} About this list, {opened} open")
        head = await page.evaluate("""() => { const h = document.querySelector('#panel .list-head');
          return Boolean(h && h.querySelector('#routes-title') && h.querySelector('.sort-group')
            && !document.querySelector('#panel .route-row .sort-group')); }""")
        w.check("s49_student_sort_in_list_head", head, "Sort sits in .list-head, not on the route row")
        mini = await page.locator("#panel .lead .facts .fact").count()
        cards = await page.locator("#panel ol.leads > li.lead").count()
        w.check("s49_student_two_facts_every_card", cards > 0 and mini == 2 * cards,
                f"{mini} facts on {cards} cards")
        await page.context.close()

    async def flow_student_compare(w, browser, base, tag, view):
        page, _, flag = await sample_brief(w, browser, base, tag, view)
        flag["kept"] = {"b1:4", "b1:5"}
        await page.evaluate("location.hash = '#/brief/b1/compare'")
        await page.reload()
        await page.wait_for_selector("#panel .compare-group, #panel .empty", timeout=20_000)
        await page.wait_for_timeout(500)
        order = await page.evaluate("""() => { const p = document.querySelector('#panel');
          const t = p.querySelector('.compare-group'), n = p.querySelector('section.handoff');
          return Boolean(t && n && (t.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING)); }""")
        w.check("s49_student_compare_tables_before_note", order, "the tables come before the note section")
        await w.snap(page, tag, "s49-student-compare")
        await page.context.close()

    async def flow_load_sample(w, browser, base, tag, view):
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["student"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)

        async def no_docs(route):
            await route.fulfill(json=[])

        await page.route("**/me/docs**", no_docs)  # registered last, so it answers first
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/student'")
        await page.wait_for_selector("#cv-text", timeout=20_000)
        have = await page.locator("[data-key=load-sample]").count()
        await w.snap(page, tag, "s49-load-sample-before")
        if have:
            await page.click("[data-key=load-sample]")
        text = await page.input_value("#cv-text") if have else ""
        tagged = await page.locator("span.tag.sample", has_text="SYNTHETIC example").count()
        w.check("s49_load_sample", have == 1 and "SYNTHETIC" in text and "Canary:" in text and tagged == 1,
                f"button {have}, cv text {len(text)} chars, tag {tagged}")
        both = [await page.input_value(s) for s in ("#st-interests", "#st-ach")]
        w.check("s49_load_sample_fills_all_three", all("Canary:" in t for t in both), f"{[len(t) for t in both]}")
        banned = re.compile(r"@|https?://|\d{3}[-. ]\d{3}[-. ]\d{4}|Tamsin|Quell")
        w.check("s49_sample_text_has_no_contact_or_name", not any(banned.search(t) for t in [text, *both]), "")
        await w.snap(page, tag, "s49-load-sample-after")
        await page.fill("#st-ach", both[1] + " edited")
        gone = await page.locator("span.tag.sample", has_text="SYNTHETIC example").count()
        w.check("s49_load_sample_tag_leaves_on_input", gone == 0, f"{gone} tags after typing")
        # Existing text: pressing again asks first; Keep mine leaves the boxes alone.
        await page.click("[data-key=load-sample]")
        ask = await page.locator("div.inline-confirm[role=group]").count()
        await w.snap(page, tag, "s49-load-sample-confirm")
        await page.click("div.inline-confirm button.quiet")
        kept = await page.input_value("#st-ach")
        await page.click("[data-key=load-sample]")
        await page.click("div.inline-confirm button:not(.quiet)")
        replaced = await page.input_value("#st-ach")
        w.check("s49_load_sample_confirms_before_replacing",
                ask == 1 and kept.endswith(" edited") and not replaced.endswith(" edited"),
                f"confirm {ask}, kept mine {kept.endswith(' edited')}, replaced {not replaced.endswith(' edited')}")
        await page.context.close()

    async def flow_load_sample_hidden(w, browser, base, tag, view):
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["student"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)  # /me/docs answers with a stored CV
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/student'")
        await page.wait_for_selector("[data-key=rm-cv]", timeout=20_000)
        n = await page.locator("[data-key=load-sample]").count()
        w.check("s49_no_load_sample_when_a_cv_is_stored", n == 0, f"{n} buttons")
        await page.context.close()

    flows = {"s49_student_list": flow_student_list, "s49_student_compare": flow_student_compare, "s49_load_sample": flow_load_sample,
             "s49_load_sample_hidden": flow_load_sample_hidden}
    return flows, []
