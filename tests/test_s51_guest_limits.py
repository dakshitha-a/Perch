"""S51 E4: the guest brief limit. `guest_job` counts per guest session, and a new scope,
`guest_job_addr`, counts per client address, so 30 guests on one venue address share one
window. A brief with explanations off counts against both. Needs the test Redis (DB 15)."""

from __future__ import annotations

import os
import time
import uuid
from datetime import date

import pytest

from perch.auth.session import Session

REDIS_URL = os.environ.get("PERCH_TEST_REDIS_URL", "")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")
AS_OF = date(2026, 10, 28)


class Runner:
    """A queue stub: no live job to reuse; each submit is a new job id."""

    def submit(self, *a, **kw):
        return uuid.uuid4()


def guest(sid: str) -> Session:
    return Session(sid=sid, user_id=None, guest=True, roles=frozenset(), audience="researcher",
                   csrf="c", display_name=None, created=time.time(),
                   abs_exp=time.time() + 3600)


@pytest.fixture
def r():
    import redis as redis_lib

    assert REDIS_URL.rstrip("/").endswith("/15")
    c = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
    c.flushdb()
    yield c
    c.flushdb()
    c.close()


def test_guest_briefs_from_one_address_share_one_window(r, tmp_path, monkeypatch):
    from perch.user import briefs as ub
    from perch.user.quota import RateLimited
    from tests.test_api import make

    monkeypatch.setenv("PERCH_RATE_LIMITS", '{"guest_job": [5, 600], "guest_job_addr": [3, 600]}')
    _, svc = make(tmp_path)
    addr = "ad" * 32
    for i in range(3):  # three guests on one address, one brief each, explanations off
        ub.submit_brief(svc, Runner(), None, r, guest(f"g-{i}" + "x" * 20), "A5026494099",
                        addr_hash=addr, as_of=AS_OF, explain=False, top=10 + i)
    with pytest.raises(RateLimited) as e:
        ub.submit_brief(svc, Runner(), None, r, guest("g-3" + "x" * 20), "A5026494099",
                        addr_hash=addr, as_of=AS_OF, explain=False)
    assert e.value.scope == "guest_job_addr"
    # another address still has its own window
    ub.submit_brief(svc, Runner(), None, r, guest("g-4" + "x" * 20), "A5026494099",
                    addr_hash="be" * 32, as_of=AS_OF, explain=False)


def test_a_brief_with_explanations_off_counts_against_the_session(r, tmp_path, monkeypatch):
    from perch.user import briefs as ub
    from perch.user.quota import RateLimited
    from tests.test_api import make

    monkeypatch.setenv("PERCH_RATE_LIMITS", '{"guest_job": [2, 600]}')
    _, svc = make(tmp_path)
    s = guest("g-s" + "y" * 20)
    for top in (10, 11):
        ub.submit_brief(svc, Runner(), None, r, s, "A5026494099", addr_hash="cd" * 32,
                        as_of=AS_OF, explain=False, top=top)
    with pytest.raises(RateLimited):
        ub.submit_brief(svc, Runner(), None, r, s, "A5026494099", addr_hash="cd" * 32,
                        as_of=AS_OF, explain=False, top=12)


def test_the_address_scope_has_a_default():
    from perch.redisx import RATE_DEFAULTS

    assert RATE_DEFAULTS["guest_job_addr"] == (60, 600)
