from datetime import UTC, datetime

from perch.profile import key_papers
from perch.schemas import Work

T = datetime(2026, 10, 28, tzinfo=UTC)


def work(i, cites, n_authors):
    return Work(id=f"W{i}", title=f"SYNTHETIC {i}", cited_by_count=cites,
                author_ids=[f"A{k}" for k in range(n_authors)], source="openalex",
                source_url=f"https://api.openalex.org/works/W{i}", fetched_at=T)


def test_consortium_papers_skipped_when_enough_small_ones():
    works = [work(0, 5000, 98)] + [work(i, 100 - i, 4) for i in range(1, 8)]
    assert [w.id for w in key_papers(works, 5)] == ["W1", "W2", "W3", "W4", "W5"]


def test_falls_back_to_all_when_few_small_papers():
    works = [work(0, 5000, 98), work(1, 10, 3)]
    assert [w.id for w in key_papers(works, 5)] == ["W0", "W1"]
