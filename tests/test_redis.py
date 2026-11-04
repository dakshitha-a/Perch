"""Redis layer tests. All text is SYNTHETIC. Needs PERCH_TEST_REDIS_URL (use DB 15 only);
the pure client-address tests run without it. Only DB 15 is ever flushed."""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime

import pytest

from perch import redisx as rx

URL = os.environ.get("PERCH_TEST_REDIS_URL", "")
needs_redis = pytest.mark.skipif(not URL, reason="PERCH_TEST_REDIS_URL is not set")


@pytest.fixture
def r():
    assert URL.rstrip("/").endswith("/15"), "tests use Redis DB 15 only"
    c = rx.get_client(URL)
    c.flushdb()
    yield c
    c.flushdb()
    c.close()


# --- client address (no Redis) ---

TRUSTED = "10.0.0.0/8"


def test_spoofed_xff_from_untrusted_peer_is_ignored() -> None:
    assert rx.client_addr_from("203.0.113.9", "1.2.3.4", TRUSTED) == "203.0.113.9"
    assert rx.client_addr_from("203.0.113.9", "1.2.3.4", None) == "203.0.113.9"


def test_xff_from_trusted_proxy_walks_from_the_right() -> None:
    # the client forged the first hop; the right-most untrusted hop is the real client
    assert rx.client_addr_from("10.0.0.2", "6.6.6.6, 198.51.100.7, 10.0.0.1", TRUSTED) \
        == "198.51.100.7"
    assert rx.client_addr_from("10.0.0.2", "10.0.0.5", TRUSTED) == "10.0.0.2"
    assert rx.client_addr_from("10.0.0.2", None, TRUSTED) == "10.0.0.2"


def test_ipv6_is_truncated_to_64() -> None:
    assert rx.client_addr_from("2001:db8:1:2:aaaa:bbbb:cccc:dddd", None, None) \
        == "2001:db8:1:2::/64"


def test_client_addr_reads_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class Req:
        client = type("C", (), {"host": "10.1.1.1"})()
        headers = {"x-forwarded-for": "198.51.100.1"}

    monkeypatch.setenv("PERCH_TRUSTED_PROXIES", "10.0.0.0/8")
    assert rx.client_addr(Req()) == "198.51.100.1"
    monkeypatch.delenv("PERCH_TRUSTED_PROXIES")
    assert rx.client_addr(Req()) == "10.1.1.1"


def test_hash_subject_is_keyed() -> None:
    assert rx.hash_subject("a", "p1") != rx.hash_subject("a", "p2")
    assert len(rx.hash_subject("a", "p1")) == 64


# --- sessions and CSRF ---

@needs_redis
def test_session_lifecycle_and_csrf(r) -> None:
    uid = uuid.uuid4()
    sid, csrf = rx.create_session(r, uid=uid, roles=["student"], audience="student",
                                  name="SYNTHETIC Name", idle_s=100, abs_s=1000)
    s = rx.get_session(r, sid)
    assert s and s["uid"] == str(uid) and s["roles"] == "student"
    assert 0 < r.ttl(f"perch:sess:{sid}") <= 100
    assert rx.csrf_ok(s, csrf) and not rx.csrf_ok(s, csrf + "x") and not rx.csrf_ok(s, None)
    assert rx.touch_session(r, sid)
    assert sid in r.smembers(f"perch:usess:{uid}")
    sid2, _ = rx.create_session(r, uid=uid)
    assert sid2 != sid
    assert rx.destroy_user_sessions(r, uid) == 2
    assert rx.get_session(r, sid) is None and rx.get_session(r, sid2) is None


@needs_redis
def test_idle_slide_is_capped_by_absolute(r) -> None:
    t = time.time()
    sid, _ = rx.create_session(r, uid=uuid.uuid4(), idle_s=100, abs_s=500, now=t)
    assert rx.touch_session(r, sid, now=t + 450)
    assert r.ttl(f"perch:sess:{sid}") <= 50
    assert rx.get_session(r, sid, now=t + 501) is None  # past the absolute limit
    assert r.exists(f"perch:sess:{sid}") == 0


