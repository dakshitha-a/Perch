"""perch/user/data.py against Postgres (user_data with row-level security) and an in-memory key
repository. SYNTHETIC text only. Skips without PERCH_TEST_DATABASE_URL."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import psycopg
import pytest

from perch import crypto
from perch.crypto import DecryptError, KeyMissing, KeyShredded
from perch.user.data import BadBlob, Conflict, NotFound
from perch.user.models import CvDoc, EntryDoc, StoredBrief
from tests.conftest import PG_URL
from tests.user_helpers import CANARY, new_user

pytestmark = pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set")


def raw(pgdb, sql, *args):
    with psycopg.connect(pgdb.admin, autocommit=True) as c:
        cur = c.execute(sql, args)
        return cur.fetchall() if cur.description else []


def test_round_trip_stores_only_ciphertext(pg_clean, ud):
    uid = new_user(pg_clean)
    rid = ud.put(uid, "entry", "student", EntryDoc(text=CANARY, label="x"))
    (blob,) = raw(pg_clean, "SELECT blob FROM user_data WHERE id = %s", rid)[0]
    assert CANARY.encode() not in bytes(blob) and blob[0] == 1
    assert ud.get(uid, rid, EntryDoc).text == CANARY
    assert [m.text for _, m in ud.list(uid, "entry", "student", EntryDoc)] == [CANARY]
    assert ud.list(uid, "entry", "researcher", EntryDoc) == []  # sides stay apart


def test_row_moved_to_another_user_kind_or_side_fails_to_decrypt(pg_clean, ud):
    a, b = new_user(pg_clean), new_user(pg_clean)
    ra = ud.put(a, "entry", "student", EntryDoc(text=CANARY))
    rb = ud.put(b, "entry", "student", EntryDoc(text="SYNTHETIC other"))
    (blob_a,) = raw(pg_clean, "SELECT blob FROM user_data WHERE id = %s", ra)[0]
    # another user's key and AAD
    raw(pg_clean, "UPDATE user_data SET blob = %s WHERE id = %s", blob_a, rb)
    with pytest.raises(DecryptError):
        ud.get(b, rb, EntryDoc)
    # the same user, a different kind or audience column
    raw(pg_clean, "UPDATE user_data SET audience = 'researcher' WHERE id = %s", ra)
    with pytest.raises(DecryptError):
        ud.get(a, ra, EntryDoc)
    raw(pg_clean, "UPDATE user_data SET audience = 'student', kind = 'doc' WHERE id = %s", ra)
    with pytest.raises(DecryptError):
        ud.get(a, ra, EntryDoc)


def test_foreign_and_missing_ids_return_none(pg_clean, ud):
    a, b = new_user(pg_clean), new_user(pg_clean)
    ra = ud.put(a, "entry", "student", EntryDoc(text=CANARY))
    assert ud.get(b, ra, EntryDoc) is None  # row-level security and the user_id check
    assert ud.get(a, uuid4(), EntryDoc) is None
    assert ud.delete(b, ra) is False and ud.get(a, ra, EntryDoc) is not None
    with pytest.raises(NotFound):
        ud.update(b, ra, EntryDoc(text="x"), expect_updated_at=datetime.now())


def test_first_write_mints_a_key_only_when_the_user_has_no_rows(pg_clean, ud, keys):
    uid = new_user(pg_clean)
    ud.put(uid, "entry", "student", EntryDoc(text=CANARY))
    assert keys.latest(uid) is not None
    # the key disappears without a tombstone (a lost keys database): a second write must not
    # quietly mint a new key over rows that can no longer be read
    keys.keys.clear()
    crypto.clear_cache()
    with pytest.raises(KeyMissing):
        ud.put(uid, "entry", "student", EntryDoc(text="SYNTHETIC again"))
    assert keys.latest(uid) is None


def test_one_cv_per_audience_replaced_in_one_transaction(pg_clean, ud):
    uid = new_user(pg_clean)
    first = ud.put(uid, "cv", "student", CvDoc(text="SYNTHETIC cv one"))
    second = ud.put(uid, "cv", "student", CvDoc(text="SYNTHETIC cv two"))
    other = ud.put(uid, "cv", "researcher", CvDoc(text="SYNTHETIC researcher cv"))
    assert ud.get(uid, first, CvDoc) is None
    assert ud.get(uid, second, CvDoc).text == "SYNTHETIC cv two"
    assert ud.get(uid, other, CvDoc) is not None
    assert ud.count(uid) == 2


def test_stale_update_conflicts_and_the_new_stamp_chains(pg_clean, ud):
    uid = new_user(pg_clean)
    rid = ud.put(uid, "entry", "student", EntryDoc(text="SYNTHETIC v1"))
    _, ts, _, _ = ud.get_row(uid, rid, EntryDoc)
    ts2 = ud.update(uid, rid, EntryDoc(text="SYNTHETIC v2"), expect_updated_at=ts)
    with pytest.raises(Conflict):
        ud.update(uid, rid, EntryDoc(text="SYNTHETIC v3"), expect_updated_at=ts)
    ud.update(uid, rid, EntryDoc(text="SYNTHETIC v3"), expect_updated_at=ts2)
    assert ud.get(uid, rid, EntryDoc).text == "SYNTHETIC v3"


def test_wrong_model_is_a_fixed_message_not_the_value(pg_clean, ud):
    uid = new_user(pg_clean)
    rid = ud.put(uid, "entry", "student", EntryDoc(text=CANARY))
    with pytest.raises(BadBlob) as e:
        ud.get(uid, rid, StoredBrief)
    assert CANARY not in str(e.value) and CANARY not in repr(e.value)


def test_shredded_user_cannot_read(pg_clean, ud):
    uid = new_user(pg_clean)
    rid = ud.put(uid, "entry", "student", EntryDoc(text=CANARY))
    crypto.shred(uid)
    with pytest.raises(KeyShredded):
        ud.get(uid, rid, EntryDoc)
    with pytest.raises(KeyShredded):
        ud.put(uid, "entry", "student", EntryDoc(text="SYNTHETIC after"))


def test_openalex_link_is_encrypted(pg_clean, ud):
    uid = new_user(pg_clean)
    ud.link_openalex(uid, "A5000000001")
    (enc,) = raw(pg_clean, "SELECT openalex_id_enc FROM users WHERE id = %s", uid)[0]
    assert b"A5000000001" not in bytes(enc)
    assert ud.linked_openalex(uid) == "A5000000001"
    ud.link_openalex(uid, None)
    assert ud.linked_openalex(uid) is None
