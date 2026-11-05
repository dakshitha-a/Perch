"""Brief storage for accounts and guests (S41 part B). SYNTHETIC text only.

Signed-in brief: one encrypted user_data row, saved at each stage. Guest brief: Redis only.
A brief that reads user documents never touches public_cache.
"""

from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

import psycopg
import pytest

from perch.schemas import Brief, Lead
from perch.user.briefs import (
    GuestBriefStore,
    UserBriefStore,
    create_guest_brief,
    create_user_brief,
    read_guest_result,
    using_store,
)
from perch.user.data import UserData
from perch.user.inputs import make_doc
from perch.user.models import StoredBrief
from tests.conftest import PG_URL
from tests.test_api import make
from tests.user_helpers import new_user

REDIS_URL = os.environ.get("PERCH_TEST_REDIS_URL", "")
needs_pg = pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set")
needs_redis = pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")
PERSONA = Path(__file__).resolve().parent.parent / "data/synthetic/persona-1"
AS_OF = date(2026, 10, 28)


def rows(pgdb, sql, *args):
    with psycopg.connect(pgdb.admin, autocommit=True) as c:
        return c.execute(sql, args).fetchall()


class CountingCache:
    """Stands in for PublicCache and records every write and read."""

    def __init__(self) -> None:
        self.puts: list[tuple] = []
        self.gets: list[tuple] = []

    def put(self, *a, **k):
        self.puts.append(a)

    def get(self, *a, **k):
        self.gets.append(a)
        return None


@needs_pg
def test_signed_in_brief_is_one_encrypted_row_saved_at_each_stage(pg_clean, ud, tmp_path,
                                                                   monkeypatch):
    uid = new_user(pg_clean)
    _, svc = make(tmp_path)
    writes: list[int] = []
    real = UserData.update

    def counting(self, *a, **k):
        writes.append(1)
        return real(self, *a, **k)

    monkeypatch.setattr(UserData, "update", counting)
    b = create_user_brief(svc, ud, uid, "researcher", "A5026494099", as_of=AS_OF)
    assert rows(pg_clean, "SELECT kind, audience FROM user_data WHERE user_id = %s", uid) \
        == [("brief", "researcher")]
    row = uuid.UUID(b.id)
    store = UserBriefStore(ud, uid, "researcher", b.id)
    assert store.load() and store.brief.status == "queued"
    with using_store(store):
        assert svc.run(b.id) == "done"
    assert len(writes) >= 8  # one per stage, at least
    got = ud.get(uid, row, StoredBrief)
    assert got.brief.status == "done" and got.leads and got.leads[0].record_id
    # one row, ciphertext only: no lead text, no researcher id, no provenance URL in the blob
    (blob,) = rows(pg_clean, "SELECT blob FROM user_data WHERE id = %s", row)[0]
    for needle in (b"A5026494099", b"PAR-25-268", b"perch://briefs"):
        assert needle not in bytes(blob)
    assert rows(pg_clean, "SELECT count(*) FROM user_data WHERE user_id = %s", uid) == [(1,)]
    # nothing in the public record store
    with svc.repo() as r:
        assert r.get(Brief, b.id) is None and not r.list(Lead)


@needs_pg
def test_a_foreign_user_cannot_read_the_brief(pg_clean, ud, tmp_path):
    a, other = new_user(pg_clean), new_user(pg_clean)
    _, svc = make(tmp_path)
    b = create_user_brief(svc, ud, a, "researcher", "A5026494099", as_of=AS_OF)
    assert ud.get(other, uuid.UUID(b.id), StoredBrief) is None


@needs_pg
def test_brief_that_reads_user_documents_leaves_public_cache_unchanged(pg_clean, ud, tmp_path):
    uid = new_user(pg_clean)
    _, svc = make(tmp_path)
    cache = CountingCache()
    svc.public_cache = cache
    doc = make_doc("proposal", (PERSONA / "specific_aims_draft.md").read_text())
    did = ud.put(uid, "doc", "researcher", doc)
    before = rows(pg_clean, "SELECT count(*) FROM public_cache")
    b = create_user_brief(svc, ud, uid, "researcher", "A5026494099", as_of=AS_OF, doc_ids=[did])
    store = UserBriefStore(ud, uid, "researcher", b.id)
    assert store.load() and store.reads_user_data
    with using_store(store):
        assert svc._text_cache(Brief(id="x", source="perch", source_url="perch://x",
                                     fetched_at=b.fetched_at, researcher_id=b.researcher_id)) \
            is False
        assert svc.run(b.id) == "done"
    assert svc.public_cache is cache
    # The author's own public profile may be cached (it is built before the documents are
    # added); no model text and nothing from the documents may be.
    assert {p[0] for p in cache.puts} <= {"author"}, "model text reached the shared cache"
    assert "PERCH-CANARY-AIMS-K2M9" not in repr(cache.puts)
    assert "ground reaction force" not in repr(cache.puts).lower()
    assert [g for g in cache.gets if g[0] in ("fit", "profile_summary")] == []
    assert rows(pg_clean, "SELECT count(*) FROM public_cache") == before
    got = ud.get(uid, uuid.UUID(b.id), StoredBrief)
    assert got.brief.options["user_data"] == [str(did)]
    assert any(t.get("label") for t in got.brief.threads)  # the document became a thread


