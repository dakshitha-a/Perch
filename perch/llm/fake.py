"""Scripted provider for tests: no network, fully deterministic."""

from __future__ import annotations

from collections.abc import Callable

from perch.llm.base import ChatResult, JsonSchema, Message, Provider, TokenChoice, Tool, Usage

Responder = Callable[[list[Message], str | None, JsonSchema | None], str]


class FakeProvider(Provider):
    """Returns scripted replies in order, or the output of a responder function.

    `logprob_tokens` sets the first-token alternatives returned when logprobs are
    requested, as {token: logprob}.
    """

    name = "fake"
    capabilities = frozenset({"tools", "schema", "logprobs", "prompt_cache"})

    def __init__(self, replies: list[str] | None = None, responder: Responder | None = None,
                 logprob_tokens: dict[str, float] | None = None, model: str = "fake-1") -> None:
        self.replies = list(replies or [])
        self.responder = responder
        self.logprob_tokens = logprob_tokens or {}
        self.model = model
        self.calls: list[dict] = []

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        self.calls.append({"messages": messages, "system": system, "schema": schema,
                           "logprobs": logprobs})
        if self.responder:
            text = self.responder(messages, system, schema)
        else:
            text = self.replies.pop(0) if self.replies else ""
        lps = None
        if logprobs and self.logprob_tokens:
            ranked = sorted(self.logprob_tokens.items(), key=lambda kv: -kv[1])[:logprobs]
            lps = [[TokenChoice(t, lp) for t, lp in ranked]]
            text = text or ranked[0][0]
        prompt_words = sum(len(m.content.split()) for m in messages) + len((system or "").split())
        return ChatResult(text=text, model=self.model, provider=self.name,
                          usage=Usage(prompt_words, len(text.split())), stop_reason="stop",
                          top_logprobs=lps)
