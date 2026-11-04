"""Shared fixtures for the user-data tests. SYNTHETIC text only."""

from __future__ import annotations

import base64
import os
from uuid import UUID, uuid4

import psycopg

from tests.conftest import PgDb

CANARY = "SYNTHETIC-canary-user-text-5d1e"


def make_env(mid: str = "m1") -> dict[str, str]:
    return {"PERCH_MASTER_KEY": base64.b64encode(os.urandom(32)).decode(),
            "PERCH_MASTER_KEY_ID": mid}


def new_user(pgdb: PgDb) -> UUID:
    with psycopg.connect(pgdb.admin, autocommit=True) as c:
        return c.execute("SELECT perch_login_user(%s, %s)",
                         (b"iss", uuid4().bytes)).fetchone()[0]
