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


def grants_factory():
    import json
    from pathlib import Path

    import httpx

    from perch.sources import grants_gov

    fix = Path(__file__).parent / "fixtures" / "grants_gov"
    search = json.loads((fix / "search2_nih_posted.json").read_text())
    detail = json.loads((fix / "fetch_opportunity.json").read_text())
    archived = json.loads((fix / "fetch_opportunity_archived.json").read_text())

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/search2"):
            if body.get("oppNum") == "PA-11-260":
                hit = {"id": archived["data"]["id"], "number": "PA-11-260", "oppStatus": "archived"}
                return httpx.Response(200, json={"errorcode": 0, "data": {"hitCount": 1,
                                                                         "oppHits": [hit]}})
            return httpx.Response(200, json=search)
        if body["opportunityId"] == int(archived["data"]["id"]):
            return httpx.Response(200, json=archived)
        return httpx.Response(200, json=detail)

    t = httpx.MockTransport(handler)
    return lambda: grants_gov.GrantsGovClient(transport=t, min_interval=0)


def test_fetch_opportunities_upserts_by_number(tmp_path, capsys):
    from perch.schemas import Opportunity

    db = str(tmp_path / "p.db")
    g = grants_factory()
    argv = ["--db", db, "fetch", "opportunities", "--agencies", "HHS-NIH11", "--limit", "2"]
    assert cli.main(argv, factory, grants_factory=g) == 0
    out = capsys.readouterr().out
    # the mock returns the same detail record for both hits, so one number, seen twice
    assert "1 new, 0 changed, 1 unchanged; 1 opportunities" in out
    assert "not endorsed or certified" in out
    assert cli.main(argv, factory, grants_factory=g) == 0
    assert "0 new, 0 changed, 2 unchanged" in capsys.readouterr().out
    assert cli.main(["--db", db, "fetch", "opportunities", "--opp-num", "PA-11-260"], factory,
                    grants_factory=g) == 0
    assert "1 new" in capsys.readouterr().out
    with SQLiteRepository(db) as repo:
        got = repo.get(Opportunity, "grants_gov:PA-11-260")
        assert got.status == "archived" and got.source_url.startswith("https://www.grants.gov/")


def test_brief_route_a_with_fake_models(tmp_path, capsys):
    db = str(tmp_path / "p.db")
    common = ["--db", db]
    assert cli.main([*common, "fetch", "openalex", "A5026494099"], factory) == 0
    assert cli.main([*common, "fetch", "opportunities", "--agencies", "HHS-NIH11", "--limit", "2"],
                    factory, grants_factory=grants_factory()) == 0
    capsys.readouterr()
    argv = [*common, "brief", "A5026494099", "--models", "fake", "--as-of", "2026-10-28"]
    assert cli.main(argv, factory) == 0
    out = capsys.readouterr().out
    assert "1 retrieved, 0 ineligible removed, top 1 after rerank" in out
    assert "PAR-25-268" in out and "award ceiling not stated in the record" in out
    assert "Timings (ms): threads" in out and "not endorsed or certified" in out
    assert (tmp_path / "logs" / "brief_timings.jsonl").read_text().count("\n") == 1
    late = [*common, "brief", "A5026494099", "--models", "fake", "--as-of", "2027-01-01"]
    assert cli.main(late, factory) == 0
    assert "1 ineligible removed, top 0" in capsys.readouterr().out  # closed by then
