"""Versioned Temple dataset: build, manifest, load. SYNTHETIC records, no network."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from perch import temple_dataset as td
from perch.cli import main
from perch.schemas import Opportunity, Scholarship
from perch.store.sqlite import SQLiteRepository
from tests.test_temple_dedupe import T, sch


def _extracted(path: Path, recs) -> Path:
    path.write_text("".join(td.row_json(r) + "\n" for r in recs), encoding="utf-8")
    path.with_name(path.name + ".pages").write_text("".join(
        json.dumps({"url": u, "records": 1, "model": "fake-1"}) + "\n"
        for u in sorted({r.source_url for r in recs})))
    return path


@pytest.fixture
def extracted(tmp_path):
    recs = [
        sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/cst",
            amount=2500),
        sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/cehd",
            deadline=date(2027, 3, 1)),
        sch("temple_pages:c", "SYNTHETIC Harbor Prize", "Fox School of Business",
            "https://x.example/fox"),
        Opportunity(id="temple_pages:o", opportunity_number="temple_pages:o",
                    title="SYNTHETIC Seed Grant", agency="OVPR", source="temple_pages",
                    source_url="https://x.example/ovpr", fetched_at=T, page_owner="OVPR"),
    ]
    return _extracted(tmp_path / "extracted.jsonl", recs)


def test_build_writes_a_dataset_and_manifest(tmp_path, extracted):
    path, man, rep = td.build_dataset(extracted, tmp_path / "ds", commit="abc123",
                                      now=datetime(2026, 11, 5, tzinfo=UTC))
    assert path.name == "temple_awards_v1.jsonl"
    assert man["version"] == 1 and man["records"] == 3 and man["input_records"] == 4
    assert man["input_pages"] == 4 and man["merged_groups"] == 1
    assert man["by_kind"] == {"opportunity": 1, "scholarship": 2}
    assert man["by_scope"]["temple_wide"] == 2 and man["by_scope"]["school"] == 1
    assert man["by_school"]["CST"] == 1 and man["by_school"]["CEHD"] == 1
    assert man["sha256"] == td.sha256_file(path)
    assert man["extraction_model"] == "fake-1" and man["code_commit"] == "abc123"
    assert json.loads(td.manifest_path(path).read_text()) == man
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    for r in rows:  # rule 4: provenance on every row
        assert r["source"] == "temple_pages" and r["source_url"] and r["fetched_at"]
        assert r["seen_on"]


def test_output_is_deterministic_and_versions_increase(tmp_path, extracted):
    p1, m1, _ = td.build_dataset(extracted, tmp_path / "d1", commit="c",
                                 now=datetime(2026, 11, 5, tzinfo=UTC))
    p2, m2, _ = td.build_dataset(extracted, tmp_path / "d2", commit="c",
                                 now=datetime(2026, 12, 9, tzinfo=UTC))
    assert p1.read_bytes() == p2.read_bytes() and m1["sha256"] == m2["sha256"]
    p3, m3, _ = td.build_dataset(extracted, tmp_path / "d1", commit="c")
    assert p3.name == "temple_awards_v2.jsonl" and m3["version"] == 2
    with pytest.raises(td.DatasetError):
        td.build_dataset(extracted, tmp_path / "d1", version=1)


def test_conflicting_pairs_are_written_beside_the_dataset(tmp_path):
    ex = _extracted(tmp_path / "e.jsonl", [
        sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/1", amount=1000),
        sch("temple_pages:b", "SYNTHETIC Quill Award", "CEHD", "https://x.example/2",
            amount=2000)])
    path, man, _ = td.build_dataset(ex, tmp_path / "ds", commit="c")
    assert man["records"] == 2 and man["conflicting_pairs"] == 1
    (c,) = [json.loads(x) for x in path.with_suffix(".conflicts.jsonl").read_text().splitlines()]
    assert c["fields"] == ["amount"]


def test_sample_and_foreign_rows_are_refused(tmp_path):
    s = Scholarship(id="sample:sch-0001", name="SYNTHETIC X", source="synthetic",
                    source_url="https://example.invalid/s", fetched_at=T, canary="CANARY")
    bad = tmp_path / "bad.jsonl"
    bad.write_text(td.row_json(s) + "\n")
    with pytest.raises(td.DatasetError):
        td.read_records(bad)
    other = Scholarship(id="temple:1", name="SYNTHETIC Y", source="temple_sdfa",
                        source_url="https://example.invalid/s", fetched_at=T)
    bad.write_text(td.row_json(other) + "\n")
    with pytest.raises(td.DatasetError):
        td.read_records(bad)


def test_load_into_sqlite_is_idempotent(tmp_path, extracted):
    path, _, _ = td.build_dataset(extracted, tmp_path / "ds", commit="c")
    with SQLiteRepository(tmp_path / "s.db") as repo:
        assert td.load_dataset(path, repo) == 3
        first = repo.list(Scholarship) + repo.list(Opportunity)
        assert td.load_dataset(path, repo) == 3
        again = repo.list(Scholarship) + repo.list(Opportunity)
        assert len(first) == 3 and first == again
        quill = next(r for r in first if getattr(r, "name", "") == "SYNTHETIC Quill Award")
        assert quill.source == "temple_pages" and len(quill.seen_on) == 2


def test_load_refuses_a_file_that_does_not_match_its_manifest(tmp_path, extracted):
    path, _, _ = td.build_dataset(extracted, tmp_path / "ds", commit="c")
    path.write_text(path.read_text() + "\n")
    with SQLiteRepository(tmp_path / "s.db") as repo, pytest.raises(td.DatasetError):
        td.load_dataset(path, repo)


def test_cli_build_and_load(tmp_path, extracted, capsys):
    out = tmp_path / "ds"
    assert main(["temple", "build-dataset", "--input", str(extracted),
                 "--out-dir", str(out)]) == 0
    f = out / "temple_awards_v1.jsonl"
    db = tmp_path / "cli.db"
    assert main(["--db", str(db), "temple", "load-dataset", str(f)]) == 0
    assert "Loaded 3 records" in capsys.readouterr().out
    assert main(["--db", str(db), "temple", "load-dataset", str(tmp_path / "none")]) == 1
