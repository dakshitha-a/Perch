"""Account routes, delete-my-data, the purge job, quotas and the no-leak checks (S41 part B).

SYNTHETIC text only. Needs PERCH_TEST_DATABASE_URL and PERCH_TEST_REDIS_URL (DB 15). The
tombstone test also needs PERCH_TEST_KEYS_DATABASE_URL. Auth is replaced with
`app.dependency_overrides`, because the sign-in work lives in perch/auth.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
import redis as redis_lib
from fastapi import FastAPI
from fastapi.testclient import TestClient

from perch import crypto, jobs, redisx
from perch.auth import deps
from perch.auth.session import Session
from perch.jobs import JobState, PostgresRunner, Timing
from perch.keystore import EnvKeyStore, InMemoryKeyRepository
from perch.llm.fake import FakeProvider
from perch.redisx import QuotaExceeded
from perch.shredhooks import publish_hook, shred_log_hook
from perch.user import delete, docs, quota
from perch.user.briefs import UserBriefStore, create_user_brief, using_store
from perch.user.data import UserData
from perch.user.models import CvDoc, EntryDoc, StoredBrief, UserDoc
from perch.user.routes import UserServices, router
from tests.conftest import PG_URL
from tests.test_api import make
from tests.user_helpers import CANARY, make_env, new_user

REDIS_URL = os.environ.get("PERCH_TEST_REDIS_URL", "")
KEYS_URL = os.environ.get("PERCH_TEST_KEYS_DATABASE_URL", "")
pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]
PERSONA = Path(__file__).resolve().parent.parent / "data/synthetic/persona-1"
FAST = Timing(lease_s=60, heartbeat_s=0.2, reaper_s=0.3, poll_s=0.05, drain_s=10)
EMAIL, PHONE = "synthetic.person" + "@" + "example.invalid", "215-555-0142"  # built, not literal


@pytest.fixture
def rds():
    assert REDIS_URL.rstrip("/").endswith("/15"), "tests use Redis DB 15 only"
    r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()
    r.close()


@dataclass
class Env:
    pg: object
    uid: uuid.UUID
    ud: UserData
    runner: PostgresRunner
    r: redis_lib.Redis
    client: TestClient
    session: Session
    pool: object
    keys: InMemoryKeyRepository


@pytest.fixture
def env(pg_clean, web_pool, rds):
    keys = InMemoryKeyRepository()
    crypto.configure(repo=keys, keystore=EnvKeyStore(make_env()),
                     shred_hooks=[shred_log_hook(web_pool), publish_hook(rds)])
    uid = new_user(pg_clean)
    ud = UserData(web_pool)
    runner = PostgresRunner(pool=web_pool, timing=FAST)
    sess = Session(sid="s-" + uuid.uuid4().hex, user_id=uid, guest=False,
                   roles=frozenset({"student", "researcher"}), audience="student", csrf="c",
                   display_name=None, created=time.time(), abs_exp=time.time() + 3600,
                   consent_version=1)
    app = FastAPI()
    app.include_router(router)
    app.state.user_services = UserServices(pool=web_pool, ud=ud, runner=runner, redis=rds)
    app.dependency_overrides[deps.require_user] = lambda: sess
    app.dependency_overrides[deps.require_csrf] = lambda: None
    redisx.create_session(rds, uid=uid, roles=["student"], audience="student")
    yield Env(pg_clean, uid, ud, runner, rds, TestClient(app), sess, web_pool, keys)
    crypto.configure()


def sql(pgdb, query, *args):
    with psycopg.connect(pgdb.admin, autocommit=True) as c:
        cur = c.execute(query, args)
        return cur.fetchall() if cur.description else []


def job_state(pgdb, jid) -> str:
    return sql(pgdb, "SELECT state FROM jobs WHERE id = %s", jid)[0][0]


def run_worker(pgdb, kinds, until, timeout=30):
    w = PostgresRunner(pgdb.worker, timing=FAST, pool_size=4)
    stop = threading.Event()
    t = threading.Thread(target=w.run_forever, args=("w-acct", kinds, 1, stop))
    t.start()
    try:
        end = time.monotonic() + timeout
        while time.monotonic() < end and not until():
            time.sleep(0.1)
    finally:
        stop.set()
        t.join()
        w.close()


# --- CV and entries ---

def test_cv_upload_blanks_contacts_and_lists_labels_only(env):
    cv = (PERSONA / "cv.md").read_text() + f"\nContact: {EMAIL}, {PHONE}\n"
    r = env.client.post("/me/docs", json={"kind": "cv", "text": cv, "filename": "cv.md"})
    assert r.status_code == 200, r.text
    got = env.ud.get(env.uid, uuid.UUID(r.json()["id"]), CvDoc)
    assert EMAIL not in got.text and PHONE not in got.text and "[contact removed]" in got.text
    assert got.facts  # the deterministic parse ran
    listed = env.client.get("/me/docs").json()
    assert [d["kind"] for d in listed] == ["cv"] and "text" not in listed[0]
    assert EMAIL not in env.client.get("/me/docs").text
    # ciphertext at rest
    (blob,) = sql(env.pg, "SELECT blob FROM user_data WHERE id = %s", r.json()["id"])[0]
    assert b"PERCH-CANARY-CV-7Q4X" not in bytes(blob) and EMAIL.encode() not in bytes(blob)


def test_second_cv_replaces_first_and_entries_are_capped(env, monkeypatch):
    for text in ("SYNTHETIC cv one", "SYNTHETIC cv two"):
        env.client.post("/me/docs", json={"kind": "cv", "text": text})
    assert [d["chars"] for d in env.client.get("/me/docs").json()] == [len("SYNTHETIC cv two")]
    monkeypatch.setattr(docs, "MAX_ENTRIES", 2)
    for i in range(2):
        assert env.client.post("/me/docs", json={"kind": "entry", "text": f"SYNTHETIC {i}"}
                               ).status_code == 200
    r = env.client.post("/me/docs", json={"kind": "entry", "text": "SYNTHETIC extra"})
    assert r.status_code == 422 and "SYNTHETIC extra" not in r.text


def test_bad_uploads_get_plain_sentences_that_never_quote_the_input(env):
    r = env.client.post("/me/docs", json={"kind": "cv", "data": "!!not base64!!",
                                          "filename": "cv.pdf"})
    assert r.status_code == 422 and "not base64" not in r.text
    r = env.client.post("/me/docs", json={"kind": "cv", "text": "   "})
    assert r.status_code == 422
    r = env.client.post("/me/docs", json={"kind": "cv", "data": "AAAA", "filename": "cv.exe"})
    assert r.status_code == 422


def test_delete_of_a_foreign_or_brief_row_is_404(env, pg_clean, web_pool):
    other = new_user(pg_clean)
    rid = env.ud.put(other, "entry", "student", EntryDoc(text=CANARY))
    assert env.client.delete(f"/me/docs/{rid}").status_code == 404
    assert env.ud.get(other, rid, EntryDoc) is not None
    bid = env.ud.put(env.uid, "brief", "student", StoredBrief(
        brief=__import__("perch.schemas", fromlist=["Brief"]).Brief(
            id="b", source="perch", source_url="perch://b", fetched_at=datetime.now(UTC),
            researcher_id="r")))
    assert env.client.delete(f"/me/docs/{bid}").status_code == 404  # only cv, doc, entry go here


def test_briefs_listing_and_read_are_the_owners_only(env, pg_clean, tmp_path):
    _, svc = make(tmp_path)
    b = create_user_brief(svc, env.ud, env.uid, "student", "A5026494099")
    assert [x["id"] for x in env.client.get("/me/briefs").json()] == [b.id]
    assert env.client.get(f"/me/briefs/{b.id}").json()["brief"]["id"] == b.id
    assert env.client.get(f"/me/briefs/{uuid.uuid4()}").status_code == 404
    other = new_user(pg_clean)
    env.session.user_id = other  # the same app, another account
    assert env.client.get(f"/me/briefs/{b.id}").status_code == 404
    assert env.client.get("/me/briefs").json() == []


# --- no leaks ---

def test_model_prompts_never_hold_contacts_and_text_never_reaches_logs_or_audit(
        env, pg_clean, tmp_path, caplog):
    _, svc = make(tmp_path)
    seen: list[str] = []

    def responder(messages, system, schema):
        seen.append((system or "") + " ".join(m.content for m in messages))
        return ""

    svc.models.provider = lambda spec: FakeProvider(responder=responder)
    text = f"{CANARY} We study gait. Write to {EMAIL} or call {PHONE}. https://example.invalid/me"
    caplog.set_level(logging.DEBUG)
    rid = docs.add(env.ud, env.uid, "researcher", "proposal", text=text)
    b = create_user_brief(svc, env.ud, env.uid, "researcher", "A5026494099",
                          as_of=datetime(2026, 10, 28).date(), doc_ids=[rid])
    store = UserBriefStore(env.ud, env.uid, "researcher", b.id)
    store.load()
    with using_store(store):
        svc.run(b.id)
    assert seen, "the fake model was called"
    for prompt in seen:
        assert EMAIL not in prompt and PHONE not in prompt and "example.invalid" not in prompt
    # nowhere in plain text: logs, the audit log, the jobs table, the model-call JSONL
    assert CANARY not in caplog.text
    assert CANARY not in repr(sql(env.pg, "SELECT * FROM audit_log"))
    assert CANARY not in repr(sql(env.pg, "SELECT payload::text, error_code FROM jobs"))
    for f in tmp_path.rglob("*.jsonl"):
        assert CANARY not in f.read_text()
    assert env.ud.get(env.uid, rid, UserDoc).abstract.count(CANARY) == 1  # it is stored, encrypted
    (blob,) = sql(env.pg, "SELECT blob FROM user_data WHERE id = %s", rid)[0]
    assert CANARY.encode() not in bytes(blob)


def test_a_blob_that_fails_validation_logs_no_value(env, caplog):
    rid = env.ud.put(env.uid, "entry", "student", EntryDoc(text=CANARY))
    caplog.set_level(logging.DEBUG)
    r = env.client.get(f"/me/briefs/{rid}")  # an entry is not a brief
    assert r.status_code == 404 and CANARY not in r.text and CANARY not in caplog.text


# --- delete-my-data ---

def test_delete_my_data_follows_the_order_and_leaves_nothing(env, pg_clean, tmp_path):
    _, svc = make(tmp_path)
    env.client.post("/me/docs", json={"kind": "cv", "text": "SYNTHETIC cv"})
    env.client.post("/me/docs", json={"kind": "entry", "text": "SYNTHETIC entry"})
    b = create_user_brief(svc, env.ud, env.uid, "student", "A5026494099")
    env.ud.link_openalex(env.uid, "A5026494099")
    queued = env.runner.submit("brief", {"brief_id": b.id}, env.uid, "k1", audience="student")
    assert sql(pg_clean, "SELECT count(*) FROM user_data WHERE user_id = %s", env.uid) == [(3,)]
    assert env.keys.latest(env.uid) is not None

    r = env.client.post("/me/delete", json={"confirm": "delete"})
    assert r.status_code == 202

    # step 1: tombstoned, key rows gone, shred_log written; the data is unreadable at once
    assert env.uid in env.keys.tombstones and env.keys.latest(env.uid) is None
    assert sql(pg_clean, "SELECT count(*) FROM shred_log WHERE user_id = %s", env.uid) == [(1,)]
    with pytest.raises(crypto.KeyShredded):
        env.ud.list(env.uid, "entry", "student", EntryDoc)
    # 1b: deleted_at set and the queued brief job cancelled
    assert sql(pg_clean, "SELECT deleted_at IS NOT NULL FROM users WHERE id = %s",
               env.uid) == [(True,)]
    assert env.runner.status(queued, env.uid).state == JobState.CANCELLED
    # 3: sessions ended
    assert env.r.smembers(f"perch:usess:{env.uid}") == set()
    assert list(env.r.scan_iter("perch:sess:*")) == []
    # 4: the purge job clears the rows
    done = lambda: sql(pg_clean, "SELECT count(*) FROM users WHERE id = %s",  # noqa: E731
                       env.uid) == [(0,)]
    run_worker(pg_clean, ["purge"], done)
    for table, col in (("user_data", "user_id"), ("jobs", "user_id"), ("consents", "user_id"),
                       ("spend_ledger", "user_id"), ("users", "id")):
        assert sql(pg_clean, f"SELECT count(*) FROM {table} WHERE {col} = %s",
                   env.uid) == [(0,)], table
    # a second delete is harmless
    delete.clear_rows(PostgresRunner(pg_clean.worker, timing=FAST, pool_size=2).pool, env.uid)


def test_delete_needs_the_confirm_word(env):
    assert env.client.post("/me/delete", json={"confirm": "yes"}).status_code == 422
    assert env.client.post("/me/delete", json={}).status_code == 422
    assert env.uid not in env.keys.tombstones  # nothing was shredded


def test_the_worker_command_imports_the_purge_handler():
    import inspect

    from perch import cli

    assert "perch.user.delete" in inspect.getsource(cli.cmd_worker)
    assert "purge" in jobs.registered_kinds()  # registered once perch.user.delete is imported


@pytest.mark.skipif(not KEYS_URL, reason="PERCH_TEST_KEYS_DATABASE_URL is not set")
def test_delete_tombstones_the_key_in_the_real_keys_database(env, pg_clean, rds):
    from perch.db.keys_migrate import apply_key_migrations
    from perch.keystore import KeyRepository

    name = f"perch_test_b_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(KEYS_URL, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    p = urlsplit(KEYS_URL)
    url = urlunsplit((p.scheme, p.netloc, "/" + name, "", ""))
    try:
        apply_key_migrations(url)
        with psycopg.connect(KEYS_URL, autocommit=True) as c:
            c.execute("ALTER ROLE perch_keys PASSWORD 'rt'")
        rt = urlunsplit((p.scheme, f"perch_keys:rt@{p.hostname}:{p.port}", "/" + name, "", ""))
        repo = KeyRepository(rt)
        crypto.configure(repo=repo, keystore=EnvKeyStore(make_env()),
                         shred_hooks=[shred_log_hook(env.pool), publish_hook(rds)])
        env.client.post("/me/docs", json={"kind": "entry", "text": "SYNTHETIC entry"})
        with psycopg.connect(url) as c:
            assert c.execute("SELECT count(*) FROM user_keys WHERE user_id = %s",
                             (env.uid,)).fetchone()[0] == 1
        assert env.client.post("/me/delete", json={"confirm": "delete"}).status_code == 202
        with psycopg.connect(url) as c:
            assert c.execute("SELECT count(*) FROM user_keys WHERE user_id = %s",
                             (env.uid,)).fetchone()[0] == 0
            assert c.execute("SELECT count(*) FROM key_tombstones WHERE user_id = %s",
                             (env.uid,)).fetchone()[0] == 1
        repo.close()
    finally:
        crypto.configure()
        with psycopg.connect(KEYS_URL, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


# --- the 12-month purge and the other purge actions ---

def test_purge_inactive_picks_only_users_past_twelve_months(env, pg_clean, rds, monkeypatch):
    monkeypatch.setenv("PERCH_REDIS_URL", REDIS_URL)
    old, recent = new_user(pg_clean), new_user(pg_clean)
    for u in (old, recent):
        env.ud.put(u, "entry", "student", EntryDoc(text="SYNTHETIC entry"))
    sql(pg_clean, "UPDATE users SET last_active_at = now() - interval '13 months' WHERE id = %s",
        old)
    sql(pg_clean, "UPDATE users SET last_active_at = now() - interval '11 months' WHERE id = %s",
        recent)
    sql(pg_clean, "UPDATE users SET last_active_at = now() WHERE id = %s", env.uid)
    rds.sadd(f"perch:usess:{old}", "sid-old")
    rds.hset("perch:sess:sid-old", mapping={"uid": str(old)})
    runner = PostgresRunner(pg_clean.worker, timing=FAST, pool_size=4)
    try:
        jid = runner.submit("purge", {"action": "inactive"}, None, "inactive-1")
        run_worker(pg_clean, ["purge"], lambda: job_state(pg_clean, jid) == "succeeded")
        assert job_state(pg_clean, jid) == "succeeded"
    finally:
        runner.close()
    left = {r[0] for r in sql(pg_clean, "SELECT id FROM users")}
    assert old not in left and {recent, env.uid} <= left
    assert sql(pg_clean, "SELECT count(*) FROM user_data WHERE user_id = %s", old) == [(0,)]
    assert old in env.keys.tombstones and recent not in env.keys.tombstones
    assert rds.exists("perch:sess:sid-old") == 0  # the old account's session ended
    assert env.ud.count(recent) == 1


def test_last_active_is_written_at_most_once_a_day(env, pg_clean, rds):
    sql(pg_clean, "UPDATE users SET last_active_at = now() - interval '5 days' WHERE id = %s",
        env.uid)
    assert delete.touch_last_active(env.pool, rds, env.uid) is True
    stamp = sql(pg_clean, "SELECT last_active_at FROM users WHERE id = %s", env.uid)[0][0]
    assert (datetime.now(UTC) - stamp).total_seconds() < 60
    sql(pg_clean, "UPDATE users SET last_active_at = now() - interval '5 days' WHERE id = %s",
        env.uid)
    assert delete.touch_last_active(env.pool, rds, env.uid) is False  # throttled
    assert (datetime.now(UTC) - sql(pg_clean, "SELECT last_active_at FROM users WHERE id = %s",
                                    env.uid)[0][0]).days >= 4


def test_purge_guests_removes_old_guest_jobs_only(pg_clean, worker_pool):
    sid = b"\x01" * 32
    runner = PostgresRunner(pool=worker_pool, timing=FAST)
    old = runner.submit("brief", {"brief_id": "b1"}, None, "g1", guest_sid_hash=sid)
    new = runner.submit("brief", {"brief_id": "b2"}, None, "g2", guest_sid_hash=sid)
    sql(pg_clean, "UPDATE jobs SET created_at = now() - interval '25 hours' WHERE id = %s", old)
    assert delete.purge_guest_jobs(worker_pool) == 1
    ids = {r[0] for r in sql(pg_clean, "SELECT id FROM jobs")}
    assert ids == {new}


def test_purge_handler_refuses_a_rekey_without_a_user(pg_clean, worker_pool, monkeypatch):
    runner = PostgresRunner(pool=worker_pool, timing=FAST)
    jid = runner.submit("purge", {"action": "rekey"}, None, "rk")
    run_worker(pg_clean, ["purge"], lambda: job_state(pg_clean, jid) in ("failed", "dead"))
    assert job_state(pg_clean, jid) == "failed"
    assert jobs.registered_kinds().count("purge") == 1


# --- quotas ---

def test_quota_is_per_account_and_not_per_address(env, pg_clean, rds, web_pool):
    other = new_user(pg_clean)
    now = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    lim = {"daily_usd": 0.50, "month_usd": 100.0}
    scopes = quota.reserve_call(rds, env.uid, redisx.usd_micro(0.30), now=now, **lim)
    quota.settle_call(rds, scopes, redisx.usd_micro(0.30), redisx.usd_micro(0.30), in_tok=10,
                      out_tok=5)
    u = quota.usage(rds, web_pool, env.uid, now=now, **lim)
    assert (u.spent_usd, u.limit_usd) == (0.30, 0.50)
    assert u.resets_at == datetime(2026, 11, 5, tzinfo=UTC)
    with pytest.raises(QuotaExceeded):  # 0.30 + 0.30 passes the 0.50 day
        quota.reserve_call(rds, env.uid, redisx.usd_micro(0.30), now=now, **lim)
    # another account on the same address is untouched
    quota.reserve_call(rds, other, redisx.usd_micro(0.30), now=now, **lim)
    quota.admit(rds, web_pool, other, now=now, **lim)
    # the first account is told when it asks to start a job past its budget
    scopes = quota.reserve_call(rds, env.uid, redisx.usd_micro(0.20), now=now, **lim)
    quota.settle_call(rds, scopes, redisx.usd_micro(0.20), redisx.usd_micro(0.20))
    with pytest.raises(QuotaExceeded):
        quota.admit(rds, web_pool, env.uid, now=now, **lim)


def test_quota_counter_is_rebuilt_from_the_ledger_after_a_flush(env, pg_clean, rds, web_pool):
    sql(pg_clean, "INSERT INTO spend_ledger (user_id, role, provider, model, input_tokens, "
        "output_tokens, cost_usd) VALUES (%s, 'fit_explainer', 'anthropic', 'm', 1, 1, 0.123)",
        env.uid)
    rds.flushall()
    u = quota.usage(rds, web_pool, env.uid)
    assert u.spent_usd == pytest.approx(0.123)
    rds.hincrby(quota.user_scopes(env.uid)[0].spend, "usd_micro", 1000)  # a live counter stays
    assert quota.usage(rds, web_pool, env.uid).spent_usd == pytest.approx(0.124)


def test_submit_rate_is_per_user(env, pg_clean, rds, web_pool, monkeypatch):
    monkeypatch.setenv("PERCH_RATE_LIMITS", '{"submit_job": [2, 60]}')
    other = new_user(pg_clean)
    quota.admit(rds, web_pool, env.uid)
    quota.admit(rds, web_pool, env.uid)
    with pytest.raises(quota.RateLimited) as e:
        quota.admit(rds, web_pool, env.uid)
    assert e.value.retry_after >= 1
    quota.admit(rds, web_pool, other)  # another account has its own window


def test_the_brief_routes_use_the_account_store_when_the_app_has_account_services(
        env, pg_clean, tmp_path, monkeypatch):
    """POST /briefs and GET /briefs/{id} in perch/api.py, gated on app.state.user_services."""
    from perch.api import create_app
    from perch.jobs import InlineRunner

    monkeypatch.setenv("PERCH_REDIS_URL", REDIS_URL)
    _, svc = make(tmp_path)
    app = create_app(svc, InlineRunner(), stored_briefs=True, web_dir=None)
    app.state.user_services = env.client.app.state.user_services
    app.dependency_overrides[deps.session_optional] = lambda request: env.session
    app.dependency_overrides[deps.require_csrf] = lambda: None  # CSRF is tested in test_auth
    c = TestClient(app)
    env.session.audience = "researcher"  # the side decides: a student brief has no author id
    r = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"})
    assert r.status_code == 202, r.text
    bid = r.json()["id"]
    assert uuid.UUID(bid) and r.json()["job_id"]
    assert sql(pg_clean, "SELECT count(*), min(kind) FROM user_data WHERE user_id = %s",
               env.uid) == [(1, "brief")]
    assert c.get(f"/briefs/{bid}").json()["brief"]["status"] == "queued"
    jobs.set_brief_service(lambda: svc)
    try:
        run_worker(pg_clean, ["brief"], lambda: c.get(f"/briefs/{bid}").json()["brief"]["status"]
                   == "done")
    finally:
        jobs._brief_service = None
    got = c.get(f"/briefs/{bid}").json()
    assert got["brief"]["status"] == "done" and got["leads"]
    with svc.repo() as repo:  # nothing in the public store
        assert repo.get(__import__("perch.schemas", fromlist=["Brief"]).Brief, bid) is None
    # another account cannot read it
    env.session.user_id = new_user(pg_clean)
    assert c.get(f"/briefs/{bid}").status_code == 404


def test_usage_route_copies_the_counter(env, rds):
    r = env.client.get("/usage")
    assert r.status_code == 200
    assert set(r.json()) == {"spent_usd", "limit_usd", "resets_at"} and r.json()["spent_usd"] == 0


def test_purge_codes_are_kept_on_the_job_row():
    """S49 B14: the purge handler's own codes used to be stored as `permanent`."""
    assert jobs.PermanentError("retention_invalid").code == "retention_invalid"
    assert jobs.PermanentError("rekey_incomplete").code == "rekey_incomplete"


