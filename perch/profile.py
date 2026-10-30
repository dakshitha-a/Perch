"""Research profile: key papers and research threads. Deterministic; no model output.

Threads: each paper is embedded (as a query), weighted by recency, and the papers
are clustered into 2 to 4 threads by spherical k-means (fixed seed); k is chosen
by weighted silhouette. Fewer than 8 papers gives one thread. A thread's vector
is the recency-weighted mean of its papers. `as_of` drops papers published after
a date, which the back-test uses to enforce its cut-off.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from perch.embed import Embedder, normalise
from perch.schemas import Work

MAX_AUTHORS = 30  # works with more authors are usually consortium papers
MIN_THREAD_PAPERS = 3
# OpenAlex work types that are research output. Excluded: "supplementary-materials",
# "other" (mostly "Data from" / "Table S" records), "erratum", "reference-entry".
RESEARCH_TYPES = {"article", "review", "preprint", "book-chapter", "book",
                  "conference-paper", "conference-abstract", "dissertation", "letter"}
MIN_PAPERS_FOR_THREADS = 8
HALF_LIFE_YEARS = 5.0
MAX_PAPERS = 200
SEED = 7
STOP = set("""a an and are as at be by for from has have in into is it its of on or
that the their this to was were with without we our using use based study
analysis results effect effects role new novel via among between during""".split())


def key_papers(works: list[Work], n: int = 10) -> list[Work]:
    """Most-cited works, skipping large-consortium papers unless too few remain.

    Deterministic: ordered by citations, then year, then id.
    """
    def rank(w: Work) -> tuple[int, int, str]:
        return (w.cited_by_count or 0, w.publication_year or 0, w.id)

    works = research_works(works)
    small = [w for w in works if len(w.author_ids) <= MAX_AUTHORS]
    pool = small if len(small) >= min(n, 5) else works
    return sorted(pool, key=rank, reverse=True)[:n]


def research_works(works: list[Work]) -> list[Work]:
    return [w for w in works if (w.type or "article") in RESEARCH_TYPES]


def work_text(w: Work, max_chars: int = 2000) -> str:
    return (w.title + (". " + w.abstract if w.abstract else ""))[:max_chars]


def work_date(w: Work) -> date | None:
    if w.publication_date:
        return w.publication_date
    return date(w.publication_year, 7, 1) if w.publication_year else None


def recency_weight(w: Work, ref: date) -> float:
    d = work_date(w)
    years = max(0.0, (ref - d).days / 365.25) if d else 20.0
    return 0.5 ** (years / HALF_LIFE_YEARS)


@dataclass
class Thread:
    index: int
    vector: np.ndarray
    work_ids: list[str]
    weight: float  # share of total recency weight
    label: str
    titles: list[str] = field(default_factory=list)
    # The thread's most common OpenAlex primary topics, e.g. "Spectroscopy and Quantum
    # Chemical Studies": the discipline that title words alone do not name (S27).
    topics: list[str] = field(default_factory=list)


def thread_topics(works: list[Work], n: int = 3) -> list[str]:
    c = Counter(w.topics[0].display_name for w in works if w.topics)
    return [name for name, _ in c.most_common(n)]


@dataclass
class Profile:
    researcher_id: str
    as_of: date
    embedder: str
    threads: list[Thread]
    work_ids: list[str]
    salt: str = ""  # hash of added text (direction, private documents), so caches split

    @property
    def hash(self) -> str:
        key = "|".join([self.researcher_id, self.as_of.isoformat(), self.embedder,
                        *sorted(self.work_ids), *([self.salt] if self.salt else [])])
        return hashlib.sha256(key.encode()).hexdigest()[:16]


def eligible_works(works: list[Work], as_of: date) -> list[Work]:
    """Works with a title, dated on or before as_of, newest first, capped."""
    dated = [w for w in research_works(works) if w.title and (d := work_date(w)) and d <= as_of]
    dated.sort(key=lambda w: (work_date(w), w.id), reverse=True)
    return dated[:MAX_PAPERS]


def spherical_kmeans(x: np.ndarray, w: np.ndarray, k: int, iters: int = 50) -> np.ndarray:
    """Weighted spherical k-means with deterministic k-means++ seeding. Returns labels."""
    rng = np.random.default_rng(SEED)
    n = len(x)
    centres = [x[int(np.argmax(w))]]
    for _ in range(1, k):
        sims = np.max(np.stack([x @ c for c in centres]), axis=0)
        d = np.clip(1.0 - sims, 0, None) * w
        probs = d / d.sum() if d.sum() > 0 else np.full(n, 1.0 / n)
        centres.append(x[int(rng.choice(n, p=probs))])
    c = np.stack(centres)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        new = np.argmax(x @ c.T, axis=1)
        if _ and np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            members = labels == j
            if members.any():
                c[j] = normalise((w[members, None] * x[members]).sum(0, keepdims=True))[0]
    return labels


def weighted_silhouette(x: np.ndarray, w: np.ndarray, labels: np.ndarray) -> float:
    k = labels.max() + 1
    if k < 2:
        return -1.0
    dist = 1.0 - x @ x.T
    scores = []
    for i in range(len(x)):
        own = labels == labels[i]
        own[i] = False
        if not own.any():
            scores.append(0.0)
            continue
        a = np.average(dist[i, own], weights=w[own])
        b = min(np.average(dist[i, labels == j], weights=w[labels == j])
                for j in range(k) if j != labels[i] and (labels == j).any())
        scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return float(np.average(scores, weights=w))


def words(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if t not in STOP]


def label_threads(groups: list[list[Work]], n_terms: int = 4) -> list[str]:
    """Title words frequent in one thread and rare in the others (tf-idf over threads)."""
    counts = [Counter(t for w in g for t in set(words(w.title))) for g in groups]
    df = Counter(t for c in counts for t in c)
    labels = []
    for c in counts:
        scored = sorted(c, key=lambda t: (-(c[t] * math.log(1 + len(counts) / df[t])), t))
        labels.append(", ".join(scored[:n_terms]) or "untitled")
    return labels


def build_threads(researcher_id: str, works: list[Work], embedder: Embedder,
                  as_of: date | None = None) -> Profile:
    as_of = as_of or date.today()
    papers = eligible_works(works, as_of)
    if not papers:
        return Profile(researcher_id, as_of, embedder.name, [], [])
    x = embedder.embed_queries([work_text(w) for w in papers])
    wts = np.array([recency_weight(w, as_of) for w in papers])
    if len(papers) < MIN_PAPERS_FOR_THREADS:
        labels = np.zeros(len(papers), dtype=int)
    else:
        best = None
        for k in range(2, min(4, len(papers) - 1) + 1):
            lab = spherical_kmeans(x, wts, k)
            if len(set(lab)) < k or np.bincount(lab).min() < MIN_THREAD_PAPERS:
                continue
            s = weighted_silhouette(x, wts, lab)
            if best is None or s > best[0] + 1e-9:
                best = (s, lab)
        labels = best[1] if best else np.zeros(len(papers), dtype=int)
    total = wts.sum()
    order = sorted(set(labels), key=lambda j: -wts[labels == j].sum())
    groups = [[papers[i] for i in np.argsort(-wts) if labels[i] == j] for j in order]
    names = label_threads(groups)
    threads = []
    for idx, (j, g, name) in enumerate(zip(order, groups, names, strict=True)):
        m = labels == j
        vec = normalise((wts[m, None] * x[m]).sum(0, keepdims=True))[0]
        threads.append(Thread(idx, vec, [w.id for w in g], float(wts[m].sum() / total), name,
                              [w.title for w in g[:3]], thread_topics(g)))
    return Profile(researcher_id, as_of, embedder.name, threads, [w.id for w in papers])
