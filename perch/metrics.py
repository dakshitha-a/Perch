"""Minimal metrics (S47): in-process request counters, served at GET /metrics.

Loopback only: the route answers 404 to any caller that is not 127.0.0.1 or ::1, or that
carries a proxy header (X-Forwarded-For, Forwarded, X-Real-IP), so it is not reachable through
the public proxy or a published port. Inside the container, `docker compose exec web` or a
sidecar on the same network namespace reads it. Counts only: no path, user, query or body.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable

_LOCK = threading.Lock()
_STATUS: Counter[str] = Counter()
_SECONDS: Counter[str] = Counter()  # summed handler seconds per status class
STARTED = time.time()
PROXY_HEADERS = (b"x-forwarded-for", b"forwarded", b"x-real-ip")


class Counting:
    """Pure ASGI middleware: one counter per status class (2xx, 3xx, 4xx, 5xx)."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        seen: list[int] = []

        async def wrap(message: dict) -> None:
            if message["type"] == "http.response.start":
                seen.append(int(message["status"]))
            await send(message)

        try:
            await self.app(scope, receive, wrap)
        finally:
            cls = f"{seen[0] // 100}xx" if seen else "5xx"
            with _LOCK:
                _STATUS[cls] += 1
                _SECONDS[cls] += time.perf_counter() - t0


def local_only(client_host: str | None, headers: list[tuple[bytes, bytes]]) -> bool:
    if client_host not in ("127.0.0.1", "::1"):
        return False
    return not any(k.lower() in PROXY_HEADERS for k, _ in headers)


def render(extra: dict[str, float] | None = None) -> str:
    """Prometheus text format."""
    lines = ["# TYPE perch_http_requests_total counter"]
    with _LOCK:
        for cls in sorted(_STATUS):
            lines.append(f'perch_http_requests_total{{status="{cls}"}} {_STATUS[cls]}')
        lines.append("# TYPE perch_http_seconds_total counter")
        for cls in sorted(_SECONDS):
            lines.append(f'perch_http_seconds_total{{status="{cls}"}} {_SECONDS[cls]:.3f}')
    lines += ["# TYPE perch_uptime_seconds gauge",
              f"perch_uptime_seconds {time.time() - STARTED:.0f}"]
    for k, v in (extra or {}).items():
        lines.append(f"{k} {v}")
    return "\n".join(lines) + "\n"
