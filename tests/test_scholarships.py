"""S17: the SYNTHETIC scholarship corpus, the student personas and the Temple listing."""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from perch import scholarships as S
from perch.schemas import Opportunity, Scholarship
from perch.sources import temple
from perch.store.sqlite import SQLiteRepository

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data/synthetic"
PERSONAS = ("persona-ug", "persona-masters", "persona-phd")


@pytest.fixture(scope="module")
def samples() -> list[Scholarship]:
    return S.read_samples()


def test_corpus_loads_into_its_own_store_under_source_synthetic(samples):
    assert 400 <= len(samples) <= 600
    repo = SQLiteRepository(":memory:")
    assert S.load_samples(repo) == len(samples)
    stored = repo.list(Scholarship)
    assert {s.source for s in stored} == {"synthetic"}
    assert all(re.fullmatch(r"sample:sch-\d{4}", s.id) for s in stored)
    assert all(s.canary and s.canary.startswith(S.CANARY_PREFIX) and s.canary in s.purpose
               for s in stored)
    assert len({s.canary for s in stored}) == len(stored)


def test_no_overlap_with_public_records(samples):
    """No sample id or source is used by a public record: fixtures, the Temple listing,
    and the local public store when there is one."""
    ids = {s.id for s in samples}
    public = temple.parse_listing((ROOT / "tests/fixtures/temple/sdfa_find_fellowship.html")
                                  .read_text("utf-8"))
    assert not ids & {p.id for p in public}
    assert all(not p.id.startswith("sample:") and p.source != "synthetic" for p in public)
    db = ROOT / "data/perch.db"
    if db.exists():
        import sqlite3

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n = con.execute("SELECT count(*) FROM records WHERE id LIKE 'sample:%' "
                        "OR source = 'synthetic'").fetchone()[0]
        assert n == 0


def test_corpus_is_internally_consistent(samples):
    made = date(2026, 10, 29)
    for s in samples:
        assert s.deadline and s.deadline > made
        assert s.amount_min is not None and s.amount_min <= s.amount_max
        assert s.level_of_study and s.award_type and s.application_requirements
        assert not s.eligibility.class_year or "bachelor's" in s.level_of_study
    levels = {lv for s in samples for lv in s.level_of_study}
    assert levels == {"high school", "associate", "bachelor's", "graduate", "professional"}
    assert {s.award_type for s in samples} == {"scholarship", "fellowship", "grant", "prize"}


def test_no_real_organisation_name_in_any_sample_sponsor(samples):
    repo = None
    if (ROOT / "data/perch.db").exists():
        repo = SQLiteRepository(ROOT / "data/perch.db")
    real = S.real_names(repo)
    # The guard list holds the well-known sponsors and the Temple page awards.
    assert {"Ford Foundation", "Fulbright", "Goldwater Scholarship"} <= real
    assert "Temple University" in real
    hits = {s.sponsor: S.name_hits(s.sponsor or "", real) for s in samples}
    assert {k: v for k, v in hits.items() if v} == {}
    # Full real names may not appear in an award name or purpose either.
    for s in samples:
        low = " ".join(S.tokens(f"{s.name} {s.purpose}"))
        assert not [r for r in real if len(r) > 6
                    and re.search(rf"\b{re.escape(' '.join(S.tokens(r)))}\b", low)], s.id


def test_name_check_catches_real_names():
    real = S.real_names()
    assert S.name_hits("Fulbright Learning Society", real)
    assert S.name_hits("Temple Education Trust", real)
    assert not S.name_hits("Quillmere Education Trust", real)


def test_model_text_never_carries_numbers_or_names():
    import importlib.util

    path = ROOT / "scripts/make_sample_scholarships.py"
    spec = importlib.util.spec_from_file_location("mk", path)
    mk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mk)
    assert mk.clean_purpose("Supports students who study rivers.") is not None
    for bad in ("Awards 5,000 to students.", "Due in March each year.", "Pays two terms.",
                "Backed by the Ford Foundation.", "Gives $ for books."):
        assert mk.clean_purpose(bad) is None, bad


def test_sdfa_listing_copies_names_levels_and_links():
    page = (ROOT / "tests/fixtures/temple/sdfa_find_fellowship.html").read_text("utf-8")
    recs = temple.parse_listing(page, datetime(2026, 10, 29, tzinfo=UTC))
    by = {r.name: r for r in recs}
    assert len(recs) == 76
    gw = by["Goldwater Scholarship"]
    assert gw.level_of_study == ["bachelor's"] and gw.eligibility.class_year == [1, 2, 3]
    assert gw.field_of_study == ["STEM"] and "campus nomination required" in gw.eligibility.notes
    assert by["NSF Graduate Research Fellowship Program"].level_of_study == [
        "bachelor's", "graduate"]
    assert all(r.source == "temple_sdfa" and r.amount_max is None and r.deadline is None
               and r.source_url.startswith("http") for r in recs)
    assert "Pivot" not in by  # a database, not an award


def test_temple_fixtures_hold_no_contact_details():
    for f in (ROOT / "tests/fixtures/temple").glob("*.html"):
        t = f.read_text("utf-8")
        assert "safelinks.protection" not in t
        assert not re.search(r"[\w.+-]+(@|%40)temple\.edu", t), f.name


def test_nih_fellowships_are_f_series_only():
    at = datetime(2026, 10, 29, tzinfo=UTC)
    repo = SQLiteRepository(":memory:")
    repo.upsert([Opportunity(id=f"o{c}", source="grants_gov", source_url="u", fetched_at=at,
                             opportunity_number=f"PA-{c}", title=f"SYNTHETIC ({c})",
                             agency="NIH", activity_code=c)
                 for c in ("F31", "F32", "K99", "T32", "R01")])
    assert [o.activity_code for o in S.nih_fellowships(repo)] == ["F31", "F32"]


@pytest.mark.parametrize("name", PERSONAS)
def test_persona_files_are_labelled_and_keyed(name, samples):
    folder = SYN / name
    files = sorted(folder.iterdir())
    assert {f.name for f in files} == {"cv.md", "interests.md", "achievements.md",
                                       "answer_key.json"}
    canaries = [re.search(r"PERCH-CANARY-[A-Z0-9-]+", f.read_text("utf-8")) for f in files]
    assert all(canaries) and len({c.group(0) for c in canaries}) == 4
    for f in files:
        if f.suffix == ".md":
            assert "SYNTHETIC" in f.read_text("utf-8").splitlines()[0]
    key = json.loads((folder / "answer_key.json").read_text("utf-8"))
    by = {s.id: s for s in samples}
    assert len(key["cases"]) == 8
    verdicts = {c["verdict"] for c in key["cases"]}
    assert verdicts == {"eligible", "may be eligible", "not eligible"}
    for c in key["cases"]:
        assert c["id"] in by and int(c["id"][-4:]) <= 24  # planted, hand-written records
        assert (c["verdict"] == "not eligible") == (c["reason"] in {
            "deadline", "level", "class_year", "graduation", "major", "gpa", "enrolment"})
