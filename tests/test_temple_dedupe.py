"""Dedupe rules on SYNTHETIC Temple records: no network, no model."""

from datetime import UTC, date, datetime

from perch.schemas import Opportunity, Scholarship
from perch.temple_dedupe import dedupe, norm_title
from perch.temple_extract import SCHOOL_OWNERS

T = datetime(2026, 11, 4, tzinfo=UTC)


def sch(rid, name, owner, url, *, amount=None, deadline=None, apply_url=None, dtext=None,
        temple=None, notes=None):
    q = {}
    kw = {}
    if amount:
        q["amount"] = f"SYNTHETIC pays ${amount:,}."
        kw.update(amount_min=amount, amount_max=amount, amount_quote=q["amount"])
    if deadline:
        kw.update(deadline=deadline, deadline_quote=f"SYNTHETIC due {deadline:%B} {deadline.day}, "
                                                   f"{deadline.year}.")
        q["deadline_text"] = kw["deadline_quote"]
    elif dtext:
        q["deadline_text"] = dtext
    if apply_url:
        q["apply_url"] = f"Apply ({apply_url})"
    if notes:
        q["eligibility"] = notes
    return Scholarship(
        id=rid, name=name, source="temple_pages", source_url=url, fetched_at=T,
        details_url=url, details_fetched_at=T, page_owner=owner, apply_url=apply_url,
        temple_funded=temple, field_quotes=q,
        schools=[owner] if owner in SCHOOL_OWNERS else [],
        scope="school" if owner in SCHOOL_OWNERS else None,
        eligibility={"notes": notes} if notes else {}, **kw)


def test_title_normalisation():
    assert norm_title("The Quill & Sons Award!") == norm_title("quill and sons award")


def test_same_title_on_two_schools_merges_and_lists_both_pages():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
            amount=2500)
    b = sch("temple_pages:b", "The SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd",
            apply_url="https://apply.example/q")
    out, rep = dedupe([b, a])
    (r,) = out
    assert rep.merged_groups == 1 and not rep.conflicts
    assert [s.source_url for s in r.seen_on] == ["https://x.example/cehd", "https://x.example/cst"]
    assert all(s.fetched_at == T for s in r.seen_on)
    assert r.scope == "temple_wide" and r.schools == ["CEHD", "CST"]


def test_fields_fill_across_pages_and_keep_their_own_quotes():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
            amount=2500)
    b = sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd",
            deadline=date(2027, 3, 1), apply_url="https://apply.example/q", temple=True)
    (r,) = dedupe([a, b])[0]
    assert r.amount_max == 2500 and r.deadline == date(2027, 3, 1)
    assert "2,500" in r.field_quotes["amount"]
    assert "March 1, 2027" in r.field_quotes["deadline_text"]
    assert r.apply_url == "https://apply.example/q" and r.temple_funded is True
    srcs = set(r.field_sources.values()) | {r.source_url}
    assert srcs <= {"https://x.example/cst", "https://x.example/cehd"}
    assert len(r.field_sources) >= 1
    Scholarship.model_validate(r.model_dump())  # still valid: each quote carries its value


def test_conflicting_amounts_are_never_merged_and_are_logged():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
            amount=2500)
    b = sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd",
            amount=3000)
    out, rep = dedupe([a, b])
    assert len(out) == 2 and len(rep.conflicts) == 1
    assert rep.conflicts[0].fields == ["amount"]
    assert {r.scope for r in out} == {"school"}


def test_conflicting_deadlines_are_never_merged():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
            deadline=date(2027, 3, 1))
    b = sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd",
            deadline=date(2027, 4, 1))
    out, rep = dedupe([a, b])
    assert len(out) == 2 and rep.conflicts[0].fields == ["deadline"]


def test_a_bare_date_text_and_a_full_date_do_not_conflict():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
            deadline=date(2027, 3, 1))
    b = sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd",
            dtext="March 1")
    assert len(dedupe([a, b])[0]) == 1


