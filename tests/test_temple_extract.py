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


def _cache(tmp_path, n):
    cache = tmp_path / "cache"
    cache.mkdir()
    lines = []
    for i in range(n):
        u = f"https://sample.example/p{i}"
        (cache / f"p{i}.html").write_text(PAGE)
        lines.append(json.dumps({**META, "url": u, "final_url": u, "file": f"p{i}.html"}))
    (cache / "manifest.jsonl").write_text("\n".join(lines) + "\n")
    return cache


def _one_award_provider():
    reply = json.dumps({"awards": [award("The Harbor Prize")]})
    return FakeProvider(responder=lambda m, s, sc: reply)


def test_extract_all_is_resumable_and_skips_done_pages(tmp_path):
    cache, out = _cache(tmp_path, 3), tmp_path / "out.jsonl"
    p = _one_award_provider()
    assert te.run_extract(cache, out, run_all=True, provider=p, budget_usd=1.0) == 0
    assert len(p.calls) == 3
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert {r["source_url"] for r in rows} == {f"https://sample.example/p{i}" for i in range(3)}
    p2 = _one_award_provider()
    te.run_extract(cache, out, run_all=True, provider=p2)
    assert p2.calls == [] and len(out.read_text().splitlines()) == 3


def test_extract_all_continues_after_a_stop_and_restart_starts_over(tmp_path):
    cache, out = _cache(tmp_path, 3), tmp_path / "out.jsonl"
    first = te.load_cached(cache)[0]
    recs, _, _ = te.extract_page(_one_award_provider(), *first)
    out.write_text("".join(json.dumps({"kind": r.kind, **r.model_dump(mode="json")}) + "\n"
                           for r in recs))
    te.done_path(out).write_text(json.dumps({"url": first[0]["url"], "records": 1}) + "\n")
    p3 = _one_award_provider()
    te.run_extract(cache, out, run_all=True, provider=p3)
    assert len(p3.calls) == 2 and len(out.read_text().splitlines()) == 3
    p4 = _one_award_provider()
    te.run_extract(cache, out, run_all=True, provider=p4, restart=True)
    assert len(p4.calls) == 3 and len(out.read_text().splitlines()) == 3


def test_extract_all_budget_stops_between_pages(tmp_path, capsys, monkeypatch):
    cache, out = _cache(tmp_path, 3), tmp_path / "out.jsonl"
    p = _one_award_provider()
    monkeypatch.setattr(te, "cost_usd", lambda res: 0.6)
    te.run_extract(cache, out, run_all=True, provider=p, budget_usd=1.0)
    assert len(p.calls) == 2
    text = capsys.readouterr().out
    assert "budget" in text.lower() and "dropped" in text.lower()


def test_temple_funded_sentence_forms_from_the_s40_handcheck() -> None:
    from perch.temple_extract import _TEMPLE_OFFERS
    yes = ["Temple will offer 10 Exchange Awards.",
           "The College of Quill and Vane Studies offers awards.",
           "Each year the School of Lute, Reed & Drum Arts gives two awards.",
           "It is awarded by the Office of Undergraduate Admissions.",
           "Funding is provided by the Office of the Provost.",
           "Global Opportunities (GO) administers the grant.",
           "The Fox School offers scholarships."]
    no = ["Students may apply to an outside program.", "Applicants must attend Temple.",
          "The Zarnow Science Foundation awards grants.",
          "Students who receive awards must report them."]
    assert all(_TEMPLE_OFFERS.search(t) for t in yes)
    assert not any(_TEMPLE_OFFERS.search(t) for t in no)


# --- S46 hand-check fixes: amounts and temple_funded wording (SYNTHETIC text) ---------

def _res(sentence, value=None):
    return te.resolve_amount(sentence, value)


def test_per_award_figure_beats_the_fund_total() -> None:
    s = ("The $250,000/year fund supports small projects, with awards of up to $50,000 "
         "per project.")
    assert _res(s, "$250,000") == (None, 50000)
    assert _res(s) == (None, 50000)


def test_fund_total_alone_is_not_an_award_amount() -> None:
    s = "SYNTHETIC Fund Size: The $250,000/year fund supports several projects."
    assert _res(s, "$250,000") is None
    assert _res("The fund totals $90,000 each year.", "$90,000") is None
    assert _res("Each award is $2,500.", "$2,500") == (2500, 2500)
    assert _res("Prizes are a $5,000 award.", "$5,000") == (5000, 5000)


def test_stipend_plus_allowance_is_not_a_range() -> None:
    s = ("This SYNTHETIC fellowship gives three years of support, a $37,000 annual stipend "
         "and a $16,000 cost-of-education allowance.")
    assert _res(s, "$37,000 annual stipend and a $16,000 cost-of-education allowance") \
        == (37000, 37000)
    assert _res(s, "$37,000") == (37000, 37000)


