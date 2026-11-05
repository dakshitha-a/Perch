# ruff: noqa: E501, ANN001, ANN201, ANN202, ANN003  - walk flows hold inline JavaScript probes, like ux_walk.py
"""S49 FE-B walk flows: lists, My Perch, account, compare, hand-off and cover points.

register(U) -> (flows, plants). `U` is the ux_walk module. Checks that rely on Playwright route
mocks (the saved list, funding's open_only, the compare number, the list-notices slot) say so in
their detail text; QA re-runs them against the real routes after the merge.
"""

from __future__ import annotations

import datetime
import json
import re
import statistics
import urllib.parse

SYNTH_AWARD = {"kind": "scholarship", "source": "temple_pages", "source_url": "https://example.invalid/award",
               "fetched_at": "2026-11-01T00:00:00+00:00", "schools": [], "levels": [], "scope": "temple_wide", "sample": False}


def saved_item(n: int, name: str, deadline: str | None, kept: bool = False, saved: bool = True, record: bool = True) -> dict:
    rid = f"temple_pages:synthetic-{n}"
    rec = dict(SYNTH_AWARD, id=rid, name=name, deadline=deadline, amount_max=None) if record else None
    return {"record_id": rid, "saved_id": f"sv-{n}" if saved else None, "saved_at": "2026-11-04T21:10:00+00:00",
            "kept_in": [{"brief_id": "b1", "built_at": "2026-11-03T18:00:00+00:00"}] if kept else [], "record": rec}


SAVED_ITEMS = [saved_item(1, "SYNTHETIC Upcoming Award", "2099-03-01"),
               saved_item(2, "SYNTHETIC Past Award", "2020-03-01", kept=True),
               saved_item(3, "SYNTHETIC Undated Award", None)]

BRIEFS = [{"id": "b1", "status": "done", "researcher_id": "you", "created_at": "2026-11-03T12:00:00", "leads": 12,
           "topics": [], "sample_leads": 0, "kept": 2, "sample_kept": 0},
          {"id": "b2", "status": "running", "researcher_id": "you", "created_at": "2026-11-02T12:00:00", "leads": 4,
           "topics": [], "sample_leads": 1, "kept": 0, "sample_kept": 0}]

HANDOFF_JOB = "55555555-5555-5555-5555-555555555555"


