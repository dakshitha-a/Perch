"""Scout guard set (S49 Q1): sentences the answer check must always remove.

Every Q49 change to perch/scout/answer.py loosens a rule somewhere; this set keeps the
loosening honest. A case leaks when its marked sentence comes out of `grade` with no error
and not marked unsupported. Records and text are SYNTHETIC; no model, no grounder.
tests/test_scout_guard.py asserts that nothing leaks; bench/scout_replay.py reports the count.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, date, datetime

from perch.schemas import Brief, Lead, Opportunity, Record, Scholarship
from perch.scout import answer as ans
from perch.scout.read_tools import ReadTools, ScoutData

AS_OF = date(2026, 11, 4)
T = datetime(2026, 11, 1, tzinfo=UTC)
OPP = Opportunity(id="grants_gov:SYN-GUARD-1", source="grants_gov", fetched_at=T,
                  source_url="https://www.grants.gov/search-results-detail/990001",
                  opportunity_number="SYN-GUARD-1", title="SYNTHETIC Kidney Repair Program",
                  agency="National Institutes of Health", close_date=date(2026, 11, 17),
                  award_ceiling=500000.0, status="posted",
                  description="SYNTHETIC. Supports kidney repair research.")
OPP2 = Opportunity(id="grants_gov:SYN-GUARD-2", source="grants_gov", fetched_at=T,
                   source_url="https://www.grants.gov/search-results-detail/990002",
                   opportunity_number="SYN-GUARD-2", title="SYNTHETIC Marsh Ecology Program",
                   agency="National Science Foundation", close_date=date(2026, 12, 9),
                   status="posted", description="SYNTHETIC. Supports wetland ecology.")
SMP = Scholarship(id="sample:guard-1", source="synthetic", source_url="perch://sample",
                  fetched_at=T, name="SYNTHETIC Quillfen Award", canary="CANARY-guard-1",
                  purpose="SYNTHETIC sample award for a demonstration.")
C1, C2, CS = f"[{OPP.id}]", f"[{OPP2.id}]", f"[{SMP.id}]"

# (answer text, a substring that marks the sentence that must be removed, what it tests)
CASES: list[tuple[str, str, str]] = [
    (f"The SYNTHETIC Kidney Repair Program offers up to $750,000 {C1}.", "$750,000",
     "an invented amount"),
    (f"The SYNTHETIC Kidney Repair Program closes December 1, 2026 {C1}.", "December 1",
     "an invented deadline"),
    ("You are eligible for this grant.", "eligible", "an uncited eligibility claim"),
    (f"Your rank 2 lead is the SYNTHETIC Kidney Repair Program {C1}.", "rank 2",
     "a wrong rank"),
    (f"Apply at https://evil.example/apply {C1}.", "evil.example", "a link not in the record"),
    ("General advice:\nThe SYNTHETIC Kidney Repair Program suits most applicants.",
     "suits most", "a named award in General advice"),
    (f"Both the SYNTHETIC Kidney Repair Program {C1} and the SYNTHETIC Quillfen Award {CS} "
     "close soon.", "Both the", "a sample cited with a public record"),
    ("The deadline is November 17, 2026.", "November 17", "an uncited date"),
    ("This is a strong fit for your work.", "strong fit", "an uncited fit word"),
    ("It closes 17 Nov 2026 [grants_gov:SYN-NOT-RETURNED].", "17 Nov",
     "an id no tool returned"),
    (f"The SYNTHETIC Kidney Repair Program closes 17 Nov 2026 {C1}. It pays $900,000.",
     "$900,000", "an invented amount after a cited sentence"),
    (f"The SYNTHETIC Kidney Repair Program supports kidney repair research {C1}. It is a "
     "perfect match for you.", "perfect match", "a fit word after a cited sentence"),
    (f"The SYNTHETIC Quillfen Award is a sample record {CS}. It is open to every student.",
     "every student", "a claim riding on a sample's citation"),
    ("Excluded: ceiling under your limit", "Excluded", "a heading that states a result"),
    (f"The SYNTHETIC Kidney Repair Program is kept on your shortlist {C1}.", "kept",
     "a wrong kept claim"),
    (f"The record gives no deadline {C1}.", "no deadline", "a false absence claim"),
    ("I found no record on that, but the SYNTHETIC Marsh Ecology Program pays $500,000.",
     "Marsh", "a claim after a nothing-found line"),
    ("You have 9 leads in your brief [user:brief].", "9 leads", "a wrong whole-brief count"),
    (f"The SYNTHETIC Marsh Ecology Program closes 9 Dec 2026 {C2}. It closes after the "
     "SYNTHETIC Kidney Repair Program, on 1 Jan 2027.", "1 Jan 2027",
     "a date carried on to the next sentence"),
    (f"**Your top lead**\n- The SYNTHETIC Marsh Ecology Program closes 9 Dec 2026 {C2}.",
     "top lead", "an uncited rank heading"),
    ("Would you like me to read the SYNTHETIC Marsh Ecology Program, your best match?",
     "best match", "an offer naming a returned record with a fit word"),
    ("Perch does not confirm personal eligibility, so check the SYNTHETIC Kidney Repair "
     "Program, which pays $500,000.", "pays", "a disclaimer tail with a claim"),
    ("Your saved list is empty, so you qualify for everything [user:saved].", "qualify",
     "an empty-state template with a conclusion"),
    ("Rank 2 is the SYNTHETIC Kidney Repair Program [user:brief].", "Rank 2",
     "a wrong rank cited to the brief record"),
    ("Your brief has no leads [user:brief].", "no leads", "a false empty-brief claim"),
    ("The SYNTHETIC Marsh Ecology Program is kept [user:brief].", "kept",
     "a wrong kept claim cited to the brief record"),
    ("Your brief has three leads [user:brief].", "three leads", "a wrong lead count"),
    (f"Your soonest-closing lead is the SYNTHETIC Marsh Ecology Program {C2}.", "soonest",
     "a wrong soonest-closing claim"),
    (f"The SYNTHETIC Kidney Repair Program closes 17 Nov 2026 {C1}. The best one is:",
     "best one", "a lead-in that grades a record"),
    # S50 G15: a short refusal line passes as help text; a verdict after it does not.
    ("I cannot help with that; you are eligible for this grant.", "eligible",
     "a refusal line with an eligibility tail"),
    ("I can't answer that, but it is a strong fit.", "strong fit",
     "a refusal line with a fit tail"),
    ("**1. SYNTHETIC Kidney Repair Program pays $900,000**\n"
     f"- It closes 17 Nov 2026 {C1}.", "$900,000", "a bold numbered line with a claim"),
]


class _Repo:
    def __init__(self, recs: list[Record]) -> None:
        self.by_id = {r.id: r for r in recs}

    def get_any(self, id: str) -> Record | None:  # noqa: A002
        return self.by_id.get(id)

    def get(self, cls: type[Record], id: str) -> Record | None:  # noqa: A002
        r = self.by_id.get(id)
        return r if isinstance(r, cls) else None


def tools() -> ReadTools:
    """Tools that have read a two-lead brief (OPP rank 1, OPP2 rank 2, neither kept) and the
    sample, as a turn would."""
    repo = _Repo([OPP, OPP2, SMP])
    b = Brief(id="guard", source="perch", source_url="perch://guard", fetched_at=T,
              researcher_id="user:guard", status="done", lead_ids=["g1", "g2", "g3"])
    leads = [Lead(id=f"g{i}", source="perch", source_url="perch://guard", fetched_at=T,
                  brief_id="guard", route=r, record_id=x.id, rank=i)
             for i, (x, r) in enumerate([(OPP, "A"), (OPP2, "A"), (SMP, "S")], 1)]
    data = ScoutData(repo=lambda: nullcontext(repo), as_of=AS_OF, brief=lambda: (b, leads))
    t = ReadTools(data)
    t.read_brief()
    t.read_saved()  # empty: [user:saved] is returned
    t.read_entries()  # empty: [user:entries] is returned
    return t


def removed(s: ans.Sentence) -> bool:
    return bool(s.errors) or s.supported is False


def leaks() -> list[str]:
    """The cases whose marked sentence was not removed."""
    names = ans.name_index([OPP, OPP2, SMP])
    out = []
    for text, mark, what in CASES:
        t = tools()
        g = ans.grade(text, t.seen, names, AS_OF, None, t)
        hit = [s for s in g.sentences + g.general_sentences if mark in s.text]
        if not hit or not all(removed(s) for s in hit):
            out.append(f"{what}: {text!r}")
    return out


if __name__ == "__main__":
    bad = leaks()
    print(f"{len(CASES)} guard cases, {len(bad)} leaks")
    for b in bad:
        print(" ", b)
