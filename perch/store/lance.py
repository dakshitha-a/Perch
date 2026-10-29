"""LanceDB implementation of VectorIndex (demo tier): cosine dense search plus BM25.

Verified against lancedb 0.40.0: FTS via create_index(config=FTS()), scores in
`_score`; cosine distance in `_distance`; upsert via merge_insert on `id`.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import lancedb
from lancedb.index import FTS

from perch.store.base import VectorIndex


class LanceIndex(VectorIndex):
    """One writer at a time: concurrent briefs on a cold index otherwise race to create
    the table and the FTS index (lance commit conflict, seen in S8)."""

    def __init__(self, path: str | Path = "data/lance", table: str = "opportunities") -> None:
        Path(path).mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(path))
        self.name = table
        names = self.db.list_tables().tables  # lancedb 0.40: a response object, not a list
        self.table = self.db.open_table(table) if table in names else None
        self.lock = threading.Lock()

    def upsert(self, ids: list[str], texts: list[str], vectors: list[list[float]]) -> int:
        rows = [{"id": i, "text": t, "vector": [float(x) for x in v]}
                for i, t, v in zip(ids, texts, vectors, strict=True)]
        if not rows:
            return 0
        with self.lock:
            return self._upsert(rows)

    def _upsert(self, rows: list[dict]) -> int:
        if self.table is None:
            self.table = self.db.create_table(self.name, data=rows)
        else:
            (self.table.merge_insert("id").when_matched_update_all()
             .when_not_matched_insert_all().execute(rows))
        self.table.create_index("text", config=FTS(stem=True, remove_stop_words=True))
        return len(rows)

    def dense(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        if self.table is None:
            return []
        hits = (self.table.search(list(map(float, vector)), vector_column_name="vector")
                .metric("cosine").limit(k).to_list())
        return [(h["id"], 1.0 - float(h["_distance"])) for h in hits]

    def bm25(self, query: str, k: int) -> list[tuple[str, float]]:
        # Keep words only: the FTS query parser treats some punctuation as syntax.
        q = " ".join(re.findall(r"[A-Za-z0-9]+", query))
        if self.table is None or not q:
            return []
        hits = self.table.search(q, query_type="fts").limit(k).to_list()
        return [(h["id"], float(h["_score"])) for h in hits]

    def ids(self) -> set[str]:
        if self.table is None:
            return set()
        return set(self.table.to_arrow().column("id").to_pylist())