def test_purge_jobs_removes_dead_rows_past_thirty_days(pg_clean, worker_pool):
    """S49 B16: dead-lettered rows used to stay for good."""
    runner = PostgresRunner(pool=worker_pool, timing=FAST)
    ids = {s: runner.submit("precache", {"author_id": f"A{i}"}, None, f"j{i}")
           for i, s in enumerate(("succeeded", "dead", "failed", "queued"))}
    for state, jid in ids.items():
        sql(pg_clean, "UPDATE jobs SET state = %s, finished_at = now() - interval '31 days' "
            "WHERE id = %s", state, jid)
    fresh = runner.submit("precache", {"author_id": "A9"}, None, "j9")
    sql(pg_clean, "UPDATE jobs SET state = 'dead', finished_at = now() WHERE id = %s", fresh)
    jid = runner.submit("purge", {"action": "jobs"}, None, "pj")
    run_worker(pg_clean, ["purge"], lambda: job_state(pg_clean, jid) == "succeeded")
    left = {r[0] for r in sql(pg_clean, "SELECT id FROM jobs WHERE kind = 'precache'")}
    assert left == {ids["queued"], fresh}


def brief_client(env, tmp_path, monkeypatch, audience="researcher"):
    """The api app wired to the account services, as `perch serve` builds it."""
    from perch.api import create_app
    from perch.jobs import InlineRunner

    monkeypatch.setenv("PERCH_REDIS_URL", REDIS_URL)
    _, svc = make(tmp_path)
    app = create_app(svc, InlineRunner(), stored_briefs=True, web_dir=None)
    app.state.user_services = env.client.app.state.user_services
    app.dependency_overrides[deps.session_optional] = lambda request: env.session
    app.dependency_overrides[deps.require_csrf] = lambda: None
    env.session.audience = audience
    return TestClient(app), svc