@needs_pg
def test_a_brief_on_public_inputs_still_uses_the_cache(pg_clean, ud, tmp_path):
    """The control for the test above: the cache wiring is live when no user data is read."""
    uid = new_user(pg_clean)
    _, svc = make(tmp_path)
    cache = CountingCache()
    svc.public_cache = cache
    b = create_user_brief(svc, ud, uid, "researcher", "A5026494099", as_of=AS_OF)
    store = UserBriefStore(ud, uid, "researcher", b.id)
    store.load()
    assert store.reads_user_data is False
    with using_store(store):
        svc.run(b.id)
    assert cache.gets, "a public-input brief reads the shared cache"


@needs_redis
def test_guest_brief_lives_in_redis_for_an_hour_and_has_no_user_row(pg_clean, tmp_path):
    import redis as redis_lib

    r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    assert REDIS_URL.rstrip("/").endswith("/15")
    r.flushdb()
    _, svc = make(tmp_path)
    gsid = "ab" * 32
    b = create_guest_brief(svc, r, gsid, "A5026494099", as_of=AS_OF)
    assert r.ttl(f"perch:gsess:{gsid}:brief:{b.id}") > 0
    job = uuid.uuid4()
    store = GuestBriefStore(r, gsid, b.id, job)
    assert store.load() and store.brief.status == "queued"
    with using_store(store):
        assert svc.run(b.id) == "done"
    ttl = r.ttl(f"perch:gres:{job}")
    assert 0 < ttl <= 3600
    got = read_guest_result(r, job)
    assert got.brief.status == "done" and got.leads
    assert rows(pg_clean, "SELECT count(*) FROM user_data") == [(0,)]
    assert rows(pg_clean, "SELECT count(*) FROM users") == [(0,)]
    r.delete(f"perch:gres:{job}")  # the hour is up
    assert read_guest_result(r, job) is None
    r.flushdb()
    r.close()


@needs_pg
def test_signed_in_brief_job_runs_by_id_end_to_end(pg_clean, ud, tmp_path, web_pool, keys):
    """Web creates the row and submits ids only; the worker's handler fills the same row."""
    import threading

    from perch import jobs
    from perch.jobs import JobState, PostgresRunner, Timing

    uid = new_user(pg_clean)
    _, svc = make(tmp_path)
    b = create_user_brief(svc, ud, uid, "researcher", "A5026494099", as_of=AS_OF)
    fast = Timing(lease_s=60, heartbeat_s=0.2, reaper_s=0.3, poll_s=0.05, drain_s=10)
    web = PostgresRunner(pool=web_pool, timing=fast)
    jid = web.submit("brief", {"brief_id": b.id}, uid, f"k-{b.id}", audience="researcher")
    jobs.set_brief_service(lambda: svc)
    w = PostgresRunner(pg_clean.worker, timing=fast, pool_size=4)
    stop = threading.Event()
    t = threading.Thread(target=w.run_forever, args=("w-ub", ["brief"], 1, stop))
    t.start()
    try:
        st = w.wait(jid, 60)
    finally:
        stop.set()
        t.join()
        jobs._brief_service = None
        w.close()
    assert st.state == JobState.SUCCEEDED, st.error_code
    assert st.result_ref == f"user_data:{b.id}"
    got = ud.get(uid, uuid.UUID(b.id), StoredBrief)
    assert got.brief.status == "done" and got.leads
    # the jobs row holds ids only
    (payload,) = rows(pg_clean, "SELECT payload::text FROM jobs WHERE id = %s", jid)[0]
    assert payload == f'{{"brief_id": "{b.id}"}}'


