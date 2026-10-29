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

DEFAULT_MODEL = "claude-sonnet-5-5"  # SPEC section 7: skill 2 default is Claude Sonnet via API
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(Provider):
    name = "anthropic"
    capabilities = frozenset({"tools", "schema", "prompt_cache"})

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None,
                 fallbacks: bool = True, effort: str | None = None, client: object = None
                 ) -> None:
        if client is None:
            import anthropic  # vendor SDK, imported only inside perch/llm

            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.client = client
        self.model = model
        self.fallbacks = fallbacks
        self.effort = effort

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 16000, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        kw: dict = {"model": self.model, "max_tokens": max_tokens,
                    "messages": [{"role": m.role, "content": m.content} for m in messages]}
        if system:
            block: dict = {"type": "text", "text": system}
            if cache_system:
                block["cache_control"] = {"type": "ephemeral"}
            kw["system"] = [block]
        if tools:
            kw["tools"] = [{"name": t.name, "description": t.description,
                            "input_schema": t.parameters, "strict": True} for t in tools]
        output_config: dict = {}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if self.effort:
            output_config["effort"] = self.effort
        if output_config:
            kw["output_config"] = output_config
        if self.fallbacks:
            kw["betas"] = [FALLBACK_BETA]
            kw["fallbacks"] = "default"
        t0 = time.perf_counter()
        resp = self.client.beta.messages.create(**kw)
        latency = (time.perf_counter() - t0) * 1000
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
        return ChatResult(
            text=text, model=resp.model, provider=self.name,
            usage=Usage(u.input_tokens or 0, u.output_tokens or 0,
                        getattr(u, "cache_read_input_tokens", 0) or 0,
                        getattr(u, "cache_creation_input_tokens", 0) or 0),
            tool_calls=calls, stop_reason=resp.stop_reason, latency_ms=latency)
