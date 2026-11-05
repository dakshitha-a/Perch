# ruff: noqa: ANN001, ANN201, ANN202, E501  (walk flow: inline JavaScript probes, flows take the ux_walk objects)
"""S53 QA walk flows: the optional citizenship and state picks, the CV panel, the footer.

Loaded by scripts/ux_walk.py. Flows:
  s53picks    signed-in (stubbed) student start and account page, guest researcher start: the picks
              fieldset has a legend and both selects have labels; Load sample sets International
  s53brief    a guest sample student brief (real build): the CV panel shows rows and no skeleton;
              with the International pick, a demoted lead is last-ordered and its note names the
              field and the page and quotes the sentence (reported honestly when no record has a rule)
  s53footer   the footer promises and the notice are centred on the landing and on another screen

Plants (each makes exactly its named check fail; they change the page in the browser, no source edits):
  picks_no_legend, picks_no_label, sample_no_pick, cv_skeleton, footer_off_centre
"""

from __future__ import annotations

import json
import re

PROFILE = {"citizenship": None, "residency_state": None}

PICKS_PROBE = """(prefix) => {
  const c = document.getElementById(prefix + '-citizenship'), s = document.getElementById(prefix + '-state');
  const fs = c && c.closest('fieldset.profile-picks');
  const lg = fs && fs.querySelector('legend');
  const lab = (el) => el ? [...el.labels].map((l) => l.textContent.trim()).filter(Boolean) : [];
  return { fieldset: !!fs, legend: lg ? lg.textContent.trim() : '', both: !!(c && s && fs.contains(s)),
           labC: lab(c), labS: lab(s), value: c ? c.value : null }; }"""

FOOT_PROBE = """() => {
  const vw = document.documentElement.clientWidth, foot = document.querySelector('.foot');
  const ul = foot.querySelector('.promises'), p = foot.querySelector('p');
  const gaps = (r, outer) => ({ l: r.left - outer.left, r: outer.right - r.right });
  const lis = [...ul.querySelectorAll('li')].filter((li) => li.getBoundingClientRect().width > 0);
  const ur = ul.getBoundingClientRect();
  const shown = getComputedStyle(ul).display !== 'none' && lis.length > 0;
  const u = { l: Math.min(...lis.map((li) => li.getBoundingClientRect().left)) - ur.left,
              r: ur.right - Math.max(...lis.map((li) => li.getBoundingClientRect().right)) };
  const pr = p.getBoundingClientRect();
  const rg = document.createRange(); rg.selectNodeContents(p);
  const lines = [...rg.getClientRects()].filter((r) => r.width > 1);
  const mid = (pr.left + pr.right) / 2;
  const off = Math.max(...lines.map((r) => Math.abs((r.left + r.right) / 2 - mid)));
  const box = gaps(pr, { left: 0, right: vw });
  return { shown, ulGap: u, ulBox: gaps(ur, { left: 0, right: vw }), pBox: box, lineOff: off, n: lines.length,
           align: getComputedStyle(p).textAlign }; }"""


