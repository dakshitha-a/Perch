"""The SOURCES.md table of Temple pages is generated and stays in step with the inventory."""

import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gen_temple_sources",
                                              ROOT / "scripts/gen_temple_sources.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

HEAD = ["url", "owner", "audience", "kind", "http_status", "robots_allowed",
        "sign_in_required", "approx_awards_on_page", "states_amounts", "states_deadlines",
        "fetched_at", "notes"]


def _inv(path, rows):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEAD)
        w.writeheader()
        for r in rows:
            w.writerow({**dict.fromkeys(HEAD, ""), **r})


def test_table_lists_every_page_with_fetched_and_skipped_reasons(tmp_path):
    inv, doc, cache = tmp_path / "inv.csv", tmp_path / "S.md", tmp_path / "cache"
    cache.mkdir()
    _inv(inv, [
        {"url": "https://a.example/ok", "owner": "CST", "http_status": "200",
         "robots_allowed": "yes", "sign_in_required": "no"},
        {"url": "https://a.example/map", "owner": "CST", "robots_allowed": "yes",
         "sign_in_required": "no"},
        {"url": "https://a.example/login", "owner": "SDFA", "sign_in_required": "yes"},
        {"url": "https://a.example/bad", "owner": "CEHD", "http_status": "200",
         "robots_allowed": "yes", "sign_in_required": "no"}])
    (cache / "manifest.jsonl").write_text(json.dumps(
        {"url": "https://a.example/ok", "fetched_at": "2026-11-04T06:00:00+00:00"}) + "\n")
    doc.write_text("# Sources\n\nintro\n")
    argv = ["--inventory", str(inv), "--doc", str(doc), "--cache-dir", str(cache)]
    assert gen.main(argv) == 0
    text = doc.read_text()
    assert "| https://a.example/ok | CST | fetched 2026-11-04 |" in text
    assert "| https://a.example/map | CST | skipped: the inventory has no http 200" in text
    assert "| https://a.example/login | SDFA | skipped: needs sign-in" in text
    assert "| https://a.example/bad | CEHD | eligible, not fetched (failed) |" in text
    assert "4 inventoried pages; 1 fetched" in text
    assert gen.main(argv) == 0 and doc.read_text() == text  # idempotent, replaces in place
    assert gen.main(["--check", "--inventory", str(inv), "--doc", str(doc)]) == 0
    _inv(inv, [{"url": "https://a.example/new", "owner": "CST"}])
    assert gen.main(["--check", "--inventory", str(inv), "--doc", str(doc)]) == 1


def test_committed_sources_table_matches_the_committed_inventory():
    doc = (ROOT / "docs/SOURCES.md").read_text("utf-8")
    inv = list(csv.DictReader((ROOT / "data/temple/inventory.csv").open()))
    assert gen.table_rows(doc) == {(gen._cell(r["url"]), gen._cell(r["owner"])) for r in inv}