def register(U):  # noqa: N803 - the module handed in by the loader
    async def mock_me(page, saved: dict) -> None:
        """Stubs for the new /me/saved routes, the briefs summary and the documents."""
        async def saved_route(route) -> None:
            req = route.request
            if req.method == "POST":
                body = json.loads(req.post_data or "{}")
                saved["posts"].append(body.get("record_id"))
                return await route.fulfill(status=201, json={"saved_id": f"sv-new-{len(saved['posts'])}",
                                                             "record_id": body.get("record_id"), "saved_at": "2026-11-04T21:10:00+00:00"})
            if req.method == "DELETE":
                saved["deletes"].append(req.url.rsplit("/", 1)[-1])
                return await route.fulfill(json={"ok": True})
            await route.fulfill(json={"audience": "student", "total": len(saved["items"]), "items": saved["items"]})

        async def briefs_route(route) -> None:
            await route.fulfill(json=BRIEFS)

        async def docs_route(route) -> None:
            await route.fulfill(json=[{"id": "d1", "kind": "cv", "label": "CV", "chars": 900, "name": "cv.md"}])
        await page.route(re.compile(r".*/me/saved(/[^?]*)?(\?.*)?$"), saved_route)
        await page.route(re.compile(r".*/me/briefs(\?.*)?$"), briefs_route)
        await page.route(re.compile(r".*/me/docs(\?.*)?$"), docs_route)

    # ---------- lists, as a guest, on the walk server's own data ----------
    async def flow_lists(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        await page.goto(base + "/#/awards")
        await page.wait_for_selector("li.award, li.award-row", timeout=30_000)
        await page.wait_for_selector(".tag-row")
        await w.snap(page, tag, "s49b-awards")
        if view["width"] > 600:
            hs = await page.evaluate("[...document.querySelectorAll('.award-row')].map(e => e.getBoundingClientRect().height)")
            med = statistics.median(hs) if hs else 9999
            w.check("s49_row_height", bool(hs) and med <= 130, f"{len(hs)} rows, median {med:.0f} px (limit 130)")
        rows = await page.evaluate("""() => [...document.querySelectorAll('.award-row')].map(e => {
          const t = e.textContent; return (t.match(/Not stated/g) || []).length; })""")
        w.check("s49_no_double_not_stated", bool(rows) and max(rows) <= 1, f"{len(rows)} rows, most 'Not stated' in one row: {max(rows or [0])}")
        lab = await page.evaluate("""() => { const l = document.querySelector('label[for=list-level]');
          return l ? { text: l.textContent.trim(), vis: l.offsetParent !== null && !l.classList.contains('sr-only') } : null; }""")
        w.check("s49_level_label", bool(lab) and lab["text"] == "Level of study" and lab["vis"], f"{lab}")
        sortopts = await page.evaluate("""() => { const s = document.querySelector('#list-sort');
          return s ? [...s.options].map(o => o.textContent) : null; }""")
        w.check("s49_awards_sort_options", sortopts == ["A to Z", "Deadline soonest", "Largest amount"], f"{sortopts}")
        keepline = await page.evaluate("document.querySelector('.keep-line')?.textContent || ''")
        keeplinks = await page.locator(".keep-line a:text-is('Sign in')").count()
        w.check("s49_guest_keep_line", "Sign in to keep awards" in keepline and keeplinks == 1 and keepline.count("Sign in") == 1
                and await page.locator(".award-row .keep").count() == 0, f"{keepline!r}, {keeplinks} links")
        await page.fill("#list-q", "zzzzqqxx")
        await page.wait_for_selector(".empty-list")
        shown = await page.evaluate("[...document.querySelectorAll('.tag-chip .n')].filter(e => e.offsetParent !== null).length")
        w.check("s49_counts_hide_on_search", shown == 0, f"{shown} counts visible during a search")
        await w.snap(page, tag, "s49b-awards-empty")
        await page.context.close()

        # funding: the walk server does not honour open_only yet, so this check mocks the answer
        page = await U.new_page(browser, w, tag, view, base)
        reqs: list[str] = []

        async def opp(route) -> None:
            url = route.request.url
            reqs.append(url)
            resp = await route.fetch()
            data = await resp.json()
            today = datetime.date.today().isoformat()
            g = data["groups"][0]
            items = [x for x in g["items"] if not (x.get("close_date") and str(x["close_date"])[:10] < today)]
            closed = dict(items[0] if items else g["items"][0], id="grants_gov:SYNTHETIC-closed", title="SYNTHETIC closed call",
                          close_date="2020-01-31", close_date_note=None)
            g["items"] = items if "open_only=true" in url else [closed, *items]
            await route.fulfill(json=data)
        await page.route(re.compile(r".*/opportunities\?.*"), opp)
        await page.goto(base + "/#/funding")
        await page.wait_for_selector("li.award, li.award-row", timeout=30_000)
        await page.wait_for_timeout(500)
        default_closed = await page.locator(".tag.closed").count()
        first = reqs[0] if reqs else ""
        sw = page.locator("[data-key=show-closed]")
        on = await sw.count()
        if on:
            await sw.click()
            await page.wait_for_timeout(800)
        after = await page.locator(".tag.closed").count()
        w.check("s49_funding_hides_closed", default_closed == 0 and on == 1 and after >= 1 and "open_only=true" in first and "sort=closing" in first,
                f"[mock] closed tags {default_closed} by default, {after} after Show closed calls; first request {first.split('?')[-1][:80]}")
        sortopts = await page.evaluate("document.querySelector('#list-sort') ? [...document.querySelector('#list-sort').options].map(o => o.textContent) : null")
        w.check("s49_funding_sort_options", sortopts == ["Closing soonest", "A to Z", "Largest award"], f"{sortopts}")
        await w.snap(page, tag, "s49b-funding")
        await page.context.close()

    # ---------- signed in, with the saved list mocked ----------
    async def flow_signed(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": [], "consented": False, "gone": False, "deleted_with": None}
        saved = {"posts": [], "deletes": [], "items": list(SAVED_ITEMS)}
        await U.stub_signed_in(page, state)
        await mock_me(page, saved)
        await page.goto(base + "/")
        await page.wait_for_selector(".welcome")
        hint = await page.locator(".welcome .hint").first.inner_text()
        body = await page.locator(".welcome").inner_text()
        w.check("s49_welcome_copy", "Graduate students" in hint and "Consent text, version" not in body, f"{hint!r}")
        await w.snap(page, tag, "s49b-welcome")
        state.update(roles=["student", "researcher"], consented=True)
        await page.reload()
        await page.evaluate("location.hash = '#/me'")
        await page.wait_for_selector(".my-perch")
        await page.wait_for_timeout(800)
        three = await page.evaluate("""() => { const q = (s) => document.querySelector(s)?.getBoundingClientRect();
          return { k: q('.home-kept'), b: q('.home-briefs'), d: q('.home-docs') }; }""")
        ok = all(three.values())
        side = ok and (view["width"] < 900 or three["d"]["left"] >= three["k"]["right"] - 1)
        w.check("s49_home_three_cards", ok and side, f"[mock] {'three cards' if ok else 'missing cards'}, docs right of kept: {side}")
        order = await page.evaluate("[...document.querySelectorAll('.kept-row')].map(r => r.textContent)")
        w.check("s49_kept_sorted", len(order) == 3 and "Upcoming" in order[0] and "Past Award" in order[1] and "Past date on the page" in order[1]
                and "Undated" in order[2] and "No date on the record" in order[2], f"[mock] {len(order)} rows")
        titles = await page.evaluate("[...document.querySelectorAll('.brief-row')].map(r => r.textContent)")
        w.check("s49_brief_row_named", len(titles) == 2 and not any("Student brief" in t for t in titles)
                and not any(re.search(r"\bdone\b", t) for t in titles) and "Options checked" in titles[0], f"[mock] {[t[:60] for t in titles]}")
        await w.snap(page, tag, "s49b-my-perch")
        # remove a saved row
        try:
            await page.locator(".kept-row button:has-text('Remove')").first.click(timeout=3000)
        except Exception:  # noqa: BLE001 - the old page has no kept rows; the check below then fails
            pass
        await page.wait_for_timeout(500)
        w.check("s49_kept_remove", saved["deletes"] == ["sv-1"], f"[mock] deletes {saved['deletes']}")
        # Keep on a list row
        await page.evaluate("location.hash = '#/awards'")
        await page.wait_for_selector("li.award", timeout=30_000)
        await page.wait_for_timeout(600)
        rid = await page.locator("li.award").first.get_attribute("data-id")
        btn = page.locator(".award-row .keep").first
        has_keep = await btn.count()
        if has_keep:
            await btn.click()
            await page.wait_for_timeout(500)
        label = (await btn.inner_text()).strip() if has_keep else ""
        w.check("s49_keep_saves", saved["posts"] == [rid] and label == "Kept" and await btn.get_attribute("aria-pressed") == "true",
                f"[mock] posts {saved['posts']}, row {rid}, button {label!r}")
        await w.snap(page, tag, "s49b-awards-signed")
        await page.evaluate("location.hash = '#/samples/student'")
        await page.wait_for_selector(".sample-note", timeout=30_000)
        await page.wait_for_selector("li.award, li.award-row")
        n = await page.locator(".keep").count()
        w.check("s49_no_keep_on_samples", has_keep == 1 and n == 0, f"awards row has Keep: {has_keep}; sample screen Keep buttons: {n}")
        await w.snap(page, tag, "s49b-samples")
        # account
        await page.evaluate("location.hash = '#/account'")
        await page.wait_for_selector("#del-open")
        label_text = await page.locator(".acct-facts dt").all_inner_texts()
        w.check("s49_account_label", "Using Perch as" in label_text and "Your sides" not in label_text, f"{label_text}")
        await page.click("#del-open")
        await page.wait_for_timeout(200)
        same = await page.evaluate("""() => { const go = getComputedStyle(document.querySelector('#del-go')).backgroundColor;
          const t = document.createElement('i'); t.style.backgroundColor = 'var(--brick)'; document.body.append(t);
          const b = getComputedStyle(t).backgroundColor; t.remove(); return [go, b]; }""")
        w.check("s49_delete_confirm_solid", same[0] == same[1], f"#del-go {same[0]} vs --brick {same[1]}")
        await w.snap(page, tag, "s49b-delete-dialog", full=False)
        await page.context.close()

    # ---------- a researcher brief: compare, hand-off, cover points ----------
    async def flow_brief(w, browser, base, tag, view) -> None:
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
        await page.click("[data-key=build]")
        status = await U.build_wait(page)
        w.check("s49_brief_built", status == "done", f"status {status}")
        bid = await page.evaluate("decodeURIComponent(location.hash.split('/')[2])")
        await page.goto(base + "/")
        await page.evaluate("(id) => { location.hash = '#/brief/' + encodeURIComponent(id) + '/routes'; }", bid)
        await page.wait_for_selector("#panel .btn.keep", timeout=30_000)
        # guests: no sign-in link on any card; one line above the list
        cards = await page.locator("#panel li.card.lead").count()
        links = await page.locator("#panel [data-cover] a, #panel a[data-key^=cover-]").count()
        w.check("s49_cover_guest_no_card_links", cards > 0 and links == 0, f"{cards} cards, {links} sign-in links on cards")
        slot = await page.locator("#list-notices").count()
        once = await page.locator("#list-notices [data-cover-line] a:text-is('Sign in')").count()
        w.check("s49_cover_guest_once", slot == 1 and once == 1, f"{slot} notice slots, {once} Sign in links above the list")
        kept = await U.keep_two(page)
        # compare: table first; titles clean and numbers in their own line (the /compare answer is mocked)
        async def compare(route) -> None:
            resp = await route.fetch()
            data = await resp.json()
            for i, r in enumerate(data["rows"]):
                r["title"] = re.sub(r"^[\w.-]+-\d+:\s*", "", r["title"]) or r["title"]
                r["number"] = f"SYNTH-{i + 1:02d}-100" if r.get("route") != "B" else None
            await route.fulfill(json=data)
        await page.route(re.compile(r".*/briefs/[^/?]+/compare$"), compare)
        await page.evaluate("location.hash = location.hash.replace(/\\/[a-z]+$/, '/compare')")
        await page.wait_for_selector("#panel table", timeout=20_000)
        await page.wait_for_timeout(600)
        pos = await page.evaluate("""() => ({ t: document.querySelector('.compare-wrap')?.getBoundingClientRect().top,
          h: document.querySelector('.handoff-box')?.getBoundingClientRect().top,
          titles: [...document.querySelectorAll('.row-title')].map(e => e.textContent),
          nums: [...document.querySelectorAll('.row-num')].map(e => e.textContent) })""")
        w.check("s49_compare_table_first", pos["t"] is not None and pos["h"] is not None and pos["t"] < pos["h"], f"table top {pos['t']}, hand-off top {pos['h']}")
        bad = [t for t in pos["titles"] if re.match(r"^[\w.-]+-\d+:", t)]
        w.check("s49_compare_title_clean", kept > 0 and not bad and len(pos["nums"]) >= 1, f"[mock] {len(pos['titles'])} titles, {len(pos['nums'])} numbers {pos['nums'][:2]}, bad {bad[:2]}")
        await w.snap(page, tag, "s49b-compare")

        # hand-off, signed in (the same stub as the hand-off flow)
        seen = {"gets": 0}

        async def session(route) -> None:
            await route.fulfill(json={"signed_in": True, "guest": False, "roles": ["researcher"], "audience": "researcher",
                                      "csrf": "walk-csrf", "display_name": "Sam Example Walker", "expires_at": 9999999999,
                                      "consent": {"required": False, "current_version": 1, "accepted_version": 1,
                                                  "provider_name": "SYNTHETIC Provider", "text": U.CONSENT},
                                      "needs_welcome": False})

        async def handoff(route) -> None:
            if route.request.method == "POST":
                return await route.fulfill(status=202, json={"job_id": HANDOFF_JOB, "status": "queued", "poll": "x"})
            seen["gets"] += 1
            office = dict(urllib.parse.parse_qsl(route.request.url.split("?", 1)[1])).get("office")
            lines = "\n".join(f"- SYNTHETIC lead number {i} with a longer line of words so that the box wraps over more than one row" for i in range(1, 9))
            draft = {"office": {"key": office, "name": "SYNTHETIC Office", "url": "https://example.invalid/"}, "to": "",
                     "subject": "SYNTHETIC: leads to discuss", "flagged": False, "model": "SYNTHETIC model", "lead_ids": ["x1", "x2"],
                     "cited_ids": [], "opening_by": "model", "body": f"SYNTHETIC opening paragraph.\n\n{lines}\n\nThis draft is a sample."}
            await route.fulfill(json={"result": draft, "job": {"id": HANDOFF_JOB, "state": "succeeded"}})
        await page.route("**/auth/session", session)
        await page.route(re.compile(r".*/briefs/[^/?]+/handoff(\?.*)?$"), handoff)
        await page.goto(base + "/")
        await page.evaluate("(id) => { location.hash = '#/brief/' + encodeURIComponent(id) + '/compare'; }", bid)
        await page.wait_for_selector("[data-key=handoff-make]", timeout=20_000)
        to_line = await page.locator(".office-link").inner_text()
        await page.locator("[data-key=handoff-make]").click()
        await page.wait_for_selector("#handoff-body", timeout=20_000)
        await page.wait_for_timeout(400)
        geo = await page.evaluate("""() => ({ again: document.querySelector('[data-key=handoff-make]').getBoundingClientRect().top,
          body: document.querySelector('#handoff-body').getBoundingClientRect().top,
          rows: Number(document.querySelector('#handoff-body').getAttribute('rows')),
          quiet: document.querySelector('[data-key=handoff-make]').classList.contains('quiet') })""")
        w.check("s49_draft_again_below", geo["again"] > geo["body"] and geo["quiet"], f"Draft again top {geo['again']}, body top {geo['body']}, quiet {geo['quiet']}")
        w.check("s49_draft_rows_and_to", 8 <= geo["rows"] <= 18 and "add the address yourself" in to_line, f"rows {geo['rows']}, {to_line!r}")
        await w.snap(page, tag, "s49b-handoff-draft")

        # cover points, signed in, quota answers on two cards
        titles = {}
        got = await page.evaluate("(id) => fetch('/briefs/' + id).then(r => r.json())", bid)
        for x in got["leads"]:
            r = x.get("record") or x.get("opportunity") or {}  # a researcher lead's record is `opportunity`
            titles[x["record_id"]] = r.get("name") or r.get("title") or x.get("title") or x["record_id"]
        cseen = await U.stub_cover(page, bid, titles, "researcher")
        await page.route("**/usage", lambda r: r.fulfill(json={"spent_usd": 1.0, "limit_usd": 1.0, "resets_at": "2099-01-01T05:00:00+00:00"}))
        await page.goto(base + "/")
        await page.evaluate("(id) => { location.hash = '#/brief/' + encodeURIComponent(id) + '/routes'; }", bid)
        await page.wait_for_selector("#panel li.card.lead button[data-key^=cover-]", timeout=20_000)
        ids = [await e.get_attribute("data-cover") for e in await page.locator("#panel [data-cover]").all() if await e.is_visible()]
        plain = [i for i in ids if not i.startswith("sample:")]
        first, q1, q2 = plain[0], plain[1], plain[2]
        cseen["refuse"].update({q1: "quota", q2: "quota"})
        await page.locator(f"button[data-key='cover-{first}']").click()
        await page.wait_for_selector(f"[data-cover='{first}'] .scout-points", timeout=15_000)
        await page.wait_for_timeout(300)
        g = await page.evaluate("""(r) => { const c = document.querySelector(`[data-cover='${r}']`);
          return { again: c.querySelector('button').getBoundingClientRect().top, pts: c.querySelector('.scout-points').getBoundingClientRect().top,
            head: c.querySelector('.scout-points summary span').textContent }; }""", first)
        w.check("s49_points_again_below", g["again"] > g["pts"] and g["head"] == "Cover-letter points", f"Points again top {g['again']}, points top {g['pts']}, heading {g['head']!r}")
        await U.show(page, f"[data-cover='{first}']")
        await w.snap(page, tag, "s49b-cover-result", full=False)
        for q in (q1, q2):
            await page.locator(f"button[data-key='cover-{q}']").click()
            await page.wait_for_timeout(900)
        notes = await page.locator("#list-notices .notice").count()
        card_err = await page.locator(".cover .notice.error").count()
        text = await page.locator("#list-notices").inner_text()
        w.check("s49_quota_once", notes == 1 and card_err == 0 and "SYNTHETIC: you have used" in text and "comes back at" in text,
                f"[mock slot, mock 429] {notes} notices above the list, {card_err} card errors, {text[:90]!r}")
        await page.evaluate("document.querySelector('#list-notices').scrollIntoView({ block: 'center' })")
        await w.snap(page, tag, "s49b-cover-quota", full=False)
        await page.context.close()

    async def flow_scoutmarks(w, browser, base, tag, view) -> None:
        """The existing scoutmarks flow with U21's one-word provenance line for a flagged answer."""
        old = U.CHECKED_FLAGGED
        U.CHECKED_FLAGGED = "Written by a model."
        try:
            await U.flow_scoutmarks(w, browser, base, tag, view)
        finally:
            U.CHECKED_FLAGGED = old

    flows = {"s49b_scoutmarks": flow_scoutmarks, "s49b_lists": flow_lists, "s49b_signed": flow_signed, "s49b_brief": flow_brief}
    return flows, []
