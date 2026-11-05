"""The saved list: /me/saved (S49 V2). SYNTHETIC user and records.

Needs PERCH_TEST_DATABASE_URL and PERCH_TEST_REDIS_URL (DB 15), like tests/test_user_account.py.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime

import pytest

from perch.auth import deps
from perch.schemas import Brief, Lead
from perch.store.sqlite import SQLiteRepository
from perch.user import saved
from perch.user.models import StoredBrief
from tests.test_browse_sort import sch
from tests.test_store import opp, sample_sch
from tests.test_user_account import (  # noqa: F401 - fixtures
    REDIS_URL,
    env,
    pytestmark,
    rds,
    sql,
)

NOW = datetime(2026, 11, 4, tzinfo=UTC)
FUTURE_A, FUTURE_B = date(2027, 3, 1), date(2027, 1, 10)
PAST = date(2026, 2, 1)


@pytest.fixture
def pub(env, tmp_path):  # noqa: F811
    db = tmp_path / "pub.db"
    with SQLiteRepository(db) as r:
        r.upsert([sch("far", "SYNTHETIC Far Prize", FUTURE_A, 100),
                  sch("near", "SYNTHETIC Near Prize", FUTURE_B, None),
                  sch("old", "SYNTHETIC Old Prize", PAST, None),
                  sch("undated", "SYNTHETIC Undated Prize", None, None),
                  opp("G1", "SYNTHETIC grant", FUTURE_A), sample_sch(1)])
    env.client.app.state.public_repo = lambda: SQLiteRepository(db)
    return env


def post(env, rid, side="student"):  # noqa: F811
    return env.client.post(f"/me/saved?audience={side}", json={"record_id": rid})


def kept_lead(env, record_id, route="S", status="kept", sample=False):  # noqa: F811
    brief = Brief(id="b1", source="perch", source_url="perch://b1", fetched_at=NOW,
                  researcher_id="r", created_at=NOW)
    lead = Lead(id="l1", source="perch", source_url="perch://l1", fetched_at=NOW,
                brief_id="b1", route=route, record_id=record_id, status=status, sample=sample)
    return env.ud.put(env.uid, "brief", "student", StoredBrief(brief=brief, leads=[lead]))


def test_post_is_idempotent(pub):
    first = post(pub, "temple_pages:far")
    again = post(pub, "temple_pages:far")
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["saved_id"] == again.json()["saved_id"]
    assert pub.client.get("/me/saved?audience=student").json()["total"] == 1


def test_a_sample_is_refused_and_an_unknown_id_is_404(pub):
    r = post(pub, "sample:sch-0001")
    assert r.status_code == 422 and r.json()["detail"] == {"error": "sample_not_saved"}
    assert post(pub, "temple_pages:nope").status_code == 404
    assert pub.client.get("/me/saved?audience=student").json()["total"] == 0


def test_a_kept_lead_and_a_saved_row_for_one_record_become_one_item(pub):
    bid = kept_lead(pub, "temple_pages:far")
    sid = post(pub, "temple_pages:far").json()["saved_id"]
    body = pub.client.get("/me/saved?audience=student").json()
    assert body["total"] == 1
    (it,) = body["items"]
    assert it["saved_id"] == sid and it["kept_in"][0]["brief_id"] == str(bid)
    assert it["kept_in"][0]["built_at"].startswith("2026-11-04")
    assert it["record"]["name"] == "SYNTHETIC Far Prize" and it["record"]["deadline"]


def test_kept_only_has_no_saved_id_and_a_missing_record_is_null_and_samples_never_appear(pub):
    kept_lead(pub, "grants_gov:gone", route="A")
    body = pub.client.get("/me/saved?audience=student").json()
    assert [(i["record_id"], i["saved_id"], i["record"]) for i in body["items"]] == [
        ("grants_gov:gone", None, None)]
    kept_lead(pub, "sample:sch-0001", route="S", sample=True)
    kept_lead(pub, "temple_pages:far", route="S", status="new")
    ids = [i["record_id"] for i in pub.client.get("/me/saved?audience=student").json()["items"]]
    assert "sample:sch-0001" not in ids and "temple_pages:far" not in ids


def test_order_upcoming_then_past_then_no_date_then_no_record(pub, monkeypatch):
    for rid in ("temple_pages:undated", "temple_pages:old", "temple_pages:far",
                "temple_pages:near", "G1"):
        assert post(pub, rid).status_code == 201
    kept_lead(pub, "grants_gov:gone", route="A")
    items = saved.listing(pub.ud, pub.client.app.state.public_repo, pub.uid, "student",
                          today=date(2026, 11, 4))["items"]
    got = [i["record_id"] for i in items]
    # near (2027-01-10), then far and G1 (2027-03-01, tie by title), past, no date, no record
    assert got[0] == "temple_pages:near" and set(got[1:3]) == {"temple_pages:far", "G1"}
    assert got[3:] == ["temple_pages:old", "temple_pages:undated", "grants_gov:gone"]


def test_the_saved_list_is_per_side_and_delete_removes_the_row(pub):
    sid = post(pub, "temple_pages:far").json()["saved_id"]
    assert pub.client.get("/me/saved?audience=researcher").json()["total"] == 0
    assert pub.client.delete(f"/me/saved/{uuid.uuid4()}").status_code == 404
    assert pub.client.delete(f"/me/saved/{sid}").json() == {"ok": True}
    assert pub.client.get("/me/saved?audience=student").json()["total"] == 0
    assert pub.client.delete(f"/me/saved/{sid}").status_code == 404


def test_delete_leaves_other_kinds_of_rows_alone(pub):
    bid = kept_lead(pub, "temple_pages:far")
    assert pub.client.delete(f"/me/saved/{bid}").status_code == 404
    assert pub.client.get(f"/me/briefs/{bid}").status_code == 200


def test_the_cap_is_200_per_side(pub, monkeypatch):
    monkeypatch.setattr(saved, "MAX_SAVED", 1)
    assert post(pub, "temple_pages:far").status_code == 201
    r = post(pub, "temple_pages:near")
    assert r.status_code == 409 and r.json()["detail"] == {"error": "saved_full"}
    assert post(pub, "temple_pages:far").status_code == 200  # a repeat still answers


def test_a_guest_gets_403(pub, monkeypatch):
    pub.client.app.dependency_overrides.pop(deps.require_user)

    async def guest(request):
        from perch.auth.session import Session
        return Session(sid="g", user_id=None, guest=True, roles=frozenset(), audience="student",
                       csrf="c", display_name=None, created=0, abs_exp=1e12, consent_version=0)

    monkeypatch.setattr(deps, "require_session", guest)
    assert pub.client.get("/me/saved").status_code == 403
    assert post(pub, "temple_pages:far").status_code == 403
    assert pub.client.delete(f"/me/saved/{uuid.uuid4()}").status_code == 403


def test_without_consent_a_save_is_refused(pub):
    pub.session.consent_version = 0
    assert post(pub, "temple_pages:far").status_code == 403


def test_no_plain_record_id_in_logs_audit_or_blobs(pub, caplog):
    caplog.set_level(logging.DEBUG)
    rid = "temple_pages:far"
    sid = post(pub, rid).json()["saved_id"]
    pub.client.get("/me/saved?audience=student")
    (blob,) = sql(pub.pg, "SELECT blob FROM user_data WHERE kind = 'saved_item'")[0]
    assert rid.encode() not in bytes(blob)
    pub.client.delete(f"/me/saved/{sid}")
    assert rid not in caplog.text
    assert not sql(pub.pg, "SELECT 1 FROM audit_log a WHERE a::text LIKE %s", f"%{rid}%")


def test_brief_summaries_count_kept_public_and_sample_leads_apart(pub):
    kept_lead(pub, "temple_pages:far")
    kept_lead(pub, "sample:sch-0001", sample=True)
    kept_lead(pub, "temple_pages:near", status="new")
    rows = pub.client.get("/me/briefs?audience=student").json()
    assert sorted((r["kept"], r["sample_kept"]) for r in rows) == [(0, 0), (0, 1), (1, 0)]
