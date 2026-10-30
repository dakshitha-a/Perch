"""Walk the web app in replay mode and save screenshots (for Checkup 2 and review).

  uv run --no-project --with playwright python scripts/screenshots.py [--chrome PATH] [--out DIR]

Needs build/artifacts/ui.html (scripts/build_ui_preview.py) and a Chromium binary;
Playwright is a dev-only tool here, not a project dependency. The replay shows the
researcher by alias.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import os
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright

PHONE = {"width": 390, "height": 844}
NARROW = {"width": 320, "height": 640}
WIDE = {"width": 1280, "height": 860}


def find_chrome() -> str | None:
    pattern = os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None


async def walk(page: Page, url: str, out: Path, tag: str, errors: list[str]) -> None:
    async def snap(name: str, full: bool = False) -> None:
        await page.screenshot(path=str(out / f"{tag}-{name}.png"), full_page=full)

    page.on("pageerror", lambda e: errors.append(f"{tag}: {e}"))
    await page.goto(url)
    await page.wait_for_selector(".landing")
    await snap("1-find")
    await page.click(".searchbox button[type=submit]")
    await page.wait_for_selector(".cand")
    await page.click(".cand .btn.outline")
    await page.wait_for_selector(".more-panel")
    await page.wait_for_timeout(500)
    await snap("2-candidate")
    await page.click("[data-key=build]")
    await page.wait_for_selector(".pcard")
    await page.wait_for_timeout(1500)
    await snap("3-building")
    await page.wait_for_selector(".leads > li", timeout=30000)
    await page.wait_for_timeout(2500)
    await snap("4-building-routes")
    ready = "() => /Brief ready/.test(document.querySelector('#progress').innerText)"
    await page.wait_for_function(ready, timeout=60000)
    await page.wait_for_timeout(500)
    await snap("5-routes-done")
    await page.click(".lead .why summary")
    await page.wait_for_timeout(200)
    await page.locator(".lead").first.scroll_into_view_if_needed()
    await snap("6-why-it-fits")
    await page.click(".lead .why .paper-ref")
    await page.wait_for_selector(".rec-title")
    await page.wait_for_timeout(350)
    await snap("7-evidence-paper")
    await page.keyboard.press("Escape")
    await page.click(".lead .title-btn")
    await page.wait_for_selector(".rec-title")
    await page.wait_for_timeout(350)
    await snap("8-evidence-opportunity")
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)
    keeps = page.locator(".leads > li:not(.kept) .btn.keep")
    await keeps.first.click()
    await page.locator(".leads > li:not(.kept)").first.locator("[data-key=dismiss]").click()
    await page.wait_for_timeout(400)
    if await page.locator(".dismissed").count() != 1:
        errors.append(f"{tag}: dismiss did not take effect")
    shown = """() => [...document.querySelectorAll('.shortlist li, #keep-float .keep-float')]
      .some((el) => el.offsetParent !== null)"""
    if not await page.evaluate(shown):
        errors.append(f"{tag}: neither the shortlist nor the keep pill shows the kept lead")
    await snap("9b-keep-bar")
    wide = await page.evaluate("document.documentElement.scrollWidth - innerWidth")
    if wide > 0:
        errors.append(f"{tag}: page scrolls sideways by {wide}px")
    await snap("9-routes-full", full=True)
    await page.click("#tab-profile")
    await page.wait_for_timeout(300)
    await snap("10-profile-full", full=True)
    await page.evaluate("location.hash = '#/help'")
    await page.wait_for_selector("#h-use")
    await page.wait_for_timeout(300)
    await snap("11-help-full", full=True)


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chrome", default=find_chrome())
    ap.add_argument("--page", default="build/artifacts/ui.html")
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--only", choices=["phone", "wide", "dark", "narrow"], action="append")
    args = ap.parse_args(argv[1:])
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    url = Path(args.page).resolve().as_uri()
    errors: list[str] = []
    runs = [("phone", PHONE, "light", 2), ("wide", WIDE, "light", 1), ("dark", PHONE, "dark", 2),
            ("narrow", NARROW, "light", 2)]
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=args.chrome, args=["--no-sandbox"])
        for tag, size, scheme, scale in runs:
            if args.only and tag not in args.only:
                continue
            ctx = await browser.new_context(viewport=size, device_scale_factor=scale,
                                            color_scheme=scheme, has_touch=tag != "wide",
                                            is_mobile=tag != "wide")
            await walk(await ctx.new_page(), url, out, tag, errors)
            await ctx.close()
        await browser.close()
    for e in errors:
        print("page error:", e)
    print(f"screenshots in {out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv)))