@needs_redis
def test_guest_session_does_not_slide(r) -> None:
    sid, _ = rx.create_session(r, guest=True, guest_ttl_s=60, gsid_hash="h")
    before = r.ttl(f"perch:sess:{sid}")
    assert rx.touch_session(r, sid)
    assert r.ttl(f"perch:sess:{sid}") <= before
    assert rx.get_session(r, sid)["guest"] == "1"


# --- quotas ---

@needs_redis
def test_quota_reserve_settle_and_refuse(r) -> None:
    uid = uuid.uuid4()
    sc = rx.quota_scopes(uid=uid, daily_usd=0.001, month_usd=10)  # 1000 micro dollars a day
    rx.reserve(r, sc, 600)
    with pytest.raises(rx.QuotaExceeded) as e:
        rx.reserve(r, sc, 600)  # 600 in flight + 600 > 1000
    assert e.value.scope == "user"
    rx.settle(r, sc, 600, 450, in_tok=10, out_tok=5)
    assert rx.spent_micro(r, sc[0]) == 450 and rx.spent_micro(r, sc[1]) == 450
    assert r.hget(sc[0].spend, "calls") == "1"
    rx.reserve(r, sc, 500)
    with pytest.raises(rx.QuotaExceeded):
        rx.reserve(r, sc, 100)


@needs_redis
def test_guest_ceiling_is_shared_by_sessions(r) -> None:
    a = rx.quota_scopes(gsid_hash="ga", guest_usd=1, guest_global_usd=0.0001, month_usd=10)
    b = rx.quota_scopes(gsid_hash="gb", guest_usd=1, guest_global_usd=0.0001, month_usd=10)
    rx.reserve(r, a, 60)
    with pytest.raises(rx.QuotaExceeded) as e:
        rx.reserve(r, b, 60)  # 100 micro dollars for all guests together
    assert e.value.scope == "guest_global"
    assert r.get(b[0].inflight) is None  # a refused call reserves nothing


@needs_redis
def test_gate_call_has_minimum_charge(r) -> None:
    sc = rx.quota_scopes(uid=uuid.uuid4(), month_usd=10)
    rx.reserve(r, sc, 5)
    rx.settle(r, sc, 5, 0, gate=True)
    assert rx.spent_micro(r, sc[0]) == 1 and r.hget(sc[0].spend, "gate_calls") == "1"


@needs_redis
def test_quota_counters_reset_by_day(r) -> None:
    uid = uuid.uuid4()
    d1 = datetime(2026, 11, 3, 23, 59, tzinfo=UTC)
    d2 = datetime(2026, 11, 4, 0, 1, tzinfo=UTC)
    s1 = rx.quota_scopes(uid=uid, daily_usd=0.001, month_usd=10, now=d1)
    s2 = rx.quota_scopes(uid=uid, daily_usd=0.001, month_usd=10, now=d2)
    assert s1[0].spend.endswith(":20261103") and s2[0].spend.endswith(":20261104")
    assert s1[1].spend == s2[1].spend  # same calendar month
    rx.reserve(r, s1, 900)
    rx.settle(r, s1, 900, 900)
    with pytest.raises(rx.QuotaExceeded):
        rx.reserve(r, s1, 900)
    rx.reserve(r, s2, 900)  # a new day starts at zero
    assert r.ttl(s1[0].spend) > 0


@needs_redis
def test_seed_counter_never_overwrites(r) -> None:
    sc = rx.quota_scopes(uid=uuid.uuid4(), month_usd=10)
    assert rx.seed_counter(r, sc[0], 100) and rx.seed_counter(r, sc[1], 7000)
    assert not rx.seed_counter(r, sc[0], 999) and not rx.seed_counter(r, sc[1], 999)
    assert rx.spent_micro(r, sc[0]) == 100 and rx.spent_micro(r, sc[1]) == 7000


# --- rate limits ---

@needs_redis
def test_rate_limit_window(r) -> None:
    tab = {"x": (3, 60)}
    t = 1_000_020.0
    res = [rx.rate_limit(r, "x", "sub", now=t, table=tab) for _ in range(4)]
    assert [a for a, _ in res] == [True, True, True, False]
    assert 1 <= res[3][1] <= 60
    assert rx.rate_limit(r, "x", "sub", now=t + 60, table=tab) == (True, 0)  # next window
    assert rx.rate_limit(r, "x", "other", now=t, table=tab)[0]  # per subject
    assert all(0 < r.ttl(k) <= 60 for k in r.keys("perch:rl:*"))


