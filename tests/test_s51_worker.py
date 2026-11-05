"""S51 E2: a worker keeps PERCH_WORKER_FAST_THREADS (default 2) job threads for the presenter's
fast jobs (scout_turn, cover_points, handoff) and purges, so a queue of briefs never delays
them. No database here; the Postgres test is in tests/test_jobs_pg.py."""

from __future__ import annotations

from perch import jobs

ALL = ["brief", "cover_points", "handoff", "precache", "purge", "scout_turn"]
FAST = ["cover_points", "handoff", "purge", "scout_turn"]


def test_the_first_threads_take_only_fast_kinds(monkeypatch):
    monkeypatch.delenv("PERCH_WORKER_FAST_THREADS", raising=False)
    assert jobs.fast_threads(8, ALL) == 2
    assert [jobs.thread_kinds(i, ALL, 2) for i in range(3)] == [FAST, FAST, ALL]


def test_the_split_is_a_setting_and_leaves_one_thread_for_briefs(monkeypatch):
    monkeypatch.setenv("PERCH_WORKER_FAST_THREADS", "3")
    assert jobs.fast_threads(8, ALL) == 3
    assert jobs.fast_threads(2, ALL) == 1  # at least one thread still takes briefs
    assert jobs.fast_threads(1, ALL) == 0
    monkeypatch.setenv("PERCH_WORKER_FAST_THREADS", "0")
    assert jobs.fast_threads(8, ALL) == 0
    monkeypatch.setenv("PERCH_WORKER_FAST_THREADS", "x")
    assert jobs.fast_threads(8, ALL) == 2  # a typo falls back to the default


def test_no_split_when_the_worker_runs_only_one_side(monkeypatch):
    monkeypatch.delenv("PERCH_WORKER_FAST_THREADS", raising=False)
    assert jobs.fast_threads(8, ["brief", "precache"]) == 0
    assert jobs.fast_threads(8, ["scout_turn", "purge"]) == 0
