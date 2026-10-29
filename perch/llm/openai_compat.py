"""OpenAI-compatible chat completions adapter (vLLM, SGLang, Ollama's /v1, hosted APIs).

Uses httpx against POST {base_url}/chat/completions. Structured output via
`response_format: {type: json_schema}`; logprobs via `logprobs` + `top_logprobs`.
Support for each varies by server; see docs/SOURCES.md-style notes in the S5
session file for what was verified live.
"""

from __future__ import annotations

import json
import time

import httpx

from perch.llm.base import (
    ChatResult,
    JsonSchema,
    Message,
    Provider,
    ProviderError,
    TokenChoice,
    Tool,
    ToolCall,
    Usage,
)


def wire_messages(m: Message) -> list[dict]:
    """Tool results become "tool" role messages keyed by call id; tool calls ride on the
    assistant turn with their arguments as JSON text."""
    out = [{"role": "tool", "tool_call_id": r.call_id, "content": r.content}
           for r in m.tool_results]
    if m.content or not m.tool_results:
        msg: dict = {"role": m.role, "content": m.content}
        if m.tool_calls:
            msg["tool_calls"] = [{"id": c.id, "type": "function", "function": {
                "name": c.name, "arguments": json.dumps(c.arguments)}} for c in m.tool_calls]
        out.append(msg)
    return out


class OpenAICompatProvider(Provider):
    name = "openai"
    capabilities = frozenset({"tools", "schema", "logprobs"})

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:8000/v1",
                 api_key: str | None = None, seed: int = 7, timeout: float = 300.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.model = model
        self.seed = seed
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.Client(base_url=base_url.rstrip("/"), headers=headers,
                                 timeout=timeout, transport=transport)

    def close(self) -> None:
        self.http.close()

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            w for m in messages for w in wire_messages(m)]
        body: dict = {"model": self.model, "messages": msgs, "temperature": 0,
                      "seed": self.seed, "max_tokens": max_tokens}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "output", "schema": schema, "strict": True}}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools]
        if logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = logprobs
        t0 = time.perf_counter()
        r = self.http.post("/chat/completions", json=body)
        latency = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            raise ProviderError(f"openai-compatible {r.status_code}: {r.text[:300]}")
        d = r.json()
        choice = (d.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            args = c["function"].get("arguments") or "{}"
            calls.append(ToolCall(c.get("id") or "", c["function"]["name"],
                                  json.loads(args) if isinstance(args, str) else args))
        lps = None
        content_lp = (choice.get("logprobs") or {}).get("content")
        if content_lp:
            lps = [[TokenChoice(a["token"], float(a["logprob"]))
                    for a in tok.get("top_logprobs") or [tok]] for tok in content_lp]
        u = d.get("usage") or {}
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        return ChatResult(
            text=msg.get("content") or "", model=d.get("model") or self.model,
            provider=self.name,
            usage=Usage(u.get("prompt_tokens") or 0, u.get("completion_tokens") or 0, cached),
            tool_calls=calls, stop_reason=choice.get("finish_reason"), latency_ms=latency,
            top_logprobs=lps)
