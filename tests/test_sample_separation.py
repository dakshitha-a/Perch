"""Rule 11: SYNTHETIC samples and public temple_pages records never share a list.

Complements tests/test_student.py (API and student leads), tests/test_export.py (exports) and
tests/test_store.py (list and browse). All records here are SYNTHETIC.
"""

import json
import re
from pathlib import Path

from perch import scholarships as S
from perch import temple_dataset as td
from perch.schemas import Scholarship
from perch.store.sqlite import SQLiteRepository
from tests.test_temple_dedupe import sch

ROOT = Path(__file__).resolve().parents[1]


def _sample():
    return S.read_samples()[0]


def test_a_store_holding_both_never_lists_them_together():
    with SQLiteRepository() as repo:
        repo.upsert([sch("temple_pages:a", "SYNTHETIC Quill Award", "CST", "https://x.example/1"),
                     _sample()])
        public = repo.list(Scholarship)
        assert [r.source for r in public] == ["temple_pages"]
        assert [r.source for r in repo.browse(Scholarship).items] == ["temple_pages"]
        assert repo.browse(Scholarship, schools=["CST"]).items == public
        assert {r.source for r in repo.list(Scholarship, include_samples=True)} == {
            "temple_pages", "synthetic"}


def test_the_sample_corpus_shares_no_id_or_source_with_the_temple_dataset(tmp_path):
    ex = tmp_path / "e.jsonl"
    ex.write_text(td.row_json(sch("temple_pages:a", "SYNTHETIC Quill", "CST",
                                  "https://x.example/1")) + "\n")
    path, _, _ = td.build_dataset(ex, tmp_path / "ds", commit="c")
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    sample_ids = {s.id for s in S.read_samples()}
    assert not sample_ids & {r["id"] for r in rows}
    assert all(r["source"] == "temple_pages" and not r["id"].startswith("sample:")
               for r in rows)
    assert all(s.source == "synthetic" and s.id.startswith("sample:") for s in S.read_samples())


def test_dataset_and_feed_code_never_opens_the_sample_store():
    pat = re.compile(r"\b(sample_records|ensure_samples|read_samples|load_samples|"
                     r"SAMPLE_JSONL|sample_db)\b")
    files = [ROOT / "perch/temple_dataset.py", ROOT / "perch/temple_dedupe.py",
             ROOT / "perch/temple_extract.py", *sorted((ROOT / "perch/feeds").glob("*.py"))]
    assert files and not [f.name for f in files if pat.search(f.read_text("utf-8"))]
