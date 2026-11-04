"""Quote checks for Temple page extraction. SYNTHETIC page, fake model, no network."""

import json
from datetime import UTC, datetime
from pathlib import Path

from perch import temple_extract as te
from perch.llm.fake import FakeProvider
from perch.schemas import Opportunity, Scholarship
from perch.store.denorm import columns

PAGE = """<main>
<h1>Sample Awards</h1>
<p>The Quill Family Memorial Scholarship is offered by Temple University to juniors.</p>
<p>It pays $2,500 and the application is due March 1.</p>
<p>Apply at <a href="https://apply.example/quill">the portal</a>.</p>
<p>Applicants need a 3.5 GPA and must be undergraduate students.</p>
<p>The Harbor Prize pays $4,000 and closes on April 3, 2027.</p>
<p>Contact Sam Sample, Director of Awards, sam.sample{AT}example.org or 215-555-0100.</p>
<p>The Faculty Seed Grant awards up to $10,000 to faculty. Deadline: May 5, 2027.</p>
</main>"""
PAGE = PAGE.replace("{AT}", "@")
URL = "https://sample.example/awards"
META = {"url": URL, "final_url": URL, "owner": "Fox School of Business",
        "audience": "mixed", "kind": "scholarship_list",
        "fetched_at": "2026-11-04T10:00:00+00:00"}


def award(title, **kw):
    base = {"title": title, "title_sentence": -1, "kind": "student_award",
            "amount_text": "", "amount_sentence": -1, "deadline_text": "",
            "deadline_sentence": -1, "link": "", "link_sentence": -1, "temple_sentence": -1,
            "eligibility": [], "level": "", "level_sentence": -1}
    return {**base, **kw}


def run(awards, meta=None):
    p = FakeProvider(replies=[json.dumps({"awards": awards})])
    return te.extract_page(p, meta or META, PAGE)


def idx(fragment):
    return next(i for i, s in enumerate(te.page_sentences(PAGE, URL)) if fragment in s)


def test_good_values_are_kept_and_quoted():
    recs, st, _ = run([award(
        "The Quill Family Memorial Scholarship",
        amount_text="$2,500", amount_sentence=idx("pays $2,500"),
        deadline_text="March 1", deadline_sentence=idx("pays $2,500"),
        link="https://apply.example/quill", link_sentence=idx("Apply at"),
        temple_sentence=idx("offered by Temple"),
        eligibility=[{"text": "must be undergraduate students",
                      "sentence": idx("3.5 GPA")}, {"text": "3.5 GPA", "sentence": idx("3.5 GPA")}],
        level="undergraduate", level_sentence=idx("3.5 GPA"))])
    (r,) = recs
    assert isinstance(r, Scholarship)
    assert r.source == "temple_pages" and r.source_url == URL
    assert r.fetched_at == datetime(2026, 11, 4, 10, tzinfo=UTC)
    assert (r.amount_min, r.amount_max) == (2500, 2500)
    assert "$2,500" in r.amount_quote
    assert r.apply_url == "https://apply.example/quill"
    assert r.temple_funded is True
    assert r.eligibility.gpa_min == 3.5
    assert r.audience_level == "mixed"  # inventory says mixed; the quote agrees on a part
    assert r.schools == ["Fox School of Business"] and r.scope == "school"
    assert r.page_owner == "Fox School of Business"
    c = columns(r)
    assert c.temple_funded and c.schools == ["Fox School of Business"]
    assert c.scope == "school" and c.audience_level == ["mixed"]


def test_yearless_deadline_keeps_text_only_no_date():
    (r,), st, _ = run([award("The Quill Family Memorial Scholarship",
                             deadline_text="March 1", deadline_sentence=idx("due March 1"))])
    assert r.deadline is None
    assert "March 1" in r.deadline_quote
    assert r.field_quotes["deadline_text"] == "March 1"
    assert st.fields_kept["deadline_text_only"] == 1


def test_dated_deadline_is_parsed_by_code():
    (r,), _, _ = run([award("The Harbor Prize", deadline_text="April 3, 2027",
                            deadline_sentence=idx("Harbor"))])
    assert str(r.deadline) == "2027-04-03"


def test_value_not_in_cited_sentence_is_dropped():
    (r,), st, _ = run([award(
        "The Harbor Prize",
        amount_text="$5,000", amount_sentence=idx("Harbor"),  # page says $4,000
        deadline_text="April 3, 2028", deadline_sentence=idx("Harbor"),
        link="https://apply.example/other", link_sentence=idx("Apply at"),
        eligibility=[{"text": "must be a senior", "sentence": idx("3.5 GPA")}],
        temple_sentence=idx("Harbor"))])
    assert r.amount_min is None and r.amount_max is None and r.amount_quote is None
    assert r.deadline is None and r.deadline_quote is None
    assert r.apply_url is None and r.eligibility.notes is None
    assert r.temple_funded is None
    for f in ("amount", "deadline", "link", "eligibility", "temple_funded"):
        assert st.fields_dropped[f] == 1, f


