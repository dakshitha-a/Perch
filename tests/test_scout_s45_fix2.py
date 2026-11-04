"""S45 fix round 2 (offline, no model, no network): the code checks that replace MiniCheck for
rank, kept and absence claims, and MiniCheck's scholarship passage. SYNTHETIC text only."""

from __future__ import annotations

from datetime import UTC, date, datetime

from perch.grounding import FakeGrounder
from perch.schemas import Scholarship, ScholarshipEligibility, ScholarshipRequirements
from perch.scout import answer as ans
from perch.scout.read_tools import ReadTools, ScoutData

AS_OF = date(2026, 10, 28)
T = datetime(2026, 10, 1, tzinfo=UTC)
PUB = {"source": "temple_pages", "source_url": "https://example.invalid/x", "fetched_at": T}


def sch(n: int, **kw) -> Scholarship:
    return Scholarship(id=f"temple_pages:s{n}", name=f"SYNTHETIC Quillfen Award {n}", **PUB, **kw)


A = sch(1)  # no deadline, no amount, no requirements
B = sch(2, deadline=date(2027, 2, 1), amount_max=1000, details_url="https://example.invalid/x",
        details_fetched_at=T, deadline_quote="Due 1 Feb 2027", amount_quote="Up to $1,000",
        application_requirements=ScholarshipRequirements(essay=True))
C = sch(3, eligibility=ScholarshipEligibility(notes="Open to juniors in any major."),
        application_requirements=ScholarshipRequirements(transcript=True, letters_count=2))
SEEN = {r.id: r for r in (A, B, C)}


def tools(*, brief=True, saved=True) -> ReadTools:
    t = ReadTools(ScoutData(repo=lambda: None, audience="student"))  # type: ignore[arg-type]
    t.seen.update(SEEN)
    t.brief_read, t.saved_read = brief, saved
    t.ranks = {A.id: 1, B.id: 2, C.id: 3}
    t.kept = {B.id}
    t.saved = {C.id}
    return t


def verdict(text, ids, **kw):
    return ans.code_check(text, ids, SEEN, tools(**kw), AS_OF)


def test_minicheck_passage_gains_eligibility_notes_and_requirements():
    doc = ans.document_for(C, AS_OF)
    assert "Eligibility: Open to juniors in any major." in doc
    assert "Application requirements: transcript, 2 letters of recommendation." in doc
    assert "Eligibility" not in ans.document_for(A, AS_OF)
    assert "juniors" not in ans.validate.evidence(C).text


def test_rank_claims_are_checked_against_the_rows_read():
    assert verdict("It is your top-ranked lead [temple_pages:s1].", [A.id]) is True
    assert verdict("It is your top-ranked lead [temple_pages:s2].", [B.id]) is False
    assert verdict("It is your second lead.", [B.id]) is True
    assert verdict("The Quillfen Award 3 is ranked 3 in your brief.", [C.id]) is True
    assert verdict("The Quillfen Award 3 is ranked 1 in your brief.", [C.id]) is False
    assert verdict("It is your top lead.", [B.id], brief=False) is None


def test_kept_claims_are_checked_against_the_rows_read():
    assert verdict("You kept this one.", [B.id]) is True
    assert verdict("You kept this one.", [A.id]) is False
    assert verdict("You have not kept this one.", [A.id]) is True
    assert verdict("You saved this one.", [C.id]) is True
    assert verdict("You saved this one.", [A.id]) is False
    assert verdict("You saved this one.", [A.id], saved=False) is None


def test_absence_claims_are_checked_against_the_record_fields():
    assert verdict("The record gives no deadline.", [A.id]) is True
    assert verdict("The record gives no deadline.", [B.id]) is False
    assert verdict("The record does not state an amount.", [A.id]) is True
    assert verdict("The record lists no amount.", [B.id]) is False
    assert verdict("It lists no application requirements.", [A.id]) is True
    assert verdict("It lists no requirements.", [C.id]) is False
    assert verdict("It lists no requirements.", [A.id, C.id]) is False
    assert ans.code_check("The record gives no deadline.", [A.id], SEEN, None, AS_OF) is True


def test_anything_else_stays_with_minicheck():
    assert verdict("It supports undergraduate research.", [A.id]) is None


class Spy(FakeGrounder):
    def __init__(self):
        self.calls = []

    def support(self, document, claims):
        self.calls.append((document, claims))
        return [0.9 for _ in claims]


def test_grade_uses_code_checks_then_minicheck_on_the_whole_sentence():
    spy = Spy()
    text = ("It is your top-ranked lead [temple_pages:s2].\n"
            "Open to juniors [temple_pages:s3].")
    g = ans.grade(text, SEEN, set(), AS_OF, spy, tools())
    by = {s.text: s.supported for s in g.sentences if s.cites}
    assert by["It is your top-ranked lead [temple_pages:s2]."] is False
    assert g.unsupported == ["It is your top-ranked lead [temple_pages:s2]."]
    assert len(spy.calls) == 1 and spy.calls[0][1] == ["Open to juniors."]  # not re-split


# --- R2, S3, S4: fit and eligibility words in sentences no real record backs ---

def _empty_seen():
    t = ReadTools(ScoutData(repo=lambda: None, audience="student"))  # type: ignore[arg-type]
    t.read_saved()
    t.read_brief()
    return {**t.seen, **SEEN}


NO_RECORD = [
    "**International students welcome:**",
    "**Undergraduates may apply:**",
    "## You will likely win this one",
    "You are eligible here, so would you like me to draft a hand-off?",
    "Nothing in your CV stops you from applying to the top lead.",
    "None of your leads require a U.S. degree.",
    "You have not saved anything, but you are a strong fit for all of them [user:saved].",
    "Nothing in your saved list requires citizenship [user:saved].",
    "Nothing you saved is open to freshmen [user:saved].",
]


def test_no_record_sentences_cannot_carry_eligibility_or_fit_claims():
    seen = _empty_seen()
    for text in NO_RECORD:
        g = ans.grade(text, seen, set(), AS_OF)
        assert not g.ok, text


def test_a_sentence_citing_a_real_record_may_use_the_same_words():
    seen = _empty_seen()
    for text in ["It is open to juniors [temple_pages:s3].",
                 "Applicants may apply with a transcript [temple_pages:s3].",
                 "You have nothing saved yet [user:saved].",
                 "I found no records for that.", "Which one should I read in full?"]:
        assert ans.grade(text, seen, set(), AS_OF).ok, text
