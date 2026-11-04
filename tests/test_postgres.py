"""Postgres-only tests: migrations, row-level security, definer functions, vector search.

All text is SYNTHETIC. They skip without PERCH_TEST_DATABASE_URL (see tests/conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import errors

from perch.schemas import Brief, Opportunity, Scholarship
from perch.store import pg
from perch.store.postgres import PgVectorIndex, PostgresRepository

pytestmark = pytest.mark.usefixtures("pgdb")
T = datetime(2026, 10, 28, tzinfo=UTC)
DIM = 1024


def vec(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def opp(id, title, description=""):
    return Opportunity(id=id, opportunity_number=id, title=title, agency="SYNTHETIC Agency",
                       description=description, source="grants_gov",
                       source_url=f"https://example.invalid/{id}", fetched_at=T)


def sch(n, source="temple_sdfa"):
    sid = f"sample:sch-{n:04d}" if source == "synthetic" else f"temple:{n}"
    return Scholarship(id=sid, name=f"SYNTHETIC Prize {n}", source=source,
                       source_url="https://example.invalid/s", fetched_at=T,
                       canary="CANARY" if source == "synthetic" else None)


def connect(dsn):
    return psycopg.connect(dsn, autocommit=True)


def login(dsn, subject: bytes) -> uuid.UUID:
    with connect(dsn) as c:
        return c.execute("SELECT perch_login_user(%s, %s)", (b"issuer", subject)).fetchone()[0]


# --- migrations ---

def test_migrate_is_idempotent(pgdb):
    from perch.db.migrate import migrate

    assert migrate(pgdb.admin) == []
    with connect(pgdb.admin) as c:
        versions = [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY 1")]
        assert versions[0] == "0001_roles" and len(versions) >= 5
        owner = c.execute("SELECT tableowner FROM pg_tables WHERE tablename = 'records'"
                          ).fetchone()[0]
        assert owner == "perch_owner"
        fn_owner = c.execute("SELECT pg_get_userbyid(proowner) FROM pg_proc "
                             "WHERE proname = 'perch_claim_job'").fetchone()[0]
        assert fn_owner == "perch_definer"


def test_every_fenced_table_has_force_rls(pgdb):
    with connect(pgdb.admin) as c:
        rows = dict(c.execute("SELECT relname, relrowsecurity AND relforcerowsecurity "
                              "FROM pg_class WHERE relname = ANY(%s)",
                              (["users", "consents", "user_data", "jobs", "job_events",
                                "spend_ledger"],)).fetchall())
    assert rows and all(rows.values())


def test_cli_db_migrate_reports_current(pgdb, capsys):
    from perch.cli import main

    assert main(["db", "migrate", "--dsn", pgdb.admin]) == 0
    assert "already current" in capsys.readouterr().out


# --- records ---

def test_kinds_not_stored_in_records_are_refused(pg_clean):
    with PostgresRepository(pg_clean.worker) as r, pytest.raises(ValueError):
        r.upsert([Brief(id="B1", researcher_id="A1", source="perch", source_url="x://y",
                        fetched_at=T)])


def test_web_repository_is_read_only(pg_clean):
    with PostgresRepository(pg_clean.worker) as w:
        w.upsert([opp("O1", "SYNTHETIC one")])
    with PostgresRepository(pg_clean.web, role="web") as r:
        assert r.get(Opportunity, "O1").title == "SYNTHETIC one"
        with pytest.raises(PermissionError):
            r.upsert([opp("O2", "x")])
    with PostgresRepository(pg_clean.web, role="worker") as r, pytest.raises(
            errors.InsufficientPrivilege):
        r.upsert([opp("O2", "x")])  # the database refuses even a mislabelled repository


def test_sample_check_holds_in_both_directions(pg_clean):
    with connect(pg_clean.admin) as c:
        for src, rid in (("synthetic", "plain"), ("openalex", "sample:x")):
            with pytest.raises(errors.CheckViolation):
                c.execute("INSERT INTO records (kind, id, source, source_url, fetched_at, data) "
                          "VALUES ('award', %s, %s, 'x://y', now(), '{}')", (rid, src))


# --- vectors ---

def test_vector_index_dense_sparse_and_filters(pg_clean):
    with PostgresRepository(pg_clean.worker) as repo:
        repo.upsert([opp("O1", "Kidney transplant donors", "allocation of organs"),
                     opp("O2", "Quantum sensing", "magnetometers"),
                     opp("O3", "Cell biology", "leukemia cells")])
        repo.upsert([sch(1), sch(2, "synthetic")])
    idx = PgVectorIndex(pg_clean.worker, "opportunities")
    assert idx.upsert(["O1", "O2", "O3"], ["kidney transplant donors", "quantum sensing",
                                          "leukemia cells"], [vec(0), vec(1), vec(2)]) == 3
    assert idx.dense(vec(1), 3)[0][0] == "O2"
    assert idx.dense(vec(1), 3)[0][1] == pytest.approx(1.0)
    assert idx.bm25("kidney donors (transplant)", 3)[0][0] == "O1"  # stemming, punctuation
    assert idx.bm25("zzzz", 3) == [] and idx.bm25("", 3) == []
    assert idx.ids() == {"O1", "O2", "O3"}
    assert idx.dense(vec(0), 5, temple_only=True) == []  # no record is temple funded
    with pytest.raises(ValueError):
        idx.upsert(["O1"], ["x"], [[0.0] * 3])  # wrong length
    with pytest.raises(ValueError):
        idx.upsert(["missing"], ["x"], [vec(3)])  # no such record
    # Samples stay out of results unless asked for (standing rule 11).
    sidx = PgVectorIndex(pg_clean.worker, "scholarships")
    sidx.upsert(["temple:1", "sample:sch-0002"], ["real prize", "sample prize"], [vec(4), vec(4)])
    assert [i for i, _ in sidx.dense(vec(4), 5)] == ["temple:1"]
    assert {i for i, _ in sidx.dense(vec(4), 5, include_samples=True)} == {
        "temple:1", "sample:sch-0002"}
    assert [i for i, _ in sidx.bm25("prize", 5)] == ["temple:1"]
    # Re-upserting a record keeps its vector row.
    with PostgresRepository(pg_clean.worker) as repo:
        repo.upsert([opp("O1", "Kidney transplant donors v2")])
    assert idx.ids() == {"O1", "O2", "O3"}


# --- row-level security ---

def test_perch_web_cannot_read_another_users_rows(pg_clean):
    a, b = login(pg_clean.web, b"subject-a"), login(pg_clean.web, b"subject-b")
    assert a != b
    pool = pg.make_pool(pg_clean.web, max_size=2)
    try:
        with pg.user_tx(pool, a) as c:
            c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                      "VALUES (%s, 'cv', 'student', 1, %s)", (a, b"SYNTHETIC-blob-a"))
        with pg.user_tx(pool, b) as c:
            c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                      "VALUES (%s, 'cv', 'student', 1, %s)", (b, b"SYNTHETIC-blob-b"))
        with pg.user_tx(pool, a) as c:
            rows = c.execute("SELECT user_id, blob FROM user_data").fetchall()
            assert [(r[0], bytes(r[1])) for r in rows] == [(a, b"SYNTHETIC-blob-a")]
            assert c.execute("SELECT count(*) FROM users").fetchone()[0] == 1
            # Another user's id is refused on write, and updates reach nothing.
            with pytest.raises(errors.InsufficientPrivilege):
                c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                          "VALUES (%s, 'entry', 'student', 1, %s)", (b, b"x"))
        with pg.user_tx(pool, a) as c:
            assert c.execute("UPDATE user_data SET blob = %s WHERE user_id = %s",
                             (b"x", b)).rowcount == 0
            assert c.execute("DELETE FROM user_data WHERE user_id = %s", (b,)).rowcount == 0
        # No user set: a fenced read returns zero rows.
        with pg.public_tx(pool) as c:
            assert c.execute("SELECT count(*) FROM user_data").fetchone()[0] == 0
    finally:
        pool.close()


def test_force_rls_holds_for_the_owner_and_the_table_owner_sees_nothing(pg_clean):
    a = login(pg_clean.web, b"subject-owner-test")
    pool = pg.make_pool(pg_clean.web, max_size=1)
    try:
        with pg.user_tx(pool, a) as c:
            c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                      "VALUES (%s, 'cv', 'student', 1, %s)", (a, b"SYNTHETIC"))
    finally:
        pool.close()
    with connect(pg_clean.owner) as c:  # owns the tables, has no policy
        assert c.execute("SELECT count(*) FROM user_data").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                      "VALUES (%s, 'cv', 'researcher', 1, %s)", (a, b"x"))
    with connect(pg_clean.admin) as c:
        c.execute("SET ROLE perch_definer")  # the definer policy still sees the row
        assert c.execute("SELECT count(*) FROM user_data").fetchone()[0] == 1


def test_guest_jobs_are_fenced_by_session_hash(pg_clean):
    h1, h2 = b"\x01" * 32, b"\x02" * 32
    pool = pg.make_pool(pg_clean.web, max_size=2)
    try:
        with pg.guest_tx(pool, h1) as c:
            jid = c.execute("INSERT INTO jobs (kind, guest_sid_hash, idempotency_key, "
                            "max_attempts) VALUES ('brief', %s, 'k1', 3) RETURNING id",
                            (h1,)).fetchone()[0]
        with pytest.raises(errors.InsufficientPrivilege), pg.guest_tx(pool, h1) as c:
            c.execute("INSERT INTO jobs (kind, guest_sid_hash, idempotency_key, "
                      "max_attempts) VALUES ('brief', %s, 'k2', 3)", (h2,))
        with pg.guest_tx(pool, h1) as c:
            assert c.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
            assert c.execute("SELECT perch_queue_position(%s)", (jid,)).fetchone()[0] == 0
        with pg.guest_tx(pool, h2) as c:
            assert c.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    finally:
        pool.close()


def test_web_may_only_cancel_a_job(pg_clean):
    a = login(pg_clean.web, b"subject-cancel")
    pool = pg.make_pool(pg_clean.web, max_size=2)
    try:
        with pg.user_tx(pool, a) as c:
            jid = c.execute("INSERT INTO jobs (kind, user_id, idempotency_key, max_attempts) "
                            "VALUES ('brief', %s, 'k', 3) RETURNING id", (a,)).fetchone()[0]
        with pytest.raises(errors.InsufficientPrivilege), pg.user_tx(pool, a) as c:
            c.execute("UPDATE jobs SET state = 'succeeded' WHERE id = %s", (jid,))
        with pytest.raises(errors.InsufficientPrivilege), pg.user_tx(pool, a) as c:
            c.execute("UPDATE jobs SET payload = '{\"x\": 1}' WHERE id = %s", (jid,))
        with pg.user_tx(pool, a) as c:
            assert c.execute("UPDATE jobs SET state = 'cancelled' WHERE id = %s",
                             (jid,)).rowcount == 1
    finally:
        pool.close()


# --- definer functions, called with no perch.user_id set ---

def test_login_user_finds_or_creates_and_ignores_deleted(pg_clean):
    first = login(pg_clean.web, b"subject-x")
    assert login(pg_clean.web, b"subject-x") == first
    with connect(pg_clean.admin) as c:
        c.execute("UPDATE users SET deleted_at = now() WHERE id = %s", (first,))
    assert login(pg_clean.web, b"subject-x") != first  # a new id after deletion


def test_claim_job_inactive_users_delete_rows_and_actors(pg_clean):
    user = login(pg_clean.web, b"subject-purge")
    pool = pg.make_pool(pg_clean.web, max_size=2)
    try:
        with pg.user_tx(pool, user) as c:
            c.execute("INSERT INTO jobs (kind, user_id, idempotency_key, max_attempts, priority) "
                      "VALUES ('brief', %s, 'k1', 3, 5), ('handoff', %s, 'k2', 3, 1)",
                      (user, user))
            c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                      "VALUES (%s, 'cv', 'student', 1, %s)", (user, b"SYNTHETIC"))
    finally:
        pool.close()
    with connect(pg_clean.worker) as w:  # no perch.user_id set
        row = w.execute("SELECT id, kind, state, attempts, lease_owner FROM "
                        "perch_claim_job('w1/t1', ARRAY[]::text[], 60)").fetchone()
        assert row[1:] == ("handoff", "running", 1, "w1/t1")  # lower priority number first
        assert w.execute("SELECT count(*) FROM perch_claim_job('w1/t2', ARRAY['ingest'], 60)"
                         ).fetchone()[0] == 0
        assert w.execute("SELECT count(*) FROM perch_inactive_users('1 day', 10)"
                         ).fetchone()[0] == 0
        assert w.execute("INSERT INTO spend_ledger (user_id, role, provider, model, "
                         "input_tokens, output_tokens, cost_usd) VALUES (%s, 'fit', 'fake', "
                         "'m', 1, 1, 0.01), (NULL, 'gate', 'fake', 'm', 1, 1, 0.01)",
                         (user,)).rowcount == 2
        w.execute("INSERT INTO audit_log (event, actor) VALUES ('login', %s)", (user,))
    with connect(pg_clean.admin) as c:
        c.execute("UPDATE users SET last_active_at = now() - interval '400 days'")
        c.execute("UPDATE audit_log SET at = now() - interval '100 days'")
    with connect(pg_clean.worker) as w:
        assert [r[0] for r in w.execute("SELECT * FROM perch_inactive_users('365 days', 10)")
                ] == [user]
        assert w.execute("SELECT perch_null_old_actors('90 days')").fetchone()[0] == 1
        w.execute("SELECT perch_delete_user_rows(%s)", (user,))
        # The worker's own policies show it the ledger rows left (the NULL-user one).
        assert w.execute("SELECT count(*) FROM spend_ledger").fetchone()[0] == 1
    with connect(pg_clean.admin) as c:
        for table in ("users", "user_data", "jobs"):
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert c.execute("SELECT actor FROM audit_log").fetchone()[0] is None


def test_functions_are_not_open_to_the_wrong_role(pg_clean):
    with connect(pg_clean.web) as c:
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT * FROM perch_claim_job('w', ARRAY[]::text[], 60)")
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT perch_delete_user_rows(gen_random_uuid())")
    with connect(pg_clean.worker) as c, pytest.raises(errors.InsufficientPrivilege):
        c.execute("SELECT perch_login_user(%s, %s)", (b"i", b"s"))


def test_grants_follow_the_contract(pg_clean):
    with connect(pg_clean.web) as c:
        for sql in ("SELECT * FROM schema_migrations", "SELECT * FROM audit_log",
                    "UPDATE records SET status = 'x'", "DELETE FROM public_cache"):
            with pytest.raises(errors.InsufficientPrivilege):
                c.execute(sql)
    with connect(pg_clean.worker) as c:
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT * FROM schema_migrations")
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT * FROM audit_log")
        c.execute("INSERT INTO audit_log (event) VALUES ('model_call')")
        with pytest.raises(errors.CheckViolation):
            c.execute("INSERT INTO audit_log (event, detail) VALUES ('x', %s::jsonb)",
                      ('{"k": "' + "a" * 3000 + '"}',))


# --- shred_log (crypto review finding 4) ---

def test_perch_web_can_log_only_its_own_shred(pg_clean):
    a, b = login(pg_clean.web, b"subject-shred-a"), login(pg_clean.web, b"subject-shred-b")
    pool = pg.make_pool(pg_clean.web, max_size=2)
    try:
        with pg.user_tx(pool, a) as c:
            c.execute("INSERT INTO shred_log (user_id) VALUES (%s)", (a,))
        with pytest.raises(errors.InsufficientPrivilege):
            with pg.user_tx(pool, a) as c:
                c.execute("INSERT INTO shred_log (user_id) VALUES (%s)", (b,))
        with pytest.raises(errors.InsufficientPrivilege):  # no signed-in user at all
            with pg.public_tx(pool) as c:
                c.execute("INSERT INTO shred_log (user_id) VALUES (%s)", (b,))
    finally:
        pool.close()
    with connect(pg_clean.worker) as c:  # the worker records inactivity purges for any id
        c.execute("INSERT INTO shred_log (user_id) VALUES (%s)", (b,))
        ids = {r[0] for r in c.execute("SELECT user_id FROM shred_log")}
    assert ids == {a, b}


# --- Temple dataset load (Phase 4 task 5) ---

def test_temple_dataset_loads_into_postgres_idempotently(pg_clean, tmp_path):
    import json

    from perch import temple_dataset as td
    from tests.test_temple_dedupe import sch

    recs = [sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
                amount=2500),
            sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd"),
            sch("temple_pages:c", "SYNTHETIC Harbor Prize", "SDFA", "https://x.example/sdfa")]
    ex = tmp_path / "e.jsonl"
    ex.write_text("".join(td.row_json(r) + "\n" for r in recs))
    path, man, _ = td.build_dataset(ex, tmp_path / "ds", commit="c")
    assert man["records"] == 2
    with PostgresRepository(pg_clean.worker, role="worker") as repo:
        assert td.load_dataset(path, repo) == 2
        assert td.load_dataset(path, repo) == 2
        got = repo.list(Scholarship)
    assert {r.id for r in got} == {json.loads(x)["id"] for x in path.read_text().splitlines()}
    quill = next(r for r in got if r.name == "SYNTHETIC Quill Award")
    assert quill.scope == "temple_wide" and len(quill.seen_on) == 2
    with connect(pg_clean.admin) as c:
        (n,) = c.execute("SELECT count(*) FROM records WHERE source = 'temple_pages'").fetchone()
    assert n == 2


def test_migration_0009_rederives_scope_and_schools_for_stored_rows(tmp_path):
    """Rows stored before 0009 have scope external and no schools; 0009 re-derives both."""
    import json
    import shutil

    from perch.db.migrate import MIGRATIONS_DIR, migrate
    from tests.conftest import PG_URL, _with

    old = tmp_path / "old"
    old.mkdir()
    for f in MIGRATIONS_DIR.glob("*.sql"):
        if not f.name.startswith("0009_"):
            shutil.copy(f, old / f.name)
    name = f"perch_test_a_{uuid.uuid4().hex[:10]}"
    with connect(PG_URL) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    admin = _with(PG_URL, dbname=name)
    try:
        assert not any(v.startswith("0009") for v in migrate(admin, old))
        rows = [("temple_pages:a", {"scope": None, "schools": ["CST"]}),
                ("temple_pages:b", {"scope": None, "schools": []}),
                ("temple_pages:c", {"scope": "temple_wide", "schools": ["Fox", "CST"]}),
                ("temple_pages:d", {"scope": "school", "schools": []})]
        with connect(admin) as c:
            for rid, d in rows:
                c.execute("INSERT INTO records (kind, id, source, source_url, fetched_at, data)"
                          " VALUES ('scholarship', %s, 'temple_pages', 'x://y', now(), %s)",
                          (rid, json.dumps(d)))
            c.execute("INSERT INTO records (kind, id, source, source_url, fetched_at, data) VALUES"
                      " ('opportunity', 'O1', 'grants_gov', 'x://y', now(), '{}')")
        assert migrate(admin) == ["0009_scope_unstated"]
        with connect(admin) as c:
            got = {r[0]: (r[1], r[2]) for r in c.execute(
                "SELECT id, scope, schools FROM records")}
            with pytest.raises(errors.CheckViolation):
                c.execute("UPDATE records SET scope = 'school' WHERE id = 'temple_pages:b'")
    finally:
        with connect(PG_URL) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    assert got == {"temple_pages:a": ("unstated", ["CST"]), "temple_pages:b": ("unstated", []),
                   "temple_pages:c": ("temple_wide", ["CST", "Fox"]),
                   "temple_pages:d": ("unstated", []), "O1": ("external", [])}
