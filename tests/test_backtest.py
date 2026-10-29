from datetime import UTC, date, datetime

from bench.backtest import PoolIndex, Row, in_window, rank_one, summarise
from perch.eligibility import Constraints, check
from perch.embed import FakeEmbedder
from perch.rerank import FakeReranker
from perch.retrieve import index_opportunities, retrieve
from perch.schemas import Opportunity, Work
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

T = datetime(2026, 10, 29, tzinfo=UTC)
HE = ["Private institutions of higher education"]


def opp(n, title, open_d, close_d):
    return Opportunity(id=f"grants_gov:{n}", opportunity_number=n, title=f"SYNTHETIC {title}",
                       agency="SYNTHETIC agency", source="grants_gov", fetched_at=T,
                       source_url=f"https://www.grants.gov/search-results-detail/{n}",
                       open_date=open_d, close_date=close_d, eligible_applicants=HE,
                       status="archived")


def work(i, title, d):
    return Work(id=f"W{i}", title=title, publication_date=d, author_ids=["https://openalex.org/A1"],
                source="openalex", source_url=f"https://api.openalex.org/works/W{i}",
                fetched_at=T)


def test_window_keeps_announcements_open_in_the_months_before_the_start():
    start = date(2020, 7, 1)
    assert in_window(date(2018, 1, 1), date(2019, 3, 1), start, 18)  # closed 16 months before
    assert not in_window(date(2017, 1, 1), date(2018, 6, 1), start, 18)  # closed too early
    assert not in_window(date(2020, 8, 1), date(2022, 1, 1), start, 18)  # opened after start
    assert in_window(None, None, start, 18)


def test_date_rules_can_be_switched_off_for_the_back_test():
    o = opp("RFA-1", "closed call", date(2018, 1, 1), date(2019, 1, 1))
    assert check(o, Constraints(as_of=date(2020, 1, 1)))
    assert check(o, Constraints(as_of=date(2020, 1, 1), check_dates=False)) == []


def test_rank_one_scores_the_true_announcement_with_papers_before_the_start(tmp_path):
    e = FakeEmbedder(256)
    repo = SQLiteRepository()
    opps = [opp("PAR-1", "blood brain barrier HIV neuroinflammation", date(2018, 1, 1),
                date(2019, 6, 1)),
            opp("PAR-2", "kidney transplant donor communication", date(2018, 1, 1),
                date(2021, 1, 1)),
            opp("PAR-3", "blood brain barrier stroke", date(2021, 1, 1), date(2023, 1, 1))]
    repo.upsert(opps)
    idx = LanceIndex(tmp_path / "lance")
    index_opportunities(repo, idx, e)
    works = [work(i, "SYNTHETIC blood brain barrier injury in HIV", date(2019, 1, i + 1))
             for i in range(3)]
    works.append(work(9, "SYNTHETIC kidney transplant donor", date(2021, 1, 1)))  # after start
    row = {"alias": "PI-X", "stratum": "targeted", "openalex_id": "A1",
           "opportunity_number": "PAR-1", "award_start": "2020-07-01"}
    by_id = {o.id: o for o in opps}
    for mode, rr in (("hybrid", FakeReranker()), ("bm25", None), ("dense", None)):
        r = rank_one(row, works, by_id, idx, e, rr, None, mode, 18, mode)
        assert r.papers == 3  # the 2021 paper is after the cut-off
        assert r.pool == 2  # PAR-3 opened after the start
        assert r.truth_eligible and r.truth_retrieved and r.rank == 1


def test_pool_index_filters_and_retrieve_modes_keep_one_list(tmp_path):
    e = FakeEmbedder(64)
    repo = SQLiteRepository()
    repo.upsert([opp(f"PA-{i}", f"topic {i} cells", None, None) for i in range(5)])
    idx = LanceIndex(tmp_path / "lance")
    index_opportunities(repo, idx, e)
    pool = PoolIndex(idx, {"grants_gov:PA-1", "grants_gov:PA-3"}, 5)
    assert {i for i, _ in pool.dense(e.embed_queries(["cells"])[0].tolist(), 5)} == pool.ids()
    from perch.profile import build_threads

    p = build_threads("https://openalex.org/A1",
                      [work(1, "SYNTHETIC topic 3 cells", date(2019, 1, 1))], e, date(2020, 1, 1))
    dense = retrieve(p, pool, mode="dense").candidates
    assert all(set(c.ranks) <= {"t0.dense"} for c in dense)
    assert all(set(c.ranks) <= {"t0.bm25"} for c in retrieve(p, pool, mode="bm25").candidates)


def test_summary_counts_hits_and_reciprocal_rank():
    rows = [Row("a", "targeted", "P", "2020-01-01", "c", 5, 1, 9, True, True, r,
                1 / r if r else 0.0, 0.1) for r in (1, 6, None, 12)]
    s = summarise(rows)
    assert (s["hit@5"], s["hit@10"], s["mrr"]) == (0.25, 0.5, round((1 + 1 / 6 + 1 / 12) / 4, 3))


def test_paired_table_counts_wins_and_losses_against_the_default():
    from bench.run import DEFAULT_CONFIG, DEFAULT_EMBEDDER, paired

    def row(alias, cfg, r):
        return Row(alias, "targeted", "P", "2020-01-01", cfg, 5, 1, 9, True, True, r,
                   1 / r if r else 0.0, 0.1)

    d = DEFAULT_CONFIG
    m = {(DEFAULT_EMBEDDER, d): [row("a", d, 3), row("b", d, None)],
         ("x/other", "dense"): [row("a", "dense", None), row("b", "dense", 2)]}
    other = next(r for r in paired(m, "targeted") if r["embedder"] == "other")
    assert (other["n"], other["hit@10 count"], other["+ / -"]) == (2, 1, "+1 / -1")
    same = next(r for r in paired(m, "targeted") if r["config"] == DEFAULT_CONFIG)
    assert same["MRR difference, 95% interval"] == "[0.000, 0.000]"


def test_profile_reranker_keys_build_cross_encoder_or_decision_server():
    from perch.rerank import DecisionReranker, make_reranker

    assert isinstance(make_reranker("systemone:clef-flash"), DecisionReranker)
