"""Provider-neutral types and the one interface every model adapter implements.

Standing rule 6: vendor SDKs are imported only inside perch/llm/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

JsonSchema = dict[str, Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: JsonSchema


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """The outcome of one tool call, sent back to the model in the next user turn."""

    call_id: str
    name: str
    content: str  # JSON text
    is_error: bool = False


@dataclass
class Message:
    role: str  # "user" or "assistant"
    content: str
    # An assistant turn that asked for tools, and the user turn that answers it. Each
    # adapter serialises these its own way (content blocks, or "tool" role messages).
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class TokenChoice:
    token: str
    logprob: float


@dataclass
class ChatResult:
    text: str
    model: str  # as the provider reports it (the model that actually served the call)
    provider: str
    usage: Usage = field(default_factory=Usage)
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    latency_ms: float = 0.0
    # One entry per generated token: the top alternatives with log probabilities.
    top_logprobs: list[list[TokenChoice]] | None = None


class ProviderError(RuntimeError):
    pass


class Refusal(ProviderError):
    """The provider declined the request (e.g. a safety classifier)."""


class Provider(ABC):
    name: str  # adapter name, e.g. "ollama"
    model: str
    # Features this adapter supports: "tools", "schema", "logprobs", "prompt_cache".
    capabilities: frozenset[str] = frozenset()

    @abstractmethod
    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        """One model call. `schema` constrains the reply to JSON matching it.

        `logprobs` > 0 asks for that many top alternatives per output token (only
        where "logprobs" is a capability). `cache_system` marks the system prompt
        as a cacheable prefix where the provider supports prompt caching.
        """

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources."""

    @property
    def spec(self) -> str:
        return f"{self.name}:{self.model}"
