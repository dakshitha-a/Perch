from datetime import UTC, date, datetime

from perch.embed import FakeEmbedder
from perch.profile import build_threads, key_papers, recency_weight
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


TOPICS = {
    "bbb": "blood brain barrier endothelial HIV alcohol neuroinflammation",
    "kid": "kidney transplant living donor decision communication",
    "leu": "leukemia DNA repair PARP synthetic lethality",
}


def topical(i, topic, year):
    words = TOPICS[topic].split()
    title = "SYNTHETIC " + " ".join(words[(i % 3):] + words[:(i % 3)])
    return Work(id=f"W{topic}{i}", title=title, publication_year=year,
                publication_date=date(year, 6, 1), author_ids=["A"], source="openalex",
                source_url=f"https://api.openalex.org/works/W{topic}{i}", fetched_at=T)


def test_threads_separate_topics_and_are_deterministic():
    works = [topical(i, t, 2015 + i) for t in TOPICS for i in range(5)]
    p1 = build_threads("A", works, FakeEmbedder(256), as_of=date(2025, 1, 1))
    p2 = build_threads("A", list(reversed(works)), FakeEmbedder(256), as_of=date(2025, 1, 1))
    assert 2 <= len(p1.threads) <= 4
    groups = [{w[1:4] for w in t.work_ids} for t in p1.threads]
    assert all(len(g) == 1 for g in groups)  # each thread holds one topic
    assert [t.work_ids for t in p1.threads] == [t.work_ids for t in p2.threads]
    assert abs(sum(t.weight for t in p1.threads) - 1.0) < 1e-6
    assert p1.hash == p2.hash


def test_few_papers_give_one_thread_and_as_of_cuts_off():
    works = [topical(i, "kid", 2010 + i) for i in range(10)]
    p = build_threads("A", works, FakeEmbedder(64), as_of=date(2014, 12, 31))
    assert len(p.threads) == 1 and len(p.work_ids) == 5  # 2010 to 2014 only
    assert all(int(w[4:]) <= 4 for w in p.work_ids)


def test_recency_weight_halves_every_five_years():
    w = topical(0, "kid", 2015)
    assert abs(recency_weight(w, date(2020, 6, 1)) - 0.5) < 0.01


def test_no_papers_gives_empty_profile():
    assert build_threads("A", [], FakeEmbedder(8), as_of=date(2020, 1, 1)).threads == []


def test_non_research_types_are_skipped():
    w = [topical(i, "kid", 2015 + i) for i in range(4)]
    w[0].type, w[1].type = "supplementary-materials", "other"
    p = build_threads("A", w, FakeEmbedder(32), as_of=date(2025, 1, 1))
    assert len(p.work_ids) == 2
    assert {x.id for x in key_papers(w)} == {w[2].id, w[3].id}
