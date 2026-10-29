"""Live Scout sessions for the API, held in memory (a restart forgets them).

Each session belongs to one brief. Model and tool work runs on a job runner, so the
API answers at once and the web app polls `view()`. One action at a time per
session: a second one while the first is running is refused.
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from perch.jobs import JobRunner
from perch.scout import make_scout
from perch.scout.log import ScoutLog
from perch.scout.loop import Mode, Scout, Session

MAX_SESSIONS = 200


class Busy(RuntimeError):
    pass


@dataclass
class Entry:
    scout: Scout
    session: Session
    brief_id: str
    busy: bool = False
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class ScoutHub:
    def __init__(self, service: object, runner: JobRunner, log: ScoutLog | None = None) -> None:
        self.service, self.runner, self.log = service, runner, log
        self.entries: OrderedDict[str, Entry] = OrderedDict()

    def start(self, brief_id: str, researcher_id: str, question: str, mode: Mode) -> Entry:
        scout = make_scout(self.service, researcher_id, brief_id=brief_id, mode=mode,
                           log=self.log)
        e = Entry(scout, scout.open(), brief_id)
        self.entries[e.session.id] = e
        while len(self.entries) > MAX_SESSIONS:
            self.entries.popitem(last=False)
        self._run(e, lambda: scout.ask(e.session, question))
        return e

    def get(self, sid: str) -> Entry | None:
        return self.entries.get(sid)

    def act(self, e: Entry, action: str, card_id: str | None = None,
            question: str | None = None) -> None:
        s, scout = e.session, e.scout
        if action == "ask":
            self._run(e, lambda: scout.ask(s, question or ""))
        elif action == "approve":
            self._run(e, lambda: scout.approve(s, card_id))
        elif action == "skip":
            self._run(e, lambda: scout.skip(s, card_id))
        elif action == "mode":
            scout.mode = s.mode = "run" if s.mode == "ask" else "ask"
            if s.mode == "run" and s.status == "awaiting_approval":
                self._run(e, lambda: scout.approve(s))
        else:
            raise ValueError(f"unknown action {action!r}")

    def _run(self, e: Entry, fn: Callable[[], object]) -> None:
        with e.lock:
            if e.busy:
                raise Busy("Scout is still working on the last step.")
            e.busy, e.error = True, None

        def job() -> None:
            try:
                fn()
            except Exception as err:  # noqa: BLE001 - shown by type only, never the text
                e.error = f"Scout stopped: {type(err).__name__}"
                e.session.status = "failed"
            finally:
                e.busy = False

        self.runner.submit(f"scout:{e.session.id}:{secrets.token_hex(3)}", job)


def view(e: Entry) -> dict:
    s = e.session
    cards = [{"id": c.id, "tool": c.tool, "arguments": c.arguments, "status": c.status,
              "detail": c.detail, "records": record_ids(c.result)} for c in s.cards]
    exchanges = []
    for i, x in enumerate(s.exchanges):
        end = s.exchanges[i + 1]["cards_from"] if i + 1 < len(s.exchanges) else len(cards)
        exchanges.append({**{k: v for k, v in x.items() if k != "cards_from"},
                          "cards": cards[x["cards_from"]:end]})
    return {"id": s.id, "brief_id": e.brief_id, "status": s.status, "busy": e.busy,
            "error": e.error, "mode": s.mode, "model": s.model, "policy": s.policy,
            "tokens": s.tokens, "usd": round(s.usd, 4), "exchanges": exchanges}


def record_ids(result: dict | None, cap: int = 12) -> list[str]:
    """Record ids a tool result names, for the card's evidence links."""
    out: list[str] = []

    def walk(v: object) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                if k in ("id", "opportunity") and isinstance(x, str) and x not in out:
                    out.append(x)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(result or {})
    return out[:cap]
