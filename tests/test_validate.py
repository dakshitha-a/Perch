from datetime import UTC, date, datetime

from perch.schemas import Opportunity, Work
from perch.validate import check, find_dates, find_numbers, generate_validated

T = datetime(2026, 10, 28, tzinfo=UTC)
OPP = Opportunity(id="grants_gov:PAR-25-371", opportunity_number="PAR-25-371",
                  title="SYNTHETIC ELSI Research (R01 Clinical Trial Optional)", agency="NIH",
                  close_date=date(2026, 11, 18), award_ceiling=500000.0,
                  description="SYNTHETIC. Budgets up to $500,000 per year for 5 years.",
                  source="grants_gov", source_url="https://www.grants.gov/x", fetched_at=T)
WORK = Work(id="https://openalex.org/W1", title="SYNTHETIC living kidney donor study",
            publication_year=2021, publication_date=date(2021, 3, 2),
            abstract="SYNTHETIC. We surveyed 412 donors.", source="openalex",
            source_url="https://api.openalex.org/works/W1", fetched_at=T)
RECS = {OPP.id: OPP, WORK.id: WORK}


def test_parsers():
    assert [d for _, d in find_dates("closes November 18, 2026 or 2026-11-18 or 11/18/2026")] \
        == [date(2026, 11, 18)] * 3
    assert find_dates("on February 30, 2026")[0][1] is None
    assert find_numbers("PAR-25-371 (R01) and W1234567 and 0000-0002-1825-009X") == []
    assert find_numbers("$1,500,000 and 41.0% of 412") == ["1500000", "41", "412"]


def test_supported_output_passes():
    text = ("The ELSI R01 (PAR-25-371) closes November 18, 2026 and allows up to $500,000 "
            "per year; the 2021 survey of 412 donors fits its aims.")
    assert check(text, [OPP.id, WORK.id], RECS).ok


def test_unknown_id_and_invented_numbers_fail():
    c = check("Awards reach $750,000 and close 2026-12-01.", ["grants_gov:PA-99-999"], RECS)
    assert not c.ok
    assert any("PA-99-999" in e for e in c.errors)
    c = check("Awards reach $750,000 and close 2026-12-01.", [OPP.id], RECS)
    assert c.errors == ["date '2026-12-01' is not in any cited record",
                        "number '750000' is not in any cited record"]


def test_number_must_come_from_a_cited_record():
    # 412 is in the work, but only the opportunity is cited
    assert not check("A survey of 412 donors.", [OPP.id], RECS).ok


def test_regenerate_once_then_flag():
    outputs = iter(["bad", "good"])
    v = generate_validated(lambda fb: next(outputs),
                           lambda o: check("" if o == "good" else "$9", [OPP.id], RECS))
    assert (v.value, v.attempts, v.flagged) == ("good", 2, False)
    seen = []

    def gen(feedback):
        seen.append(feedback)
        return "bad"

    v = generate_validated(gen, lambda o: check("$9", [OPP.id], RECS))
    assert v.flagged and v.value is None and seen[1] == ["number '9' is not in any cited record"]


def test_unparseable_output_counts_as_an_attempt():
    def gen(feedback):
        raise ValueError("not JSON")

    v = generate_validated(gen, lambda o: check("", [], RECS))
    assert v.flagged and "could not be parsed" in v.errors[0]


def test_links_and_calls_to_act_must_come_from_a_cited_record():
    """S16: injected record text can still steer prose that has no number. A link, or
    the words click and visit, pass only when a cited record holds them."""
    bad = check("Visit https://evil.example/apply to apply now.", [OPP.id], RECS)
    assert not bad.ok
    assert any("link 'https://evil.example/apply'" in e for e in bad.errors)
    assert any("'visit'" in e for e in bad.errors)
    assert not check("Click here for the details.", [OPP.id], RECS).ok
    assert check(f"The listing is at {OPP.source_url}.", [OPP.id], RECS).ok
    home = Work(id="https://openalex.org/W9", source="openalex", fetched_at=T,
                source_url="https://openalex.org/W9", title="SYNTHETIC home visits for gait")
    assert check("The paper used home visits.", [home.id], {home.id: home}).ok
