"""Frames for the README clips, and where the camera should look.

A Python port of Dakshitha's NextTex recorder (e2e/shots/recorder.ts); it writes the same
scene.json, which scripts/tour/animate.py (copied from NextTex) turns into an animated WebP.

The page is filmed through the DevTools screencast: a frame each time it repaints, with
the time it painted, at full resolution. The scene says what matters and when, with
`focus` and `wide`; the camera glides between those marks and crops the full frames, so a
zoomed view is as sharp as the screen. `quickly` plays a slow wait back faster. Headless
Chromium draws no pointer, so `install` puts a drawn one on the page that follows the
real one and pulses on a click.
"""

from __future__ import annotations

import base64
import json
import shutil
import time
from pathlib import Path

from playwright.async_api import Locator, Page

POINTER = """
(() => {
  if (window.__pPointer) return;
  window.__pPointer = true;
  const start = () => {
    const dot = document.createElement("div");
    dot.setAttribute("aria-hidden", "true");
    dot.style.cssText = "position:fixed;left:0;top:0;width:22px;height:22px;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px);transition:transform 40ms linear";
    dot.innerHTML = '<svg width="22" height="22" viewBox="0 0 22 22"><path d="M3 2l14 8.2-6.3 1.3 3.6 7.1-2.6 1.3-3.6-7.2L3 17z" fill="#fff" stroke="#1b1f1d" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    const ring = document.createElement("div");
    ring.style.cssText = "position:fixed;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:2.5px solid #d9a441;z-index:2147483646;pointer-events:none;opacity:0;transform:scale(.4)";
    document.documentElement.append(ring, dot);
    let x = -100, y = -100;
    addEventListener("mousemove", (e) => { x = e.clientX; y = e.clientY; dot.style.transform = "translate(" + (x - 3) + "px," + (y - 2) + "px)"; }, true);
    addEventListener("mousedown", () => {
      ring.style.left = x + "px"; ring.style.top = y + "px";
      ring.animate([{ opacity: .9, transform: "scale(.4)" }, { opacity: 0, transform: "scale(1.3)" }], { duration: 420, easing: "ease-out" });
    }, true);
  };
  if (document.documentElement) start(); else addEventListener("DOMContentLoaded", start);
})();"""  # noqa: E501


class Recorder:
    def __init__(self, page: Page, name: str, root: Path) -> None:
        self.page, self.name, self.dir = page, name, root / name
        self.frames: list[dict] = []
        self.marks: list[dict] = []
        self.fast: list[dict] = []
        self.t0 = 0.0
        self.count = 0
        self.session = None

    @staticmethod
    async def install(page: Page) -> None:
        await page.add_init_script(POINTER)
        await page.evaluate(POINTER)

    async def start(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        view = self.page.viewport_size
        scale = await self.page.evaluate("window.devicePixelRatio")
        self.session = await self.page.context.new_cdp_session(self.page)
        self.t0 = time.time()

        async def on_frame(frame: dict) -> None:
            name = f"f{self.count:05d}.jpg"
            self.count += 1
            t = (frame.get("metadata", {}).get("timestamp") or time.time()) - self.t0
            try:
                await self.session.send("Page.screencastFrameAck",
                                        {"sessionId": frame["sessionId"]})
            except Exception:  # noqa: BLE001 - the session may be closing
                pass
            (self.dir / name).write_bytes(base64.b64decode(frame["data"]))
            self.frames.append({"t": t, "file": name})

        self.session.on("Page.screencastFrame", on_frame)
        await self.session.send("Page.startScreencast", {
            "format": "jpeg", "quality": 94, "maxWidth": round(view["width"] * scale),
            "maxHeight": round(view["height"] * scale), "everyNthFrame": 1})
        await self.page.evaluate("document.body.style.setProperty('--p-rec', '1')")
        await self.page.wait_for_timeout(250)

    def now(self) -> float:
        return time.time() - self.t0

    async def focus(self, target: Locator | dict, pad: int = 40, ease: float = 0.7,
                    zoom: float | None = None) -> None:
        box = target if isinstance(target, dict) else await target.bounding_box()
        if not box:
            raise RuntimeError(f"{self.name}: nothing to focus on")
        mark = {"t": self.now(), "kind": "focus", "ease": ease,
                "rect": {"x": box["x"] - pad, "y": box["y"] - pad,
                         "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad}}
        if zoom:
            mark["zoom"] = zoom
        self.marks.append(mark)

    def wide(self, ease: float = 0.7) -> None:
        self.marks.append({"t": self.now(), "kind": "wide", "ease": ease})

    async def quickly(self, wait, speed: float = 5):  # noqa: ANN001, ANN201 - any awaitable
        start = self.now()
        out = await wait()
        self.fast.append({"from": start, "to": self.now(), "speed": speed})
        return out

    async def hold(self, ms: int) -> None:
        await self.page.wait_for_timeout(ms)

    async def stop(self) -> None:
        await self.page.wait_for_timeout(300)
        try:
            await self.session.send("Page.stopScreencast")
        except Exception:  # noqa: BLE001
            pass
        await self.page.wait_for_timeout(200)
        await self.session.detach()
        (self.dir / "scene.json").write_text(json.dumps(
            {"name": self.name, "viewport": self.page.viewport_size, "end": self.now(),
             "frames": self.frames, "marks": self.marks, "fast": self.fast}, indent=1))


async def glide(page: Page, target: Locator, steps: int = 18) -> None:
    """Move the drawn pointer to an element the way a hand would, in steps."""
    box = await target.bounding_box()
    if not box:
        raise RuntimeError("nothing to point at")
    await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)


async def click(page: Page, target: Locator, steps: int = 18) -> None:
    await target.scroll_into_view_if_needed()
    await glide(page, target, steps)
    await page.wait_for_timeout(120)
    await target.click()
