"""Migrate the public corpus from the demo stores into Postgres (ARCHITECTURE_V1 section 11.2).

Reads, never writes, the SQLite record store, the SYNTHETIC sample store, the LanceDB table
and the embedding cache. Writes `records` and `record_vectors`. Idempotent: a record whose
stored JSON already matches is not touched, and a vector whose text and embedder match is
not rewritten, so a second run changes nothing (and does not bump the epoch).

Opportunity vectors are reused from LanceDB. Before reuse the command checks a sample of
them against the embedding cache entries made by Qwen/Qwen3-Embedding-0.6B (the Lance table
does not record its embedder). Scholarship vectors have no Lance source: they are computed
once on CPU from `perch.student.record_text`. Only counts and ids are printed.
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import numpy as np
from psycopg_pool import ConnectionPool

from perch.embed import DEFAULT_MODEL
from perch.schemas import RECORD_TYPES, Record
from perch.store.denorm import STORED_KINDS
from perch.store.pg import EMBED_DIM, make_pool
from perch.store.postgres import PgVectorIndex, PostgresRepository

BATCH = 1000
SAMPLE_CHECK = 50
VERIFY_PER_INDEX = 20
_CLS = {c.kind: c for c in RECORD_TYPES}


class CorpusError(RuntimeError):
    pass


def _ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise CorpusError(f"store not found: {path}")
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def read_records(path: Path) -> tuple[dict[str, list[Record]], dict[str, int]]:
    """Every stored-kind record in one SQLite store, plus counts of the kinds left out."""
    con = _ro(path)
    try:
        rows = con.execute("SELECT kind, data FROM records ORDER BY kind, id").fetchall()
    finally:
        con.close()
    out: dict[str, list[Record]] = {k: [] for k in STORED_KINDS}
    skipped: dict[str, int] = {}
    for kind, data in rows:
        if kind in STORED_KINDS:
            out[kind].append(_CLS[kind].model_validate_json(data))
        else:
            skipped[kind] = skipped.get(kind, 0) + 1
    return out, skipped


def _json(r: Record) -> object:
    return json.loads(r.model_dump_json())


def _plain(v: object) -> object:
    """Stable form for comparing a stored JSONB value with a fresh dump."""
    return json.loads(json.dumps(v, default=lambda o: o.isoformat()
                                 if isinstance(o, date | datetime) else str(o)))


def _write_records(pool: ConnectionPool, repo: PostgresRepository, label: str,
                   recs: dict[str, list[Record]]) -> dict[str, dict[str, int]]:
    report: dict[str, dict[str, int]] = {}
    for kind, rows in recs.items():
        if not rows:
            continue
        with pool.connection() as conn:
            have = {r[0]: r[1] for r in conn.execute(
                "SELECT id, data FROM records WHERE kind = %s", (kind,))}
        new = changed = same = 0
        todo: list[Record] = []
        for r in rows:
            if r.id not in have:
                new += 1
                todo.append(r)
            elif _plain(have[r.id]) != _json(r):
                changed += 1
                todo.append(r)
            else:
                same += 1
        for i in range(0, len(todo), BATCH):
            repo.upsert(todo[i:i + BATCH])
        report[f"{label}:{kind}"] = {"read": len(rows), "new": new, "changed": changed,
                                     "unchanged": same}
    return report


def _check_samples(recs: dict[str, list[Record]]) -> None:
    """Rule 11: the sample store holds only SYNTHETIC scholarships with sample: ids."""
    for kind, rows in recs.items():
        for r in rows:
            if r.source != "synthetic" or not r.id.startswith("sample:") or kind != "scholarship":
                raise CorpusError("the sample store holds a record that is not a SYNTHETIC "
                                  "sample scholarship")
            if not getattr(r, "canary", None):
                raise CorpusError("a sample record has no canary token")


def _verify_lance_embedder(rows: list[dict], cache: Path | None) -> str:
    """Return how the embedder was confirmed; raise if it cannot be."""
    if cache is None or not cache.exists():
        raise CorpusError("cannot confirm the Lance vectors' embedder: no embedding cache. "
                          f"Pass --cache, or compute vectors again with {DEFAULT_MODEL}.")
    con = _ro(cache)
    pick = random.Random(0).sample(rows, min(SAMPLE_CHECK, len(rows)))
    try:
        for r in pick:
            h = hashlib.sha256(r["text"].encode("utf-8")).hexdigest()
            row = con.execute("SELECT vec FROM vectors WHERE model = ? AND kind = 'doc' "
                              "AND hash = ?", (DEFAULT_MODEL, h)).fetchone()
            if row is None or not np.allclose(np.frombuffer(row[0], dtype=np.float32),
                                              np.asarray(r["vector"], dtype=np.float32),
                                              atol=1e-4):
                raise CorpusError(f"a Lance vector does not match the {DEFAULT_MODEL} "
                                  "embedding cache; not reusing Lance vectors")
    finally:
        con.close()
    return f"{len(pick)} sampled vectors match the {DEFAULT_MODEL} cache"


def read_lance(path: Path, table: str = "opportunities") -> list[dict]:
    import lancedb

    db = lancedb.connect(str(path))
    if table not in db.list_tables().tables:
        raise CorpusError(f"no Lance table {table} in {path}")
    t = db.open_table(table)
    width = t.schema.field("vector").type.list_size
    if width != EMBED_DIM:
        raise CorpusError(f"Lance vectors have {width} dimensions, expected {EMBED_DIM}")
    return t.to_arrow().to_pylist()


def _write_vectors(pool: ConnectionPool, index_name: str, kind: str, ids: list[str],
                   texts: list[str], vecs: list[list[float]]) -> tuple[int, int, int]:
    """Insert missing vectors; replace one only when its text or embedder differs.
    Returns (written, unchanged, orphans)."""
    from pgvector import Vector

    with pool.connection() as conn:
        have = {r[0]: (r[1], r[2]) for r in conn.execute(
            "SELECT record_id, text, embedder FROM record_vectors WHERE index_name = %s",
            (index_name,))}
        known = {r[0] for r in conn.execute("SELECT id FROM records WHERE kind = %s", (kind,))}
    todo = [(i, t, v) for i, t, v in zip(ids, texts, vecs, strict=True)
            if i in known and have.get(i) != (t, DEFAULT_MODEL)]
    orphans = sum(1 for i in ids if i not in known)
    sql = ("INSERT INTO record_vectors (index_name, record_id, record_kind, text, embedding, "
           "embedder, embedded_at, sample, temple_funded, schools) "
           "SELECT %s, r.id, r.kind, %s, %s, %s, now(), r.sample, r.temple_funded, r.schools "
           "FROM records r WHERE r.kind = %s AND r.id = %s "
           "ON CONFLICT (index_name, record_id) DO UPDATE SET text = EXCLUDED.text, "
           "embedding = EXCLUDED.embedding, embedder = EXCLUDED.embedder, "
           "embedded_at = EXCLUDED.embedded_at")
    for i in range(0, len(todo), BATCH):
        with pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(sql, [(index_name, t, Vector([float(x) for x in v]), DEFAULT_MODEL,
                                   kind, rid) for rid, t, v in todo[i:i + BATCH]])
    return len(todo), len(ids) - len(todo) - orphans, orphans


def _cpu_embedder() -> object:
    import os

    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    from perch.embed import get_embedder

    return get_embedder(DEFAULT_MODEL, cache=None, device="cpu")


def migrate_corpus(dsn: str, sqlite_path: Path, lance_path: Path, sample_path: Path | None,
                   cache_path: Path | None = None,
                   embedder_factory: Callable[[], object] | None = None) -> dict:
    """Copy the public corpus into Postgres and verify it. Returns a report dict."""
    from perch.student import record_text

    report: dict = {"records": {}, "vectors": {}, "skipped": {}, "verify": {}}
    pool = make_pool(dsn, max_size=4)
    repo = PostgresRepository(pool=pool, role="owner")
    try:
        public, skipped = read_records(sqlite_path)
        report["skipped"] = skipped
        report["records"].update(_write_records(pool, repo, "public", public))
        samples: dict[str, list[Record]] = {k: [] for k in STORED_KINDS}
        if sample_path is not None:
            samples, _ = read_records(sample_path)
            _check_samples({k: v for k, v in samples.items() if v})
            report["records"].update(_write_records(pool, repo, "sample", samples))

        # Opportunity vectors from Lance.
        lrows = read_lance(lance_path)
        report["verify"]["lance_embedder"] = _verify_lance_embedder(lrows, cache_path)
        w, u, o = _write_vectors(pool, "opportunities", "opportunity",
                                 [r["id"] for r in lrows], [r["text"] for r in lrows],
                                 [list(r["vector"]) for r in lrows])
        report["vectors"]["opportunities"] = {"lance_rows": len(lrows), "written": w,
                                              "unchanged": u, "orphans": o, "source": "lance"}

        # Scholarship vectors: computed once, on CPU.
        sch = public["scholarship"] + samples["scholarship"]
        ids = [s.id for s in sch]
        texts = [record_text(s) for s in sch]  # type: ignore[arg-type]
        with pool.connection() as conn:
            have = {r[0]: (r[1], r[2]) for r in conn.execute(
                "SELECT record_id, text, embedder FROM record_vectors "
                "WHERE index_name = 'scholarships'")}
        need = [k for k, (i, t) in enumerate(zip(ids, texts, strict=True))
                if have.get(i) != (t, DEFAULT_MODEL)]
        vecs: list[list[float]] = []
        if need:
            emb = (embedder_factory or _cpu_embedder)()
            out = np.asarray(emb.embed_documents([texts[k] for k in need]))  # type: ignore[attr-defined]
            if out.shape[1] != EMBED_DIM:
                raise CorpusError(f"embedder returned {out.shape[1]} dimensions")
            vecs = out.tolist()
        w, u, o = _write_vectors(pool, "scholarships", "scholarship",
                                 [ids[k] for k in need], [texts[k] for k in need], vecs)
        report["vectors"]["scholarships"] = {
            "records": len(sch), "written": w, "unchanged": len(sch) - len(need),
            "orphans": o, "source": "computed on CPU" if need else "already present"}

        with pool.connection() as conn:
            try:
                conn.execute("ANALYZE records")
                conn.execute("ANALYZE record_vectors")
            except Exception:  # noqa: BLE001 - only the owner may ANALYZE; not worth failing
                conn.rollback()

        report["verify"].update(_verify(pool, public, samples, lrows))
        changed = (sum(v["new"] + v["changed"] for v in report["records"].values())
                   + sum(v["written"] for v in report["vectors"].values()))
        report["epoch"] = (repo.bump_epoch() if changed or repo.epoch() == 0
                           else repo.epoch())
        report["changed"] = changed
    finally:
        repo.close()
        pool.close()
    return report


def _verify(pool: ConnectionPool, public: dict, samples: dict, lrows: list[dict]) -> dict:
    out: dict = {"mismatches": []}
    with pool.connection() as conn:
        for kind in STORED_KINDS:
            for label, src in (("public", public), ("sample", samples)):
                want = len(src[kind])
                cond = "sample" if label == "sample" else "NOT sample"
                got = conn.execute(f"SELECT count(*) FROM records WHERE kind = %s AND {cond}",
                                   (kind,)).fetchone()[0]
                if want and want != got:
                    out["mismatches"].append(f"{label}:{kind} sqlite {want} postgres {got}")
        got = conn.execute("SELECT count(*) FROM record_vectors WHERE index_name = "
                           "'opportunities'").fetchone()[0]
        if got != len(lrows):
            out["mismatches"].append(f"opportunities lance {len(lrows)} postgres {got}")
        out["vectors_by_index"] = {r[0]: r[1] for r in conn.execute(
            "SELECT index_name, count(*) FROM record_vectors GROUP BY 1")}
        out["records_by_kind"] = {f"{r[0]}{'(sample)' if r[1] else ''}": r[2]
                                  for r in conn.execute("SELECT kind, sample, count(*) FROM "
                                                        "records GROUP BY 1, 2 ORDER BY 1, 2")}
    rng = random.Random(1)
    for name in ("opportunities", "scholarships"):
        idx = PgVectorIndex(index_name=name, pool=pool)
        with pool.connection() as conn:
            rows = conn.execute("SELECT record_id, embedding FROM record_vectors WHERE "
                                "index_name = %s", (name,)).fetchall()
        pick = rng.sample(rows, min(VERIFY_PER_INDEX, len(rows)))
        bad = 0
        for rid, emb in pick:
            vec = emb.to_list() if hasattr(emb, "to_list") else list(emb)
            hit = idx.dense([float(x) for x in vec], 1, include_samples=True)
            bad += 0 if hit and hit[0][0] == rid else 1
        out[f"self_search_{name}"] = f"{len(pick) - bad}/{len(pick)} returned themselves first"
        if bad:
            out["mismatches"].append(f"{name}: {bad} self-searches failed")
    return out


def format_report(rep: dict) -> str:
    lines = ["Records (read / new / changed / unchanged):"]
    for k, v in rep["records"].items():
        lines.append(f"  {k}: {v['read']} / {v['new']} / {v['changed']} / {v['unchanged']}")
    lines.append("Skipped kinds (user data in v1): " + (
        ", ".join(f"{k} {n}" for k, n in rep["skipped"].items()) or "none"))
    lines.append("Vectors:")
    for k, v in rep["vectors"].items():
        lines.append(f"  {k}: " + ", ".join(f"{a} {b}" for a, b in v.items()))
    vf = rep["verify"]
    lines.append(f"Embedder check: {vf['lance_embedder']}")
    lines.append(f"Postgres records: {vf['records_by_kind']}")
    lines.append(f"Postgres vectors: {vf['vectors_by_index']}")
    for k in ("self_search_opportunities", "self_search_scholarships"):
        lines.append(f"{k}: {vf[k]}")
    lines.append("Mismatches: " + ("; ".join(vf["mismatches"]) or "none"))
    lines.append(f"Changed rows this run: {rep['changed']}; epoch {rep['epoch']}")
    return "\n".join(lines)
