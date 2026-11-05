"""Render the architecture, roadmap and cost figures in docs/architecture/*.svg to PNG.

  uv run --no-project --with playwright python scripts/render_figures.py

Writes docs/architecture/<name>-light.png and <name>-dark.png for v1, v1-simple, roadmap and
cost_model. The SVGs draw text and lines in currentColor and fill two box kinds with fixed
light tints; the dark render sets a light ink on a dark page and swaps those two tints.
"""

from __future__ import annotations

import asyncio
import glob
import os
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "docs/architecture"
NAMES = ["v1", "v1-simple", "roadmap", "cost_model"]
SCHEMES = {
    "light": {"bg": "#f7f7f3", "ink": "#1c2b26", "swap": {}},
    "dark": {"bg": "#101a17", "ink": "#e6efe9",
             "swap": {"#dcefe8": "#183a31", "#f6ead8": "#3d2f17",
                      "#1f6f5c": "#5fc2a6", "#a15c07": "#e0a04a"}},
}
WIDTH = 1400


async def main() -> None:
    exe = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=exe[-1] if exe else None, args=["--no-sandbox"])
        for name in NAMES:
            svg = (ARCH / f"{name}.svg").read_text(encoding="utf-8")
            for scheme, c in SCHEMES.items():
                s = svg
                for a, z in c["swap"].items():
                    s = s.replace(a, z)
                page = await b.new_page(viewport={"width": WIDTH, "height": 800})
                await page.set_content(
                    f"<body style='margin:0;padding:32px;background:{c['bg']};color:{c['ink']};"
                    f"width:{WIDTH - 64}px'>{s}</body>")
                await page.evaluate("document.querySelector('svg').style.cssText='display:block;width:100%;height:auto'")
                await page.locator("body").screenshot(path=str(ARCH / f"{name}-{scheme}.png"))
                await page.close()
                print(f"docs/architecture/{name}-{scheme}.png")
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
