"""Parallel reservations cannot overrun the cap (S47 task 5; perch/llm/budget.py)."""

from __future__ import annotations

import threading
import time

import pytest

from perch.llm.budget import _IN_FLIGHT, Budget, BudgetExceeded


def test_parallel_reservations_stop_at_the_cap(tmp_path) -> None:
    path = tmp_path / "ledger.jsonl"
    b = Budget(limit=1.0, path=path)  # empty ledger: nothing spent yet
    n, est = 12, 0.3  # check() admits while the held total is under 1.0: 0, 0.3, 0.6, 0.9
    start = threading.Barrier(n)
    hold = threading.Event()
    admitted: list[int] = []
    refused: list[int] = []
    lock = threading.Lock()

    def call(i: int) -> None:
        start.wait()
        try:
            with b.reserve(est):
                with lock:
                    admitted.append(i)
                hold.wait(5)  # the call stays in flight until every thread has tried
        except BudgetExceeded:
            with lock:
                refused.append(i)

    ts = [threading.Thread(target=call, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    deadline = time.monotonic() + 5
    while len(admitted) + len(refused) < n and time.monotonic() < deadline:
        time.sleep(0.01)
    hold.set()
    for t in ts:
        t.join()
    assert len(admitted) == 4 and len(refused) == 8
    assert _IN_FLIGHT[str(path.resolve())] == pytest.approx(0.0)  # all released


def test_a_failed_call_releases_its_reservation(tmp_path) -> None:
    b = Budget(limit=1.0, path=tmp_path / "ledger.jsonl")
    with pytest.raises(RuntimeError), b.reserve(0.9):
        raise RuntimeError("provider error")
    with b.reserve(0.9):
        pass
