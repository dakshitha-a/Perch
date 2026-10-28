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
    assert "Fetched 7 works" in capsys.readouterr().out
    with SQLiteRepository(db) as repo:
        works = repo.works_by_author(AUTHOR)
        assert len(works) == 5  # 7 fetched across two pages; 2 repeat and are upserted
        assert all(w.source == "openalex" and w.source_url and w.fetched_at for w in works)
        assert len(repo.list(Work)) == 5


def test_unknown_source(tmp_path):
    assert cli.main(["--db", str(tmp_path / "p.db"), "fetch", "nsf", "A1"], factory) == 2
