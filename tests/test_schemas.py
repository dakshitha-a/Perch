from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from perch.schemas import RECORD_TYPES, Lead, Work

PROV = {
    "source": "openalex",
    "source_url": "https://api.openalex.org/works/W1",
    "fetched_at": datetime(2026, 10, 28, tzinfo=UTC),
}


def test_every_record_type_requires_provenance():
    for cls in RECORD_TYPES:
        for field in ("source", "source_url", "fetched_at"):
            assert cls.model_fields[field].is_required(), (cls.__name__, field)


def test_missing_provenance_is_rejected():
    with pytest.raises(ValidationError):
        Work(id="W1", title="SYNTHETIC paper", source="openalex", fetched_at=PROV["fetched_at"])


def test_naive_fetched_at_is_rejected_and_aware_is_normalised():
    with pytest.raises(ValidationError):
        Work(id="W1", title="SYNTHETIC", **{**PROV, "fetched_at": datetime(2026, 10, 28)})
    est = timezone(timedelta(hours=-4))
    local = datetime(2026, 10, 28, 8, tzinfo=est)
    w = Work(id="W1", title="SYNTHETIC", **{**PROV, "fetched_at": local})
    assert w.fetched_at == datetime(2026, 10, 28, 12, tzinfo=UTC)


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        Work(id="W1", title="SYNTHETIC", made_up=1, **PROV)


def test_lead_route_is_constrained():
    with pytest.raises(ValidationError):
        Lead(id="L1", brief_id="B1", route="C", record_id="O1", **PROV)
