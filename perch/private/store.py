"""Write paths switched to memory for a private session (docs/design/PRIVATE_MODE.md).

`OverlayRepository` reads the shared store through a read-only SQLite connection and
keeps every write in a dict the session owns. A write path that someone forgets to
route here fails instead of persisting, because the base connection cannot write.
`ReadOnlyCacheEmbedder` reads the shared embedding cache and never adds to it, so the
hash of a private text never reaches disk.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from perch.embed import CachedEmbedder, Embedder, content_hash
from perch.schemas import RECORD_TYPES, Record, Work
from perch.store.base import R, Repository


class OverlayRepository(Repository):
    """Memory over a read-only base. `mem` maps (kind, id) to a record and belongs to
    the session, so it outlives this object and dies with the session."""

    def __init__(self, base: str | Path, mem: dict[tuple[str, str], Record]) -> None:
        self.mem = mem
        self.conn: sqlite3.Connection | None = None
        if Path(base).is_file():
            self.conn = sqlite3.connect(f"file:{Path(base).resolve()}?mode=ro", uri=True,
                                        timeout=30, check_same_thread=False)

    def upsert(self, records: Iterable[Record]) -> int:
        n = 0
        for r in records:
            self.mem[(r.kind, r.id)] = r
            n += 1
        return n

    def _base(self, sql: str, args: tuple) -> list[tuple]:
        return self.conn.execute(sql, args).fetchall() if self.conn else []

    def get(self, cls: type[R], id: str) -> R | None:
        if (x := self.mem.get((cls.kind, id))) is not None:
            return x  # type: ignore[return-value]
        rows = self._base("SELECT data FROM records WHERE kind = ? AND id = ?", (cls.kind, id))
        return cls.model_validate_json(rows[0][0]) if rows else None

    def list(self, cls: type[R]) -> list[R]:
        rows = self._base("SELECT data FROM records WHERE kind = ? ORDER BY id", (cls.kind,))
        out = {x.id: x for x in (cls.model_validate_json(r[0]) for r in rows)}
        out.update({i: x for (k, i), x in self.mem.items() if k == cls.kind})
        return [out[i] for i in sorted(out)]

    def get_any(self, id: str) -> Record | None:
        for (_, i), x in sorted(self.mem.items()):
            if i == id:
                return x
        rows = self._base("SELECT kind, data FROM records WHERE id = ? ORDER BY kind LIMIT 1",
                          (id,))
        if not rows:
            return None
        cls = next((c for c in RECORD_TYPES if c.kind == rows[0][0]), None)
        return cls.model_validate_json(rows[0][1]) if cls else None

    def works_by_author(self, author_id: str) -> list[Work]:
        rows = self._base(
            """
            SELECT r.data FROM records r, json_each(json_extract(r.data, '$.author_ids')) a
            WHERE r.kind = 'work' AND a.value = ?
            """, (author_id,))
        out = {w.id: w for w in (Work.model_validate_json(r[0]) for r in rows)}
        out.update({i: x for (k, i), x in self.mem.items()
                    if k == "work" and author_id in x.author_ids})
        return sorted(out.values(), key=lambda w: (-(w.publication_date.toordinal()
                                                     if w.publication_date else 0), w.id))

    def close(self) -> None:
        if self.conn:
            self.conn.close()


class ReadOnlyCacheEmbedder(Embedder):
    """Cache hits from the shared cache; misses are computed and never written."""

    def __init__(self, inner: Embedder) -> None:
        self.inner, self.name, self.dim = inner, inner.name, inner.dim

    def _get(self, texts: list[str], kind: str) -> np.ndarray:
        c = self.inner
        if not isinstance(c, CachedEmbedder):
            return c.embed_queries(texts) if kind == "query" else c.embed_documents(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        missing: list[int] = []
        with c.lock:
            for i, t in enumerate(texts):
                row = c.conn.execute("SELECT vec FROM vectors WHERE model=? AND kind=? AND "
                                     "hash=?", (c.name, kind, content_hash(t))).fetchone()
                if row:
                    out[i] = np.frombuffer(row[0], dtype=np.float32)
                else:
                    missing.append(i)
            if missing:
                todo = [texts[i] for i in missing]
                vecs = (c.inner.embed_queries(todo) if kind == "query"
                        else c.inner.embed_documents(todo))
                for i, v in zip(missing, vecs, strict=True):
                    out[i] = v
        return out

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._get(texts, "doc")

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._get(texts, "query")
