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
