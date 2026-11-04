"""S45, offline with the fake provider: a running turn honours cancel. No spend, no database.
SYNTHETIC text only."""

from __future__ import annotations

import pytest

from perch.scout import texts
from perch.scout.turn import TurnCancelled, run_turn
from tests.test_scout_v2 import SpyProvider, call, deps, gate_by_words, service, smart  # noqa: F401


def test_a_cancelled_turn_stops_before_the_next_model_call(service):  # noqa: F811
    p = SpyProvider(responder=lambda m, s, sc: gate_by_words(m) if s == texts.GATE_SYSTEM
                    else call("read_brief"))  # would ask for tools for ever
    stop = {"now": False}

    def cancelled():
        stop["now"] = stop["now"] or p.n("scout") >= 2  # the owner presses stop after step 2
        return stop["now"]

    with pytest.raises(TurnCancelled):
        run_turn(deps(service, p, cancelled=cancelled), [], question="Which lead is strongest?")
    assert p.n("scout") == 2  # no third call, and no answer was built


def test_a_turn_cancelled_before_the_gate_makes_no_call(service):  # noqa: F811
    p = smart(["unused"])
    with pytest.raises(TurnCancelled):
        run_turn(deps(service, p, cancelled=lambda: True), [], question="Hello")
    assert p.log == []
