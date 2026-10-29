import json
from datetime import UTC, date, datetime

import numpy as np

from perch.llm.audit import AuditedProvider, AuditLog
from perch.llm.fake import FakeProvider
from perch.profile import Profile, Thread
from perch.schemas import Opportunity, Work
from perch.skills.fit import explain_leads
from perch.skills.summary import summarise_profile

T = datetime(2026, 10, 28, tzinfo=UTC)


def work(i, title):
    return Work(id=f"https://openalex.org/W{i}", title=f"SYNTHETIC {title}", publication_year=2021,
                publication_date=date(2021, 1, 1), author_ids=["A"], source="openalex",
                source_url=f"https://api.openalex.org/works/W{i}", fetched_at=T)


WORKS = {w.id: w for w in [work(1, "living kidney donor communication"),
                           work(2, "kidney transplant waitlist networks"),
                           work(3, "organ donation attitudes")]}
PROFILE = Profile("A", date(2026, 10, 28), "fake",
                  [Thread(0, np.zeros(2), list(WORKS), 1.0, "kidney, donor", [])], list(WORKS))
OPP = Opportunity(id="grants_gov:PAR-1", opportunity_number="PAR-1", title="SYNTHETIC ELSI (R01)",
                  agency="NIH", close_date=date(2026, 11, 18), source="grants_gov",
                  source_url="https://www.grants.gov/x", fetched_at=T)


def audited(replies):
    log = AuditLog(None)
    return AuditedProvider(FakeProvider(replies), log, "x"), log


def fit_reply(explanation, cited=("PAR-1", "W1")):
    return json.dumps({"reasoning": "r", "fit": 80, "explanation": explanation,
                       "cited_ids": list(cited)})


GOOD = "PAR-1 funds research on ethics of donation. W1 studies living kidney donor communication."


def test_fit_passes_first_time_and_is_logged():
    p, log = audited([fit_reply(GOOD)])
    (v,) = explain_leads([OPP], PROFILE, WORKS, p)
    assert not v.flagged and v.value.fit == 80 and v.attempts == 1
    assert log.rejection_rate("fit_explainer") == (0, 1)
    assert sum(e["kind"] == "call" for e in log.events) == 1


def test_invented_number_is_regenerated_then_passes():
    bad = GOOD + " It pays $2,000,000."
    p, log = audited([fit_reply(bad), fit_reply(GOOD)])
    (v,) = explain_leads([OPP], PROFILE, WORKS, p)
    assert v.attempts == 2 and not v.flagged
    assert "number '2000000'" in p.inner.calls[1]["messages"][0].content  # errors fed back
    assert log.rejection_rate("fit_explainer") == (1, 2)


def test_twice_bad_is_flagged_without_explanation():
    p, log = audited([fit_reply(GOOD, cited=("W1",)), fit_reply(GOOD, cited=("PAR-1", "W9"))])
    (v,) = explain_leads([OPP], PROFILE, WORKS, p)
    assert v.flagged and v.value is None
    assert any("W9" in e for e in v.errors)


def test_summary_skill_validates_topics_and_two_sentences():
    reply = json.dumps({"topics": [{"label": "living donation", "work_ids": ["W1"]},
                                   {"label": "waitlist networks", "work_ids": ["W2"]},
                                   {"label": "donation attitudes", "work_ids": ["W3"]}],
                        "summary": "Studies kidney donation. Focus on communication.",
                        "cited_ids": ["W1", "W2", "W3"]})
    p, log = audited([reply])
    v = summarise_profile(PROFILE, WORKS, p)
    assert not v.flagged and len(v.value.topics) == 3
    one_sentence = json.loads(reply)
    one_sentence["summary"] = "Only one sentence."
    p, log = audited([json.dumps(one_sentence)] * 2)
    assert summarise_profile(PROFILE, WORKS, p).flagged
