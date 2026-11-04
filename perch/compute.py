"""CPU model compute limits for a worker process.

Cores: `usable_cores()` counts the cores this process may run on (the scheduler affinity
mask), not `os.cpu_count()`, which reports the whole host inside a container or a shared box.

Threads: `configure_torch()` sets torch's intra-op thread count from PERCH_TORCH_THREADS,
default min(`usable_cores()`, 4).

Slots: a worker runs many job threads (16 by default) and most of them wait on the cloud
provider. Only PERCH_MODEL_SLOTS (default 1) of them may hold the embedder, reranker or
MiniCheck at once, so 16 jobs never run 16 reranks on 8 cores. Every CPU model that
`default_models` builds is wrapped here, so the limit is one semaphore around model compute.
With S slots and N torch threads a busy worker can ask for up to S x N threads for short
bursts; keep slots x threads at or under the usable cores.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import numpy as np

from perch.config import env
from perch.embed import Embedder
from perch.grounding import Grounder
from perch.rerank import Reranker

DEFAULT_SLOTS = 1
MAX_DEFAULT_THREADS = 4


def usable_cores() -> int:
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:  # not Linux
        return os.cpu_count() or 1


def torch_threads() -> int:
    return max(1, int(env("PERCH_TORCH_THREADS") or min(usable_cores(), MAX_DEFAULT_THREADS)))


def configure_torch() -> int:
    """Set torch's thread count once per process; return it."""
    import torch

    n = torch_threads()
    torch.set_num_threads(n)
    return n


def model_slots() -> int:
    return max(1, int(env("PERCH_MODEL_SLOTS") or DEFAULT_SLOTS))


_sem: threading.BoundedSemaphore | None = None
_sem_lock = threading.Lock()


def _semaphore() -> threading.BoundedSemaphore:
    global _sem
    with _sem_lock:
        if _sem is None:
            _sem = threading.BoundedSemaphore(model_slots())
        return _sem


def reset_slots() -> None:
    """Rebuild the semaphore from the environment (tests)."""
    global _sem
    with _sem_lock:
        _sem = None


class SlotTimeout(RuntimeError):
    """No model slot came free in time: a holder is hung, or the slots are too few."""


def slot_timeout() -> float:
    return float(env("PERCH_MODEL_SLOT_TIMEOUT") or 300)


@contextmanager
def model_slot() -> Iterator[None]:
    """One model call at a time per slot. A wait past PERCH_MODEL_SLOT_TIMEOUT seconds (300)
    raises SlotTimeout, so a hung holder fails the waiting job loudly instead of silently
    stalling every worker thread (S38: a Scout run sat on a lock for about 7 hours)."""
    sem = _semaphore()
    if not sem.acquire(timeout=slot_timeout()):
        raise SlotTimeout(f"no model slot free after {slot_timeout():.0f} s "
                          f"({model_slots()} slot(s)); a holder may be hung")
    try:
        yield
    finally:
        sem.release()


class SlottedEmbedder(Embedder):
    def __init__(self, inner: Embedder) -> None:
        self.inner, self.name, self.dim = inner, inner.name, inner.dim

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        with model_slot():
            return self.inner.embed_documents(texts)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        with model_slot():
            return self.inner.embed_queries(texts)


class SlottedReranker(Reranker):
    def __init__(self, inner: Reranker) -> None:
        self.inner, self.name = inner, inner.name

    def score(self, query: str, docs: list[str]) -> list[float]:
        with model_slot():
            return self.inner.score(query, docs)


class SlottedGrounder(Grounder):
    def __init__(self, inner: Grounder) -> None:
        self.inner, self.name = inner, getattr(inner, "name", "grounder")

    def support(self, document: str, claims: list[str]) -> list[float]:
        with model_slot():
            return self.inner.support(document, claims)
