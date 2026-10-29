"""Ollama adapter over its native /api/chat endpoint.

Verified live on Ollama 0.32.13 (2026-10-28): `format` takes a JSON schema,
`think: false` turns off Qwen3 thinking, `tools` returns native tool calls, and
`logprobs` with `top_logprobs` returns per-token alternatives. Leave `num_ctx`
unset unless configured: changing it reloads the model, and the dev profile keeps
a model resident on GPU 0.
"""

from __future__ import annotations

import time
import uuid

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


class OllamaProvider(Provider):
    name = "ollama"
    capabilities = frozenset({"tools", "schema", "logprobs"})

    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434",
                 think: bool = False, num_ctx: int | None = None, seed: int = 7,
                 timeout: float = 300.0, transport: httpx.BaseTransport | None = None) -> None:
        self.model = model
        self.think = think
        self.num_ctx = num_ctx
        self.seed = seed
        self.http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self.http.close()

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": m.role, "content": m.content} for m in messages]
        options: dict = {"temperature": 0, "seed": self.seed, "num_predict": max_tokens}
        if self.num_ctx:
            options["num_ctx"] = self.num_ctx
        body: dict = {"model": self.model, "messages": msgs, "stream": False,
                      "think": self.think, "options": options}
        if schema:
            body["format"] = schema
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools]
        if logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = logprobs
        t0 = time.perf_counter()
        r = self.http.post("/api/chat", json=body)
        latency = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            raise ProviderError(f"ollama {r.status_code}: {r.text[:300]}")
        d = r.json()
        if d.get("error"):
            raise ProviderError(f"ollama: {d['error']}")
        msg = d.get("message") or {}
        calls = [ToolCall(c.get("id") or uuid.uuid4().hex[:8], c["function"]["name"],
                          c["function"].get("arguments") or {})
                 for c in msg.get("tool_calls") or []]
        lps = None
        if d.get("logprobs"):
            lps = [[TokenChoice(a["token"], float(a["logprob"]))
                    for a in tok.get("top_logprobs") or [tok]] for tok in d["logprobs"]]
        return ChatResult(
            text=msg.get("content") or "", model=d.get("model") or self.model, provider=self.name,
            usage=Usage(d.get("prompt_eval_count") or 0, d.get("eval_count") or 0),
            tool_calls=calls, stop_reason=d.get("done_reason"), latency_ms=latency,
            top_logprobs=lps)