def test_rate_table_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERCH_RATE_LIMITS", '{"submit_job": [2, 30]}')
    assert rx.rate_table()["submit_job"] == (2, 30)
    assert rx.rate_table()["api_read"] == (300, 60)


# --- response cache and epoch ---

def test_cache_key_is_canonical() -> None:
    a = rx.cache_key(3, "awards", "b=2&a=1")
    assert a == rx.cache_key(3, "awards", {"a": "1", "b": "2"})
    assert a.startswith("perch:rc:3:awards:") and a != rx.cache_key(4, "awards", "a=1&b=2")


@needs_redis
def test_cache_invalidates_with_epoch(r) -> None:
    ep = rx.current_epoch(r, lambda: 5)
    assert ep == 5 and rx.current_epoch(r, lambda: 99) == 5  # NX: a live key is kept
    rx.cache_put(r, ep, "awards", "q=1", "body", ttl=30)
    assert rx.cache_get(r, ep, "awards", "q=1") == "body"
    assert 0 < r.ttl(rx.cache_key(ep, "awards", "q=1")) <= 30
    rx.set_epoch(r, 6)
    assert rx.cache_get(r, rx.current_epoch(r), "awards", "q=1") is None


# --- shred channel ---

@needs_redis
def test_shred_publish_reaches_subscriber(r) -> None:
    got: list[uuid.UUID] = []
    stop = rx.listen_shreds(rx.get_client(URL), got.append)
    try:
        time.sleep(0.2)
        uid = uuid.uuid4()
        assert rx.publish_shred(r, uid) >= 1
        for _ in range(40):
            if got:
                break
            time.sleep(0.05)
        assert got == [uid]
    finally:
        stop()


@needs_redis
def test_keys_hold_no_user_text(r) -> None:
    rx.create_session(r, uid=uuid.uuid4(), name="SYNTHETIC Canary Name")
    rx.rate_limit(r, "api_read", rx.hash_subject("203.0.113.9", "p"))
    assert all("canary" not in k.lower() for k in r.keys("*"))


# --- shred hooks ---

def test_ledger_and_rekey_hooks(tmp_path) -> None:
    from perch import shredhooks

    uid = uuid.uuid4()
    shredhooks.ledger_hook(str(tmp_path / "ledger"))(uid)
    shredhooks.ledger_hook(str(tmp_path / "ledger"))(uid)  # idempotent
    f = tmp_path / "ledger" / str(uid)
    assert f.read_text().strip() == datetime.now(UTC).date().isoformat()

    calls: list[tuple] = []

    class Runner:
        def submit(self, *a):
            calls.append(a)

    shredhooks.rekey_hook(Runner())(uid)
    assert calls == [("purge", {"action": "rekey", "user_id": str(uid)}, None, f"rekey:{uid}")]


@needs_redis
def test_publish_hook(r) -> None:
    from perch import shredhooks

    got: list[uuid.UUID] = []
    stop = rx.listen_shreds(rx.get_client(URL), got.append)
    try:
        time.sleep(0.2)
        uid = uuid.uuid4()
        shredhooks.publish_hook(r)(uid)
        for _ in range(40):
            if got:
                break
            time.sleep(0.05)
        assert got == [uid]
    finally:
        stop()


def test_hash_subject_refuses_an_empty_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERCH_PEPPER_GUEST", raising=False)
    with pytest.raises(RuntimeError):
        rx.hash_subject("a")
    with pytest.raises(RuntimeError):
        rx.hash_subject("a", "")
    monkeypatch.setenv("PERCH_PEPPER_GUEST", "x")
    assert len(rx.hash_subject("a")) == 64


def test_global_caps_are_not_a_lockout() -> None:
    assert rx.RATE_DEFAULTS["login_global"][0] >= 10000
    assert rx.RATE_DEFAULTS["guest_new_global"][0] >= 10000
