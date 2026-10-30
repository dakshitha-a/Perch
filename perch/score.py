"""Match: the ranking model's score on a 0-100 scale, the one score Perch shows (S27).

The reranker's raw score is a probability squeezed toward 0 and 1, so a good second lead
can read 0.03. Its log-odds are spread evenly; Match maps log-odds -6 to 0 and +6 to 100,
clipped. Set from the NIH back-test (bench/calibrate.py, bench/results/calibration.json):
every funded announcement Perch placed in the top 10 scored 80 or more, and those it
ranked 13th or lower scored 30 to 73. Match is a monotone function of the ranking score,
so sorting by it is Perch's order. It says how closely a listing's text matches the
papers; it is not the odds of funding. Code computes it; no model writes it.
"""

from __future__ import annotations

import math

LO, HI = -6.0, 6.0
EPS = 1e-9


def match_score(p: float | None) -> int | None:
    if p is None:
        return None
    p = min(max(p, EPS), 1 - EPS)
    logit = math.log(p / (1 - p))
    return round(min(max((logit - LO) / (HI - LO) * 100, 0), 100))
