"""Provider layer: adapters against mocked HTTP shaped like live responses, registry, cost."""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from perch.llm import Message, Tool, ToolCall, ToolResult, cost_usd, get_provider, spec_for_role
from perch.llm.anthropic_provider import AnthropicProvider, wire_message
from perch.llm.base import Refusal
from perch.llm.fake import FakeProvider
from perch.llm.ollama import OllamaProvider
from perch.llm.openai_compat import OpenAICompatProvider
from perch.llm.openai_compat import wire_messages as openai_wire

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
TOOL = Tool("get_record", "Fetch a record by id",
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]})


def test_ollama_request_and_parse():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={  # shape of a live Ollama 0.32.13 reply
            "model": "qwen3.8:27b", "message": {"role": "assistant", "content": '{"answer":"yes"}',
                                                "tool_calls": [{"id": "call_1", "function": {
                                                    "index": 0, "name": "get_record",
                                                    "arguments": {"id": "R1"}}}]},
            "done_reason": "stop", "prompt_eval_count": 26, "eval_count": 12,
            "logprobs": [{"token": "Yes", "logprob": -0.44, "top_logprobs": [
                {"token": "Yes", "logprob": -0.44}, {"token": "No", "logprob": -1.26}]}]})

    p = OllamaProvider("qwen3.8:27b", transport=httpx.MockTransport(handler))
    r = p.chat([Message("user", "q")], system="s", schema=SCHEMA, tools=[TOOL], logprobs=2)
    assert seen["think"] is False and seen["format"] == SCHEMA and seen["top_logprobs"] == 2
    assert seen["messages"][0] == {"role": "system", "content": "s"}
    assert "num_ctx" not in seen["options"]  # never reload the resident model by accident
    assert r.text == '{"answer":"yes"}' and r.usage.input_tokens == 26
    assert r.tool_calls[0].name == "get_record" and r.tool_calls[0].arguments == {"id": "R1"}
    assert [t.token for t in r.top_logprobs[0]] == ["Yes", "No"]
    assert cost_usd(r) == 0.0


FIXTURE = Path(__file__).parent / "fixtures/ollama/chat_tools_gemma.json"


def test_ollama_tool_round_trip_matches_live_fixture():
    """A live gemma4:26b-a4b exchange (SYNTHETIC record): the tool call parses, and the
    follow-up request Perch builds has the shape the live server accepted."""
    live = json.loads(FIXTURE.read_text())
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json=live[f"response_{len(seen)}"])

    p = OllamaProvider("gemma4:26b-a4b", transport=httpx.MockTransport(handler))
    user = Message("user", live["request_1"]["messages"][1]["content"])
    r1 = p.chat([user], system=live["request_1"]["messages"][0]["content"], tools=[TOOL])
    assert [(c.name, c.arguments) for c in r1.tool_calls] == [
        ("get_record", {"id": "grants.gov:SYNTHETIC-1"})]
    result = ToolResult(r1.tool_calls[0].id, "get_record",
                        live["request_2"]["messages"][3]["content"])
    msgs = [user, Message("assistant", r1.text, tool_calls=r1.tool_calls),
            Message("user", "", tool_results=[result])]
    r2 = p.chat(msgs, system=live["request_1"]["messages"][0]["content"], tools=[TOOL])
    assert seen[1] == live["request_2"]
    assert "2027-02-05" in r2.text


def test_tool_turns_on_the_wire_for_anthropic_and_openai():
    call = ToolCall("c1", "get_record", {"id": "R1"})
    asked = Message("assistant", "", tool_calls=[call])
    answered = Message("user", "", tool_results=[ToolResult("c1", "get_record", "{}", True)])
    assert wire_message(asked) == {"role": "assistant", "content": [
        {"type": "tool_use", "id": "c1", "name": "get_record", "input": {"id": "R1"}}]}
    assert wire_message(answered)["content"] == [
        {"type": "tool_result", "tool_use_id": "c1", "content": "{}", "is_error": True}]
    assert openai_wire(asked)[0]["tool_calls"][0]["function"]["arguments"] == '{"id": "R1"}'
    assert openai_wire(answered) == [{"role": "tool", "tool_call_id": "c1", "content": "{}"}]


