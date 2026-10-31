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

    def cancel(self, job_id: str) -> bool:
        """Drop the job if it has not started; False if it runs, ran, or is unknown."""
        return False


class InProcessRunner(JobRunner):
    def __init__(self, workers: int = 1) -> None:
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="perch-job")
        self.futures: dict[str, Future] = {}

    def submit(self, job_id: str, fn: Callable[[], None]) -> None:
        f = self.pool.submit(fn)
        self.futures[job_id] = f
        f.add_done_callback(lambda _: self.futures.pop(job_id, None))

    def cancel(self, job_id: str) -> bool:
        f = self.futures.get(job_id)
        return bool(f and f.cancel())

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
