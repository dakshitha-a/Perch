"""Audit log of every model call (SPEC section 6): prompt hash, model, version, tokens,
cost, validator result. Prompts are stored as hashes only, never as text (SPEC section 12).

Two event kinds go to one JSONL file: "call" (written by AuditedProvider after each
call) and "validation" (written by the skill once it has checked the output).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from perch.llm import cost_usd
from perch.llm.base import ChatResult, JsonSchema, Message, Provider, Tool

AUDIT_LOG = Path("data/logs/model_calls.jsonl")


def prompt_hash(system: str | None, messages: list[Message], schema: JsonSchema | None,
                tools: list[Tool] | None) -> str:
    payload = json.dumps({"system": system, "messages": [asdict(m) for m in messages],
                          "schema": schema, "tools": [asdict(t) for t in tools or []]},
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class AuditLog:
    def __init__(self, path: Path | None = AUDIT_LOG) -> None:
        self.path = path
        self.events: list[dict] = []  # kept in memory too, for per-run summaries

    def write(self, event: dict) -> None:
        self.events.append(event)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")

    def validation(self, call_id: str, skill: str, passed: bool, errors: list[str],
                   attempt: int, layer: int = 1) -> None:
        self.write({"kind": "validation", "at": datetime.now(UTC).isoformat(),
                    "call_id": call_id, "skill": skill, "layer": layer, "passed": passed,
                    "attempt": attempt, "errors": errors})

    def rejection_rate(self, skill: str | None = None, layer: int = 1) -> tuple[int, int]:
        """(rejected, total) validation events, optionally for one skill."""
        v = [e for e in self.events if e["kind"] == "validation" and e["layer"] == layer
             and (skill is None or e["skill"] == skill)]
        return sum(not e["passed"] for e in v), len(v)

    def spend(self) -> tuple[int, int, float]:
        calls = [e for e in self.events if e["kind"] == "call"]
        return (sum(e["input_tokens"] for e in calls), sum(e["output_tokens"] for e in calls),
                sum(e["cost_usd"] for e in calls if e["cost_usd"] == e["cost_usd"]))


class AuditedProvider(Provider):
    """Wraps a provider; every chat() appends a "call" event. `last_call_id` links the
    validation event that follows."""

    def __init__(self, inner: Provider, log: AuditLog, role: str) -> None:
        self.inner, self.log, self.role = inner, log, role
        self.name, self.model, self.capabilities = inner.name, inner.model, inner.capabilities
        self.last_call_id = ""

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        r = self.inner.chat(messages, system=system, tools=tools, schema=schema,
                            max_tokens=max_tokens, logprobs=logprobs, cache_system=cache_system)
        self.last_call_id = uuid.uuid4().hex[:12]
        self.log.write({
            "kind": "call", "at": datetime.now(UTC).isoformat(), "call_id": self.last_call_id,
            "role": self.role, "provider": r.provider, "requested_model": self.inner.model,
            "model": r.model, "prompt_hash": prompt_hash(system, messages, schema, tools),
            "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
            "cache_read_tokens": r.usage.cache_read_tokens,
            "cache_write_tokens": r.usage.cache_write_tokens, "cost_usd": cost_usd(r),
            "latency_ms": round(r.latency_ms, 1), "stop_reason": r.stop_reason})
        return r

    def close(self) -> None:
        self.inner.close()
