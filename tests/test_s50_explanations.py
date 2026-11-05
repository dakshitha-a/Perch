"""S50 explanation quality from the live capture: no internal id in visible text (3a), code
chooses the papers per lead (3b). SYNTHETIC records; a fake provider, no spend."""

import json
from datetime import UTC, date, datetime

import numpy as np

from perch.profile import Profile, Thread
from perch.schemas import Opportunity, Work
from perch.skills.fit import choose_papers, explain_leads, name_ids
from tests.test_skills import audited

T = datetime(2026, 10, 28, tzinfo=UTC)


def work(i: int, title: str, abstract: str = "") -> Work:
    return Work(id=f"https://openalex.org/W{i}", source="openalex", fetched_at=T,
                source_url=f"https://openalex.org/W{i}", title=title, abstract=abstract)


PAPERS = [work(1, "SYNTHETIC kidney donor communication survey"),
          work(2, "SYNTHETIC coral reef heat stress genomics"),
          work(3, "SYNTHETIC battery cathode degradation imaging"),
          work(4, "SYNTHETIC kidney transplant waitlist networks")]
WORKS = {w.id: w for w in PAPERS}
PROFILE = Profile("A", date(2026, 10, 28), "fake",
                  [Thread(0, np.zeros(2), list(WORKS), 1.0, "mixed")], list(WORKS))


def opp(n: str, title: str, desc: str) -> Opportunity:
    return Opportunity(id=f"grants_gov:{n}", source="grants_gov", fetched_at=T,
                       source_url=f"https://example.gov/{n}", opportunity_number=n, title=title,
                       agency="SYNTHETIC Agency", description=desc)


KIDNEY = opp("SYN-K", "SYNTHETIC Kidney Donation Research", "Studies of kidney donor and "
             "transplant waitlist communication.")
REEF = opp("SYN-R", "SYNTHETIC Coral Reef Resilience", "Genomics of reef heat stress.")


def test_code_chooses_different_papers_for_different_leads():
    records = {w.id.rsplit("/", 1)[-1]: w for w in PAPERS}
    k = choose_papers(KIDNEY, records, 3)
    r = choose_papers(REEF, records, 3)
    assert k[:2] == ["W1", "W4"] and r[0] == "W2"
    assert k != r


def test_a_finding_outside_the_chosen_papers_is_rejected():
    def reply(pid):
        return json.dumps({"reasoning": "r", "opportunity_sentence":
                           "SYN-R funds reef genomics [SYN-R].",
                           "research_findings": [{"paper_id": pid, "finding": "studied a topic"}],
                           "link_sentence": "Both concern reefs.", "cited_ids": ["SYN-R", pid]})

    p, _ = audited([reply("W3"), reply("W2")])
    (v,) = explain_leads([REEF], PROFILE, WORKS, p)
    assert not v.flagged and v.attempts == 2
    assert "cite only the papers chosen" in p.inner.calls[1]["messages"][0].content
    assert "closest first: [W2]" in p.inner.calls[0]["messages"][0].content


def test_student_text_names_documents_by_title_never_by_bare_id():
    from perch.student import achievement_docs

    docs = achievement_docs(["SYNTHETIC poster on stream nitrate after storms",
                             "SYNTHETIC volunteer team for monthly stream sampling",
                             "SYNTHETIC map of storm drain outfalls"])
    works = {d.id: d for d in docs}
    prof = Profile("user:you", date(2026, 11, 6), "fake",
                   [Thread(0, np.zeros(2), list(works), 1.0, "streams")], list(works))
    o = opp("syn-award", "SYNTHETIC Stream Research Award", "Supports stream nitrate research.")
    reply = json.dumps({
        "reasoning": "r", "opportunity_sentence": "The award supports stream research "
                                                  "[syn-award].",
        "research_findings": [{"paper_id": "achievement-a", "finding":
                               "presented a poster on stream nitrate [user:achievement-a]"}],
        "link_sentence": "As user:achievement-a shows, the topics match.",
        "cited_ids": ["syn-award", "user:achievement-a"]})
    p, _ = audited([reply])
    (v,) = explain_leads([o], prof, works, p, audience="student")
    f = v.value
    visible = f.explanation.replace("[user:achievement-a]", "").replace("[syn-award]", "")
    assert "user:" not in visible and "achievement-a" not in visible
    assert f.research_sentence == ("Cited work: One of your entries presented a poster on "
                                   "stream nitrate [user:achievement-a].")  # S51 H9
    assert f.link_sentence == "As one of your entries shows, the topics match."


def test_name_ids_leaves_brackets_alone():
    labels = {"user:cv": "CV"}
    assert name_ids("Your user:cv lists it [user:cv].", labels) == "Your CV lists it [user:cv]."
