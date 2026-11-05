"""Security follow-ups after the S48 review. SYNTHETIC text only.

1. The worker reconciles at every start, cheaply when nothing is out of step.
2. A failed tombstone-copy write is a failure, and the delete flow reports it.
3. Guest spend: the day ceiling times 30 stays under the month; a per-address day cap.
5. Web and worker refuse to start without their secrets.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from unittest import mock

import psycopg
import pytest

from perch import crypto, shredhooks
from perch import redisx as rx
from perch.crypto import CryptoError
from perch.keystore import EnvKeyStore
from perch.user.models import EntryDoc
from tests.test_redis import needs_redis, r  # noqa: F401 - fixtures
from tests.test_restore_safety import TEXT, _admin, _keys_db, db
from tests.test_user_account import KEYS_URL, env, rds, sql  # noqa: F401 - fixtures
from tests.user_helpers import make_env

# --- 1. start-up reconcile ---

@db
def test_start_reconcile_runs_without_a_marker_only_when_out_of_step(
        env, pg_clean, worker_pool, tmp_path):  # noqa: F811
    from perch.keystore import KeyRepository
    from perch.shredhooks import ledger_hook, shred_log_hook

    ledger = tmp_path / "ledger"
    name, admin, rt = _keys_db()
    repo = KeyRepository(rt)
    try:
        crypto.configure(repo=repo, keystore=EnvKeyStore(make_env()),
                         shred_hooks=[shred_log_hook(env.pool), ledger_hook(str(ledger))])
        assert shredhooks.reconcile_at_start(rt, worker_pool, str(ledger)) is None
        env.ud.put(env.uid, "entry", "student", EntryDoc(text=TEXT))
        _admin(admin, "CREATE TABLE snap_keys AS SELECT * FROM user_keys WHERE user_id = %s",
               env.uid)
        crypto.shred(env.uid)
        # every copy agrees: nothing to do
        assert not shredhooks.out_of_step(rt, worker_pool, str(ledger))
        assert shredhooks.reconcile_at_start(rt, worker_pool, str(ledger)) is None
        # the keys database restored from before the shred, and no marker written
        _admin(admin, "DELETE FROM key_tombstones")
        _admin(admin, "INSERT INTO user_keys SELECT * FROM snap_keys")
        assert not shredhooks.restore_pending(str(ledger))
        assert shredhooks.out_of_step(rt, worker_pool, str(ledger))
        res = shredhooks.reconcile_at_start(rt, worker_pool, str(ledger))
        assert res and res["key_rows_revived"] == 1
        assert not shredhooks.out_of_step(rt, worker_pool, str(ledger))
        # the data database restored without its shred_log row is repaired too
        sql(pg_clean, "DELETE FROM shred_log")
        assert shredhooks.out_of_step(rt, worker_pool, str(ledger))
        assert shredhooks.reconcile_at_start(rt, worker_pool, str(ledger)) is not None
        assert sql(pg_clean, "SELECT count(*) FROM shred_log") == [(1,)]
        # the marker alone still forces a run, and the run clears it
        shredhooks.mark_restore(str(ledger))
        assert shredhooks.reconcile_at_start(rt, worker_pool, str(ledger)) is not None
        assert not shredhooks.restore_pending(str(ledger))
    finally:
        repo.close()
        crypto.configure()
        with psycopg.connect(KEYS_URL, autocommit=True) as c:
            c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_start_reconcile_with_a_marker_and_no_keys_url_refuses(tmp_path):
    shredhooks.mark_restore(str(tmp_path))
    with pytest.raises(shredhooks.LedgerMissing):
        shredhooks.reconcile_at_start(None, mock.Mock(), str(tmp_path))
    (tmp_path / shredhooks.RESTORE_MARKER).unlink()
    assert shredhooks.reconcile_at_start(None, mock.Mock(), str(tmp_path)) is None


# --- 2. a failed tombstone-copy write is a failure ---

def test_a_failed_ledger_write_is_reported_by_code(tmp_path, caplog):
    blocked = tmp_path / "ledger"
    blocked.write_text("a file where the directory should be")
    uid = uuid.uuid4()
    with caplog.at_level(logging.ERROR, logger="perch.shred"):
        with pytest.raises(shredhooks.ShredHookFailed) as e:
            shredhooks.ledger_hook(str(blocked))(uid)
    assert e.value.code == "ledger_write_failed" and str(uid) not in str(e.value)
    assert "code=ledger_write_failed" in caplog.text and str(uid) not in caplog.text


def test_a_failed_hook_makes_shred_raise_after_the_keys_are_gone(tmp_path):
    repo = mock.Mock()
    crypto.configure(repo=repo, keystore=mock.Mock(),
                     shred_hooks=[shredhooks.ledger_hook(str(_file(tmp_path)))])
    try:
        with pytest.raises(CryptoError):
            crypto.shred(uuid.uuid4())
        repo.shred.assert_called_once()
    finally:
        crypto.configure()


def _file(tmp_path):
    f = tmp_path / "notadir"
    f.write_text("x")
    return f


def test_the_delete_flow_finishes_the_order_then_reports_incomplete(monkeypatch):
    from perch.jobs import RetryableError
    from perch.user import delete

    uid = uuid.uuid4()
    calls: list[str] = []

    def failing_shred(u):
        calls.append("shred")
        raise CryptoError("hook failed")

    monkeypatch.setattr(delete.crypto, "shred", failing_shred)
    monkeypatch.setattr(delete, "_cancel_jobs", lambda *a: calls.append("cancel") or 0)
    monkeypatch.setattr(delete, "clear_rows", lambda *a: calls.append("clear"))
    with pytest.raises(CryptoError):
        delete.delete_account(uid, pool=mock.Mock(), runner=mock.Mock(), r=None, inline=True)
    assert calls == ["shred", "cancel", "clear"]  # the whole order ran before it reported

    calls.clear()  # the queued purge clears the rows, then asks for a retry of the hooks
    monkeypatch.setattr(delete, "queue_purge_retry", lambda *a: calls.append("retry"))
    ctx = mock.Mock(payload={"action": "user", "user_id": str(uid)}, pool=mock.Mock(),
                    user_id=uid)
    with pytest.raises(RetryableError):
        delete.purge_handler(ctx)
    # S50 C9: its own row went with the user's rows, so an ownerless job carries the retry
    assert calls == ["shred", "clear", "retry"]
    calls.clear()
    ctx.user_id = None  # that ownerless job retries itself
    with pytest.raises(RetryableError):
        delete.purge_handler(ctx)
    assert calls == ["shred", "clear"]


# --- 3. guest spend ---

def test_guest_defaults_stay_under_the_month_and_add_an_address_scope(monkeypatch) -> None:
    for v in ("PERCH_GUEST_GLOBAL_DAILY_BUDGET_USD", "PERCH_ANTHROPIC_BUDGET_USD",
              "PERCH_GUEST_ADDR_DAILY_BUDGET_USD"):
        monkeypatch.delenv(v, raising=False)
    sc = {s.name: s for s in rx.quota_scopes(gsid_hash="g", addr_hash="a")}
    assert sc["guest_global"].limit * 30 < sc["global"].limit
    assert sc["guest_addr"].limit == rx.usd_micro(0.30)
    assert sc["guest_addr"].spend.endswith(f":ga:a:{datetime.now(UTC):%Y%m%d}")
    assert "guest_addr" not in {s.name for s in rx.quota_scopes(gsid_hash="g")}


@needs_redis
def test_one_address_cannot_spend_past_its_cap_across_sessions(r) -> None:  # noqa: F811
    kw = {"guest_usd": 1, "guest_global_usd": 10, "month_usd": 100, "guest_addr_usd": 0.0001,
          "addr_hash": "addr-1"}
    a, b = rx.quota_scopes(gsid_hash="ga", **kw), rx.quota_scopes(gsid_hash="gb", **kw)
    rx.reserve(r, a, 60)
    with pytest.raises(rx.QuotaExceeded) as e:
        rx.reserve(r, b, 60)  # 100 micro dollars for the address
    assert e.value.scope == "guest_addr"
    rx.reserve(r, rx.quota_scopes(gsid_hash="gc", **{**kw, "addr_hash": "addr-2"}), 60)


@needs_redis
def test_admit_guest_refuses_a_spent_address_and_the_meter_finds_it(r) -> None:  # noqa: F811
    from perch.user import quota, spend

    gh, ah = "ab" * 32, "cd" * 32
    r.set(f"perch:gsess:{gh}:addr", ah)  # what submit_brief stores for the worker
    meter = spend.for_job(r, None, user_id=None, guest_sid_hash=bytes.fromhex(gh), job_id=None)
    assert "guest_addr" in {s.name for s in meter.scopes()}
    full = next(s for s in rx.quota_scopes(gsid_hash=gh, addr_hash=ah) if s.name == "guest_addr")
    rx.seed_counter(r, full, full.limit)
    with pytest.raises(rx.QuotaExceeded) as e:
        quota.admit_guest(r, "ef" * 32, addr_hash=ah)  # a different session, same address
    assert e.value.scope == "guest_addr"


# --- 5. secrets are required ---

def test_compose_requires_the_peppers_and_audit_key():
    from pathlib import Path

    import yaml

    c = yaml.safe_load((Path(__file__).resolve().parents[1]
                        / "deploy/compose/docker-compose.v1.yml").read_text())["services"]
    for svc, names in (("web", ("PERCH_PEPPER", "PERCH_PEPPER_GUEST")),
                       ("worker", ("PERCH_AUDIT_KEY",))):
        for n in names:
            assert re.fullmatch(rf"\$\{{{n}:\?.+\}}", str(c[svc]["environment"][n])), (svc, n)


def test_web_and_worker_refuse_to_start_without_their_secrets(monkeypatch, capsys):
    from perch import cli
    from perch.auth.wiring import require_peppers

    monkeypatch.setenv("PERCH_PEPPER", "x")
    monkeypatch.setenv("PERCH_PEPPER_GUEST", " ")
    with pytest.raises(RuntimeError, match="PERCH_PEPPER_GUEST"):
        require_peppers()
    monkeypatch.setenv("PERCH_PEPPER_GUEST", "y")
    require_peppers()

    monkeypatch.setenv("PERCH_ENV", "prod")
    monkeypatch.delenv("PERCH_AUDIT_KEY", raising=False)
    assert cli.cmd_worker(mock.Mock(check=False)) == 2
    assert "PERCH_AUDIT_KEY" in capsys.readouterr().err