def test_right_value_wrong_sentence_is_dropped():
    (r,), _, _ = run([award("The Harbor Prize", amount_text="$4,000",
                            amount_sentence=idx("Quill"))])
    assert r.amount_max is None


def test_title_not_on_page_is_dropped():
    recs, st, _ = run([award("The Invented Award"), award("The Harbor Prize")])
    assert [r.name for r in recs] == ["The Harbor Prize"]
    assert st.dropped_records["title_not_on_page"] == 1


def test_not_an_award_and_bad_index_are_dropped():
    recs, _, _ = run([award("Sample Awards", kind="not_an_award"),
                      award("The Harbor Prize", amount_text="$4,000", amount_sentence=99)])
    assert len(recs) == 1 and recs[0].amount_max is None


def test_staff_contacts_never_survive():
    s = idx("Contact Sam")
    recs, st, _ = run([award(
        "The Harbor Prize",
        eligibility=[{"text": "Sam Sample, Director of Awards, sam.sample" + "@" + "example.org",
                      "sentence": s}],
        link="mailto:sam.sample@" + "example.org", link_sentence=s)])
    blob = json.dumps(recs[0].model_dump(mode="json"))
    assert "sam.sample" not in blob.lower() and "Sam Sample" not in blob and "215-555" not in blob


def test_page_sentences_carry_no_contacts_when_page_is_cleaned():
    from perch.sources.temple_pages import clean_page
    text = " ".join(te.page_sentences(clean_page(PAGE), URL))
    assert "Sample" not in text.replace("Sample Awards", "") and "@" not in text


def test_model_rank_inventory_conflict_goes_mixed():
    meta = {**META, "audience": "graduate"}
    (r,), _, _ = run([award("The Quill Family Memorial Scholarship",
                            level="undergraduate", level_sentence=idx("3.5 GPA"))], meta)
    assert r.audience_level == "mixed"


def test_internal_research_funding_is_an_opportunity():
    meta = {**META, "owner": "OVPR", "audience": "faculty", "kind": "internal_research_funding"}
    (r,), _, _ = run([award("The Faculty Seed Grant", kind="faculty_research_funding",
                            amount_text="$10,000", amount_sentence=idx("Seed Grant"),
                            deadline_text="May 5, 2027", deadline_sentence=idx("Deadline:"))],
                     meta)
    assert isinstance(r, Opportunity)
    assert r.award_ceiling == 10000 and r.award_floor is None  # "up to"
    assert str(r.close_date) == "2027-05-05" and r.details_url == URL
    assert r.agency == "OVPR" and r.scope is None and r.audience_level == "faculty"


def test_bad_json_is_retried_once():
    p = FakeProvider(replies=["not json", json.dumps({"awards": [award("The Harbor Prize")]})])
    recs, _, _ = te.extract_page(p, META, PAGE)
    assert len(recs) == 1 and len(p.calls) == 2


def test_old_records_load_without_new_fields():
    s = Scholarship(id="x:1", source="temple_sdfa", source_url="https://a.example",
                    fetched_at=datetime(2026, 1, 1, tzinfo=UTC), name="Old")
    assert s.schools == [] and s.temple_funded is None and s.audience_level is None
    assert te.pick_pilot([], 3) == []


def test_pilot_spreads_across_owners():
    pages = [({"url": f"u{i}", "owner": o}, "") for i, o in
             enumerate(["A", "A", "A", "B", "C"])]
    got = te.pick_pilot(pages, 3)
    assert sorted(m["owner"] for m, _ in got) == ["A", "B", "C"]


FIX = Path(__file__).parent / "fixtures" / "temple_pages"


def _fixtures():
    meta = json.loads((FIX / "manifest.json").read_text())
    return {k: (m, (FIX / f"{k}.html").read_text()) for k, m in meta.items()}


def test_real_page_fixtures_have_no_contacts():
    from perch.sources.temple_pages import is_contact_text
    assert len(_fixtures()) == 3
    for m, h in _fixtures().values():
        assert "mailto" not in h and "tel:" not in h
        assert not any(is_contact_text(s) for s in te.page_sentences(h, m["url"]))


def test_extraction_on_a_real_page_fixture():
    m, h = _fixtures()["dentistry_alumni_grant"]
    s = te.page_sentences(h, m["url"])
    i = next(k for k, x in enumerate(s) if "Grant applications are due" in x)
    p = FakeProvider(replies=[json.dumps({"awards": [
        award("Alumni Grant Fund", deadline_text="Dec. 1, 2020", deadline_sentence=i),
        award("Alumni Association Grant Application", deadline_text="Dec. 1, 2020",
              deadline_sentence=i, amount_text="$500", amount_sentence=i)]})])
    recs, st, _ = te.extract_page(p, m, h)
    (r,) = recs  # "Alumni Grant Fund" is not on the page
    assert str(r.deadline) == "2020-12-01" and r.amount_max is None
    assert r.schools == ["Kornberg School of Dentistry"] and r.source == "temple_pages"
