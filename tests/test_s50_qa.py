"""S50 QA: a stored failed brief carries its reason to My Perch (the walk's s50b_stop_error)."""

from datetime import UTC, datetime
from uuid import uuid4

from perch.schemas import Brief
from perch.user.models import StoredBrief
from perch.user.routes import _summary

T = datetime(2026, 11, 5, tzinfo=UTC)


def brief(status: str, error: str | None = None) -> StoredBrief:
    return StoredBrief(brief=Brief(id="b1", source="perch", source_url="perch://brief",
                                   fetched_at=T, researcher_id="user:you", status=status,
                                   error=error))


def test_a_failed_brief_says_why_and_a_done_one_has_no_error_key():
    got = _summary(uuid4(), brief("failed", "SYNTHETIC: the model server was down."))
    assert got["status"] == "failed" and got["error"] == "SYNTHETIC: the model server was down."
    assert "error" not in _summary(uuid4(), brief("done"))
    assert "error" not in _summary(uuid4(), brief("failed"))