@needs_pg
@needs_redis
def test_submit_and_load_for_a_user_and_for_a_guest(pg_clean, ud, tmp_path, web_pool, keys,
                                                    monkeypatch):
    """The two calls api.py makes. A guest's brief runs on a worker and is read from Redis."""
    import threading
    import time

    import redis as redis_lib

    from perch import jobs
    from perch.auth.session import Session
    from perch.jobs import PostgresRunner, Timing
    from perch.user.briefs import guest_hash, load_brief, submit_brief

    monkeypatch.setenv("PERCH_REDIS_URL", REDIS_URL)  # the worker finds Redis here
    r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    r.flushdb()
    uid = new_user(pg_clean)
    _, svc = make(tmp_path)
    fast = Timing(lease_s=60, heartbeat_s=0.2, reaper_s=0.3, poll_s=0.05, drain_s=10)
    web = PostgresRunner(pool=web_pool, timing=fast)

    def sess(user, sid):
        return Session(sid=sid, user_id=user, guest=user is None, roles=frozenset(),
                       audience="researcher", csrf="c", display_name=None, created=time.time(),
                       abs_exp=time.time() + 3600)

    user_s, guest_s = sess(uid, "u-1"), sess(None, "g-1")
    ub, ujob = submit_brief(svc, web, ud, r, user_s, "A5026494099", as_of=AS_OF)
    gb, gjob = submit_brief(svc, web, ud, r, guest_s, "A5026494099", as_of=AS_OF)
    assert load_brief(ud, r, user_s, ub).brief.status == "queued"
    assert load_brief(ud, r, guest_s, gb).brief.status == "queued"
    assert load_brief(ud, r, guest_s, ub) is None and load_brief(ud, r, user_s, gb) is None
    jobs.set_brief_service(lambda: svc)
    w = PostgresRunner(pg_clean.worker, timing=fast, pool_size=4)
    stop = threading.Event()
    t = threading.Thread(target=w.run_forever, args=("w-sl", ["brief"], 2, stop))
    t.start()
    try:
        end = time.monotonic() + 60
        while time.monotonic() < end and not (
                rows(pg_clean, "SELECT count(*) FROM jobs WHERE state = 'succeeded'") == [(2,)]):
            time.sleep(0.1)
    finally:
        stop.set()
        t.join()
        jobs._brief_service = None
        w.close()
    assert load_brief(ud, r, user_s, ub).brief.status == "done"
    g = load_brief(ud, r, guest_s, gb)
    assert g.brief.status == "done" and g.leads
    assert rows(pg_clean, "SELECT result_ref FROM jobs WHERE id = %s", gjob) \
        == [(f"redis:perch:gres:{gjob}",)]
    assert rows(pg_clean, "SELECT count(*) FROM user_data") == [(1,)]  # the user's only
    assert guest_hash("g-1") in "".join(r.keys("perch:gsess:*"))
    with pytest.raises(PermissionError):
        submit_brief(svc, web, ud, r, guest_s, "A5026494099", doc_ids=[uuid.uuid4()])
    r.flushdb()
    r.close()


@needs_pg
@needs_redis
def test_two_identical_clicks_return_the_brief_that_runs(pg_clean, ud, tmp_path, web_pool, keys,
                                                         monkeypatch):
    """S49 B4: two requests that both passed the idempotency check made two briefs, and the
    second caller got the second brief with the first job, which never runs it."""
    import time

    import redis as redis_lib

    from perch.auth.session import Session
    from perch.jobs import PostgresRunner, Timing
    from perch.user import briefs as ub

    r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    r.flushdb()
    uid = new_user(pg_clean)
    _, svc = make(tmp_path)
    web = PostgresRunner(pool=web_pool, timing=Timing())

    def sess(user, sid):
        return Session(sid=sid, user_id=user, guest=user is None, roles=frozenset(),
                       audience="researcher", csrf="c", display_name=None, created=time.time(),
                       abs_exp=time.time() + 3600)

    for s in (sess(uid, "u-2"), sess(None, "g-2")):
        first = ub.submit_brief(svc, web, ud, r, s, "A5026494099", as_of=AS_OF)
        real, calls = ub._existing, []

        def late(*a, _real=real, _calls=calls):  # the twin's check ran before the first insert
            _calls.append(1)
            return None if len(_calls) == 1 else _real(*a)

        monkeypatch.setattr(ub, "_existing", late)
        second = ub.submit_brief(svc, web, ud, r, s, "A5026494099", as_of=AS_OF)
        monkeypatch.setattr(ub, "_existing", real)
        assert second == first
    assert rows(pg_clean, "SELECT count(*) FROM user_data WHERE kind = 'brief'") == [(1,)]
    assert len(r.keys("perch:gsess:*:brief:*")) == 1
    r.flushdb()
    r.close()
