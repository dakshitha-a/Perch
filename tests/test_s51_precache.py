"""S51 H8: the precache key carries the rules version, so a rule change recomputes the stored
federal eligibility split instead of serving the old one. SYNTHETIC profile."""

from datetime import date

import numpy as np

from perch.profile import Profile, Thread


def test_the_precache_key_changes_with_the_rules_version(monkeypatch):
    from perch import eligibility
    from perch.precache import precache_key

    p = Profile("A1", date(2026, 11, 5), "fake", [Thread(0, np.zeros(2), ["W1"], 1.0, "x")],
                ["W1"])
    assert eligibility.RULES_VERSION == "2026-11-05.1"
    before = precache_key(p, 3)
    monkeypatch.setattr(eligibility, "RULES_VERSION", "2026-11-05.2")
    assert precache_key(p, 3) != before
