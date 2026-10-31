"""Write paths switched to memory for a private session (docs/design/PRIVATE_MODE.md).

`OverlayRepository` reads the shared store through a read-only SQLite connection and
keeps every write in a dict the session owns. A write path that someone forgets to
route here fails instead of persisting, because the base connection cannot write.
`ReadOnlyCacheEmbedder` reads the shared embedding cache and adds only the vectors of
public works (P6), so the hash of a private text never reaches disk.

Since S23 every brief runs in a session, so public records fetched for a researcher
(OpenAlex, NIH RePORTER, NSF) may be written through to the shared store when the
session allows it: public data stays cached. Only those kinds from those sources pass;
briefs, leads and anything private stay in memory.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from perch.embed import CachedEmbedder, Embedder, content_hash
from perch.schemas import RECORD_TYPES, Record, Work
from perch.store.base import R, Repository

# What a session may write to the shared store: public records from public sources.
PUBLIC_KINDS = ("researcher", "work", "award", "organisation")
PUBLIC_SOURCES = ("openalex", "nih_reporter", "nsf")


def is_public(r: Record) -> bool:
    return (r.kind in PUBLIC_KINDS and r.source in PUBLIC_SOURCES
            and not r.id.startswith(("private:", "sample:")))


class OverlayRepository(Repository):
    """Memory over a read-only base. `mem` maps (kind, id) to a record and belongs to
    the session, so it outlives this object and dies with the session."""

    def __init__(self, base: str | Path, mem: dict[tuple[str, str], Record],
                 public_writes: bool = False) -> None:
        self.mem, self.base, self.public_writes = mem, Path(base), public_writes
        self.conn: sqlite3.Connection | None = None
        if Path(base).is_file():
            self.conn = sqlite3.connect(f"file:{Path(base).resolve()}?mode=ro", uri=True,
                                        timeout=30, check_same_thread=False)

    def upsert(self, records: Iterable[Record]) -> int:
        n = 0
        public: list[Record] = []
        for r in records:
            if self.public_writes and is_public(r):
                public.append(r)
            else:
                self.mem[(r.kind, r.id)] = r
            n += 1
        if public:  # through the store's own writer, as a stored brief would
            from perch.store.sqlite import SQLiteRepository

            with SQLiteRepository(self.base) as w:
                w.upsert(public)
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
    """Cache hits from the shared cache; misses are computed and never written, except
    for a text in `public`: the text of a public work the session's brief is built from
    (review P6). A document's text, or anything the visitor typed, is never in it."""

    def __init__(self, inner: Embedder, public: set[str] | None = None) -> None:
        self.inner, self.name, self.dim = inner, inner.name, inner.dim
        self.public = public if public is not None else set()

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
                keep = [i for i in missing if texts[i] in self.public]
                if keep:
                    with c.conn:
                        for i in keep:
                            c.conn.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)",
                                           (c.name, kind, content_hash(texts[i]),
                                            out[i].astype(np.float32).tobytes()))
        return out

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._get(texts, "doc")

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._get(texts, "query")
