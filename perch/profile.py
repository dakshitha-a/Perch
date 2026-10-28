"""Research profile pieces. S4 adds research threads here."""

from __future__ import annotations

from perch.schemas import Work

MAX_AUTHORS = 30  # works with more authors are usually consortium papers


def key_papers(works: list[Work], n: int = 10) -> list[Work]:
    """Most-cited works, skipping large-consortium papers unless too few remain.

    Deterministic: ordered by citations, then year, then id.
    """
    def rank(w: Work) -> tuple[int, int, str]:
        return (w.cited_by_count or 0, w.publication_year or 0, w.id)

    small = [w for w in works if len(w.author_ids) <= MAX_AUTHORS]
    pool = small if len(small) >= min(n, 5) else works
    return sorted(pool, key=rank, reverse=True)[:n]
