"""Ollama adapter over its native /api/chat endpoint.

Verified live on Ollama 0.32.13 (2026-10-28): `format` takes a JSON schema,
`think: false` turns off Qwen3 thinking, `tools` returns native tool calls, and
`logprobs` with `top_logprobs` returns per-token alternatives. Leave `num_ctx`
unset unless configured: changing it reloads the model, and the dev profile keeps
a model resident on GPU 0.

Reasoning (QA round 3, T2), checked on a raw call to gemma4:26b-a4b on Ollama 0.32.13
(1 Nov 2026): the model's own renderer and parser are on; with `think: false` the reply
has no `thinking` field, and with `think: true` the reasoning comes back in
`message.thinking`, apart from `content`. Now and then, with thinking off, the model opens
its thought channel anyway; the parser does not expect it and passes it through, so the
content starts with a line "thought", then the thought, then the answer. Such a reply is
asked again once with thinking on, so the parser puts the thought in `thinking`, which is
dropped; a leftover "thought" line and any <think> block are stripped as well. Only the
answer text leaves the adapter.
"""

from __future__ import annotations

import re
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

# A leaked thought channel: a first line that is only the channel's name.
THOUGHT_LINE = re.compile(r"\A\s*(?:<\|?channel\|?>\s*)?(?:thought|thinking)\s*(?:\n|\Z)", re.I)
THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.S | re.I)


def leaked_thought(text: str) -> bool:
    return bool(THOUGHT_LINE.match(text) or THINK_BLOCK.search(text))


def strip_reasoning(text: str) -> str:
    """The answer only: no <think> block and no leading thought-channel line."""
    return THOUGHT_LINE.sub("", THINK_BLOCK.sub("", text), count=1).lstrip()


def wire_messages(m: Message) -> list[dict]:
    """Tool results become "tool" role messages; tool calls ride on the assistant turn."""
    out = [{"role": "tool", "tool_name": r.name, "content": r.content} for r in m.tool_results]
    if m.content or not m.tool_results:
        msg: dict = {"role": m.role, "content": m.content}
        if m.tool_calls:
            msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}}
                                 for c in m.tool_calls]
        out.append(msg)
    return out


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

    def _post(self, body: dict) -> dict:
        r = self.http.post("/api/chat", json=body)
        if r.status_code != 200:
            raise ProviderError(f"ollama {r.status_code}: {r.text[:300]}")
        d = r.json()
        if d.get("error"):
            raise ProviderError(f"ollama: {d['error']}")
        return d

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            w for m in messages for w in wire_messages(m)]
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
        d = self._post(body)
        msg = d.get("message") or {}
        spent = 0
        if not body["think"] and not schema and leaked_thought(msg.get("content") or ""):
            spent = (d.get("prompt_eval_count") or 0) + (d.get("eval_count") or 0)
            d = self._post({**body, "think": True})  # T2: the parser now splits it off
            msg = d.get("message") or {}
        latency = (time.perf_counter() - t0) * 1000
        calls = [ToolCall(c.get("id") or uuid.uuid4().hex[:8], c["function"]["name"],
                          c["function"].get("arguments") or {})
                 for c in msg.get("tool_calls") or []]
        lps = None
        if d.get("logprobs"):
            lps = [[TokenChoice(a["token"], float(a["logprob"]))
                    for a in tok.get("top_logprobs") or [tok]] for tok in d["logprobs"]]
        return ChatResult(
            text=strip_reasoning(msg.get("content") or ""),
            model=d.get("model") or self.model, provider=self.name,
            usage=Usage((d.get("prompt_eval_count") or 0) + spent, d.get("eval_count") or 0),
            tool_calls=calls, stop_reason=d.get("done_reason"), latency_ms=latency,
            top_logprobs=lps)
