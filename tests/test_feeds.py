"""Feed seam: Importer protocol, CSV, JSON, dataset and ScholarshipUniverse. SYNTHETIC files."""

import json
from datetime import UTC, date, datetime

import pytest

from perch import temple_dataset as td
from perch.feeds import CsvImporter, DatasetImporter, Importer, JsonImporter
from perch.schemas import Opportunity, Scholarship
from perch.sources.scholarshipuniverse import ScholarshipUniverseImporter
from tests.test_temple_dedupe import sch

NOW = datetime(2026, 11, 5, tzinfo=UTC)
HEADER = "name,source_url,amount_min,amount_max,deadline,level_of_study,schools,colour\n"


def test_all_importers_conform_to_the_protocol(tmp_path):
    assert isinstance(CsvImporter(tmp_path / "x.csv"), Importer)
    assert isinstance(JsonImporter(tmp_path / "x.json"), Importer)
    assert isinstance(DatasetImporter(tmp_path / "x.jsonl"), Importer)
    assert isinstance(ScholarshipUniverseImporter(), Importer)


def test_csv_maps_columns_ignores_unknown_and_rejects_rows_without_a_source_url(tmp_path):
    f = tmp_path / "feed.csv"
    f.write_text(
        HEADER
        + "SYNTHETIC Quill Award,https://feed.example/q,\"1,000\",2500,2027-03-01,"
          "bachelor's;graduate,CST;CEHD,blue\n"
        + "SYNTHETIC No Link,,500,500,,,,\n"
        + "SYNTHETIC Bad Number,https://feed.example/b,abc,,,,,\n"
        + "SYNTHETIC Backwards,https://feed.example/c,900,100,,,,\n")
    imp = CsvImporter(f, source="synthetic_feed", now=NOW)
    (r,) = imp.read()
    assert isinstance(r, Scholarship) and r.source == "synthetic_feed"
    assert (r.amount_min, r.amount_max, r.deadline) == (1000, 2500, date(2027, 3, 1))
    assert r.level_of_study == ["bachelor's", "graduate"] and r.schools == ["CST", "CEHD"]
    assert r.source_url == "https://feed.example/q" and r.fetched_at == NOW
    assert imp.ignored_columns == ["colour"]
    reasons = dict(imp.rejected)
    assert sorted(reasons) == [2, 3, 4]
    assert "source_url" in reasons[2] and "rule 4" in reasons[2]


def test_json_array_and_records_object_and_opportunity_kind(tmp_path):
    rows = [{"title": "SYNTHETIC Seed Grant", "agency": "SYNTHETIC Office",
             "source_url": "https://feed.example/s", "close_date": "2027-05-05",
             "award_ceiling": 10000, "temple_funded": "yes", "extra": 1}]
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(rows))
    b.write_text(json.dumps({"records": rows}))
    for f in (a, b):
        imp = JsonImporter(f, kind="opportunity", now=NOW)
        (r,) = imp.read()
        assert isinstance(r, Opportunity) and r.award_ceiling == 10000
        assert r.temple_funded is True and r.opportunity_number == r.id
        assert imp.ignored_columns == ["extra"]


def test_ids_are_stable_across_reads(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps([{"name": "SYNTHETIC Quill", "source_url": "https://feed.example/q"}]))
    assert JsonImporter(f).read()[0].id == JsonImporter(f).read()[0].id


def test_sample_rows_are_never_imported(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps([
        {"name": "SYNTHETIC A", "source_url": "https://feed.example/a", "id": "sample:sch-0001"},
        {"name": "SYNTHETIC B", "source_url": "https://feed.example/b", "source": "synthetic"}]))
    imp = JsonImporter(f)
    assert imp.read() == [] and len(imp.rejected) == 2
    assert all("rule 11" in why for _, why in imp.rejected)


def test_dataset_importer_reads_and_checks_the_manifest(tmp_path):
    ex = tmp_path / "e.jsonl"
    ex.write_text(td.row_json(sch("temple_pages:a", "SYNTHETIC Quill", "CST",
                                  "https://x.example/1", amount=1000)) + "\n")
    path, _, _ = td.build_dataset(ex, tmp_path / "ds", commit="c")
    (r,) = DatasetImporter(path).read()
    assert r.source == "temple_pages" and r.amount_max == 1000
    path.write_text(path.read_text() + "\n")
    with pytest.raises(td.DatasetError):
        DatasetImporter(path).read()


def test_scholarshipuniverse_behaviour_is_unchanged():
    assert ScholarshipUniverseImporter().read() == []
    with pytest.raises(NotImplementedError):
        ScholarshipUniverseImporter([{"x": 1}]).read()
