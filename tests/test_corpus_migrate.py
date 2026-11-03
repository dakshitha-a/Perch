"""migrate-corpus on a tiny store: SQLite records, a Lance table and a SYNTHETIC sample store.

All text is SYNTHETIC. Skips without PERCH_TEST_DATABASE_URL; makes and drops its own
perch_test_d_* database.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from perch.db.corpus import CorpusError, migrate_corpus
from perch.embed import DEFAULT_MODEL
from perch.schemas import Opportunity, Scholarship
from perch.store.postgres import PgVectorIndex
from perch.store.sqlite import SQLiteRepository

PG_URL = os.environ.get("PERCH_TEST_DATABASE_URL", "")
T = datetime(2026, 10, 28, tzinfo=UTC)
DIM = 1024

pytestmark = pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set")


def onehot(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


class FakeEmbedder:
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.array([onehot(100 + i) for i in range(len(texts))], dtype=np.float32)


@pytest.fixture
def dsn():
    from perch.db.migrate import migrate

    name = f"perch_test_d_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(PG_URL, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    url = make_conninfo(PG_URL, dbname=name)
    migrate(url)
    try:
        yield url
    finally:
        with psycopg.connect(PG_URL, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def build_stores(tmp: Path, good_cache: bool = True):
    from perch.store.lance import LanceIndex

    opps = [Opportunity(id=f"opp:{i}", opportunity_number=f"N{i}", title=f"SYNTHETIC call {i}",
                        agency="SYNTHETIC Agency", description="synthetic text",
                        source="grants_gov", source_url=f"https://example.invalid/{i}",
                        fetched_at=T) for i in range(3)]
    temple = Scholarship(id="temple:1", name="SYNTHETIC Prize", source="temple_sdfa",
                         source_url="https://example.invalid/s", fetched_at=T)
    sample = Scholarship(id="sample:sch-0001", name="SYNTHETIC Sample Prize", source="synthetic",
                         source_url="https://example.invalid/x", fetched_at=T, canary="CANARY-1")
    with SQLiteRepository(tmp / "perch.db") as repo:
        repo.upsert([*opps, temple])
        repo.conn.execute("INSERT INTO records VALUES ('lead', 'lead:1', 's', 'u', 't', '{}')")
        repo.conn.commit()
    with SQLiteRepository(tmp / "sample.db") as repo:
        repo.upsert([sample])
    texts = [f"{o.title}. {o.description}" for o in opps]
    LanceIndex(tmp / "lance").upsert([o.id for o in opps], texts, [onehot(i) for i in range(3)])
    cache = tmp / "emb.db"
    con = sqlite3.connect(cache)
    con.execute("CREATE TABLE vectors (model TEXT, kind TEXT, hash TEXT, vec BLOB, "
                "PRIMARY KEY (model, kind, hash))")
    for i, t in enumerate(texts):
        v = np.array(onehot(i if good_cache else i + 500), dtype=np.float32)
        con.execute("INSERT INTO vectors VALUES (?, 'doc', ?, ?)",
                    (DEFAULT_MODEL, hashlib.sha256(t.encode()).hexdigest(), v.tobytes()))
    con.commit()
    con.close()
    return cache


def run(dsn, tmp, cache):
    return migrate_corpus(dsn, tmp / "perch.db", tmp / "lance", tmp / "sample.db", cache,
                          embedder_factory=FakeEmbedder)


def test_migrate_corpus_and_idempotent(dsn, tmp_path):
    cache = build_stores(tmp_path)
    rep = run(dsn, tmp_path, cache)
    assert rep["skipped"] == {"lead": 1}
    assert rep["records"]["public:opportunity"]["new"] == 3
    assert rep["records"]["public:scholarship"]["new"] == 1
    assert rep["records"]["sample:scholarship"]["new"] == 1
    assert rep["vectors"]["opportunities"]["written"] == 3
    assert rep["vectors"]["scholarships"]["written"] == 2
    assert rep["verify"]["mismatches"] == []
    with psycopg.connect(dsn) as c:
        # Provenance survives, and the sample is marked apart (rule 11).
        row = c.execute("SELECT source, source_url, fetched_at FROM records "
                        "WHERE id = 'opp:1'").fetchone()
        assert row == ("grants_gov", "https://example.invalid/1", T)
        assert c.execute("SELECT count(*) FROM records WHERE sample AND id LIKE 'sample:%'"
                         ).fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM record_vectors WHERE sample").fetchone()[0] == 1
        before = c.execute("SELECT max(embedded_at) FROM record_vectors").fetchone()[0]
    idx = PgVectorIndex(dsn, "opportunities")
    assert idx.dense(onehot(2), 1)[0][0] == "opp:2"
    sch = PgVectorIndex(dsn, "scholarships")
    assert [i for i, _ in sch.dense(onehot(101), 5)] == ["temple:1"]  # samples hidden
    assert sch.dense(onehot(101), 1, include_samples=True)[0][0] == "sample:sch-0001"
    sch.close()
    idx.close()

    again = run(dsn, tmp_path, cache)
    assert again["changed"] == 0
    assert all(v["new"] == 0 and v["changed"] == 0 for v in again["records"].values())
    assert all(v["written"] == 0 for v in again["vectors"].values())
    with psycopg.connect(dsn) as c:
        assert c.execute("SELECT max(embedded_at) FROM record_vectors").fetchone()[0] == before


def test_refuses_lance_vectors_from_another_embedder(dsn, tmp_path):
    cache = build_stores(tmp_path, good_cache=False)
    with pytest.raises(CorpusError):
        run(dsn, tmp_path, cache)
    with psycopg.connect(dsn) as c:
        assert c.execute("SELECT count(*) FROM record_vectors").fetchone()[0] == 0


def test_refuses_a_sample_store_with_a_real_looking_record(dsn, tmp_path):
    cache = build_stores(tmp_path)
    with SQLiteRepository(tmp_path / "sample.db") as repo:
        repo.upsert([Scholarship(id="temple:9", name="SYNTHETIC Prize", source="temple_sdfa",
                                 source_url="https://example.invalid/s", fetched_at=T)])
    with pytest.raises(CorpusError):
        run(dsn, tmp_path, cache)
