"""Job queue tests on Postgres. All data is SYNTHETIC. Skips without PERCH_TEST_DATABASE_URL.

Uses a database of its own (perch_test_c_*) so the shared test database is left alone.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter

import psycopg
import pytest

from perch import jobs
from perch.jobs import (
    HandlerSpec,
    JobState,
    LeaseLost,
    PayloadError,
    PermanentError,
    PostgresRunner,
    RetryableError,
    Timing,
)
from tests.conftest import PG_URL, _with

pytestmark = pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set")
FAST = {"lease_s": 60, "heartbeat_s": 0.2, "reaper_s": 0.3, "poll_s": 0.05, "drain_s": 10}


@pytest.fixture(scope="module")
def dsns():
    from perch.db.migrate import migrate

    name = f"perch_test_c_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(PG_URL, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    admin = _with(PG_URL, dbname=name)
    try:
        migrate(admin)
        with psycopg.connect(admin, autocommit=True) as c:
            for role in ("perch_web", "perch_worker"):
                c.execute(f"ALTER ROLE {role} PASSWORD 'pw'")
        yield {"admin": admin, "web": _with(PG_URL, "perch_web", "pw", name),
               "worker": _with(PG_URL, "perch_worker", "pw", name)}
    finally:
        with psycopg.connect(PG_URL, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def clean(dsns):
    with psycopg.connect(dsns["admin"], autocommit=True) as c:
        c.execute("TRUNCATE users, jobs, job_events, audit_log, worker_heartbeat CASCADE")
    return dsns


def reg(monkeypatch, kind, fn, *, max_attempts=3, timeout_s=30, priority=8):
    monkeypatch.setitem(jobs._REGISTRY, kind, HandlerSpec(fn, max_attempts, timeout_s, priority))


def mk(dsn, **timing):
    return PostgresRunner(dsn, timing=Timing(**{**FAST, **timing}), pool_size=6)


def user(dsns) -> uuid.UUID:
    with psycopg.connect(dsns["admin"], autocommit=True) as c:
        return c.execute("SELECT perch_login_user(%s, %s)",
                         (b"iss", uuid.uuid4().bytes)).fetchone()[0]


def pre(i) -> dict:
    return {"author_id": f"A{i}"}


def start(runner, kinds=(), concurrency=1, name="w"):
    stop = threading.Event()
    t = threading.Thread(target=runner.run_forever, args=(name, list(kinds), concurrency, stop))
    t.start()
    return stop, t


def test_ten_workers_run_each_of_200_jobs_once(clean, monkeypatch):
    runs: Counter = Counter()
    lock = threading.Lock()

    def h(ctx):
        with lock:
            runs[ctx.job_id] += 1
        return "ok"

    reg(monkeypatch, "precache", h)
    sched = mk(clean["worker"])  # ownerless jobs come from the scheduler, which is the worker role
    ids = [sched.submit("precache", pre(i), None, f"k{i}") for i in range(200)]
    assert len(set(ids)) == 200
    started = [start(mk(clean["worker"]), name=f"w{i}") for i in range(10)]
    try:
        for j in ids:
            assert sched.wait(j, 60).state == JobState.SUCCEEDED
    finally:
        for stop, _ in started:
            stop.set()
        for _, t in started:
            t.join()
    assert set(runs) == set(ids)
    assert set(runs.values()) == {1}


def test_expired_lease_is_reclaimed_and_late_update_is_fenced(clean, monkeypatch):
    reg(monkeypatch, "precache", lambda ctx: "ok")
    r = mk(clean["worker"], lease_s=1)
    jid = r.submit("precache", pre(1), None, "k")
    a = r.claim("A/0", ["precache"])
    ctx_a = r.context(a, "A/0")
    time.sleep(1.3)
    assert r.reap() == 1
    with psycopg.connect(clean["admin"], autocommit=True) as c:
        c.execute("UPDATE jobs SET run_after = now() WHERE id = %s", (jid,))
    b = r.claim("B/0", ["precache"])
    assert b["id"] == jid
    assert b["attempts"] == 2
    with pytest.raises(LeaseLost):
        r.finish_ok(ctx_a, "stale")
    with pytest.raises(LeaseLost):
        ctx_a.stage("x", "done")
    with pytest.raises(LeaseLost):
        ctx_a.heartbeat()
    r.finish_ok(r.context(b, "B/0"), "good")
    st = r.wait(jid, 5)
    assert st.state == JobState.SUCCEEDED
    assert st.result_ref == "good"
    assert st.attempts == 2


def test_timeout_fails_the_job_at_once_and_the_late_result_is_dropped(clean, monkeypatch):
    """S49 B6: a timed-out job used to go quiet until the reaper requeued it, while the old
    handler kept running beside the next attempt. Now it fails with `timeout`, once."""
    seen = {"runs": 0}

    def h(ctx):
        seen["runs"] += 1
        time.sleep(2.5)  # past the 1 second timeout; the lease (60 s) has not run out
        seen["cancelled"] = ctx.cancelled()
        with pytest.raises(LeaseLost):
            ctx.stage("late", "done")
        return "late"

    reg(monkeypatch, "precache", h, max_attempts=3, timeout_s=1)
    r = mk(clean["worker"])
    jid = r.submit("precache", pre(1), None, "k")
    stop, t = start(r)
    try:
        st = r.wait(jid, 10)
        time.sleep(2)  # the handler finishes; nothing runs it again
    finally:
        stop.set()
        t.join()
    assert seen["cancelled"] is True and seen["runs"] == 1
    assert st.state == JobState.FAILED
    assert st.error_code == "timeout"
    assert st.result_ref is None
    with psycopg.connect(clean["admin"]) as c:
        assert c.execute("SELECT count(*) FROM job_events").fetchone()[0] == 0
        assert c.execute("SELECT state, error_code FROM jobs").fetchall() == [("failed",
                                                                              "timeout")]


def test_a_result_just_past_the_deadline_is_kept(clean, monkeypatch):
    """S49 B6: a handler that finished a moment after the deadline had its result thrown
    away and was run again; the fence alone decides now."""
    reg(monkeypatch, "precache", lambda ctx: time.sleep(1.2) or "ok", timeout_s=1)
    r = mk(clean["worker"], heartbeat_s=5)  # the timeout check has not run yet
    jid = r.submit("precache", pre(1), None, "k")
    stop, t = start(r)
    try:
        st = r.wait(jid, 10)
    finally:
        stop.set()
        t.join()
    assert st.state == JobState.SUCCEEDED and st.result_ref == "ok"


def test_retries_then_dead_letter(clean, monkeypatch):
    monkeypatch.setattr(jobs, "backoff_s", lambda n: 0.0)
    calls = []

    def h(ctx):
        calls.append(ctx.attempt)
        raise RetryableError("provider_error")

    reg(monkeypatch, "precache", h, max_attempts=3)
    r = mk(clean["worker"])
    jid = r.submit("precache", pre(1), None, "k")
    stop, t = start(r)
    try:
        st = r.wait(jid, 20)
    finally:
        stop.set()
        t.join()
    assert calls == [1, 2, 3]
    assert st.state == JobState.DEAD
    assert st.error_code == "provider_error"
    assert st.attempts == 3
    assert r.submit("precache", pre(1), None, "k") != jid  # a dead job frees its key


def test_permanent_error_fails_without_retry(clean, monkeypatch):
    def h(ctx):
        raise PermanentError("refusal")

    reg(monkeypatch, "precache", h)
    r = mk(clean["worker"])
    jid = r.submit("precache", pre(1), None, "k")
    r.execute(r.claim("w/0", ["precache"]), "w/0")
    st = r.wait(jid, 5)
    assert st.state == JobState.FAILED
    assert st.error_code == "refusal"
    assert st.attempts == 1


def test_cancel_queued_and_running(clean, monkeypatch):
    started, release = threading.Event(), threading.Event()
    seen = {}

    def h(ctx):
        started.set()
        release.wait(10)
        seen["cancelled"] = ctx.cancelled()
        return "x"

    reg(monkeypatch, "brief", h, priority=2)
    uid, other = user(clean), user(clean)
    web = mk(clean["web"])
    q = web.submit("brief", {"brief_id": "b1"}, uid, "k1")
    assert web.cancel(q, other) is False  # not the owner
    assert web.status(q, other) is None
    assert web.cancel(q, uid) is True
    assert web.status(q, uid).state == JobState.CANCELLED
    assert web.cancel(q, uid) is False  # already finished

    run = web.submit("brief", {"brief_id": "b2"}, uid, "k2")
    stop, t = start(mk(clean["worker"]))
    try:
        assert started.wait(10)
        assert web.cancel(run, uid) is True
        time.sleep(0.6)  # a heartbeat finds the lease gone
        release.set()
    finally:
        stop.set()
        t.join()
    assert seen["cancelled"] is True
    st = web.status(run, uid)
    assert st.state == JobState.CANCELLED
    assert st.result_ref is None


def test_idempotency_returns_same_job_id(clean):
    uid, other = user(clean), user(clean)
    web = mk(clean["web"])
    p = {"brief_id": "b1"}
    a = web.submit("brief", p, uid, "same")
    assert web.submit("brief", p, uid, "same") == a
    assert web.submit("brief", p, other, "same") != a  # keys are per user
    assert web.submit("brief", p, uid, "different") != a
    g = b"\x01" * 32
    ga = web.submit("brief", p, None, "same", guest_sid_hash=g)
    assert web.submit("brief", p, None, "same", guest_sid_hash=g) == ga
    with psycopg.connect(clean["admin"], autocommit=True) as c:
        c.execute("UPDATE jobs SET state = 'succeeded' WHERE id = %s", (a,))
    assert web.submit("brief", p, uid, "same") == a  # a succeeded job still holds its key


@pytest.mark.parametrize("kind,payload", [
    ("brief", {"brief_id": "b1", "text": "SYNTHETIC cv text"}),  # extra key
    ("brief", {"brief_id": "SYNTHETIC text with spaces"}),        # not an id
    ("brief", {"brief_id": 5}),                                   # wrong type
    ("brief", {}),                                                # missing
    ("scout_turn", {"session_id": "s", "message_id": "m", "question": "SYNTHETIC?"}),
    ("purge", {"action": "everything"}),
    ("nope", {}),
])
def test_forbidden_payloads_are_rejected(clean, kind, payload):
    web = mk(clean["web"])
    with pytest.raises(PayloadError) as e:
        web.submit(kind, payload, user(clean), "k")
    assert "SYNTHETIC" not in str(e.value)
    with psycopg.connect(clean["admin"]) as c:
        assert c.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0


def test_stages_are_reported_and_user_tx_is_fenced(clean):
    uid = user(clean)
    web, w = mk(clean["web"]), mk(clean["worker"])
    jid = web.submit("brief", {"brief_id": "b1"}, uid, "k")
    ctx = w.context(w.claim("w/0", ["brief"]), "w/0")
    ctx.stage("profile", "running")
    ctx.stage("profile", "done", "x" * 500, 12)
    with ctx.user_tx() as c:
        assert c.execute("SELECT 1").fetchone()
    st = web.status(jid, uid)
    assert st.state == JobState.RUNNING
    assert [s["status"] for s in st.stages] == ["running", "done"]
    assert len(st.stages[1]["detail"]) == 120
    ctx.lease_owner = "someone-else/0"  # a stale thread
    with pytest.raises(LeaseLost):
        with ctx.user_tx():
            pass


def test_an_ownerless_brief_job_fails_and_the_worker_row_is_written(clean):
    """v1 submits every brief with an owner; an ownerless one fails at once (S49 B31). A
    signed-in job writes a user_data row instead
    (tests/test_user_briefs.py::test_signed_in_brief_job_runs_by_id_end_to_end)."""
    seen = {}

    class Svc:
        def run(self, brief_id):
            seen["id"] = brief_id
            return "done"

    jobs.set_brief_service(Svc)
    w = mk(clean["worker"])
    jid = w.submit("brief", {"brief_id": "b9"}, None, "k")
    stop, t = start(w, ["brief"], 2, "wk1")
    try:
        st = w.wait(jid, 20)
        with psycopg.connect(clean["admin"]) as c:
            kinds = c.execute("SELECT kinds FROM worker_heartbeat WHERE worker = 'wk1'").fetchone()
        assert kinds[0] == ["brief"]
    finally:
        stop.set()
        t.join()
        jobs._brief_service = None
    assert st.state == JobState.FAILED
    assert st.error_code == "invalid_input"
    assert seen == {}


def test_a_database_error_in_finish_does_not_end_the_job_thread(clean, monkeypatch):
    """S49 B3: an OperationalError from the terminal write used to escape `execute` and end
    the thread for good while the heartbeat row stayed fresh."""
    def h(ctx):
        if ctx.payload["author_id"] == "A1":
            raise RetryableError("provider_error")
        return "ok"

    reg(monkeypatch, "precache", h)
    calls = []

    def broken(self, ctx, code, permanent):
        calls.append(ctx.job_id)
        raise psycopg.OperationalError("connection lost")

    monkeypatch.setattr(PostgresRunner, "finish_error", broken)
    r = mk(clean["worker"])
    first = r.submit("precache", pre(1), None, "k1")
    stop, t = start(r, ["precache"], 1)
    try:
        end = time.monotonic() + 10
        while not calls and time.monotonic() < end:
            time.sleep(0.05)
        second = r.submit("precache", pre(2), None, "k2")
        assert r.wait(second, 10).state == JobState.SUCCEEDED
    finally:
        stop.set()
        t.join()
    assert calls == [first]
