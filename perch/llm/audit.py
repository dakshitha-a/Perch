"""Audit log of every model call (SPEC section 6): prompt hash, model, version, tokens,
cost, validator result. Prompts are stored as hashes only, never as text (SPEC section 12).

Two event kinds go to one JSONL file: "call" (written by AuditedProvider after each
call) and "validation" (written by the skill once it has checked the output).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from perch.config import env
from perch.llm import cost_usd
from perch.llm.base import ChatResult, JsonSchema, Message, Provider, Tool

AUDIT_LOG = Path("data/logs/model_calls.jsonl")


def prompt_hash(system: str | None, messages: list[Message], schema: JsonSchema | None,
                tools: list[Tool] | None) -> str:
    payload = json.dumps({"system": system, "messages": [asdict(m) for m in messages],
                          "schema": schema, "tools": [asdict(t) for t in tools or []]},
                         sort_keys=True)
    key = env("PERCH_AUDIT_KEY")
    if key:  # keyed, so a guessed prompt cannot be confirmed against the log
        return hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if env("PERCH_ENV") == "prod":
        raise RuntimeError("PERCH_AUDIT_KEY is not set (required when PERCH_ENV=prod)")
    return hashlib.sha256(payload.encode()).hexdigest()  # dev only: a plain, unkeyed hash


MAX_EVENTS = 20000  # in-memory cap; the oldest events drop first

# Validator error text can quote a model sentence that paraphrases the user's CV, so the
# log never holds it (rule 5). Each message maps to a stable code; first match wins, run on
# the message with quoted fragments removed.
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_PATTERNS = [
    ("unsupported", r"^unsupported\b"),
    ("unparseable", r"unparse|not valid json|could not parse|schema"),
    ("cited_id_unknown", r"cited id .*not in the input|names no record|not one of the given"),
    ("cited_id_missing", r"cited_ids must|does not list it|cite 1 to 3"),
    ("date_invalid", r"\bdate\b.*not a real date"),
    ("date_unsupported", r"\bdate\b.*not in any cited"),
    ("number_unsupported", r"\bnumber\b.*not in any cited"),
    ("link_unsupported", r"\blink\b.*not in any cited"),
    ("action_word", r"\bword\b.*not in any cited|describe fit only|do not direct"),
    ("fragment", r"fragment"),
    ("sentence_count", r"sentence|exactly two"),
    ("point_count", r"give \d+ to \d+ points|holds at most"),
    ("ids_mismatch", r"asks_ids|you_ids"),
    ("missing_form", r"nothing the applicant added|a gap in the record"),
    ("record_only", r"describe the record|cite only records"),
]
_CODES = [(c, re.compile(p)) for c, p in _PATTERNS]


def error_code(msg: str) -> str:
    plain = _QUOTED.sub("", msg)
    for code, rx in _CODES:
        if rx.search(plain):
            return code
    return "other"


class AuditLog:
    def __init__(self, path: Path | None = AUDIT_LOG) -> None:
        self.path = path
        self.events: list[dict] = []  # kept in memory too, for per-run summaries
        self._lock = threading.Lock()

    def write(self, event: dict) -> None:
        with self._lock:
            self._write(event)

    def _write(self, event: dict) -> None:
        self.events.append(event)
        if len(self.events) > MAX_EVENTS:
            del self.events[:len(self.events) - MAX_EVENTS]
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")

    def validation(self, call_id: str, skill: str, passed: bool, errors: list[str],
                   attempt: int, layer: int = 1) -> None:
        """Logs error codes and counts only; the full text stays with the caller, which hands
        it back to the model as regeneration feedback."""
        codes = dict(sorted(Counter(error_code(e) for e in errors).items()))
        self.write({"kind": "validation", "at": datetime.now(UTC).isoformat(),
                    "call_id": call_id, "skill": skill, "layer": layer, "passed": passed,
                    "attempt": attempt, "error_count": len(errors), "error_codes": codes})

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
    """Wraps a provider; every chat() appends a "call" event. `last_call_id` (per thread,
    since skills call in parallel) links the validation event that follows."""

    def __init__(self, inner: Provider, log: AuditLog, role: str) -> None:
        self.inner, self.log, self.role = inner, log, role
        self.name, self.model, self.capabilities = inner.name, inner.model, inner.capabilities
        self._local = threading.local()

    @property
    def last_call_id(self) -> str:
        return getattr(self._local, "call_id", "")

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0,
             cache_system: bool = False) -> ChatResult:
        r = self.inner.chat(messages, system=system, tools=tools, schema=schema,
                            max_tokens=max_tokens, logprobs=logprobs, cache_system=cache_system)
        self._local.call_id = uuid.uuid4().hex[:12]
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


class CountedProvider(AuditedProvider):
    """An audited provider that also adds up its own calls' tokens and dollars, for one
    Scout session's budget (S28: a shared audit log would mix in other sessions' calls)."""

    def __init__(self, inner: Provider, log: AuditLog, role: str) -> None:
        super().__init__(inner, log, role)
        self.tokens, self.usd = 0, 0.0
        self._count_lock = threading.Lock()

    def chat(self, messages: list[Message], **kw: object) -> ChatResult:  # type: ignore[override]
        r = super().chat(messages, **kw)
        c = cost_usd(r)
        with self._count_lock:
            self.tokens += r.usage.input_tokens + r.usage.output_tokens
            self.usd += c if c == c else 0.0  # unknown price (nan) is reported by the log
        return r
