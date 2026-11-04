"""Key maintenance run by the worker and by `perch keys` (ARCHITECTURE_V1 sections 6.5, 6.6).

* rekey: re-encrypt a user's stored blobs under that user's newest data key version.
* tombstone retention: remove tombstones older than the retention from all three copies.

Every result is counts and ids only. Nothing here logs or returns plaintext, blobs or keys.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from perch import crypto
from perch.config import env
from perch.crypto import Aad, CryptoError, DecryptError, KeyMissing, KeyShredded
from perch.store import pg

log = logging.getLogger("perch.keyops")

REKEY_BATCH = 100


def audit(pool: ConnectionPool, event: str, **counts: int | str) -> None:
    """One audit_log row with counts and ids only."""
    with pg.public_tx(pool) as c:
        c.execute("INSERT INTO audit_log (event, detail) VALUES (%s, %s)",
                  (event, Jsonb(dict(counts))))


def rekey_user(pool: ConnectionPool, user_id: UUID, *, dry_run: bool = False,
               batch: int = REKEY_BATCH) -> dict[str, int]:
    """Re-encrypt the user's rows whose key_version is below the newest. One batch per
    transaction; each row is locked FOR UPDATE, read, re-sealed with the same AAD and written
    back with only blob and key_version changed (updated_at stays, so an open editor's
    optimistic check is not broken). Idempotent: a second run finds nothing. A shredded user
    or a user with no key has nothing to do. Returns {"stale", "done", "failed"}; with
    dry_run only "stale" is filled and nothing is decrypted or written."""
    from perch.user.data import aad_for

    out = {"stale": 0, "done": 0, "failed": 0}
    newest = crypto.newest_version(user_id)
    if newest is None:
        return out
    if dry_run:
        with pg.user_tx(pool, user_id) as c:
            out["stale"] = c.execute(
                "SELECT count(*) FROM user_data WHERE user_id = %s AND key_version < %s",
                (user_id, newest)).fetchone()[0]
            link = c.execute("SELECT openalex_id_enc FROM users WHERE id = %s",
                             (user_id,)).fetchone()
            if link and link[0] is not None and crypto.key_version_of(bytes(link[0])) < newest:
                out["stale"] += 1
        return out
    skip: list[UUID] = []
    while True:
        with pg.user_tx(pool, user_id) as c:
            rows = c.execute(
                "SELECT id, kind, audience, blob FROM user_data WHERE user_id = %s "
                "AND key_version < %s AND id <> ALL(%s::uuid[]) ORDER BY id LIMIT %s "
                "FOR UPDATE", (user_id, newest, skip, batch)).fetchall()
            if not rows:
                break
            for rid, kind, audience, blob in rows:
                aad = aad_for(user_id, rid, kind, audience)
                out["stale"] += 1
                try:
                    new = crypto.encrypt_field(
                        user_id, crypto.decrypt_field(user_id, bytes(blob), aad), aad)
                except KeyShredded:
                    return out
                except (DecryptError, KeyMissing):
                    out["failed"] += 1
                    skip.append(rid)
                    continue
                c.execute("UPDATE user_data SET blob = %s, key_version = %s WHERE id = %s "
                          "AND user_id = %s", (new, crypto.key_version_of(new), rid, user_id))
                out["done"] += 1
    link_aad = Aad(user_id, "users", "openalex_id_enc", str(user_id))
    with pg.user_tx(pool, user_id) as c:  # the OpenAlex link blob on users
        link = c.execute("SELECT openalex_id_enc FROM users WHERE id = %s FOR UPDATE",
                         (user_id,)).fetchone()
        if link and link[0] is not None and crypto.key_version_of(bytes(link[0])) < newest:
            out["stale"] += 1
            try:
                new = crypto.encrypt_field(
                    user_id, crypto.decrypt_field(user_id, bytes(link[0]), link_aad), link_aad)
                c.execute("UPDATE users SET openalex_id_enc = %s WHERE id = %s", (new, user_id))
                out["done"] += 1
            except KeyShredded:
                pass
            except (DecryptError, KeyMissing):
                out["failed"] += 1
    return out


def rekey_all(pool: ConnectionPool, *, dry_run: bool = False, page: int = 200
              ) -> dict[str, int]:
    """rekey_user for every user whose key has been rotated (more than one version). Users
    with a single version have nothing stale. The list comes from the keys database, so no
    cross-user read of the data database is needed. Resumable: a rerun skips finished rows."""
    total = {"users": 0, "stale": 0, "done": 0, "failed": 0}
    after: UUID | None = None
    while True:
        users = crypto.users_with_rotated_keys(after, page)
        if not users:
            return total
        for uid, _ in users:
            r = rekey_user(pool, uid, dry_run=dry_run)
            total["users"] += 1
            for k in ("stale", "done", "failed"):
                total[k] += r[k]
        after = users[-1][0]


def _backup_days() -> int:
    try:
        return int(env("BACKUP_RETENTION_DAYS") or 35)
    except ValueError:
        raise CryptoError("retention settings must be whole numbers") from None


def retention_days() -> int:
    """PERCH_TOMBSTONE_RETENTION_DAYS (default 400), never below the 400 day floor or the
    longest backup retention (BACKUP_RETENTION_DAYS, default 35). Raises CryptoError."""
    raw = env("PERCH_TOMBSTONE_RETENTION_DAYS")
    try:
        configured = int(raw) if raw else None
    except ValueError:
        raise CryptoError("retention settings must be whole numbers") from None
    return crypto.tombstone_retention_days(_backup_days(), configured)


def _ledger_old(older_than_days: int, ledger: str | None, dry_run: bool) -> int:
    """Ledger objects (dev: a directory) whose recorded date is past the retention."""
    d = ledger if ledger is not None else env("PERCH_SHRED_LEDGER_URI")
    if not d or "://" in d or not Path(d).is_dir():
        return 0
    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).date()
    n = 0
    for f in Path(d).iterdir():
        try:
            UUID(f.name)
            when = datetime.strptime(f.read_text().strip(), "%Y-%m-%d").date()  # noqa: DTZ007
        except (ValueError, OSError):
            continue  # not a ledger object, or unreadable: leave it
        if when < cutoff:
            n += 1
            if not dry_run:
                f.unlink()
    return n


def purge_old_tombstones(pool: ConnectionPool, *, dry_run: bool = True,
                         days: int | None = None, ledger: str | None = None
                         ) -> dict[str, int]:
    """Remove tombstones older than the retention from the ledger, shred_log and key_tombstones.
    The keys database goes last, so reconcile-shreds cannot re-assert a tombstone from a copy
    that was purged later. Counts only."""
    days = retention_days() if days is None else crypto.tombstone_retention_days(
        _backup_days(), days)
    out = {"retention_days": days, "ledger": _ledger_old(days, ledger, dry_run)}
    with pg.public_tx(pool) as c:
        if dry_run:
            out["shred_log"] = c.execute(
                "SELECT count(*) FROM shred_log WHERE shredded_at < now() - %s * interval '1 day'",
                (days,)).fetchone()[0]
        else:
            out["shred_log"] = c.execute(
                "DELETE FROM shred_log WHERE shredded_at < now() - %s * interval '1 day'",
                (days,)).rowcount
    out["key_tombstones"] = crypto.purge_tombstones(days, dry_run=dry_run)
    log.info("tombstone purge dry_run=%s counts=%s", dry_run, out)
    return out
