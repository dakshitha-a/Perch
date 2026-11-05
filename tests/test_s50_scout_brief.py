"""S50 (3d): "which kept lead fits best" had nothing code-written to cite. read_brief now
names the kept leads with their ranks and match bands, in the brief record too, and gives
each kept lead's checked fit sentence from its card. SYNTHETIC records."""

from contextlib import nullcontext

from bench.scout_guard import AS_OF, OPP, OPP2, SMP, T, _Repo
from perch.schemas import Brief, Lead
from perch.scout import answer as ans
from perch.scout.read_tools import ReadTools, ScoutData


def tools() -> tuple[ReadTools, dict]:
    repo = _Repo([OPP, OPP2, SMP])
    b = Brief(id="k", source="perch", source_url="perch://k", fetched_at=T,
              researcher_id="user:k", status="done", lead_ids=["k1", "k2"])
    leads = [Lead(id="k1", source="perch", source_url="perch://k", fetched_at=T, brief_id="k",
                  route="A", record_id=OPP.id, rank=1, match_score=82, status="kept",
                  inference="The kidney repair aims match the researcher's work [SYN-GUARD-1]."),
             Lead(id="k2", source="perch", source_url="perch://k", fetched_at=T, brief_id="k",
                  route="A", record_id=OPP2.id, rank=2, match_score=45, status="kept")]
    t = ReadTools(ScoutData(repo=lambda: nullcontext(repo), as_of=AS_OF,
                            brief=lambda: (b, leads)))
    return t, t.read_brief()


def test_read_brief_names_the_kept_leads_with_rank_and_match():
    _, out = tools()
    kept = out["kept_leads"]
    assert [(k["rank"], k["match"]) for k in kept] == [(1, "strong match"), (2, "partial match")]
    assert kept[0]["fit_sentence"] == "The kidney repair aims match your work."
    assert "fit_sentence" not in kept[1]
    assert out["leads"][0]["match"] == "strong match"


def test_a_sentence_on_the_best_kept_lead_can_cite_the_brief():
    t, _ = tools()
    names = ans.name_index([OPP, OPP2])
    text = ("Of your kept leads, the SYNTHETIC Kidney Repair Program ranks highest, at rank 1 "
            "with a strong match [user:brief].")
    g = ans.grade(text, t.seen, names, AS_OF, None, t)
    assert all(not s.errors for s in g.sentences), [s.errors for s in g.sentences]
    brief_doc = t.seen["user:brief"]
    assert "Kept leads, in the brief's order: rank 1, SYNTHETIC Kidney Repair Program, strong " \
           "match; rank 2, SYNTHETIC Marsh Ecology Program, partial match." in brief_doc.abstract