def test_different_apply_urls_keep_records_apart():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
            apply_url="https://apply.example/one")
    b = sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd",
            apply_url="https://apply.example/two")
    out, rep = dedupe([a, b])
    assert len(out) == 2 and rep.conflicts[0].fields == ["apply_url"]


def test_url_forms_compare_equal():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
            apply_url="https://www.apply.example/one/")
    b = sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd",
            apply_url="http://apply.example/one")
    assert len(dedupe([a, b])[0]) == 1


def test_clustering_is_order_independent_with_a_blank_record_between_conflicts():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/1", amount=2500)
    b = sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/2", amount=3000)
    c = sch("temple_pages:c", "SYNTHETIC Quill Award", "Liberal Arts", "https://x.example/3")
    o1, _ = dedupe([a, b, c])
    o2, _ = dedupe([c, b, a])
    assert [r.model_dump() for r in o1] == [r.model_dump() for r in o2]
    assert len(o1) == 2  # the blank record joins one of the two, never both


def test_different_titles_and_kinds_stay_apart():
    a = sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/1")
    b = sch("temple_pages:b", "SYNTHETIC Quill Prize", "CST", "https://x.example/1")
    o = Opportunity(id="temple_pages:o", opportunity_number="temple_pages:o",
                    title="SYNTHETIC Quill Award", agency="OVPR", source="temple_pages",
                    source_url="https://x.example/o", fetched_at=T, page_owner="OVPR")
    assert len(dedupe([a, b, o])[0]) == 3


def test_scope_rules():
    cases = [
        ("CST", "CST", "school"),
        ("CST", "CEHD", "temple_wide"),
        ("CPH", "CPH (Social Work)", "school"),  # one school under two owner names
        ("CST", "SDFA", "temple_wide"),
        ("Education Abroad", "Education Abroad", "temple_wide"),
        ("Temple Rome", "Temple Rome", None),  # not a school or a university office: no guess
    ]
    for o1, o2, want in cases:
        a = sch("temple_pages:a", "SYNTHETIC Quill Award", o1, "https://x.example/1")
        b = sch("temple_pages:b", "SYNTHETIC Quill Award", o2, "https://x.example/2")
        (r,) = dedupe([a, b])[0]
        assert r.scope == want, (o1, o2)


def test_single_university_office_page_is_temple_wide_with_no_school():
    (r,) = dedupe([sch("temple_pages:a", "SYNTHETIC Quill Award", "SDFA",
                       "https://x.example/1")])[0]
    assert r.scope == "temple_wide" and r.schools == []
    assert [s.page_owner for s in r.seen_on] == ["SDFA"]


def test_same_id_reads_merge_and_disagreeing_fields_become_not_stated() -> None:
    from perch.temple_dedupe import dedupe
    recs = _same_id_pair()
    out, rep = dedupe(recs)
    assert len(out) == 1 and len(rep.blanked) == 1 and not rep.conflicts
    assert out[0].apply_url is None and "apply_url" not in out[0].field_quotes


def _same_id_pair():  # noqa: ANN202
    import json
    from pathlib import Path

    from perch.temple_dataset import parse_row
    line = next(x for x in Path("data/temple/pilot_s39.jsonl").read_text("utf-8").splitlines()
                if '"apply_url": "http' in x)
    a = parse_row(line)
    d = json.loads(a.model_dump_json())
    d["apply_url"] = "https://example.org/other-form"
    d["field_quotes"]["apply_url"] = "Apply at https://example.org/other-form today."
    b = type(a).model_validate(d)
    return [a, b]


def test_two_titles_sharing_a_cut_id_stay_two_records() -> None:
    from perch.temple_dedupe import dedupe
    a, b = _same_id_pair()
    b = b.model_copy(update={"name": a.name + " for Prospective Students", "apply_url": None})
    out, _ = dedupe([a, b])
    assert len(out) == 2 and len({r.id for r in out}) == 2
