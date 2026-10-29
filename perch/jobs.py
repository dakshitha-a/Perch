"""Job runner: in-process background threads for the demo, behind an interface a queue
(Redis, Postgres-backed) can replace later. Briefs run one at a time by default: the
pipeline shares GPU models, and the demo node serves a handful of users."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor


class JobRunner(ABC):
    @abstractmethod
    def submit(self, job_id: str, fn: Callable[[], None]) -> None:
        """Run fn in the background. Failures are the job's own business (it records them)."""

    def wait(self, job_id: str, timeout: float | None = None) -> None:  # noqa: B027
        """Block until the job finishes (tests and CLI); a no-op where unsupported."""


class InProcessRunner(JobRunner):
    def __init__(self, workers: int = 1) -> None:
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="perch-job")
        self.futures: dict[str, Future] = {}

    def submit(self, job_id: str, fn: Callable[[], None]) -> None:
        self.futures[job_id] = self.pool.submit(fn)

    def wait(self, job_id: str, timeout: float | None = None) -> None:
        f = self.futures.get(job_id)
        if f:
            f.result(timeout=timeout)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


class InlineRunner(JobRunner):
    """Runs the job at submit time (tests)."""

    def submit(self, job_id: str, fn: Callable[[], None]) -> None:
        fn()
