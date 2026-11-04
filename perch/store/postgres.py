"""Postgres implementations of Repository and VectorIndex (ARCHITECTURE_V1 sections 2.2, 2.3).

Public records live in the `records` table, one row per (kind, id), with the full pydantic
record in JSONB and a few filter columns filled from the record itself (perch.store.denorm).
Vectors live in `record_vectors`: dense search through pgvector, sparse search through
stock tsvector (decision D-2). Sort order is `COLLATE "C"` on ids so results match SQLite.

The database role comes from the URL. `role` is a label: a "web" repository refuses writes
before the database does. Nothing here logs a query, a parameter or an exception message.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Sequence
from datetime import date

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from perch.embed import DEFAULT_MODEL
from perch.schemas import RECORD_TYPES, Record, Work
from perch.store.base import Page, R, Repository, VectorIndex
from perch.store.denorm import STORED_KINDS, TEMPLE_SOURCES, TEXT_SQL, columns
from perch.store.pg import EMBED_DIM, make_pool

INDEX_KINDS = {"opportunities": "opportunity", "scholarships": "scholarship"}
_COLS = ("kind, id, source, source_url, fetched_at, data, scope, schools, temple_funded, "
         "audience_level, deadline, amount_max, status")
_UPSERT = (f"INSERT INTO records ({_COLS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
           "%s, %s) ON CONFLICT (kind, id) DO UPDATE SET source = EXCLUDED.source, "
           "source_url = EXCLUDED.source_url, fetched_at = EXCLUDED.fetched_at, "
           "data = EXCLUDED.data, scope = EXCLUDED.scope, schools = EXCLUDED.schools, "
           "temple_funded = EXCLUDED.temple_funded, audience_level = EXCLUDED.audience_level, "
           "deadline = EXCLUDED.deadline, amount_max = EXCLUDED.amount_max, "
           "status = EXCLUDED.status")
_SYNC_VECTORS = ("UPDATE record_vectors SET sample = (%s = 'synthetic'), temple_funded = %s, "
                 "schools = %s WHERE record_kind = %s AND record_id = %s")


def _cls_for(kind: str) -> type[Record] | None:
    return next((c for c in RECORD_TYPES if c.kind == kind), None)


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class PostgresRepository(Repository):
    def __init__(self, dsn: str | None = None, role: str = "worker",
                 pool: ConnectionPool | None = None) -> None:
        if role not in ("web", "worker", "owner"):
            raise ValueError("role must be web, worker or owner")
        self.role = role
        self._owns_pool = pool is None
        self.pool = pool or make_pool(dsn)

    def upsert(self, records: Iterable[Record]) -> int:
        if self.role == "web":
            raise PermissionError("a web repository is read only")
        rows: list[tuple] = []
        syncs: list[tuple] = []
        for r in records:
            if r.kind not in STORED_KINDS:
                raise ValueError("this kind is user data in v1 and is not stored in records")
            c = columns(r)
            rows.append((r.kind, r.id, r.source, r.source_url, r.fetched_at,
                         Jsonb(r.model_dump(mode="json")), c.scope, c.schools, c.temple_funded,
                         c.audience_level, c.deadline, c.amount_max, c.status))
            syncs.append((r.source, c.temple_funded, c.schools, r.kind, r.id))
        if not rows:
            return 0
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(_UPSERT, rows)
            cur.executemany(_SYNC_VECTORS, syncs)
        return len(rows)

    def get(self, cls: type[R], id: str) -> R | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT data FROM records WHERE kind = %s AND id = %s",
                               (cls.kind, id)).fetchone()
        return cls.model_validate(row[0]) if row else None

    def list(self, cls: type[R], *, include_samples: bool = False) -> list[R]:
        sql = "SELECT data FROM records WHERE kind = %s"
        if not include_samples:
            sql += " AND NOT sample"
        with self.pool.connection() as conn:
            rows = conn.execute(sql + ' ORDER BY id COLLATE "C"', (cls.kind,)).fetchall()
        return [cls.model_validate(r[0]) for r in rows]

    def get_any(self, id: str) -> Record | None:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT kind, data FROM records WHERE id = %s ORDER BY kind LIMIT 1",
                               (id,)).fetchone()
        cls = _cls_for(row[0]) if row else None
        return cls.model_validate(row[1]) if cls else None

    def works_by_author(self, author_id: str) -> list[Work]:
        with self.pool.connection() as conn:
            rows = conn.execute(
                "SELECT data FROM records WHERE kind = 'work' AND data->'author_ids' @> %s "
                "ORDER BY data->>'publication_date' DESC NULLS LAST, id COLLATE \"C\"",
                (Jsonb([author_id]),)).fetchall()
        return [Work.model_validate(r[0]) for r in rows]

    def browse(self, cls: type[R], *, temple_only: bool = False, schools: Sequence[str] = (),
               audience_level: Sequence[str] = (), q: str | None = None,
               closes_after: date | None = None, limit: int = 50,
               cursor: str | None = None) -> Page[R]:
        where = ["kind = %s", "NOT sample"]
        args: list = [cls.kind]
        if temple_only:
            where.append("source = ANY(%s)")
            args.append(list(TEMPLE_SOURCES))
        if schools:
            where.append("schools && %s")
            args.append(list(schools))
        if audience_level:
            where.append("audience_level && %s")
            args.append(list(audience_level))
        if q:
            where.append(f"{TEXT_SQL} ILIKE %s")
            args.append(_like(q))
        if closes_after is not None:
            where.append("deadline >= %s")
            args.append(closes_after)
        base = " AND ".join(where)
        page_where, page_args = base, list(args)
        if cursor:
            page_where += ' AND id COLLATE "C" > %s'
            page_args.append(base64.urlsafe_b64decode(cursor.encode()).decode())
        with self.pool.connection() as conn:
            total = conn.execute(f"SELECT count(*) FROM records WHERE {base}", args).fetchone()[0]
            rows = conn.execute(
                f'SELECT id, data FROM records WHERE {page_where} ORDER BY id COLLATE "C" LIMIT %s',
                [*page_args, limit + 1]).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = base64.urlsafe_b64encode(rows[-1][0].encode()).decode() if more else None
        return Page(items=[cls.model_validate(r[1]) for r in rows], next_cursor=nxt, total=total)

    def epoch(self) -> int:
        with self.pool.connection() as conn:
            row = conn.execute("SELECT COALESCE(max(epoch), 0) FROM ingest_runs").fetchone()
        return int(row[0])

    def bump_epoch(self) -> int:
        if self.role == "web":
            raise PermissionError("a web repository is read only")
        with self.pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(7262002)")
            new = int(conn.execute(
                "INSERT INTO ingest_runs (source, started_at, finished_at, epoch) "
                "VALUES ('epoch', now(), now(), (SELECT COALESCE(max(epoch), 0) + 1 FROM "
                "ingest_runs)) RETURNING epoch").fetchone()[0])
        return new

    def close(self) -> None:
        if self._owns_pool:
            self.pool.close()


class PgVectorIndex(VectorIndex):
    """One named index (`opportunities` or `scholarships`) in record_vectors."""

    def __init__(self, dsn: str | None = None, index_name: str = "opportunities",
                 embedder: str = DEFAULT_MODEL, pool: ConnectionPool | None = None) -> None:
        if index_name not in INDEX_KINDS:
            raise ValueError("index_name must be opportunities or scholarships")
        self.name, self.kind, self.embedder = index_name, INDEX_KINDS[index_name], embedder
        self._owns_pool = pool is None
        self.pool = pool or make_pool(dsn)

    def _filters(self, temple_only: bool, schools: Sequence[str], include_samples: bool,
                 args: list) -> str:
        # The index name is a validated literal so the partial HNSW index can be used.
        parts = [f"index_name = '{self.name}'"]
        if not include_samples:
            parts.append("NOT sample")
        if temple_only:
            parts.append("temple_funded")
        if schools:
            parts.append("schools && %s")
            args.append(list(schools))
        return " AND ".join(parts)

    def upsert(self, ids: list[str], texts: list[str], vectors: list[list[float]]) -> int:
        from pgvector import Vector

        rows = list(zip(ids, texts, vectors, strict=True))
        for _, _, v in rows:
            if len(v) != EMBED_DIM:
                raise ValueError(f"vector length must be {EMBED_DIM}")
        n = 0
        with self.pool.connection() as conn, conn.cursor() as cur:
            for rid, text, v in rows:
                cur.execute(
                    "INSERT INTO record_vectors (index_name, record_id, record_kind, text, "
                    "embedding, embedder, embedded_at, sample, temple_funded, schools) "
                    "SELECT %s, r.id, r.kind, %s, %s, %s, now(), r.sample, r.temple_funded, "
                    "r.schools FROM records r WHERE r.kind = %s AND r.id = %s "
                    "ON CONFLICT (index_name, record_id) DO UPDATE SET text = EXCLUDED.text, "
                    "embedding = EXCLUDED.embedding, embedder = EXCLUDED.embedder, "
                    "embedded_at = EXCLUDED.embedded_at, sample = EXCLUDED.sample, "
                    "temple_funded = EXCLUDED.temple_funded, schools = EXCLUDED.schools",
                    (self.name, text, Vector([float(x) for x in v]), self.embedder,
                     self.kind, rid))
                if cur.rowcount != 1:
                    conn.rollback()
                    raise ValueError("an id has no record of the index's kind")
                n += 1
        return n

    def dense(self, vector: list[float], k: int, *, temple_only: bool = False,
              schools: Sequence[str] = (), include_samples: bool = False
              ) -> list[tuple[str, float]]:
        from pgvector import Vector

        v = Vector([float(x) for x in vector])
        args: list = [v]
        where = self._filters(temple_only, schools, include_samples, args)
        with self.pool.connection() as conn:
            # strict_order keeps ranks exact for the rank fusion; ef_search is at least k.
            conn.execute("SELECT set_config('hnsw.iterative_scan', 'strict_order', true), "
                         "set_config('hnsw.ef_search', %s, true)", (str(min(max(k, 40), 1000)),))
            rows = conn.execute(
                "SELECT record_id, 1 - (embedding <=> %s) FROM record_vectors "
                f"WHERE {where} ORDER BY embedding <=> %s, record_id COLLATE \"C\" LIMIT %s",
                [v, *args[1:], v, k]).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def bm25(self, query: str, k: int, *, temple_only: bool = False,
             schools: Sequence[str] = (), include_samples: bool = False
             ) -> list[tuple[str, float]]:
        args: list = []
        where = self._filters(temple_only, schools, include_samples, args)
        with self.pool.connection() as conn:
            rows = conn.execute(
                "WITH q AS (SELECT string_agg(quote_literal(lexeme), ' | ') AS s "
                "FROM unnest(to_tsvector('english', %s))), "
                "tq AS (SELECT to_tsquery('simple', s) AS t FROM q WHERE s IS NOT NULL) "
                "SELECT record_id, ts_rank_cd(tsv, t) AS score FROM record_vectors, tq "
                f"WHERE {where} AND tsv @@ t "
                'ORDER BY score DESC, record_id COLLATE "C" LIMIT %s',
                [query, *args, k]).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def ids(self) -> set[str]:
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT record_id FROM record_vectors WHERE index_name = %s",
                                (self.name,)).fetchall()
        return {r[0] for r in rows}

    def close(self) -> None:
        if self._owns_pool:
            self.pool.close()
