"""Auth audit events (section 7.3 `csrf_reject`, section 4.3 `rate_limited`). Ids only: no
address, no cookie value, no token. Written to audit_log when the pool is configured, and
always logged by event name."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import Request

log = logging.getLogger("perch.auth")


def record(request: Request, event: str, *, actor: Any = None, **detail: str | int) -> None:  # noqa: ANN401
    log.info("auth event %s", event)
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        return
    try:
        with pool.connection() as c:
            c.execute("INSERT INTO audit_log (event, actor, detail) VALUES (%s, %s, %s)",
                      (event, actor, json.dumps(detail)))
    except Exception:  # noqa: BLE001  an audit failure never blocks or leaks a request
        log.warning("auth audit write failed for %s", event)