def test_opening_a_document_id_as_a_brief_is_a_404(env, tmp_path, monkeypatch):
    """S49 B20: the id of the user's own CV row decrypted as a brief and gave a 500."""
    c, _ = brief_client(env, tmp_path, monkeypatch)
    cv = env.ud.put(env.uid, "cv", "researcher", CvDoc(text="SYNTHETIC CV text"))
    r = c.get(f"/briefs/{cv}")
    assert r.status_code == 404, r.text
    assert UserBriefStore(env.ud, env.uid, "researcher", str(cv)).load() is False


def test_a_brief_whose_job_ended_without_it_stops_the_page(env, pg_clean, tmp_path,
                                                         monkeypatch):
    """S49 B1: the page read only the brief's own status, so a job refused before the run,
    dead after its lease ran out, or gone left the owl spinning for good."""
    from perch.user.briefs import JOB_ENDED, JOB_ENDED_DEFAULT, JOB_GONE

    c, _ = brief_client(env, tmp_path, monkeypatch)

    def new_brief(n):
        r = c.post("/briefs", json={"author_id": "A5026494099", "as_of": f"2026-10-{n:02d}"})
        assert r.status_code == 202, r.text
        return r.json()["id"], r.json()["job_id"]

    bid, jid = new_brief(1)
    got = c.get(f"/briefs/{bid}").json()
    assert got["brief"]["status"] == "queued"
    assert got["job"]["state"] == "queued" and got["job"]["worker_seen"] is False
    sql(pg_clean, "INSERT INTO worker_heartbeat (worker, at, kinds, models_loaded) "
        "VALUES ('w-seen', now(), '{brief}', false)")
    assert c.get(f"/briefs/{bid}").json()["job"]["worker_seen"] is True
    sql(pg_clean, "DELETE FROM worker_heartbeat")

    sql(pg_clean, "UPDATE jobs SET state = 'dead', error_code = 'lease_expired', "
        "finished_at = now() WHERE id = %s", jid)
    got = c.get(f"/briefs/{bid}").json()
    assert got["brief"]["status"] == "failed" and got["brief"]["error"] == JOB_ENDED_DEFAULT
    assert got["job"]["state"] == "dead"

    bid, jid = new_brief(2)
    sql(pg_clean, "UPDATE jobs SET state = 'failed', error_code = 'consent_required', "
        "finished_at = now() WHERE id = %s", jid)
    assert c.get(f"/briefs/{bid}").json()["brief"]["error"] == JOB_ENDED["consent_required"]

    bid, jid = new_brief(3)
    sql(pg_clean, "DELETE FROM jobs WHERE id = %s", jid)
    got = c.get(f"/briefs/{bid}").json()
    assert got["brief"]["status"] == "failed" and got["brief"]["error"] == JOB_GONE

    bid, jid = new_brief(4)  # the owner stops it
    assert c.post(f"/briefs/{bid}/cancel").json()["cancelled"] is True
    got = c.get(f"/briefs/{bid}").json()
    assert got["brief"]["status"] == "failed" and got["brief"]["error"] == JOB_ENDED["cancelled"]
    assert c.post(f"/briefs/{bid}/cancel").json()["cancelled"] is False

    bid, jid = new_brief(5)  # a retry is pending: the page keeps polling
    sql(pg_clean, "UPDATE jobs SET attempts = 1, error_code = 'network_error' WHERE id = %s",
        jid)
    assert c.get(f"/briefs/{bid}").json()["brief"]["status"] == "queued"

    # the stored brief itself is unchanged; another account sees nothing
    assert UserBriefStore(env.ud, env.uid, "researcher", bid).load()
    env.session.user_id = new_user(pg_clean)
    assert c.post(f"/briefs/{bid}/cancel").status_code == 404


