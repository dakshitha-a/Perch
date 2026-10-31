"""Hard spending cap for the hosted API (Anthropic): a budget to the demo, enforced in code.

The Anthropic adapter appends every billed call to its own ledger (JSONL) and checks
the running total before each call: above the warning share it prints a warning once;
at or above the budget it refuses. Unknown prices are charged at the most expensive
listed model, so a missing price can never hide spend.
"""

from __future__ import annotations

import json
import math
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from perch.config import env
from perch.llm.base import ProviderError, Usage

LEDGER = Path("data/logs/anthropic_spend.jsonl")
DEFAULT_BUDGET_USD = 100.0
WARN_SHARE = 0.8


class BudgetExceeded(ProviderError):
    pass


# Spend reserved by calls in flight, per ledger. Parallel calls each checked the ledger
# before any of them was recorded, so together they could pass the cap (review S17).
_LOCK = threading.Lock()
_IN_FLIGHT: dict[str, float] = {}


def budget_usd() -> float:
    return float(env("PERCH_ANTHROPIC_BUDGET_USD", str(DEFAULT_BUDGET_USD)))


def ledger_path() -> Path:
    return Path(env("PERCH_SPEND_LEDGER", str(LEDGER)))


def call_cost(model: str, usage: Usage) -> float:
    from perch.llm import PRICES  # late import: perch.llm imports this module's users

    price = PRICES.get(model) or max(PRICES.values(), key=lambda p: p[1])
    return (usage.input_tokens * price[0] + usage.output_tokens * price[1]
            + usage.cache_read_tokens * price[2] + usage.cache_write_tokens * price[3]) / 1e6


def spent_usd(path: Path | None = None) -> float:
    p = path or ledger_path()
    if not p.is_file():
        return 0.0
    total = 0.0
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = float(json.loads(line)["cost_usd"])
            total += c if not math.isnan(c) else 0.0
    return total


class Budget:
    def __init__(self, limit: float | None = None, path: Path | None = None) -> None:
        self.limit = budget_usd() if limit is None else limit
        self.path = path or ledger_path()
        self._warned = False

    @contextmanager
    def reserve(self, estimate: float) -> Iterator[float]:
        """Check the cap counting the calls already in flight, then hold `estimate` (the
        call's largest likely cost) until the call is recorded or fails."""
        key = str(self.path.resolve())
        with _LOCK:
            spent = self.check(_IN_FLIGHT.get(key, 0.0))
            _IN_FLIGHT[key] = _IN_FLIGHT.get(key, 0.0) + estimate
        try:
            yield spent
        finally:
            with _LOCK:
                _IN_FLIGHT[key] -= estimate

    def check(self, in_flight: float = 0.0) -> float:
        """Raise if the budget is used up; warn once past the warning share. Returns spend.
        `in_flight`: spend reserved by calls not yet recorded."""
        spent = spent_usd(self.path) + in_flight
        if spent >= self.limit:
            raise BudgetExceeded(f"Anthropic budget used: ${spent:.2f} of ${self.limit:.2f}. "
                                 "Refusing the call; use a local model or ask Dakshitha.")
        if spent >= WARN_SHARE * self.limit and not self._warned:
            print(f"warning: Anthropic spend ${spent:.2f} of ${self.limit:.2f} budget",
                  file=sys.stderr)
            self._warned = True
        return spent

    def record(self, model: str, usage: Usage) -> float:
        cost = call_cost(model, usage)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(UTC).isoformat(), "model": model,
                                "input_tokens": usage.input_tokens,
                                "output_tokens": usage.output_tokens,
                                "cache_read_tokens": usage.cache_read_tokens,
                                "cache_write_tokens": usage.cache_write_tokens,
                                "cost_usd": cost}) + "\n")
        return cost