def test_openai_compat_request_and_parse():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(200, json={
            "model": "m", "choices": [{"finish_reason": "stop", "message": {
                "content": "ok", "tool_calls": [{"id": "c1", "function": {
                    "name": "get_record", "arguments": '{"id": "R2"}'}}]},
                "logprobs": {"content": [{"token": "ok", "logprob": -0.1, "top_logprobs": [
                    {"token": "ok", "logprob": -0.1}]}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2,
                      "prompt_tokens_details": {"cached_tokens": 4}}})

    p = OpenAICompatProvider("m", base_url="http://x/v1", transport=httpx.MockTransport(handler))
    r = p.chat([Message("user", "q")], schema=SCHEMA, tools=[TOOL], logprobs=1)
    assert seen["response_format"]["type"] == "json_schema"
    assert r.tool_calls[0].arguments == {"id": "R2"} and r.usage.cache_read_tokens == 4
    assert r.top_logprobs[0][0].token == "ok"


class FakeAnthropicClient:
    def __init__(self, response):
        self.kw = None
        self.response = response
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.kw = kw
        return self.response


def anthropic_response(stop="end_turn"):
    return SimpleNamespace(
        model="claude-sonnet-5-5", stop_reason=stop, stop_details=None,
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text='{"answer": "yes"}')],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=5000,
                              cache_creation_input_tokens=0))


def budget(tmp_path, limit=100.0):
    from perch.llm.budget import Budget
    return Budget(limit, tmp_path / "ledger.jsonl")


def test_anthropic_request_shape_caching_fallback_and_cost(tmp_path):
    client = FakeAnthropicClient(anthropic_response())
    p = AnthropicProvider(client=client, budget=budget(tmp_path))
    r = p.chat([Message("user", "q")], system="stable prefix", schema=SCHEMA, tools=[TOOL],
               cache_system=True)
    kw = client.kw
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert kw["tools"][0]["strict"] is True and "tool_choice" not in kw
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in kw
    assert r.text == '{"answer": "yes"}'
    assert cost_usd(r) == pytest.approx((1000 * 2 + 100 * 10 + 5000 * 0.2) / 1e6)
    assert "logprobs" not in p.capabilities


def test_anthropic_refusal_raises(tmp_path):
    p = AnthropicProvider(client=FakeAnthropicClient(anthropic_response("refusal")),
                          budget=budget(tmp_path))
    with pytest.raises(Refusal):
        p.chat([Message("user", "q")])


def test_registry_and_roles(monkeypatch):
    assert isinstance(get_provider("fake:x"), FakeProvider)
    monkeypatch.delenv("PERCH_LLM_DEFAULT", raising=False)
    monkeypatch.delenv("PERCH_LLM_FIT_EXPLAINER", raising=False)
    monkeypatch.setenv("PERCH_PROFILE", "dev")
    assert spec_for_role("fit_explainer") == "ollama:gemma4:26b-a4b"
    monkeypatch.setenv("PERCH_PROFILE", "deploy-1gpu")
    assert spec_for_role("fit_explainer") == "ollama:qwen3:14b"
    monkeypatch.setenv("PERCH_PROFILE", "nope")
    with pytest.raises(ValueError):
        spec_for_role("fit_explainer")
    monkeypatch.setenv("PERCH_PROFILE", "dev")
    monkeypatch.setenv("PERCH_LLM_DEFAULT", "fake:a")
    monkeypatch.setenv("PERCH_LLM_FIT_EXPLAINER", "anthropic:claude-sonnet-5-5")
    assert spec_for_role("fit_explainer") == "anthropic:claude-sonnet-5-5"
    assert spec_for_role("handoff") == "fake:a"
    with pytest.raises(ValueError):
        spec_for_role("nope")
    with pytest.raises(ValueError):
        get_provider("mystery:m")


def test_unknown_price_is_nan_not_guessed():
    import math

    from perch.llm.base import ChatResult
    assert math.isnan(cost_usd(ChatResult("x", "unknown-model", "anthropic")))


def test_budget_records_every_call_and_refuses_at_the_cap(tmp_path, capsys):
    from perch.llm.budget import BudgetExceeded, spent_usd
    b = budget(tmp_path, limit=0.005)  # one call costs 0.004
    p = AnthropicProvider(client=FakeAnthropicClient(anthropic_response()), budget=b)
    p.chat([Message("user", "q")])
    assert spent_usd(b.path) == pytest.approx(0.004)
    p.chat([Message("user", "q")])  # 0.004 < 0.005: allowed, and warns past 80%
    assert "warning: Anthropic spend" in capsys.readouterr().err
    with pytest.raises(BudgetExceeded):
        p.chat([Message("user", "q")])  # 0.008 >= 0.005: refused before calling


def test_unknown_model_priced_at_the_most_expensive():
    from perch.llm.base import Usage
    from perch.llm.budget import call_cost
    assert call_cost("claude-unknown", Usage(1_000_000, 0)) == 4.00


def test_anthropic_schema_goes_through_transform(tmp_path):
    seen = []
    client = FakeAnthropicClient(anthropic_response())
    p = AnthropicProvider(client=client, budget=budget(tmp_path),
                          transform=lambda sch: seen.append(sch) or {"type": "object"})
    p.chat([Message("user", "q")], schema=SCHEMA, tools=[TOOL])
    assert seen == [TOOL.parameters, SCHEMA]
    assert client.kw["output_config"]["format"]["schema"] == {"type": "object"}
