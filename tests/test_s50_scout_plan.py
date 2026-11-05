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
