import json

from perch.llm import Message
from perch.llm.audit import AuditedProvider, AuditLog, prompt_hash
from perch.llm.fake import FakeProvider


def test_every_call_logged_with_hash_not_text(tmp_path):
    log = AuditLog(tmp_path / "calls.jsonl")
    p = AuditedProvider(FakeProvider(["one two"]), log, "fit_explainer")
    p.chat([Message("user", "SECRET-PROMPT-TEXT")], system="sys")
    log.validation(p.last_call_id, "fit_explainer", False, ["number '9'"], attempt=1)
    lines = [json.loads(x) for x in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert [e["kind"] for e in lines] == ["call", "validation"]
    call = lines[0]
    assert call["role"] == "fit_explainer" and call["model"] == "fake-1"
    assert call["prompt_hash"] == prompt_hash("sys", [Message("user", "SECRET-PROMPT-TEXT")],
                                              None, None)
    assert call["output_tokens"] == 2 and call["cost_usd"] == 0.0
    assert "SECRET-PROMPT-TEXT" not in (tmp_path / "calls.jsonl").read_text()
    assert lines[1]["call_id"] == call["call_id"]
    assert log.rejection_rate() == (1, 1)


def test_hash_is_order_stable():
    a = prompt_hash("s", [Message("user", "x")], {"b": 1, "a": 2}, None)
    assert a == prompt_hash("s", [Message("user", "x")], {"a": 2, "b": 1}, None)


def test_prompt_hash_is_keyed_with_audit_key(monkeypatch):
    msgs = [Message("user", "x")]
    monkeypatch.delenv("PERCH_AUDIT_KEY", raising=False)
    monkeypatch.setenv("PERCH_ENV", "dev")
    plain = prompt_hash("s", msgs, None, None)
    monkeypatch.setenv("PERCH_AUDIT_KEY", "synthetic-key-1")
    k1 = prompt_hash("s", msgs, None, None)
    monkeypatch.setenv("PERCH_AUDIT_KEY", "synthetic-key-2")
    assert k1 != plain and k1 != prompt_hash("s", msgs, None, None)
    assert len(k1) == 64


def test_prompt_hash_without_key_is_dev_only(monkeypatch):
    import pytest

    monkeypatch.delenv("PERCH_AUDIT_KEY", raising=False)
    monkeypatch.setenv("PERCH_ENV", "prod")
    with pytest.raises(RuntimeError, match="PERCH_AUDIT_KEY"):
        prompt_hash("s", [Message("user", "x")], None, None)
