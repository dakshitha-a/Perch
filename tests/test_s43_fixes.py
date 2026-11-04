"""S43 fix pass: small checks that need no database."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from perch.user.routes import _summary


def test_my_perch_counts_public_and_sample_leads_apart() -> None:
    brief = SimpleNamespace(status="done", researcher_id="user:you", topics=[],
                            created_at=datetime(2026, 11, 3, tzinfo=UTC))
    leads = [SimpleNamespace(sample=False)] * 5 + [SimpleNamespace(sample=True)] * 3
    out = _summary(uuid4(), SimpleNamespace(brief=brief, leads=leads))  # type: ignore[arg-type]
    assert out["leads"] == 5 and out["sample_leads"] == 3
