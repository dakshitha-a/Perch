"""Bounded retry for a model server's busy answers (S50 C5).

A 429 or 5xx from a local model server (llama.cpp, vLLM, Ollama) or from perch.model_server is
retried here, inside one adapter call, so the spend meter that wraps the call reserves and
settles it once. Timeouts are not retried here: a 300 s read timeout three times over would
outlast the job. The job's own retry covers them (perch.service.is_transient).

The Anthropic SDK retries its own 429, 5xx and 529 answers (max_retries in the adapter).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

# Seconds to wait before the second and third attempts. Tests set these to zero.
DELAYS: tuple[float, ...] = (1.0, 3.0)
MAX_RETRY_AFTER = 10.0


def transient_status(code: int | None) -> bool:
    return code is not None and (code == 429 or code >= 500)


def _wait(r: httpx.Response, default: float) -> float:
    try:
        return min(MAX_RETRY_AFTER, max(default, float(r.headers.get("retry-after", ""))))
    except ValueError:
        return default


def post(send: Callable[[], httpx.Response]) -> httpx.Response:
    """Call `send` again after a 429 or 5xx answer, up to len(DELAYS) more times; return the
    last response, whatever its status, for the caller to check."""
    r = send()
    for delay in DELAYS:
        if not transient_status(r.status_code):
            break
        time.sleep(_wait(r, delay) if delay else 0.0)
        r = send()
    return r


def is_transient_provider_error(e: BaseException) -> bool:
    """A model provider's answer worth another attempt later: a ProviderError with status 429
    or 5xx, or an SDK error that carries such a status or names a lost connection or a
    timeout. Read by class and attribute, so no vendor SDK is imported here."""
    from perch.llm.base import ProviderError

    if isinstance(e, ProviderError):
        return transient_status(getattr(e, "status", None))
    status = getattr(e, "status_code", None)
    if isinstance(status, int) and transient_status(status):
        return True
    return type(e).__name__ in ("APIConnectionError", "APITimeoutError", "OverloadedError",
                                "RateLimitError", "InternalServerError")
