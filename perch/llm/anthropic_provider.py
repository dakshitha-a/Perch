"""Anthropic adapter on the official SDK (optional extra: `uv sync --extra anthropic`).

Structured output via `output_config.format` (json_schema); tools with
`strict: true` and `tool_choice` left on auto (forced tool choice returns a 400 on
Claude Sonnet 5.5 and Opus 5.5); the system prompt is a cacheable prefix
(`cache_control: ephemeral`) when asked. Server-side refusal fallback is on by
default (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`, Claude API
only). The Messages API exposes no token logprobs, so "logprobs" is not a
capability: `decide` falls back to structured output without logprob confidence.

Not yet live-verified: no API key on the lab node (S5). Request shapes follow the
claude-api skill reference (cached 2026-10-06).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

from perch.llm.base import (
    ChatResult,
    JsonSchema,
    Message,
    Provider,
    ProviderError,
    Refusal,
    Tool,
    ToolCall,
    Usage,
)
from perch.llm.budget import Budget


def wire_message(m: Message) -> dict:
    """A Message as the Messages API wants it: tool calls as tool_use blocks on the
    assistant turn, results as tool_result blocks on the next user turn."""
    if not m.tool_calls and not m.tool_results:
        return {"role": m.role, "content": m.content}
    blocks: list[dict] = [{"type": "tool_result", "tool_use_id": r.call_id, "content": r.content,
                           "is_error": r.is_error} for r in m.tool_results]
    if m.content:
        blocks.append({"type": "text", "text": m.content})
    blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments}
               for c in m.tool_calls]
    return {"role": m.role, "content": blocks}


DEFAULT_MODEL = "claude-sonnet-5-5"  # SPEC section 7: skill 2 default is Claude Sonnet via API
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(Provider):
    name = "anthropic"
    capabilities = frozenset({"tools", "schema", "prompt_cache"})

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None,
                 fallbacks: bool = True, effort: str | None = None, client: object = None,
                 budget: Budget | None = None,
                 transform: Callable[[JsonSchema], JsonSchema] | None = None) -> None:
        if client is None:
            import anthropic  # vendor SDK, imported only inside perch/llm

            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
            # The API supports a JSON Schema subset (no minimum/maximum, minItems only 0 or 1;
            # live 400 on 2026-10-28). The SDK's transform_schema moves unsupported
            # constraints into descriptions; Perch's validator still checks them.
            transform = transform or anthropic.transform_schema
        self.client = client
        self.transform = transform or (lambda schema: schema)
        self.model = model
        self.fallbacks = fallbacks
        self.effort = effort
        self.budget = budget or Budget()  # hard cap to the demo; see perch/llm/budget.py

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 16000, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        kw: dict = {"model": self.model, "max_tokens": max_tokens,
                    "messages": [wire_message(m) for m in messages]}
        if system:
            block: dict = {"type": "text", "text": system}
            if cache_system:
                block["cache_control"] = {"type": "ephemeral"}
            kw["system"] = [block]
        if tools:
            kw["tools"] = [{"name": t.name, "description": t.description,
                            "input_schema": self.transform(t.parameters), "strict": True}
                           for t in tools]
        output_config: dict = {}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": self.transform(schema)}
        if self.effort:
            output_config["effort"] = self.effort
        if output_config:
            kw["output_config"] = output_config
        if self.fallbacks:
            kw["betas"] = [FALLBACK_BETA]
            kw["fallbacks"] = "default"
        self.budget.check()
        t0 = time.perf_counter()
        resp = self.client.beta.messages.create(**kw)
        latency = (time.perf_counter() - t0) * 1000
        if resp.stop_reason == "refusal" and resp.usage is not None:
            self.budget.record(resp.model, Usage(resp.usage.input_tokens or 0,
                                                 resp.usage.output_tokens or 0))
        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            raise Refusal(f"anthropic refused ({cat})")
        text, calls = "", []
        for b in resp.content:
            if b.type == "text":
                text += b.text
            elif b.type == "tool_use":
                args = b.input if isinstance(b.input, dict) else json.loads(b.input)
                calls.append(ToolCall(b.id, b.name, args))
        u = resp.usage
        if u is None:
            raise ProviderError("anthropic: response without usage")
        self.budget.record(resp.model, Usage(u.input_tokens or 0, u.output_tokens or 0,
                                             getattr(u, "cache_read_input_tokens", 0) or 0,
                                             getattr(u, "cache_creation_input_tokens", 0) or 0))
        return ChatResult(
            text=text, model=resp.model, provider=self.name,
            usage=Usage(u.input_tokens or 0, u.output_tokens or 0,
                        getattr(u, "cache_read_input_tokens", 0) or 0,
                        getattr(u, "cache_creation_input_tokens", 0) or 0),
            tool_calls=calls, stop_reason=resp.stop_reason, latency_ms=latency)
