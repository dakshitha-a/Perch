"""S53: the stored citizenship and state picks (kind `profile`).

SYNTHETIC values only. Needs the test Postgres and Redis; run by `make test-user`."""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from perch.auth import deps
from perch.user.briefs import UserBriefStore, persona_inputs
from perch.user.models import ProfileDoc
from perch.user.routes import router
from tests.conftest import PG_URL
from tests.test_user_account import REDIS_URL, env, rds, sql  # noqa: F401 - fixtures

pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]


def put(env, body, side="student"):  # noqa: F811
    return env.client.put(f"/me/profile?audience={side}", json=body)


def test_round_trip_per_side(env):  # noqa: F811
    assert env.client.get("/me/profile?audience=student").json() == {
        "citizenship": None, "residency_state": None}
    r = put(env, {"citizenship": "permanent_resident", "residency_state": "PA"})
    assert r.status_code == 200, r.text
    assert env.client.get("/me/profile?audience=student").json() == {
        "citizenship": "permanent_resident", "residency_state": "PA"}
    # the other side is its own row
    assert env.client.get("/me/profile?audience=researcher").json()["citizenship"] is None
    put(env, {"citizenship": "us_citizen", "residency_state": None}, "researcher")
    assert env.client.get("/me/profile?audience=researcher").json() == {
        "citizenship": "us_citizen", "residency_state": None}
    # a second save replaces: still one row per side
    put(env, {"citizenship": "international", "residency_state": "NJ"})
    assert sql(env.pg, "SELECT count(*) FROM user_data WHERE kind = 'profile'") == [(2,)]
    assert env.client.get("/me/profile?audience=student").json()["citizenship"] == "international"


def test_blank_picks_remove_the_row(env):  # noqa: F811
    put(env, {"citizenship": "us_citizen"})
    assert put(env, {"citizenship": None, "residency_state": None}).status_code == 200
    assert sql(env.pg, "SELECT count(*) FROM user_data WHERE kind = 'profile'") == [(0,)]


def test_bad_values_are_422(env):  # noqa: F811
    for body in ({"citizenship": "citizen"}, {"citizenship": "US_CITIZEN"},
                 {"residency_state": "XX"}, {"residency_state": "Pennsylvania"},
                 {"residency_state": "pa"}):
        r = put(env, body)
        assert r.status_code == 422, body
    assert sql(env.pg, "SELECT count(*) FROM user_data WHERE kind = 'profile'") == [(0,)]
    # all 50 states and DC are accepted
    from perch.citizenship import STATE_CODES

    assert len(STATE_CODES) == 51 and "DC" in STATE_CODES
    assert put(env, {"residency_state": "DC"}).status_code == 200


def test_saving_needs_consent_and_csrf(env):  # noqa: F811
    env.session.consent_version = 0
    assert put(env, {"citizenship": "us_citizen"}).status_code == 403
    assert env.client.get("/me/profile?audience=student").status_code == 200  # reading is open
    route = next(r for r in router.routes if r.path == "/me/profile" and "PUT" in r.methods)
    assert any(d.call is deps.require_csrf for d in route.dependant.dependencies)


def test_stored_encrypted_and_never_in_plain_text(env):  # noqa: F811
    put(env, {"citizenship": "permanent_resident", "residency_state": "PA"})
    (blob, audience) = sql(env.pg, "SELECT blob, audience FROM user_data WHERE kind = 'profile'")[0]
    raw = bytes(blob)
    assert audience == "student"
    for needle in (b"permanent_resident", b"PA", b"citizenship", b"residency"):
        assert needle not in raw


def test_the_unique_index_allows_one_row_per_user_and_side(env):  # noqa: F811
    put(env, {"citizenship": "us_citizen"})
    with psycopg.connect(env.pg.admin, autocommit=True) as c:
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute("INSERT INTO user_data (user_id, kind, audience, key_version, blob) "
                      "VALUES (%s, 'profile', 'student', 1, %s)", (env.uid, b"x"))


def test_the_student_job_reads_the_picks_and_the_guest_persona_is_international(env):  # noqa: F811
    put(env, {"citizenship": "international", "residency_state": "NJ"})
    store = UserBriefStore(env.ud, env.uid, "student", str(uuid.uuid4()))
    assert store.profile_picks() == ("international", "NJ")
    env.client.post("/me/docs", json={"kind": "cv", "text": "SYNTHETIC cv. Bachelor of Science."})
    inp = store.student_inputs()
    assert (inp.citizenship, inp.residency_state) == ("international", "NJ")
    assert UserBriefStore(env.ud, env.uid, "researcher", str(uuid.uuid4())).profile_picks() == (
        None, None)
    assert persona_inputs("persona-ug").citizenship == "international"


def test_delete_my_data_removes_the_profile_row(env, pg_clean):  # noqa: F811
    from tests.test_user_account import run_worker

    put(env, {"citizenship": "us_citizen", "residency_state": "PA"})
    assert env.client.post("/me/delete", json={"confirm": "delete"}).status_code == 202
    run_worker(pg_clean, ["purge"], lambda: sql(
        pg_clean, "SELECT count(*) FROM user_data WHERE kind = 'profile'") == [(0,)])
    assert sql(pg_clean, "SELECT count(*) FROM user_data WHERE kind = 'profile'") == [(0,)]


def test_profile_doc_rejects_unknown_fields_and_values():
    with pytest.raises(ValueError):
        ProfileDoc(citizenship="nope")
    with pytest.raises(ValueError):
        ProfileDoc.model_validate(json.loads('{"citizenship": null, "extra": 1}'))


def test_a_changed_pick_changes_the_researcher_brief_key(env):  # noqa: F811
    """S53 review: the same-day brief must not be returned after the pick changed."""
    from perch.user.briefs import compute_idempotency_key, side_row_ids

    def key():
        ids = side_row_ids(env.ud, env.uid, "researcher", ("profile",))
        return compute_idempotency_key(str(env.uid), "researcher", "A1", ids, {}), ids

    k0, ids0 = key()
    assert ids0 == []
    put(env, {"citizenship": "us_citizen", "residency_state": None}, "researcher")
    k1, ids1 = key()
    put(env, {"citizenship": "international", "residency_state": None}, "researcher")
    k2, ids2 = key()
    assert len(ids1) == len(ids2) == 1 and ids1 != ids2
    assert len({k0, k1, k2}) == 3
    put(env, {"citizenship": "us_citizen", "residency_state": None}, "student")
    assert len(side_row_ids(env.ud, env.uid, "student")) == 1
