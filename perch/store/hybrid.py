"""Public records from Postgres, other kinds in a scratch SQLite file.

Not used by the app since S49 (B10): `perch serve`, `perch worker`, `perch mcp` and
`perch scout` read PostgresRepository directly, because a brief and its leads are the user's
encrypted data and every other kind is a public record. Kept only for the scripts and bench
harnesses that still build one (scripts/walk_server.py, scripts/e2e_student_brief.py,
bench/cpu_timings.py, bench/gpu_timings.py).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

from psycopg_pool import ConnectionPool

from perch.schemas import Record, Work
from perch.store.base import Facets, Page, R, Repository
from perch.store.denorm import STORED_KINDS
from perch.store.postgres import PostgresRepository
from perch.store.sqlite import SQLiteRepository


class HybridRepository(Repository):
    def __init__(self, pool: ConnectionPool, scratch: str | Path) -> None:
        self.pg = PostgresRepository(role="worker", pool=pool)
        self.scratch = SQLiteRepository(str(scratch))

    def _side(self, kind: str) -> Repository:
        return self.pg if kind in STORED_KINDS else self.scratch

    def upsert(self, records: Iterable[Record]) -> int:
        recs = list(records)
        n = self.pg.upsert([r for r in recs if r.kind in STORED_KINDS])
        return n + self.scratch.upsert([r for r in recs if r.kind not in STORED_KINDS])

    def get(self, cls: type[R], id: str) -> R | None:
        return self._side(cls.kind).get(cls, id)

    def list(self, cls: type[R], *, include_samples: bool = False) -> list[R]:
        return self._side(cls.kind).list(cls, include_samples=include_samples)

    def get_any(self, id: str) -> Record | None:
        return self.pg.get_any(id) or self.scratch.get_any(id)

    def works_by_author(self, author_id: str) -> list[Work]:
        return self.pg.works_by_author(author_id)

    def browse(self, cls: type[R], *, temple_only: bool = False, schools: Sequence[str] = (),
               audience_level: Sequence[str] = (), q: str | None = None,
               closes_after: date | None = None, limit: int = 50,
               cursor: str | None = None, scopes: Sequence[str] = (),
               exclude_schools: Sequence[str] = (), sort: str = "name",
               open_only: bool = False, today: date | None = None) -> Page[R]:
        return self.pg.browse(cls, temple_only=temple_only, schools=schools,
                              audience_level=audience_level, q=q, closes_after=closes_after,
                              limit=limit, cursor=cursor, scopes=scopes,
                              exclude_schools=exclude_schools, sort=sort, open_only=open_only,
                              today=today)

    def facets(self, cls: type[R]) -> Facets:
        return self.pg.facets(cls)

    def epoch(self) -> int:
        return self.pg.epoch()

    def bump_epoch(self) -> int:
        return self.pg.bump_epoch()

    def close(self) -> None:
        self.scratch.close()  # the pool is shared and owned by the worker
