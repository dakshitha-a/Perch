"""Model layer: one interface, several adapters, a model per role.

A provider spec is "<adapter>:<model>", e.g. "ollama:qwen3.8:27b",
"anthropic:claude-sonnet-5-5", "openai:Qwen/Qwen3-8B" or "fake:fake-1". Each role
reads PERCH_LLM_<ROLE> from the environment, then PERCH_LLM_DEFAULT, then the
built-in default below. Roles: profile_summary, fit_explainer, handoff, scout,
decide.
"""

from __future__ import annotations

from perch.config import env
from perch.llm.base import (
    ChatResult,
    Message,
    Provider,
    ProviderError,
    Refusal,
    TokenChoice,
    Tool,
    ToolCall,
    ToolResult,
    Usage,
)

__all__ = ["ChatResult", "Message", "Provider", "ProviderError", "Refusal", "TokenChoice",
           "Tool", "ToolCall", "ToolResult", "Usage", "cost_usd", "get_provider",
           "provider_for_role"]

ROLES = ("profile_summary", "fit_explainer", "handoff", "scout", "decide")
# Fallback when no profile applies; the chat model per profile is in perch/profiles.py.
DEFAULT_SPEC = "ollama:qwen3.8:27b"

# USD per million tokens: (input, output, cache read, cache write). Anthropic first-party
# rates from the claude-api skill model table (cached 2026-10-06); 5-minute cache writes
# bill at 1.25x input. Local models cost nothing per token.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}


def cost_usd(result: ChatResult) -> float:
    if result.provider in ("ollama", "fake"):
        return 0.0
    price = PRICES.get(result.model)
    if price is None:
        return float("nan")  # unknown price: shown as unknown, never guessed
    u = result.usage
    return (u.input_tokens * price[0] + u.output_tokens * price[1]
            + u.cache_read_tokens * price[2] + u.cache_write_tokens * price[3]) / 1e6


def get_provider(spec: str) -> Provider:
    adapter, _, model = spec.partition(":")
    if adapter == "ollama":
        from perch.llm.ollama import OllamaProvider

        return OllamaProvider(model, base_url=env("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    if adapter == "openai":
        from perch.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(model, base_url=env("OPENAI_BASE_URL",
                                                         "http://127.0.0.1:8000/v1"),
                                    api_key=env("OPENAI_API_KEY"))
    if adapter == "anthropic":
        from perch.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model or "claude-sonnet-5-5", api_key=env("ANTHROPIC_API_KEY"))
    if adapter == "fake":
        from perch.llm.fake import FakeProvider

        return FakeProvider(model=model or "fake-1")
    raise ValueError(f"unknown provider adapter {adapter!r} in {spec!r}")


def spec_for_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; roles are {', '.join(ROLES)}")
    from perch.profiles import current

    return env(f"PERCH_LLM_{role.upper()}") or env("PERCH_LLM_DEFAULT") or current().chat


def provider_for_role(role: str) -> Provider:
    return get_provider(spec_for_role(role))
