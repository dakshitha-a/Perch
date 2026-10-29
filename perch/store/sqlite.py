"""SQLite implementation of the repository (demo tier).

One table holds every record as JSON, keyed by (kind, id). Provenance columns
are stored alongside so they can be queried without parsing JSON.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from perch.schemas import RECORD_TYPES, Record, Work
from perch.store.base import R, Repository

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

    def list(self, cls: type[R]) -> list[R]:
        rows = self.conn.execute(
            "SELECT data FROM records WHERE kind = ? ORDER BY id", (cls.kind,)
        ).fetchall()
        return [cls.model_validate_json(r[0]) for r in rows]

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
