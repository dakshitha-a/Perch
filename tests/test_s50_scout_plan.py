"""S50 Scout plan, G9 onward: the replay is exact and code accepts what it can check.
SYNTHETIC records; no model, no grounder, no spend."""

from contextlib import nullcontext

from bench.scout_guard import AS_OF, OPP, OPP2, SMP, _Repo
from bench.scout_guard import tools as guard_tools
from bench.scout_replay import searches
from perch.scout import answer as ans
from perch.scout.read_tools import ReadTools, ScoutData

NAMES = ans.name_index([OPP, OPP2, SMP])


def fresh() -> ReadTools:
    return ReadTools(ScoutData(repo=lambda: nullcontext(_Repo([OPP, OPP2, SMP])), as_of=AS_OF))


# --- G9: the replay rebuilds a search with its count ---

def test_grade_carries_each_search_record_text():
    from perch.scout.read_tools import user_doc

    t = fresh()
    t._see(user_doc("search:1", "Search 1", "Scout searched the records for \"kidney\" and "
                                            "found 1 record: SYNTHETIC Kidney Repair Program."))
    g = ans.grade("I searched the records [search:1].", t.seen, NAMES, AS_OF, None, t)
    assert g.search_records == {"search:1": t.seen["search:1"].abstract}


def test_a_logged_search_makes_its_count_checkable_in_the_replay():
    text = "The search for kidney found 8 records [search:1]."
    logged = {"search:1": "Scout searched the records for \"kidney\" and found 8 records: "
                          "SYNTHETIC Kidney Repair Program."}
    old, new = fresh(), fresh()
    searches(old, ["search:1"])  # a run before G9: no logged text, so the count fails
    searches(new, ["search:1"], logged)
    assert not ans.grade(text, old.seen, NAMES, AS_OF, None, old).ok
    assert ans.grade(text, new.seen, NAMES, AS_OF, None, new).ok


def test_guard_tools_still_build():
    assert "user:brief" in guard_tools().seen


# --- G13: neutral section names ---

def _heading_errors(heading: str) -> list[str]:
    t = guard_tools()
    text = f"**{heading}**\n- The SYNTHETIC Kidney Repair Program closes 17 Nov 2026 [{OPP.id}]."
    g = ans.grade(text, t.seen, NAMES, AS_OF, None, t)
    return [e for s in g.sentences if heading in s.text for e in s.errors]


def test_neutral_section_names_pass_and_a_relevance_heading_does_not():
    for h in ("Side by side", "Closes soonest", "Next", "Deadlines in your brief",
              "Your brief", "Where it sits in your brief", "What the search does not show"):
        assert _heading_errors(h) == [], h
    assert _heading_errors("Closest matches")


# --- G12: a top-lead heading over the records the brief ranks first ---

def _top(heading: str, *opps) -> list[str]:
    t = guard_tools()
    lines = "\n".join(f"- {o.title} closes soon [{o.id}]." for o in opps)
    g = ans.grade(f"**{heading}**\n{lines}", t.seen, NAMES, AS_OF, None, t)
    return [e for s in g.sentences if heading in s.text for e in s.errors]


def test_top_lead_heading_passes_over_rank_one_only():
    assert _top("Your top lead", OPP) == []
    assert _top("Top lead: SYNTHETIC Kidney Repair Program", OPP) == []
    assert _top("Top two leads", OPP, OPP2) == []
    assert _top("Your top lead", OPP2)  # rank 2
    assert _top("Top lead: SYNTHETIC Marsh Ecology Program", OPP)  # the title is not rank 1
    assert _top("Top two leads", OPP)  # only one record under it


# --- G15: a one-line refusal inside a mixed answer ---

def _errors(text: str, mark: str) -> list[str]:
    t = guard_tools()
    g = ans.grade(text, t.seen, NAMES, AS_OF, None, t)
    return [e for s in g.sentences if mark in s.text for e in s.errors]


def test_a_short_refusal_line_passes_and_a_claim_after_it_does_not():
    ok = (f"The SYNTHETIC Kidney Repair Program closes 17 Nov 2026 [{OPP.id}]. "
          "I cannot help with the integral question.")
    assert _errors(ok, "integral") == []
    assert _errors("I cannot help with that, but the SYNTHETIC Marsh Ecology Program pays "
                   "$500,000.", "Marsh")
    assert _errors("I cannot help with the SYNTHETIC Marsh Ecology Program.", "Marsh")
