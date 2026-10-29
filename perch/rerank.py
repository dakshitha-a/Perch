"""Rerank retrieved candidates (top 50 to top 10). Local default Qwen3-Reranker-0.6B.

Each candidate is scored against the research thread it matched best. Scores are
cached by (model, profile hash, record id), so a repeat brief does not rerun the
model. Tests use FakeReranker.
"""

from __future__ import annotations

import re
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from perch.profile import Profile
from perch.retrieve import Candidate, opportunity_text, thread_query
from perch.schemas import Opportunity

DEFAULT_MODEL = "Qwen/Qwen3-Reranker-0.6B"
INSTRUCTION = ("Given a description of a researcher's line of work, judge whether this funding "
               "opportunity fits that work")
TOP_N = 10


class Reranker(ABC):
    name: str

    @abstractmethod
    def score(self, query: str, docs: list[str]) -> list[float]:
        """Relevance in [0, 1], one per doc."""


class FakeReranker(Reranker):
    """Share of query words found in the doc."""

    name = "fake-overlap"

    def score(self, query: str, docs: list[str]) -> list[float]:
        q = set(re.findall(r"[a-z0-9]+", query.lower()))
        return [len(q & set(re.findall(r"[a-z0-9]+", d.lower()))) / max(len(q), 1) for d in docs]


class CrossEncoderReranker(Reranker):
    """sentence-transformers CrossEncoder, as the Qwen3-Reranker model card shows."""

    def __init__(self, model: str = DEFAULT_MODEL, device: str | None = None,
                 batch_size: int = 8, max_length: int = 2048) -> None:
        import torch
        from sentence_transformers import CrossEncoder  # optional dependency

        self.model = CrossEncoder(model, device=device, max_length=max_length,
                                  prompts={"fit": INSTRUCTION}, default_prompt_name="fit")
        self.name = model
        self.batch_size = batch_size
        self._sigmoid = torch.nn.Sigmoid()

    def score(self, query: str, docs: list[str]) -> list[float]:
        s = self.model.predict([(query, d) for d in docs], batch_size=self.batch_size,
                               activation_fn=self._sigmoid, show_progress_bar=False)
        return [float(x) for x in s]


class RerankCache:
    def __init__(self, path: str | Path = "data/cache/rerank.db") -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("CREATE TABLE IF NOT EXISTS scores (model TEXT, profile TEXT, "
                          "record TEXT, score REAL, PRIMARY KEY (model, profile, record))")

    def get(self, model: str, profile: str, record: str) -> float | None:
        row = self.conn.execute("SELECT score FROM scores WHERE model=? AND profile=? AND "
                                "record=?", (model, profile, record)).fetchone()
        return row[0] if row else None

    def put(self, model: str, profile: str, record: str, score: float) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?)",
                              (model, profile, record, score))


@dataclass
class Ranked:
    opportunity: Opportunity
    candidate: Candidate
    rerank_score: float


def rerank(cands: list[Candidate], opps: dict[str, Opportunity], profile: Profile,
           reranker: Reranker, cache: RerankCache | None = None, top: int = TOP_N
           ) -> tuple[list[Ranked], int]:
    """Top `top` by rerank score (ties broken by retrieval order). Returns (ranked, cache hits)."""
    threads = {t.index: t for t in profile.threads}
    scores: dict[str, float] = {}
    hits = 0
    todo: dict[int, list[Candidate]] = {}
    for c in cands:
        cached = cache.get(reranker.name, profile.hash, c.record_id) if cache else None
        if cached is not None:
            scores[c.record_id] = cached
            hits += 1
        else:
            todo.setdefault(c.best_thread, []).append(c)
    for ti, group in todo.items():
        docs = [opportunity_text(opps[c.record_id])[:2000] for c in group]
        for c, s in zip(group, reranker.score(thread_query(threads[ti]), docs), strict=True):
            scores[c.record_id] = s
            if cache:
                cache.put(reranker.name, profile.hash, c.record_id, s)
    order = {c.record_id: i for i, c in enumerate(cands)}
    best = sorted(cands, key=lambda c: (-scores[c.record_id], order[c.record_id]))[:top]
    return [Ranked(opps[c.record_id], c, scores[c.record_id]) for c in best], hits


class DecisionReranker(Reranker):
    """Rerank through `decide` (SPEC section 7): the probability of yes to "does this
    opportunity fit this line of work?". Decision model or LLM-logprobs fallback."""

    QUESTION = "Does this funding opportunity fit the researcher's line of work?"

    def __init__(self, decider: object, name: str) -> None:
        from perch.llm.decide import Decider

        assert isinstance(decider, Decider)
        self.decider, self.name = decider, name

    def score(self, query: str, docs: list[str]) -> list[float]:
        from perch.llm.decide import YesNo

        out = []
        for d in docs:
            r = self.decider.decide(YesNo(self.QUESTION),
                                    f"RESEARCH:\n{query}\n\nOPPORTUNITY:\n{d}")
            out.append(r.probs.get("yes", 1.0 if r.value else 0.0))
        return out


def make_reranker(key: str, device: str | None = None) -> Reranker:
    """Reranker from a profile key: a cross-encoder model id, or "systemone:clef-flash" /
    "systemone:clef" for a decision server."""
    if key.startswith("systemone:"):
        from perch.llm.systemone import CLEF_FLASH_URL, CLEF_URL, SystemOneClient, SystemOneDecider

        name = key.split(":", 1)[1]
        url = {"clef-flash": CLEF_FLASH_URL, "clef": CLEF_URL}[name]
        return DecisionReranker(SystemOneDecider(SystemOneClient(url), name), key)
    return CrossEncoderReranker(key, device=device)