def test_a_range_is_kept_only_when_the_sentence_says_so() -> None:
    assert _res("Awards range from $1,000 to $5,000.", "$1,000 to $5,000") == (1000, 5000)
    assert _res("Awards are between $1,000 and $5,000.", "$1,000 and $5,000") == (1000, 5000)
    assert _res("Awards of $1,000-$5,000 are made.", "$1,000-$5,000") == (1000, 5000)
    assert _res("Prizes of $1,000 and $5,000 are given.", "$1,000 and $5,000") is None
    assert _res("Awards of up to $4,000.", "$4,000") == (None, 4000)
    # A range is not broken up by a component word after the second amount.
    assert _res("Typically $600 to $1,000 in tuition remission.", "$600 to $1,000") \
        == (600, 1000)
    assert _res("A stipend ranging from $300 for freshmen to $500 for seniors.",
                "$300 for freshmen to $500") == (300, 500)


def test_the_amount_rules_reach_verify() -> None:
    fund = "The SYNTHETIC Harbor Fund Size is a $250,000/year fund for small projects."
    page = f"<main><p>The Quill Prize.</p><p>{fund}</p></main>"
    sents = te.page_sentences(page, URL)
    i = next(n for n, x in enumerate(sents) if "Harbor" in x)
    p = FakeProvider(replies=[json.dumps({"awards": [award(
        "Quill Prize", amount_text="$250,000", amount_sentence=i)]})])
    (r,), st, _ = te.extract_page(p, META, page)
    assert r.amount_max is None and r.amount_quote is None
    assert st.fields_dropped["amount"] == 1


def test_temple_funded_wording_widened_for_explicit_funding() -> None:
    yes = ["Temple University Grants are university-funded, need-based grants.",
           "The Office of the Provost and the schools fund the grants.",
           "These grants come from an internal fund for faculty.",
           "OVPR funding supports the program.",
           "The Office of the Vice President for Research internal fund supports pilots.",
           "The $250,000/year fund is subject to annual budget approvals by the Vice "
           "President for Research."]
    no = ["The Zarnow Science Foundation funds this award; contact the Office of the "
          "Vice President for Research.",
          "Funded by the SYNTHETIC Garnet Trust.",
          "Applicants should submit through OVPR.",
          "The award is listed on this Temple page.",
          "Federal funding is available from outside sponsors."]
    assert all(te._TEMPLE_OFFERS.search(t) for t in yes), [
        t for t in yes if not te._TEMPLE_OFFERS.search(t)]
    assert not any(te._TEMPLE_OFFERS.search(t) for t in no), [
        t for t in no if te._TEMPLE_OFFERS.search(t)]


def _rec(**kw):
    q = kw.pop("field_quotes", {})
    return Scholarship(id="temple_pages:x", name="SYNTHETIC Quill Award", source="temple_pages",
                       source_url=URL, fetched_at=datetime(2026, 11, 4, tzinfo=UTC),
                       details_url=URL, details_fetched_at=datetime(2026, 11, 4, tzinfo=UTC),
                       field_quotes=q, **kw)


def test_refine_record_fixes_old_amounts_and_temple_funded_from_quotes() -> None:
    sent = ("This fellowship provides a $37,000 annual stipend and $16,000 "
            "cost-of-education allowance.")
    old = _rec(amount_min=16000, amount_max=37000, amount_quote=sent,
               field_quotes={"amount": sent})
    new = te.refine_record(old)
    assert (new.amount_min, new.amount_max) == (37000, 37000)
    fund = "The $250,000/year fund supports several projects."
    gone = te.refine_record(_rec(amount_min=250000, amount_max=250000, amount_quote=fund,
                                 field_quotes={"amount": fund}))
    assert gone.amount_min is None and gone.amount_max is None and gone.amount_quote is None
    assert "amount" not in gone.field_quotes
    tf = te.refine_record(_rec(field_quotes={
        "eligibility": "Grants are university-funded, need-based grants for undergraduates."}))
    assert tf.temple_funded is True and "university-funded" in tf.field_quotes["temple_funded"]
    ext = _rec(field_quotes={"eligibility": "Funded by the SYNTHETIC Garnet Trust."})
    assert te.refine_record(ext).temple_funded is None
    prog = _rec(field_quotes={"eligibility": "The SYNTHETIC Grow Vale Grant Program provides "
                                             "money to residents."})
    assert te.refine_record(prog).temple_funded is None  # a program is not proof it is Temple's
    same = _rec(amount_min=2500, amount_max=2500, amount_quote="Pays $2,500.")
    assert te.refine_record(same) is same
