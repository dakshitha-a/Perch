"""Hand-check tool: draw, sheet and score. SYNTHETIC page and records, no model."""

import csv
import json

from bench import handcheck_temple as hc
from perch import temple_dataset as td
from perch import temple_extract as te
from perch.llm.fake import FakeProvider
from tests.test_temple_extract import META, PAGE, URL, award, idx


def _dataset(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "p.html").write_text(PAGE)
    (cache / "manifest.jsonl").write_text(json.dumps({**META, "file": "p.html"}) + "\n")
    reply = json.dumps({"awards": [award(
        "The Quill Family Memorial Scholarship", amount_text="$2,500",
        amount_sentence=idx("pays $2,500"), link="https://apply.example/quill",
        link_sentence=idx("Apply at"))]})
    recs, _, _ = te.extract_page(FakeProvider(replies=[reply]), META, PAGE)
    ex = tmp_path / "e.jsonl"
    ex.write_text("".join(td.row_json(r) + "\n" for r in recs))
    path, _, _ = td.build_dataset(ex, tmp_path / "ds", commit="c")
    return path, cache


def test_draw_is_seeded_sized_and_sorted():
    class R:
        def __init__(self, i):
            self.id = f"r{i:03d}"
    recs = [R(i) for i in range(50)]
    a, b = hc.draw(recs, 0.1, seed=3), hc.draw(recs, 0.1, seed=3)
    assert [r.id for r in a] == [r.id for r in b] and len(a) == 5
    assert [r.id for r in a] == sorted(r.id for r in a)
    assert [r.id for r in a] != [r.id for r in hc.draw(recs, 0.1, seed=4)]
    assert len(hc.draw(recs[:3], 0.1)) == 1 and hc.draw([], 0.1) == []


def test_sheet_has_a_row_per_field_with_the_quote_and_page_sentence(tmp_path, capsys):
    path, cache = _dataset(tmp_path)
    sheet, n, total = hc.make_sheet(path, cache, tmp_path / "out", 0.1, 1)
    assert (n, total) == (1, 1)
    rows = list(csv.DictReader(sheet.open()))
    assert [r["field"] for r in rows] == list(hc.FIELDS) and list(rows[0]) == hc.COLUMNS
    amount = next(r for r in rows if r["field"] == "amount")
    assert amount["kept_value"] == "min 2500.0 max 2500.0"
    assert "$2,500" in amount["quoted_sentence"] and "$2,500" in amount["page_sentence"]
    link = next(r for r in rows if r["field"] == "apply_url")
    assert link["kept_value"] == "https://apply.example/quill" and link["page_sentence"]
    assert all(r["verdict"] == "" for r in rows)  # the reviewer fills these
    assert URL in capsys.readouterr().out


def test_score_counts_errors_per_field_with_a_wilson_interval(tmp_path):
    sheet = tmp_path / "s.csv"
    rows = [("title", "correct")] * 8 + [("title", "wrong")] * 2 + [
        ("amount", "missing"), ("amount", "correct"), ("deadline", "")]
    with sheet.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=hc.COLUMNS)
        w.writeheader()
        for f, v in rows:
            w.writerow({"record_id": "r", "kind": "scholarship", "field": f, "verdict": v})
    lines, s = hc.score(sheet)
    t = s["fields"]["title"]
    assert (t["n"], t["errors"], t["rate"]) == (10, 2, 0.2)
    lo, hi = t["ci95"]
    assert abs(lo - 0.0567) < 0.001 and abs(hi - 0.5098) < 0.001
    assert s["fields"]["amount"]["missing"] == 1 and s["unreviewed"] == 1
    assert s["overall"]["n"] == 12 and s["overall"]["errors"] == 3
    assert any(x.startswith("overall") for x in lines)


def test_score_rejects_an_unknown_verdict(tmp_path):
    sheet = tmp_path / "s.csv"
    sheet.write_text("record_id,kind,field,verdict\nr,scholarship,title,maybe\n")
    import pytest
    with pytest.raises(ValueError):
        hc.score(sheet)
    assert hc.main(["--score", str(sheet)]) == 1
