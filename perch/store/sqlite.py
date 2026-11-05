"""SQLite implementation of the repository (demo tier).

One table holds every record as JSON, keyed by (kind, id). Provenance columns
are stored alongside so they can be queried without parsing JSON.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from pathlib import Path

from perch.schemas import RECORD_TYPES, Record, Work
from perch.store.base import SORTS, Page, R, Repository, offset_cursor, read_offset
from perch.store.denorm import TEMPLE_SOURCES, columns, matches_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


class SQLiteRepository(Repository):
    def __init__(self, path: str | Path = ":memory:") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), timeout=30)  # API jobs and reads share the file
        self.conn.executescript(SCHEMA)

    def upsert(self, records: Iterable[Record]) -> int:
        rows = [
            (r.kind, r.id, r.source, r.source_url, r.fetched_at.isoformat(), r.model_dump_json())
            for r in records
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?, ?, ?)", rows
            )
        return len(rows)

    def get(self, cls: type[R], id: str) -> R | None:
        row = self.conn.execute(
            "SELECT data FROM records WHERE kind = ? AND id = ?", (cls.kind, id)
        ).fetchone()
        return cls.model_validate_json(row[0]) if row else None

    def list(self, cls: type[R], *, include_samples: bool = False) -> list[R]:
        extra = "" if include_samples else " AND source != 'synthetic'"
        rows = self.conn.execute(
            f"SELECT data FROM records WHERE kind = ?{extra} ORDER BY id", (cls.kind,)
        ).fetchall()
        return [cls.model_validate_json(r[0]) for r in rows]

    def browse(self, cls: type[R], *, temple_only: bool = False, schools: Sequence[str] = (),
               audience_level: Sequence[str] = (), q: str | None = None,
               closes_after: date | None = None, limit: int = 50,
               cursor: str | None = None, scopes: Sequence[str] = (),
               exclude_schools: Sequence[str] = (), sort: str = "name",
               open_only: bool = False, today: date | None = None) -> Page[R]:
        if sort not in SORTS:
            raise ValueError("bad sort")
        today = today or date.today()

        def keep(r: R) -> bool:
            c = columns(r)
            return ((not temple_only or r.source in TEMPLE_SOURCES)
                    and (not scopes or c.scope in scopes)
                    and not (set(exclude_schools) & set(c.schools))
                    and (not schools or bool(set(schools) & set(c.schools)))
                    and (not audience_level or bool(set(audience_level) & set(c.audience_level)))
                    and (not q or matches_text(r, q))
                    and (closes_after is None
                         or (c.deadline is not None and c.deadline >= closes_after))
                    and (not open_only or c.deadline is None or c.deadline >= today))

        # Name order, case-folded, then the id, as in the Postgres store (S43 S6).
        def key(r: R) -> tuple[str, str]:
            return (str(getattr(r, "name", None) or getattr(r, "title", None) or "").lower(), r.id)

        if sort != "name":
            return self._browse_ranked(cls, [r for r in self.list(cls) if keep(r)], key, sort,
                                       today, limit, cursor)
        hits = sorted((r for r in self.list(cls) if keep(r)), key=key)
        after = None
        if cursor:
            after = tuple(json.loads(base64.urlsafe_b64decode(cursor.encode()).decode()))
            if len(after) != 2 or not all(isinstance(x, str) for x in after):
                raise ValueError("bad cursor")
        page = [r for r in hits if after is None or key(r) > after]
        more = len(page) > limit
        page = page[:limit]
        nxt = (base64.urlsafe_b64encode(json.dumps(list(key(page[-1]))).encode()).decode()
               if more else None)
        return Page(items=page, next_cursor=nxt, total=len(hits))

    def _browse_ranked(self, cls: type[R], found: list[R], key: Callable[[R], tuple[str, str]],
                       sort: str, today: date, limit: int, cursor: str | None) -> Page[R]:
        """The closing and amount orders; the cursor is an offset (S49 V1)."""
        def rank(r: R) -> tuple:
            c = columns(r)
            if sort == "amount":
                return (c.amount_max is None, -(c.amount_max or 0), *key(r))
            d = c.deadline
            if d is None:
                return (2, 0, *key(r))
            if d >= today:
                return (0, d.toordinal(), *key(r))
            return (1, -d.toordinal(), *key(r))

        hits = sorted(found, key=rank)
        start = read_offset(cursor)
        page = hits[start:start + limit]
        more = start + limit < len(hits)
        return Page(items=page, next_cursor=offset_cursor(start + limit) if more else None,
                    total=len(hits))

    def epoch(self) -> int:
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'epoch'").fetchone()
        return row[0] if row else 0

    def bump_epoch(self) -> int:
        with self.conn:
            self.conn.execute("INSERT INTO meta VALUES ('epoch', 1) "
                              "ON CONFLICT(key) DO UPDATE SET value = value + 1")
        return self.epoch()

    def get_any(self, id: str) -> Record | None:
        row = self.conn.execute("SELECT kind, data FROM records WHERE id = ? ORDER BY kind LIMIT 1",
                                (id,)).fetchone()
        if not row:
            return None
        cls = next((c for c in RECORD_TYPES if c.kind == row[0]), None)
        return cls.model_validate_json(row[1]) if cls else None

    def works_by_author(self, author_id: str) -> list[Work]:
        rows = self.conn.execute(
            """
            SELECT r.data FROM records r, json_each(json_extract(r.data, '$.author_ids')) a
            WHERE r.kind = 'work' AND a.value = ?
            ORDER BY json_extract(r.data, '$.publication_date') DESC, r.id
            """,
            (author_id,),
        ).fetchall()
        return [Work.model_validate_json(r[0]) for r in rows]

    def close(self) -> None:
        self.conn.close()
