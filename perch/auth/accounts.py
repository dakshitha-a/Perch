"""Account rows behind sign-in (sections 2.1, 7.2 and 7.5). Synchronous: routes call these
through the thread pool. Every statement runs through the pool's role, perch_web, so row-level
security fences it to the signed-in user; login uses the definer function perch_login_user.

Nothing here logs an id, a subject, a token or the OpenAlex id."""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from uuid import UUID

from psycopg_pool import ConnectionPool

from perch.auth.consent import consent_sha256
from perch.config import env
from perch.store.pg import public_tx, user_tx


def issuer_hash(issuer: str) -> bytes:
    return hashlib.sha256(issuer.encode()).digest()


def subject_hash(subject: str) -> bytes:
    """HMAC-SHA256(PERCH_PEPPER, IdP subject)."""
    raw = env("PERCH_PEPPER")
    if not raw:
        raise RuntimeError("PERCH_PEPPER is not set")
    return hmac.new(base64.b64decode(raw), subject.encode(), hashlib.sha256).digest()


@dataclass(frozen=True)
class Account:
    user_id: UUID
    roles: frozenset[str]
    last_audience: str | None
    consent_version: int  # 0 when none or withdrawn
    openalex_linked: bool


def login_user(pool: ConnectionPool, issuer: str, subject: str) -> UUID:
    with public_tx(pool) as c:
        row = c.execute("SELECT perch_login_user(%s, %s)",
                        (issuer_hash(issuer), subject_hash(subject))).fetchone()
    return row[0]


def consent_version_of(c, user_id: UUID) -> int:  # noqa: ANN001
    row = c.execute("SELECT version, withdrawn_at FROM consents WHERE user_id = %s "
                    "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return int(row[0]) if row and row[1] is None else 0


def load_account(pool: ConnectionPool, user_id: UUID) -> Account:
    with user_tx(pool, user_id) as c:
        u = c.execute("SELECT roles, last_audience, openalex_id_enc IS NOT NULL FROM users "
                      "WHERE id = %s", (user_id,)).fetchone()
        if u is None:
            raise LookupError("user")
        return Account(user_id, frozenset(u[0]), u[1], consent_version_of(c, user_id), bool(u[2]))


def set_roles(pool: ConnectionPool, user_id: UUID, chosen: list[str]) -> frozenset[str]:
    """Replace the self-chosen roles and keep an existing `staff` (granted by the operator)."""
    with user_tx(pool, user_id) as c:
        cur = c.execute("SELECT roles FROM users WHERE id = %s", (user_id,)).fetchone()
        if cur is None:
            raise LookupError("user")
        roles = sorted(set(chosen) | ({"staff"} & set(cur[0])))
        c.execute("UPDATE users SET roles = %s WHERE id = %s", (roles, user_id))
    return frozenset(roles)


def set_last_audience(pool: ConnectionPool, user_id: UUID, audience: str) -> None:
    with user_tx(pool, user_id) as c:
        c.execute("UPDATE users SET last_audience = %s WHERE id = %s", (audience, user_id))


def add_consent(pool: ConnectionPool, user_id: UUID, version: int, provider: str) -> None:
    with user_tx(pool, user_id) as c:
        c.execute("INSERT INTO consents (user_id, version, provider_name, text_sha256) "
                  "VALUES (%s, %s, %s, %s)", (user_id, version, provider, consent_sha256()))


def withdraw_consent(pool: ConnectionPool, user_id: UUID) -> int:
    with user_tx(pool, user_id) as c:
        cur = c.execute("UPDATE consents SET withdrawn_at = now() "
                        "WHERE user_id = %s AND withdrawn_at IS NULL", (user_id,))
        return cur.rowcount
