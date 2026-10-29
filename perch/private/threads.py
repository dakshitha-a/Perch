"""Threads from text the user adds: private documents, or the normal-mode direction.

Each document becomes one thread: its paragraphs are embedded as queries and averaged.
Together these threads take PRIVATE_SHARE of the thread weight (Q13); inside that
share, each kind takes DOC_SHARES (Q21), renormalised over the kinds present. Public
threads keep their relative weights and share the rest. With no public papers the
added threads take all of it. Both numbers are defaults, not findings.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import replace

from perch.embed import Embedder, normalise
from perch.profile import Profile, Thread, words
from perch.schemas import Work

PRIVATE_SHARE = 0.6
DOC_SHARES = {"proposal": 0.5, "direction": 0.3, "manuscript": 0.2}
CHUNK_CHARS = 1500
MAX_CHUNKS = 24
# Words too common in proposals to name a thread.
LABEL_STOP = set("""not also may will can could would should more most other than then these those
which while when where what who how aim aims specific year years week weeks month months data
work draft section""".split())
QUERY_CHARS = 600  # opening text used as the thread's keyword and rerank query


def chunks(text: str) -> list[str]:
    """Paragraphs packed into chunks of about CHUNK_CHARS."""
    out, cur = [], ""
    for p in re.split(r"\n\s*\n", text):
        p = p.strip()
        if not p:
            continue
        if cur and len(cur) + len(p) > CHUNK_CHARS:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}".strip()
    if cur:
        out.append(cur)
    return [c[:CHUNK_CHARS * 2] for c in out][:MAX_CHUNKS]


def kind_of(doc: Work) -> str:
    """"private:proposal" -> "proposal"; the normal-mode "said:direction" -> "direction"."""
    return doc.id.split(":", 1)[1]


def add_threads(profile: Profile, docs: list[Work], embedder: Embedder,
                share: float = PRIVATE_SHARE) -> Profile:
    """The profile with one thread per document appended and every weight rescaled."""
    docs = [d for d in docs if kind_of(d) in DOC_SHARES and d.abstract]
    if not docs:
        return profile
    total = sum(DOC_SHARES[kind_of(d)] for d in docs)
    added = share if profile.threads else 1.0
    labels = [label(d.abstract or "") for d in docs]
    threads = [replace(t, weight=t.weight * (1 - added)) for t in profile.threads]
    for d, lab in zip(docs, labels, strict=True):
        x = embedder.embed_queries(chunks(d.abstract or ""))
        vec = normalise(x.mean(0, keepdims=True))[0]
        lead = " ".join((d.abstract or "").split())[:QUERY_CHARS]
        threads.append(Thread(len(threads), vec, [d.id], added * DOC_SHARES[kind_of(d)] / total,
                              lab, [lead]))
    salt = hashlib.sha256("|".join([profile.salt, *(d.abstract or "" for d in docs)])
                          .encode()).hexdigest()[:16]
    return Profile(profile.researcher_id, profile.as_of, profile.embedder, threads,
                   profile.work_ids, salt)


def label(text: str, n: int = 4) -> str:
    """The most frequent content words, ties by first appearance."""
    ws = [w for w in words(text) if not w.isdigit() and w not in LABEL_STOP]
    c = Counter(ws)
    first = {w: i for i, w in reversed(list(enumerate(ws)))}
    return ", ".join(sorted(c, key=lambda w: (-c[w], first[w]))[:n]) or "untitled"
