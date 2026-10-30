"""Match (S27): the ranking model's score on a 0-100 scale, monotone, so it is the order."""

from perch.score import match_score


def test_anchor_points_and_clipping():
    assert match_score(0.5) == 50  # log-odds 0
    assert match_score(0.905) == 69  # log-odds 2.25
    assert match_score(0.028) == 20  # log-odds -3.55
    assert match_score(0.9999) == 100 and match_score(1.2) == 100  # a sponsor bonus can pass 1
    assert match_score(0.0) == 0 and match_score(None) is None


def test_monotone_so_sorting_by_match_is_perchs_order():
    ps = [0.001, 0.01, 0.03, 0.2, 0.5, 0.8, 0.97, 0.999]
    scores = [match_score(p) for p in ps]
    assert scores == sorted(scores)
