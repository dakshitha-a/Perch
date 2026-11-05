# ruff: noqa: ANN001, ANN201, ANN202, E501  (walk flow: inline JavaScript probes, flows take the ux_walk objects)
"""Shared demo account walk flow: the banner and the CV-box warning.

Loaded by scripts/ux_walk.py. Flow:
  s55shared   a stubbed signed-in session with `shared: true` (the stub is in scripts/ux_walk.py):
              the banner shows the notice on the landing, the student start, the researcher start (a
              real candidate search) and the account page; the CV box on the student start, the
              researcher start and the account page carries the same line. A second, ordinary
              session shows neither.

Plants (each makes exactly its named check fail; they change the page in the browser, no source edits):
  no_banner, no_cv_warn
"""

from __future__ import annotations

import re

NOTICE = "Shared demo account. Everyone who signs in sees what you save here. Do not paste a real CV."

BANNER = """() => { const b = document.getElementById('banner'); const p = b && b.querySelector('[data-key=shared-banner]');
  const r = b ? b.getBoundingClientRect() : null;
  return { shown: Boolean(p) && !b.hidden && b.checkVisibility(), text: p ? p.textContent.trim() : '', h: r ? r.height : 0,
           over: p ? p.scrollWidth - p.clientWidth : 0 }; }"""

WARN = """() => [...document.querySelectorAll('[data-key=shared-cv-warn]')].map((e) => {
  const r = e.getBoundingClientRect(); const box = e.closest('section.box');
  return { text: e.textContent.trim(), visible: e.checkVisibility() && r.height > 0, inBox: Boolean(box), cvBox: Boolean(box && box.querySelector('textarea, input[type=file]')) }; })"""


def register(U):  # noqa: N803 - the ux_walk module handed in by the loader
    async def flow_shared(w, browser, base, tag, view) -> None:
        page = await U.new_page(browser, w, tag, view, base)
        state = {"roles": ["student", "researcher"], "consented": True, "gone": False, "deleted_with": None, "shared": True}
        await U.stub_signed_in(page, state)
        await page.route(re.compile(r".*/me/docs(\?.*)?$"), lambda r: r.fulfill(json=[]))  # no stored CV: the box shows

        async def strip(name: str) -> None:
            if w.plant == "no_banner":
                await page.evaluate("document.querySelectorAll('[data-key=shared-banner]').forEach((e) => e.remove())")
            if w.plant == "no_cv_warn":
                await page.evaluate("document.querySelectorAll('[data-key=shared-cv-warn]').forEach((e) => e.remove())")

        async def banner(name: str) -> None:
            await strip(name)
            r = await page.evaluate(BANNER)
            w.check(f"s55_banner_{name}", r["shown"] and r["text"] == NOTICE and r["over"] <= 0, f"{name}: {r}")

        await page.goto(base + "/")
        await page.wait_for_selector("[data-key=shared-banner]", timeout=20_000)
        await banner("landing")
        await w.snap(page, tag, "s55-landing")
        # student start
        await page.evaluate("location.hash = '#/student'")
        await page.wait_for_selector("#cv-text", timeout=20_000)
        await strip("student")
        await banner("student_start")
        r = await page.evaluate(WARN)
        w.check("s55_cv_warning_student_start", len(r) == 1 and r[0]["text"] == NOTICE and r[0]["visible"] and r[0]["cvBox"], f"student start: {r}")
        await w.snap(page, tag, "s55-student-start")
        # account page
        await page.evaluate("location.hash = '#/account'")
        await page.wait_for_selector("#docs-h", timeout=20_000)
        await page.wait_for_timeout(500)
        await strip("account")
        await banner("account")
        r = await page.evaluate(WARN)
        w.check("s55_cv_warning_account", len(r) == 1 and r[0]["text"] == NOTICE and r[0]["visible"] and r[0]["inBox"], f"account: {r}")
        await w.snap(page, tag, "s55-account")
        # researcher start: search, pick a candidate, the CV box shows
        await page.evaluate("location.hash = '#/start'")
        await page.wait_for_selector("[data-key=fit]", timeout=20_000)
        if await page.locator("[data-key=seg-r]").count() and await page.locator("[data-key=seg-r]").is_visible():
            await page.click("[data-key=seg-r]")  # the phone landing shows one side at a time
        await page.wait_for_selector("#q", state="visible", timeout=20_000)
        await page.fill("#q", U.AUTHOR)
        await page.click(".searchbox button[type=submit]")
        await page.wait_for_selector("[data-key=build], .cand button", timeout=60_000)
        if not await page.locator("[data-key=build]").count():
            await page.click(".cand button")
        await page.wait_for_selector("#r-cv-file", state="attached", timeout=20_000)
        await strip("researcher")
        await banner("researcher_start")
        r = await page.evaluate(WARN)
        w.check("s55_cv_warning_researcher_start", len(r) == 1 and r[0]["text"] == NOTICE and r[0]["visible"] and r[0]["cvBox"], f"researcher start: {r}")
        await w.snap(page, tag, "s55-researcher-start")
        await page.context.close()
        # an ordinary account: neither the banner nor the line
        page = await U.new_page(browser, w, tag, view, base)
        await U.stub_signed_in(page, {"roles": ["student", "researcher"], "consented": True, "gone": False, "deleted_with": None})
        await page.route(re.compile(r".*/me/docs(\?.*)?$"), lambda r: r.fulfill(json=[]))
        await page.goto(base + "/#/student")
        await page.wait_for_selector("#cv-text", timeout=20_000)
        n = await page.evaluate("() => document.querySelectorAll('[data-key=shared-banner], [data-key=shared-cv-warn]').length")
        w.check("s55_ordinary_account_unmarked", n == 0, f"{n} shared marks on an ordinary account")
        await page.context.close()

    return ({"s55shared": flow_shared}, ["no_banner", "no_cv_warn"])
