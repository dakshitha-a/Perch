from perch import cli
from perch.schemas import Researcher, Work
from perch.sources import openalex as oa
from perch.store.sqlite import SQLiteRepository

from .test_openalex import AUTHOR, fixture_transport


def factory():
    return oa.OpenAlexClient(transport=fixture_transport([]), min_interval=0)


def test_resolve_by_name_lists_and_stores_candidates(tmp_path, capsys):
    db = tmp_path / "p.db"
    assert cli.main(["--db", str(db), "resolve", "Axel Kohlmeyer"], factory) == 0
    out = capsys.readouterr().out
    assert "A5026494099  Axel Kohlmeyer" in out and "Temple University" in out
    with SQLiteRepository(db) as repo:
        assert repo.get(Researcher, AUTHOR) is not None


def test_resolve_by_orcid(tmp_path, capsys):
    assert cli.main(["--db", str(tmp_path / "p.db"), "resolve", "0000-0001-6204-6475"],
                    factory) == 0
    assert "1 candidate(s)" in capsys.readouterr().out


def test_fetch_stores_works_with_provenance(tmp_path, capsys):
    db = tmp_path / "p.db"
    assert cli.main(["--db", str(db), "fetch", "openalex", "A5026494099"], factory) == 0
    assert "Fetched 5 works" in capsys.readouterr().out
    with SQLiteRepository(db) as repo:
        works = repo.works_by_author(AUTHOR)
        assert len(works) == 5
        assert all(w.source == "openalex" and w.source_url and w.fetched_at for w in works)
        assert len(repo.list(Work)) == 5


def test_unknown_source(tmp_path):
    assert cli.main(["--db", str(tmp_path / "p.db"), "fetch", "nsf", "A1"], factory) == 2


def award_factories():
    import json
    from pathlib import Path

    import httpx

    from perch.sources import nih_reporter, nsf

    fix = Path(__file__).parent / "fixtures"
    nih_page = json.loads((fix / "nih_reporter/projects_search_pi.json").read_text())
    nsf_page = json.loads((fix / "nsf/awards_copi.json").read_text())
    nih_t = httpx.MockTransport(lambda r: httpx.Response(200, json=nih_page))
    nsf_t = httpx.MockTransport(lambda r: httpx.Response(200, json=nsf_page))
    return (lambda: nih_reporter.NIHReporterClient(transport=nih_t, min_interval=0),
            lambda: nsf.NSFClient(transport=nsf_t, min_interval=0))


def test_fetch_awards_and_profile_horizon(tmp_path, capsys):
    db, ov = str(tmp_path / "p.db"), str(tmp_path / "none.csv")
    nih_f, nsf_f = award_factories()
    common = ["--db", db, "--overrides", ov]
    assert cli.main([*common, "fetch", "openalex", "A5026494099"], factory) == 0
    assert cli.main([*common, "fetch", "awards", "A5026494099"], factory, nih_f, nsf_f) == 0
    assert "1 linked by name (1 awards)" in capsys.readouterr().out  # NIH records are another PI
    assert cli.main([*common, "profile", "A5026494099"], factory) == 0
    out = capsys.readouterr().out
    assert "Public federal awards (1)" in out
    assert "Public award horizon: 2016-06-30 (end of 1212416" in out
    assert "says nothing about lab finances" in out


def test_profile_needs_store(tmp_path, capsys):
    assert cli.main(["--db", str(tmp_path / "p.db"), "profile", "A1"], factory) == 1
