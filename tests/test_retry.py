"""S50 C5: a model server's 429 or 5xx is retried, bounded, inside one adapter call, and the
job counts provider busy answers and a full model slot as transient. No network."""

from __future__ import annotations

import httpx
import pytest

from perch.llm import Message, retry
from perch.llm.base import ProviderError
from perch.llm.ollama import OllamaProvider
from perch.llm.openai_compat import OpenAICompatProvider

OK = {"model": "m", "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
      "usage": {"prompt_tokens": 3, "completion_tokens": 1}}


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(retry, "DELAYS", (0.0, 0.0))


def scripted(*answers):
    calls = []

    def handler(req):
        calls.append(req.url.path)
        status, body = answers[min(len(calls), len(answers)) - 1]
        return httpx.Response(status, json=body)

    return calls, httpx.MockTransport(handler)


def test_a_busy_local_server_is_retried_inside_one_call():
    calls, tr = scripted((503, {"error": "busy"}), (429, {"error": "slow down"}), (200, OK))
    p = OpenAICompatProvider("m", base_url="http://x/v1", transport=tr)
    assert p.chat([Message("user", "q")]).text == "ok"
    assert len(calls) == 3


def test_retries_are_bounded_and_the_status_is_kept():
    calls, tr = scripted((503, {"error": "busy"}))
    p = OpenAICompatProvider("m", base_url="http://x/v1", transport=tr)
    with pytest.raises(ProviderError) as e:
        p.chat([Message("user", "q")])
    assert e.value.status == 503 and len(calls) == 3


def test_a_client_error_is_not_retried():
    calls, tr = scripted((400, {"error": "bad"}))
    p = OllamaProvider("m", transport=tr)
    with pytest.raises(ProviderError) as e:
        p.chat([Message("user", "q")])
    assert e.value.status == 400 and len(calls) == 1


def test_the_job_retries_busy_answers_and_a_full_model_slot():
    from perch.compute import SlotTimeout
    from perch.service import BUSY_DETAIL, RETRY_DETAIL, is_transient, retry_detail

    assert is_transient(ProviderError("x", status=503))
    assert is_transient(ProviderError("x", status=429))
    assert not is_transient(ProviderError("x", status=400))
    assert not is_transient(ProviderError("x"))
    assert is_transient(SlotTimeout("no slot"))

    class RateLimitError(Exception):  # the SDK's error, by name and status
        status_code = 429

    class APIStatusError(Exception):
        status_code = 529

    assert is_transient(RateLimitError()) and is_transient(APIStatusError())
    assert retry_detail(SlotTimeout("no slot")) == BUSY_DETAIL
    assert retry_detail(ProviderError("x", status=503)) == RETRY_DETAIL


def test_the_model_server_clients_retry_a_busy_answer():
    from perch.remote_models import RemoteReranker

    calls, tr = scripted((503, {}), (200, {"scores": [0.5]}))
    assert RemoteReranker("http://x", "r", transport=tr).score("q", ["d"]) == [0.5]
    assert len(calls) == 2
