from datetime import UTC, date, datetime

from perch.embed import FakeEmbedder
from perch.profile import build_threads
from perch.retrieve import index_opportunities, retrieve, rrf
from perch.schemas import Opportunity, Work
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

T = datetime(2026, 10, 28, tzinfo=UTC)


def opp(n, title):
    return Opportunity(id=f"grants_gov:{n}", opportunity_number=n, title=f"SYNTHETIC {title}",
                       agency="SYNTHETIC agency", source="grants_gov",
                       source_url=f"https://www.grants.gov/search-results-detail/{n}",
                       fetched_at=T)


def work(i, title):
    return Work(id=f"W{i}", title=title, publication_date=date(2020, 1, i + 1), author_ids=["A"],
                source="openalex", source_url=f"https://api.openalex.org/works/W{i}",
                fetched_at=T)


def test_rrf_is_reciprocal_rank():
    assert rrf(["a", "b"]) == {"a": 1 / 61, "b": 1 / 62}


def test_retrieve_ranks_matching_opportunity_first_and_times_stages(tmp_path):
    e = FakeEmbedder(256)
    repo = SQLiteRepository()
    repo.upsert([opp("PA-1", "blood brain barrier HIV neuroinflammation research"),
                 opp("PA-2", "kidney transplant living donor communication"),
                 opp("PA-3", "astronomy telescope instrumentation")])
    idx = LanceIndex(tmp_path / "lance")
    assert index_opportunities(repo, idx, e) == 3
    works = [work(i, "SYNTHETIC blood brain barrier injury in HIV") for i in range(3)]
    profile = build_threads("A", works, e, as_of=date(2025, 1, 1))
    r = retrieve(profile, idx, k=3)
    assert r.candidates[0].record_id == "grants_gov:PA-1"
    assert r.candidates[0].ranks["t0.dense"] == 1 and r.candidates[0].ranks["t0.bm25"] == 1
    assert set(r.timings_ms) == {"dense", "bm25", "total"}
    assert [c.record_id for c in retrieve(profile, idx, k=3).candidates] == \
        [c.record_id for c in r.candidates]  # deterministic
