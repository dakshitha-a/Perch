"""S51: a long Retry-After from OpenAlex fails the request instead of sleeping for hours."""

import time

import httpx
import pytest

from perch.sources import openalex


def test_a_long_retry_after_fails_fast(monkeypatch):
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    transport = httpx.MockTransport(
        lambda req: httpx.Response(429, headers={"Retry-After": "46857"}, json={}))
    c = openalex.OpenAlexClient(transport=transport, retries=4, min_interval=0)
    with pytest.raises(httpx.HTTPStatusError):
        c.get("/authors/A1")
    assert not any(s > openalex.MAX_RETRY_AFTER_S for s in slept)


def test_a_short_retry_after_is_still_waited(monkeypatch):
    slept, calls = [], []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    def answer(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={})
        return httpx.Response(200, json={"ok": True})

    c = openalex.OpenAlexClient(transport=httpx.MockTransport(answer), min_interval=0)
    assert c.get("/authors/A1") == {"ok": True}
    assert 2.0 in slept
