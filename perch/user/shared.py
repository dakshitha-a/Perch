"""Shared demo accounts: the nightly wipe and the one-time setup (operator tools).

A shared account is a SYNTHETIC audience account whose sign-in is handed out in public, so
everyone who signs in sees what the last visitor saved. Two operator commands keep it clean:

  wipe_user_data   deletes every row of user data and every job, and clears the OpenAlex link.
                   The account row, its consents, its roles and the spend ledger stay. The
                   ledger stays on purpose: a wipe must not reset the daily budget.
  prepare_shared   makes the account ready to use: both roles and consent at the current
                   version, so a visitor lands in the app and not on the first-time Welcome.

Both run with an admin DSN the operator supplies: a superuser, or a role with BYPASSRLS,
because row-level security is forced on the user tables (the web, worker and owner roles cannot
reach them without a signed-in user). They refuse any other role. The database stores only
a hash of the identity provider's user id, never the sign-in name, so these take the user id
(`--subject`). Nothing here logs an id, a name or any user text.
"""

from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from perch.auth import accounts
from perch.auth.settings import consent_provider_name, consent_version
from perch.store import pg

ROLES = ("student", "researcher")


def wipe_user_data(pool: ConnectionPool, user_id: UUID) -> dict[str, int]:
    """Delete the user's data rows, jobs and OpenAlex link. Counts only."""
    require_admin(pool)
    with pg.user_tx(pool, user_id) as c:
        ev = c.execute("DELETE FROM job_events WHERE job_id IN "
                       "(SELECT id FROM jobs WHERE user_id = %s)", (user_id,)).rowcount
        jobs = c.execute("DELETE FROM jobs WHERE user_id = %s", (user_id,)).rowcount
        rows = c.execute("DELETE FROM user_data WHERE user_id = %s", (user_id,)).rowcount
        c.execute("UPDATE users SET openalex_id_enc = NULL, openalex_linked_at = NULL "
                  "WHERE id = %s", (user_id,))
        c.execute("INSERT INTO audit_log (event, detail) VALUES ('shared_account_wipe', %s)",
                  (Jsonb({"rows": rows, "jobs": jobs, "job_events": ev}),))
    return {"rows": rows, "jobs": jobs, "job_events": ev}


def find_user(pool: ConnectionPool, issuer: str, subject: str) -> UUID | None:
    """The user id for an identity, or None when that identity never signed in."""
    with pg.public_tx(pool) as c:
        row = c.execute("SELECT id FROM users WHERE issuer_hash = %s AND subject_hash = %s "
                        "AND deleted_at IS NULL",
                        (accounts.issuer_hash(issuer), accounts.subject_hash(subject))).fetchone()
    return row[0] if row else None


class NotAdmin(Exception):
    """The DSN's role is subject to row-level security, so it would see no user rows."""


def require_admin(pool: ConnectionPool) -> None:
    """Row-level security is forced on the user tables, so only a superuser or a role with
    BYPASSRLS can reach another account's rows. The web, worker and owner roles cannot."""
    with pg.public_tx(pool) as c:
        ok = c.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles "
                       "WHERE rolname = current_user").fetchone()
    if not ok or not ok[0]:
        raise NotAdmin("the DSN must be a superuser or a role with BYPASSRLS")


def prepare_shared(pool: ConnectionPool, issuer: str, subject: str,
                   roles: list[str]) -> UUID:
    """Create the account row when it is missing, set the roles and record consent at the
    current version. The consent is recorded by the operator for a SYNTHETIC shared account;
    the audit entry says so."""
    require_admin(pool)
    bad = [r for r in roles if r not in ROLES]
    if bad or not roles:
        raise ValueError("roles must be student, researcher or both")
    uid = accounts.login_user(pool, issuer, subject)  # creates the row on first use
    accounts.set_roles(pool, uid, roles)
    need = consent_version()
    if accounts.load_account(pool, uid).consent_version < need:
        accounts.add_consent(pool, uid, need, consent_provider_name())
    with pg.public_tx(pool) as c:
        c.execute("INSERT INTO audit_log (event, detail) VALUES ('shared_account_prepare', %s)",
                  (Jsonb({"consent_version": need, "roles": sorted(roles),
                          "note": "consent recorded by the operator for a SYNTHETIC "
                                  "shared account, not by a visitor"}),))
    return uid
