"""S53 review: a guest's picks are part of the same-day brief key."""

from datetime import date

from perch.user.briefs import compute_idempotency_key

D = date(2026, 11, 5)


def test_guest_key_changes_with_the_picks():
    base = {"window": 1}
    a = compute_idempotency_key("g", "researcher", "A1", (), {**base, "picks": {}}, today=D)
    b = compute_idempotency_key("g", "researcher", "A1", (),
                                {**base, "picks": {"citizenship": "international"}}, today=D)
    c = compute_idempotency_key("g", "researcher", "A1", (),
                                {**base, "picks": {"citizenship": "us_citizen"}}, today=D)
    assert len({a, b, c}) == 3