def register(U):  # noqa: N803 - the ux_walk module handed in by the loader
    async def stub_profile(page) -> None:
        async def prof(route) -> None:
            if route.request.method == "PUT":
                return await route.fulfill(json=json.loads(route.request.post_data or "{}"))
            await route.fulfill(json=PROFILE)
        await page.route(re.compile(r".*/me/profile(\?.*)?$"), prof)

    async def flow_picks(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["student", "researcher"], "consented": True, "gone": False, "deleted_with": None}
        await U.stub_signed_in(page, state)
        await stub_profile(page)
        await page.route(re.compile(r".*/me/docs(\?.*)?$"), lambda r: r.fulfill(json=[]))
        await page.goto(base + "/")
        await page.evaluate("location.hash = '#/student'")
        await page.wait_for_selector("#st-pick-citizenship", timeout=20_000)
        if w.plant == "picks_no_legend":
            await page.evaluate("document.querySelector('fieldset.profile-picks legend').remove()")
        if w.plant == "picks_no_label":
            await page.evaluate("document.querySelectorAll('fieldset.profile-picks label').forEach((l) => l.remove())")
        r = await page.evaluate(PICKS_PROBE, "st-pick")
        w.check("s53_picks_student_legend_labels", r["fieldset"] and r["both"] and bool(r["legend"]) and bool(r["labC"]) and bool(r["labS"]),
                f"student start: {r}")
        await w.snap(page, tag, "s53-student-start-picks")
        await page.click("[data-key=load-sample]")
        await page.wait_for_timeout(500)
        if w.plant == "sample_no_pick":
            await page.select_option("#st-pick-citizenship", "")
        v = await page.input_value("#st-pick-citizenship")
        w.check("s53_load_sample_sets_international", v == "international", f"citizenship after Load sample is {v!r}")
        await w.snap(page, tag, "s53-student-sample-loaded")
        # the account page, both sides
        await page.evaluate("location.hash = '#/account'")
        await page.wait_for_selector("#acct-student-citizenship", timeout=20_000)
        if w.plant == "picks_no_legend":
            await page.evaluate("document.querySelectorAll('fieldset.profile-picks legend').forEach((l) => l.remove())")
        if w.plant == "picks_no_label":
            await page.evaluate("document.querySelectorAll('fieldset.profile-picks label').forEach((l) => l.remove())")
        ra = [await page.evaluate(PICKS_PROBE, p) for p in ("acct-student", "acct-researcher")]
        w.check("s53_picks_account_legend_labels", all(x["fieldset"] and x["both"] and x["legend"] and x["labC"] and x["labS"] for x in ra),
                f"account page: {ra}")
        await w.snap(page, tag, "s53-account-picks")
        await page.context.close()
        # a guest's researcher start (real server): a candidate is chosen, then the picks box shows
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/")
        await page.click("[data-key=guest-start]")
        await page.wait_for_selector("[data-key=guest-banner]")
        await page.click("[data-key=seg-r]")
        await page.fill("#q", U.AUTHOR)
        await page.click(".searchbox button[type=submit]")
        await page.wait_for_selector("[data-key=build], .cand button", timeout=60_000)
        if not await page.locator("[data-key=build]").count():
            await page.click(".cand button")
        await page.wait_for_selector("#r-pick-citizenship", timeout=20_000)
        if w.plant == "picks_no_legend":
            await page.evaluate("document.querySelector('fieldset.profile-picks legend').remove()")
        if w.plant == "picks_no_label":
            await page.evaluate("document.querySelectorAll('fieldset.profile-picks label').forEach((l) => l.remove())")
        r = await page.evaluate(PICKS_PROBE, "r-pick")
        w.check("s53_picks_researcher_legend_labels", r["fieldset"] and r["both"] and bool(r["legend"]) and bool(r["labC"]) and bool(r["labS"]),
                f"researcher start: {r}")
        await w.snap(page, tag, "s53-researcher-start-picks")
        await page.context.close()

    async def flow_brief(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/")
        await page.click("[data-key=guest-start]")
        await page.wait_for_selector("[data-key=guest-banner]")
        await page.click("[data-key=seg-s]")
        await page.click("[data-key=fit]")
        await U.sample_after_fit(page)
        status = await U.build_wait(page)
        w.check("s53_sample_brief_built", status == "done", f"status {status}")
        bid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
        got = await page.evaluate("(id) => fetch('/briefs/' + id).then(r => r.json())", bid)
        leads = got["leads"]
        dem = [x for x in leads if x.get("demoted")]
        stated = (got.get("citizenship_rules") or got.get("brief", {}).get("citizenship_rules") or {})
        # the CV panel
        await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/profile')")
        await page.wait_for_selector(".pblock", timeout=20_000)
        await page.wait_for_timeout(1500)
        if w.plant == "cv_skeleton":
            await page.evaluate("document.querySelector('.fields').replaceWith(Object.assign(document.createElement('div'), {className: 'skeleton'}))")
        cv = await page.evaluate("""() => { const t = [...document.querySelectorAll('.pblock h2')].find((h) => /What the rules read/.test(h.textContent));
          const b = t && t.closest('.pblock'); return { found: !!t, rows: b ? b.querySelectorAll('.field').length : 0,
            skeleton: document.querySelectorAll('.skeleton').length, keys: b ? [...b.querySelectorAll('dt')].map((e) => e.textContent) : [] }; }""")
        w.check("s53_cv_panel_rows_no_skeleton", cv["found"] and cv["rows"] > 0 and cv["skeleton"] == 0, f"CV panel {cv}")
        await w.snap(page, tag, "s53-cv-panel")
        # the leads: demoted ones are last, each with a note that names the rule and quotes it
        await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/routes')")
        await page.wait_for_selector("#panel .btn.keep", timeout=20_000)
        info = {"leads": len(leads), "demoted": len(dem), "counts": stated}
        if not dem:
            w.check("s53_demoted_lead_note", True, f"NO DEMOTED LEAD in the walk corpus ({info}); not checked, reported honestly")
        else:
            order = await page.evaluate("""() => [...document.querySelectorAll('#panel ol.leads[aria-labelledby] > li .card.lead, #panel ol.leads[aria-labelledby] > .card.lead')].map((c) => ({ id: c.getAttribute('data-id') || '',
              low: !!c.querySelector('[data-lower]'), text: c.innerText.slice(0, 40) }))""")
            first_low = next((i for i, o in enumerate(order) if o["low"]), -1)
            tail_ok = first_low >= 0 and all(o["low"] for o in order[first_low:])
            d0 = dem[0]
            rule = d0.get("citizenship_rule") or {}
            checks = [c for c in d0.get("checks", []) if c["rule"] in ("citizenship", "residency")]
            quoted = bool(rule.get("quote")) and any(rule["quote"][:30] in (c["text"] + " ".join(d0.get("notes", []))) or "asks for" in c["text"] for c in checks)
            w.check("s53_demoted_lead_note", tail_ok and quoted and bool(rule.get("source_url")),
                    f"{info}; last-ordered={tail_ok} (first low index {first_low} of {len(order)}); rule={ {k: rule.get(k) for k in ('field', 'quote', 'source_url')} }; checks={[c['text'] for c in checks]}")
            low = page.locator("#panel ol.leads[aria-labelledby] .card.lead").nth(first_low) if first_low >= 0 else None
            if low is not None:
                await low.scroll_into_view_if_needed()
                await low.evaluate("(el) => el.querySelectorAll('details').forEach((d) => d.open = true)")
                await low.screenshot(path=str(w.out / f"{tag}-s53-demoted-card.png"))
        await w.snap(page, tag, "s53-routes-demoted")
        if not dem:
            # [mock] the corpus has no rule, so the first lead is given a SYNTHETIC one in the response, to see the card and the order
            quote = "SYNTHETIC rule: open to U.S. citizens and permanent residents only."
            url = "https://example.invalid/synthetic-award"

            async def demote(route) -> None:
                resp = await route.fetch()
                body = await resp.json()
                firsts = {}
                for y in body["leads"]:
                    firsts.setdefault(y.get("route"), y)
                for x in firsts.values():  # the first lead of each route, so the shown route has one
                    demote_one(x)
                await route.fulfill(response=resp, json=body)

            def demote_one(x: dict) -> None:
                x["demoted"] = True
                x["citizenship_rule"] = {"record_id": x.get("record_id") or "", "source_url": url, "field": "eligibility.notes",
                                         "where": "the award's eligibility notes", "quote": quote, "outcome": "fail", "has_text": True}
                line = f"From the award's eligibility notes, the listing asks for: \u201c{quote.rstrip('.')}\u201d. You entered: International."
                x["checks"] = [c for c in x.get("checks", []) if c["rule"] != "citizenship"] + [{"rule": "citizenship", "outcome": "unknown", "text": f"Citizenship: {line}"}]
            await page.route(re.compile(r".*/briefs/[^/?]+(\?.*)?$"), demote)
            await page.reload()
            await page.wait_for_selector("#panel .card.lead", timeout=30_000)
            await page.wait_for_timeout(1000)
            order = await page.evaluate("""() => [...document.querySelectorAll('#panel ol.leads[aria-labelledby] > li .card.lead, #panel ol.leads[aria-labelledby] > .card.lead')].map((c) => ({ low: !!c.querySelector('[data-lower]'),
              note: /asks for/.test(c.innerText) && /SYNTHETIC rule/.test(c.innerText), link: !!c.querySelector('a.pick-source') }))""")
            last = order[-1] if order else {}
            w.check("s53_demoted_mock_last_with_note", len(order) > 1 and last.get("low") and last.get("note") and last.get("link") and not any(o["low"] for o in order[:-1]),
                    f"[mock] {len(order)} cards, low at {[i for i, o in enumerate(order) if o['low']]}, last {last}, lead0 route {leads[0].get('route')}")
            await page.locator("#panel ol.leads[aria-labelledby] .card.lead").last.scroll_into_view_if_needed()
            await page.locator("#panel ol.leads[aria-labelledby] .card.lead").last.screenshot(path=str(w.out / f"{tag}-s53-demoted-card-mock.png"))
        await page.context.close()

    async def flow_footer(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/")
        await page.wait_for_selector(".foot .promises li", state="attached")
        await page.wait_for_timeout(500)
        if w.plant == "footer_off_centre":
            await page.evaluate("""() => { const f = document.querySelector('.foot'); f.querySelector('p').style.setProperty('text-align', 'left', 'important');
              const u = f.querySelector('.promises'); u.style.setProperty('justify-content', 'flex-start', 'important'); u.style.setProperty('align-items', 'flex-start', 'important'); }""")
        r = await page.evaluate(FOOT_PROBE)
        eq = lambda g: abs(g["l"] - g["r"]) <= 2  # noqa: E731
        w.check("s53_footer_promises_centred", r["shown"] and eq(r["ulGap"]) and eq(r["ulBox"]), f"landing promises {r['ulGap']}, box {r['ulBox']}")
        w.check("s53_footer_notice_centred", eq(r["pBox"]) and r["lineOff"] <= 2 and r["align"] == "center", f"landing notice box {r['pBox']}, line offset {r['lineOff']:.1f}, {r['n']} lines, align {r['align']}")
        await page.locator(".foot").scroll_into_view_if_needed()
        await page.locator(".foot").screenshot(path=str(w.out / f"{tag}-s53-footer-landing.png"))
        await page.evaluate("location.hash = '#/help'")
        await page.wait_for_selector("article.help h1", timeout=20_000)
        r2 = await page.evaluate(FOOT_PROBE)
        w.check("s53_footer_notice_centred_help", eq(r2["pBox"]) and r2["lineOff"] <= 2, f"help notice box {r2['pBox']}, line offset {r2['lineOff']:.1f}")
        await page.locator(".foot").scroll_into_view_if_needed()
        await page.locator(".foot").screenshot(path=str(w.out / f"{tag}-s53-footer-help.png"))
        await page.context.close()

    return ({"s53picks": flow_picks, "s53brief": flow_brief, "s53footer": flow_footer},
            ["picks_no_legend", "picks_no_label", "sample_no_pick", "cv_skeleton", "footer_off_centre"])
