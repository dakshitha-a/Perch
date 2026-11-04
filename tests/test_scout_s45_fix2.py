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


# --- S1: wider crisis words, and a quiet period for the free path ---

def test_wider_crisis_words_match_and_research_phrasing_does_not():
    from perch.scout import texts

    for q in ["I wish I were dead", "I have suicidal thoughts", "im having suicidal thoughts",
              "I keep thinking about suicide", "thinking about suicide", "I want to end it all",
              "there is no reason to live", "I can't go on", "cant go on", "I dont wanna live",
              "I don't want to live anymore"]:
        assert texts.DISTRESS_RE.search(q), q
    for q in ["suicide prevention funding", "self-harm research grants",
              "funding to study suicidal thoughts in teens", "suicidal ideation grants",
              "grants on thinking about suicide prevention"]:
        assert not texts.DISTRESS_RE.search(q), q


def test_recent_distress_only_within_a_minute():
    from datetime import timedelta

    from perch.scout.web import recent_distress

    now = datetime.now(UTC)
    fresh = [{"kind": "distress", "at": now.isoformat()}]
    old = [{"kind": "distress", "at": (now - timedelta(minutes=2)).isoformat()}]
    assert recent_distress(fresh) and not recent_distress(old)
    assert not recent_distress([{"kind": "answer", "at": now.isoformat()}])
    assert not recent_distress([])


# --- S5: more contact shapes ---

def test_more_phone_link_and_email_shapes_are_blanked():
    from perch.llm.contacts import blank_contacts

    for t in ["(215)204-1234", "215-2041234", "(215) 2041234", "020 7946 0958", "x.ai/jdoe",
              "bit.ly/abc", "t.me/jdoe", "jdoe at temple dot edu", "jdoe [at] temple [dot] edu"]:
        assert blank_contacts(t) == "[contact removed]", t
    assert blank_contacts("orcid.org/0000-0002-1825-0097") == "[contact removed]"
    assert blank_contacts("https://orcid.org/0000-0002-1825-0097") == "[contact removed]"
    assert blank_contacts("email me at jdoe at temple dot edu please") == (
        "email me at [contact removed] please")


def test_a_ten_digit_grant_number_after_its_word_is_kept():
    from perch.llm.contacts import blank_contacts

    for t in ["grant 1234567890 awarded", "Award No. 1234567890", "Project ID: 1234567890"]:
        assert blank_contacts(t) == t, t
    assert blank_contacts("call 2155550100") == "call [contact removed]"
    for t in ["meet at 5 and look at the data", "i.e./e.g. fine", "see a.b/c"]:
        assert blank_contacts(t) == t, t


# --- R3: history drops budget-answered and unanswered user messages ---

def test_history_drops_budget_answered_and_unanswered_user_messages():
    from perch.scout import texts
    from perch.scout.turn import history_of

    msgs = [
        {"id": "1", "role": "user", "kind": "question", "text": "inject one"},
        {"id": "2", "role": "assistant", "kind": "budget", "text": texts.BUDGET},
        {"id": "3", "role": "user", "kind": "question", "text": "cancelled before the gate"},
        {"id": "4", "role": "user", "kind": "question", "text": "Which lead is strongest?"},
        {"id": "5", "role": "assistant", "kind": "answer", "text": "The first one."},
        {"id": "6", "role": "user", "kind": "question", "text": "still pending"}]
    assert [(m.role, m.content) for m in history_of(msgs)] == [
        ("user", "Which lead is strongest?"), ("assistant", "The first one.")]
