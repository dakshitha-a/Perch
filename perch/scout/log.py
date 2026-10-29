"""Scout's log: one JSONL line per session start, question, tool call and answer.

Tool calls are logged with their arguments and with hashes of the arguments and the
result, so a session can be replayed: `perch scout replay <session>` re-runs each
logged call and compares result hashes. Questions and answers are stored as hashes
only. Private sessions write no Scout log (Q14).
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

SCOUT_LOG = Path("data/logs/scout.jsonl")
# Tools whose result depends on something outside the store, so a hash mismatch on
# replay is expected: a model writes the explanation; OpenAlex search results change.
NOT_REPLAYABLE = {"explain_fit": "model output", "resolve_author": "live OpenAlex search"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


class ScoutLog:
    def __init__(self, path: Path = SCOUT_LOG) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, event: dict) -> None:
        event = {"at": datetime.now(UTC).isoformat(), **event}
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, sort_keys=True, default=str) + "\n")

    def events(self, session: str) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [e for e in map(json.loads, f) if e.get("session") == session]


def replay(log: ScoutLog, session: str, ctx_factory: Callable[[str, str], object]) -> list[dict]:
    """Re-run every logged tool call of a session; one row per call with "match" true,
    false, or None when the tool is not replayable or the call never ran."""
    from perch.scout.tools import TOOLS, ToolError

    events = log.events(session)
    start = next((e for e in events if e["kind"] == "session"), None)
    if start is None:
        raise KeyError(f"no session {session!r} in {log.path}")
    ctx = ctx_factory(start["researcher"], start["as_of"])
    rows = []
    for e in (e for e in events if e["kind"] == "tool"):
        row = {"turn": e["turn"], "tool": e["tool"], "logged": e["status"], "match": None}
        if e["status"] == "done" and e["tool"] in NOT_REPLAYABLE:
            row["note"] = f"not replayed: {NOT_REPLAYABLE[e['tool']]}"
        elif e["status"] == "done":
            args = {k: v for k, v in e["arguments"].items() if v is not None}
            try:
                result = TOOLS[e["tool"]][1](ctx, **args)
            except ToolError as err:
                result = {"error": str(err)}
            row["match"] = digest(result) == e["result_hash"]
        else:
            row["note"] = "not run in the session"
        rows.append(row)
    return rows
