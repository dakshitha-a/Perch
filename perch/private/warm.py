"""Warm demo briefs, held in memory (S24 task 9; Q31 answered 2026-10-30).

Every brief is a session since S23, so a demo researcher's brief took about 45 s on
stage. At server start a background thread builds one default brief per researcher in
`PERCH_WARM_AUTHORS` (OpenAlex ids, comma-separated) in a session of its own, never on
disk. A visitor who asks for the same default brief (no documents, no context, local
models, explanations on) gets a deep copy in their own session at once, with their own
keep and dismiss state. Nothing about visitors is stored; a copy is dropped when its
session ends. A warm brief is rebuilt when the day changes, so its as-of date stays today.

Review P5: the builds go through the brief job runner, one brief at a time like any
visitor's, instead of a thread beside it on the same model; and a timer rebuilds them
just after midnight, so the first visitor of the day does not find them stale.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from perch.config import env
from perch.privacy import PrivateSettings
from perch.private.session import PrivateService, PrivateSession, PrivateSessions
from perch.schemas import Brief, Record
from perch.sources import openalex as oa


@dataclass
class Warm:
    day: date
    brief_id: str
    mem: dict[tuple[str, str], Record]


def warm_authors() -> list[str]:
    raw = env("PERCH_WARM_AUTHORS") or ""
    return [a for a in (oa.parse_author_id(x.strip()) for x in raw.split(",")) if a]


def seconds_to_rebuild(now: datetime) -> float:
    """Seconds from `now` to five minutes past the next local midnight."""
    nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(),
                           now.tzinfo) + timedelta(minutes=5)
    return (nxt - now).total_seconds()


class WarmBriefs:
    def __init__(self, sessions: PrivateSessions, settings: PrivateSettings,
                 authors: list[str], today: callable = date.today,
                 submit: Callable[[str, Callable[[], None]], None] | None = None) -> None:
        self.sessions, self.settings, self.authors, self.today = sessions, settings, authors, today
        self.ready: dict[str, Warm] = {}
        self.lock = threading.Lock()
        self.building = False
        self.submit = submit  # the brief job runner's submit; a thread of its own if None
        self.timer: threading.Timer | None = None

    def start(self) -> None:
        """Build every warm brief in the background; the server answers meanwhile."""
        with self.lock:
            if self.building or not self.authors:
                return
            self.building = True
        if self.submit:
            self.submit(f"warm-{self.today().isoformat()}", self._build_all)
        else:
            threading.Thread(target=self._build_all, name="perch-warm", daemon=True).start()

    def schedule(self) -> None:
        """Rebuild just after each midnight, before the day's first visitor."""
        if not self.authors:
            return

        def tick() -> None:
            self.start()
            self.schedule()

        self.timer = threading.Timer(seconds_to_rebuild(datetime.now()), tick)
        self.timer.daemon = True
        self.timer.start()

    def _build_all(self) -> None:
        try:
            for aid in self.authors:
                try:
                    self.build(aid)
                except Exception:  # noqa: BLE001 - a warm brief is a convenience; visitors build live
                    pass
        finally:
            self.building = False

    def build(self, aid: str) -> Warm | None:
        s = PrivateSession("warm", 0.0)
        s.service = PrivateService(self.sessions.base, s, self.settings)
        b = s.service.create_private(aid, explain=True)
        s.service.run(b.id)
        got = s.service.get(b.id)
        if not got or got[0].status != "done":
            return None
        w = Warm(date.fromisoformat(got[0].options["as_of"]), b.id, dict(s.mem))
        with self.lock:
            self.ready[aid] = w
        return w

    def take(self, s: PrivateSession, author_id: str | None) -> Brief | None:
        """A copy of the warm brief in `s`, or None (the caller builds it live)."""
        aid = oa.parse_author_id(author_id or "")
        with self.lock:
            w = self.ready.get(aid or "")
        if w is None:
            return None
        if w.day != self.today():
            self.start()  # stale: rebuild in the background, build this one live
            return None
        for key, r in w.mem.items():
            s.mem[key] = r.model_copy(deep=True)
        s.brief_id = w.brief_id
        return s.mem[("brief", w.brief_id)]


def is_default(req: object, s: PrivateSession) -> bool:
    """The request a warm brief answers: a researcher, nothing added, local models."""
    return bool(req.author_id) and not s.docs and not s.cloud and req.explain \
        and req.as_of is None and req.min_amount is None and req.top == 10 \
        and not any(req.context().values())


__all__ = ["WarmBriefs", "is_default", "warm_authors"]