def test_a_repeated_brief_poll_reads_no_public_record_again(env, pg_clean, tmp_path,
                                                            monkeypatch):
    """S49 B9: every 1.5 s poll re-read every Award, the overrides file and each lead's record.
    Public records are now kept per process for a short while; the brief itself is not."""
    from perch import awards as aw
    from perch.store.sqlite import SQLiteRepository

    c, svc = brief_client(env, tmp_path, monkeypatch)
    r = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"})
    bid = r.json()["id"]
    jobs.set_brief_service(lambda: svc)
    try:
        run_worker(pg_clean, ["brief"],
                   lambda: c.get(f"/briefs/{bid}").json()["brief"]["status"] == "done")
    finally:
        jobs._brief_service = None
    first = c.get(f"/briefs/{bid}").json()
    assert first["leads"]
    calls = []
    real_get, real_list, real_ov = SQLiteRepository.get, SQLiteRepository.list, aw.load_overrides
    monkeypatch.setattr(SQLiteRepository, "get",
                        lambda self, cls, i: calls.append(("get", cls.kind)) or
                        real_get(self, cls, i))
    monkeypatch.setattr(SQLiteRepository, "list",
                        lambda self, cls, **k: calls.append(("list", cls.kind)) or
                        real_list(self, cls, **k))
    monkeypatch.setattr(aw, "load_overrides",
                        lambda *a, **k: calls.append(("overrides",)) or real_ov(*a, **k))
    again = c.get(f"/briefs/{bid}").json()
    assert again["leads"] == first["leads"] and again["awards"] == first["awards"]
    assert calls == []
