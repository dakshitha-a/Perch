"""API end to end with fake models and fixture-backed clients (no network, no GPU)."""

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from perch.api import create_app
from perch.jobs import InlineRunner
from perch.service import BriefService, Clients, default_models
from perch.sources import grants_gov, nih_reporter, nsf
from perch.sources import openalex as oa
from perch.store.sqlite import SQLiteRepository

from .test_openalex import NAME, fixture_transport

FIX = Path(__file__).parent / "fixtures"


def json_transport(payload):
    return httpx.MockTransport(lambda r: httpx.Response(200, json=payload))


def make(tmp_path):
    db = tmp_path / "perch.db"
    with grants_gov.GrantsGovClient(
            transport=json_transport(json.loads((FIX / "grants_gov/fetch_opportunity.json")
                                                .read_text())), min_interval=0) as g:
        opp = g.fetch(357303, "posted")
    with SQLiteRepository(db) as r:
        r.upsert([opp])
    clients = Clients(
        openalex=lambda: oa.OpenAlexClient(transport=fixture_transport([]), min_interval=0),
        nih=lambda: nih_reporter.NIHReporterClient(
            transport=json_transport(json.loads((FIX / "nih_reporter/projects_search_pi.json")
                                                .read_text())), min_interval=0),
        nsf=lambda: nsf.NSFClient(transport=json_transport(json.loads(
            (FIX / "nsf/awards_copi.json").read_text())), min_interval=0))
    service = BriefService(db, default_models(fake=True, data_dir=tmp_path), clients,
                           overrides=tmp_path / "none.csv")
    return TestClient(create_app(service, InlineRunner())), service


def test_brief_end_to_end_reports_stages_and_leads(tmp_path):
    c, _ = make(tmp_path)
    r = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"})
    assert r.status_code == 202
    bid = r.json()["id"]
    got = c.get(f"/briefs/{bid}").json()
    b = got["brief"]
    assert b["status"] == "done", b["error"]
    assert [s["name"] for s in b["stages"]] == ["researcher", "works", "awards", "profile",
                                                "route_a", "route_b", "summary", "explanations"]
    assert all(s["status"] in ("done", "skipped") for s in b["stages"])
    assert b["stages"][1]["detail"] == "5 works fetched from OpenAlex"
    assert b["award_horizon"] == "2016-06-30"
    assert len(got["leads"]) == 1 and got["leads"][0]["opportunity"]["opportunity_number"] \
        == "PAR-25-268"
    assert got["leads"][0]["flagged"] is True  # the fake LLM returns nothing usable
    assert "not endorsed or certified" in got["notice"]
    assert b["source"] == "perch" and b["source_url"] == f"perch://briefs/{bid}"


def test_keep_dismiss_export_records_and_errors(tmp_path):
    c, _ = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    b = c.get(f"/briefs/{bid}").json()["brief"]
    assert b["stages"][-1]["status"] == "skipped"
    lead_id = b["lead_ids"][0]
    assert c.post(f"/briefs/{bid}/leads/{lead_id}/keep").json()["status"] == "kept"
    assert c.post(f"/briefs/{bid}/leads/{lead_id}/dismiss").json()["status"] == "dismissed"
    assert c.post(f"/briefs/{bid}/leads/nope/keep").status_code == 404
    exp = c.get(f"/briefs/{bid}/export.json").json()
    kinds = {x["kind"] for x in exp["records"]}
    assert {"researcher", "opportunity"} <= kinds
    assert all(x["source"] and x["source_url"] and x["fetched_at"] for x in exp["records"])
    assert c.get(f"/briefs/{bid}/export.json", params={"status": "kept"}).json()["leads"] == []
    c.post(f"/briefs/{bid}/leads/{lead_id}/keep")
    kept = c.get(f"/briefs/{bid}/export.json", params={"status": "kept"}).json()
    assert [x["id"] for x in kept["leads"]] == [lead_id]
    assert any(x["kind"] == "opportunity" for x in kept["records"])
    assert c.get("/records/A5026494099").json()["kind"] == "researcher"
    assert c.get("/records/PAR-25-268").json()["kind"] == "opportunity"
    assert c.get("/records/nothing").status_code == 404
    assert c.get("/briefs/missing").status_code == 404
    assert c.post("/briefs", json={"author_id": "Jane Doe"}).status_code == 422


def test_resolve_candidates(tmp_path):
    c, _ = make(tmp_path)
    cands = c.get("/authors/resolve", params={"q": NAME}).json()["candidates"]
    assert [x["id"] for x in cands] == ["https://openalex.org/A5026494099"]


def test_failed_stage_is_recorded(tmp_path):
    c, service = make(tmp_path)

    def boom():
        raise RuntimeError("OpenAlex unreachable")

    service.clients.openalex = boom
    bid = c.post("/briefs", json={"author_id": "A5000000001"}).json()["id"]
    b = c.get(f"/briefs/{bid}").json()["brief"]
    assert b["status"] == "failed" and "OpenAlex unreachable" in b["error"]
    assert b["stages"][0]["status"] == "failed"


def test_a_finished_brief_is_reused_with_fresh_lead_state(tmp_path):
    c, _ = make(tmp_path)
    req = {"author_id": "A5026494099", "as_of": "2026-10-28"}
    first = c.post("/briefs", json=req).json()["id"]
    lead = c.get(f"/briefs/{first}").json()["leads"][0]["id"]
    c.post(f"/briefs/{first}/leads/{lead}/keep")
    r = c.post("/briefs", json=req)
    assert r.status_code == 200 and r.json()["reused"] is True
    again = c.get(f"/briefs/{r.json()['id']}").json()
    assert again["brief"]["status"] == "done" and r.json()["id"] != first
    assert [x["status"] for x in again["leads"]] == ["new"]  # the first visitor's keep stays
    assert c.post("/briefs", json={**req, "top": 5}).status_code == 202  # other options: new


def test_a_brief_from_older_code_is_not_reused(tmp_path):
    from perch.schemas import Brief

    c, service = make(tmp_path)
    req = {"author_id": "A5026494099", "as_of": "2026-10-28"}
    first = c.post("/briefs", json=req).json()["id"]
    with service.repo() as r:  # as built before S11: no route_b stage
        b = r.get(Brief, first)
        r.upsert([b.model_copy(update={"stages": [x for x in b.stages if x.name != "route_b"]})])
    assert c.post("/briefs", json=req).status_code == 202


def test_rate_limit_counts_new_briefs_per_forwarded_visitor(tmp_path, monkeypatch):
    monkeypatch.setenv("PERCH_BRIEFS_PER_HOUR", "2")
    monkeypatch.setenv("PERCH_BRIEF_REUSE_HOURS", "0")
    c, _ = make(tmp_path)
    c = TestClient(c.app, client=("127.0.0.1", 50000))  # as the tunnel's local proxy
    req = {"author_id": "A5026494099", "as_of": "2026-10-28"}
    one = {"x-forwarded-for": "198.51.100.7"}
    assert [c.post("/briefs", json=req, headers=one).status_code for _ in range(3)] == \
        [202, 202, 429]
    r = c.post("/briefs", json=req, headers=one)
    assert "2 new briefs an hour" in r.json()["detail"] and int(r.headers["retry-after"]) > 0
    assert c.post("/briefs", json=req, headers={"x-forwarded-for": "198.51.100.8"}) \
        .status_code == 202


def test_rate_limiter_window_slides():
    from perch.api import RateLimiter

    t = [0.0]
    lim = RateLimiter(1, clock=lambda: t[0])
    assert lim.take("a") == 0 and lim.take("a") == 3601
    t[0] = 3600.5
    assert lim.take("a") == 0


def test_deep_health_names_each_model_service(tmp_path, monkeypatch):
    monkeypatch.setenv("PERCH_PROFILE", "deploy-2gpu")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("PERCH_CLEF_URL", "http://127.0.0.1:9")
    c, _ = make(tmp_path)
    assert c.get("/health").json() == {"status": "ok"}
    deep = c.get("/health?deep=true").json()
    assert deep["status"] == "degraded"
    assert deep["services"] == {"ollama": False, "clef": False}


def test_scout_session_over_the_api(tmp_path, monkeypatch):
    from perch.llm import ToolCall
    from perch.llm.fake import FakeProvider

    c, service = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    fake = FakeProvider([[ToolCall("c1", "get_record", {"id": "grants_gov:PAR-25-268"})],
                         "It closes 2026-11-17 [grants_gov:PAR-25-268].", "Thanks."])
    service.models.provider = lambda spec: fake
    r = c.post(f"/briefs/{bid}/scout", json={"question": "When does it close?"})
    assert r.status_code == 202
    s = r.json()
    assert s["status"] == "awaiting_approval" and s["mode"] == "ask" and not s["busy"]
    card = s["exchanges"][0]["cards"][0]
    assert card["tool"] == "get_record" and card["status"] == "proposed"
    s = c.post(f"/scout/{s['id']}/approve", json={"card_id": card["id"]}).json()
    x = s["exchanges"][0]
    assert x["status"] == "done" and x["answer"].startswith("It closes 2026-11-17")
    assert x["cards"][0]["status"] == "done" and "grants_gov:PAR-25-268" in x["cards"][0]["records"]
    s = c.post(f"/scout/{s['id']}/ask", json={"question": "Thanks"}).json()
    assert len(s["exchanges"]) == 2 and c.get(f"/scout/{s['id']}").json()["id"] == s["id"]
    assert c.post(f"/scout/{s['id']}/ask", json={"question": " "}).status_code == 422
    assert c.get("/scout/nope").status_code == 404
    assert c.post(f"/scout/{s['id']}/delete", json={}).status_code == 422
    assert c.post("/briefs/nope/scout", json={"question": "x"}).status_code == 404


def test_route_b_lead_carries_organisation_signals_and_records(tmp_path):
    """SYNTHETIC Route B records added to a finished brief."""
    from datetime import UTC, date, datetime

    from perch.schemas import Brief, Lead, Organisation, Signal, Work

    c, service = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"}).json()["id"]
    t = datetime(2026, 10, 29, tzinfo=UTC)
    org = Organisation(id="https://openalex.org/I1", source="openalex",
                       source_url="https://api.openalex.org/institutions/I1", fetched_at=t,
                       name="SYNTHETIC Co", type="company", aliases=["SYNTHETIC Co"])
    w = Work(id="https://openalex.org/W77", source="openalex", source_url="u", fetched_at=t,
             title="SYNTHETIC company paper", publication_date=date(2026, 1, 2))
    lead = Lead(id=f"{bid}:B1", source="openalex", source_url=org.source_url, fetched_at=t,
                brief_id=bid, route="B", record_id=org.id, rank=1, inferred=True,
                inference="Inferred from public signals; not verified.", cited_ids=["W1"],
                signals=[Signal(kind="citing_works", record_ids=[w.id], count=4,
                                latest=date(2026, 1, 2))])
    with service.repo() as r:
        b = r.get(Brief, bid)
        r.upsert([org, w, lead, b.model_copy(update={"lead_ids": [*b.lead_ids, lead.id]})])
    got = c.get(f"/briefs/{bid}").json()
    x = next(x for x in got["leads"] if x["route"] == "B")
    assert x["organisation"]["name"] == "SYNTHETIC Co"
    item = x["signal_items"][0]
    assert item["text"] == ("4 works with an author at SYNTHETIC Co cite 1 of your papers; the "
                            "newest was published 2026-01-02.")
    assert item["records"][0]["title"] == "SYNTHETIC company paper" and item["more"] == 3
    exported = c.get(f"/briefs/{bid}/export.json").json()
    assert w.id in {r["id"] for r in exported["records"]}


def test_compare_shows_kept_leads_with_a_record_behind_every_cell(tmp_path):
    from perch.schemas import Brief, Lead, Organisation, Signal

    c, service = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    assert c.get(f"/briefs/{bid}/compare").json()["rows"] == []
    a = c.get(f"/briefs/{bid}").json()["brief"]["lead_ids"][0]
    c.post(f"/briefs/{bid}/leads/{a}/keep")
    with service.repo() as r:  # a SYNTHETIC Route B lead, kept
        b = r.get(Brief, bid)
        org = Organisation(id="https://openalex.org/I1", source="openalex", source_url="u",
                           fetched_at=b.fetched_at, name="SYNTHETIC Co")
        lead = Lead(id=f"{bid}:B1", source="openalex", source_url="u", fetched_at=b.fetched_at,
                    brief_id=bid, route="B", record_id=org.id, rank=1, inferred=True,
                    status="kept", relationship="Collaboration", confidence="moderate",
                    signals=[Signal(kind="citing_works"), Signal(kind="topic_works")])
        r.upsert([org, lead, b.model_copy(update={"lead_ids": [*b.lead_ids, lead.id]})])
    got = c.get(f"/briefs/{bid}/compare").json()
    assert [x["key"] for x in got["columns"]] == ["money", "closes", "code", "kind",
                                                  "evidence", "office"]
    ra, rb = got["rows"]
    assert ra["route"] == "A" and ra["title"].startswith("PAR-25-268")
    assert ra["cells"]["office"]["text"] == "Research Development"
    assert ra["cells"]["closes"]["record_id"] == ra["record_id"]
    assert rb["title"] == "SYNTHETIC Co"
    assert rb["cells"]["money"]["text"] == "Not in the record"
    assert rb["cells"]["evidence"]["text"] == "2 kinds of public signal"
    assert "inferred" in rb["cells"]["evidence"]["note"]
    assert rb["cells"]["office"]["text"] == "Innovation and Technology Commercialization"
    assert len(c.get(f"/briefs/{bid}/compare", params={"status": "all"}).json()["rows"]) == 2
    assert c.get(f"/briefs/{bid}/compare", params={"status": "x"}).status_code == 422


def test_handoff_draft_is_returned_not_stored(tmp_path):
    c, service = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    a = c.get(f"/briefs/{bid}").json()["brief"]["lead_ids"][0]
    c.post(f"/briefs/{bid}/leads/{a}/keep")
    with service.repo() as r:
        before = len(r.list(__import__("perch.schemas", fromlist=["Lead"]).Lead))
    d = c.post(f"/briefs/{bid}/handoff", json={"office": "research_development"}).json()
    assert d["to"] == "" and d["office"]["name"] == "Research Development"
    assert d["office"]["url"].startswith("https://research.temple.edu/")
    assert d["lead_ids"] == [a] and "PAR-25-268" in d["body"]
    assert d["flagged"] is True  # the fake model returns nothing usable: code text only
    empty = c.post(f"/briefs/{bid}/handoff", json={"office": "technology_commercialization"})
    assert empty.json()["lead_ids"] == []
    assert c.post(f"/briefs/{bid}/handoff", json={"office": "dean"}).status_code == 422
    assert c.post("/briefs/nope/handoff", json={"office": "research_development"}) \
        .status_code == 404
    with service.repo() as r:
        assert len(r.list(__import__("perch.schemas", fromlist=["Lead"]).Lead)) == before


def test_markdown_and_print_exports_carry_records_and_the_notice(tmp_path):
    c, _ = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    a = c.get(f"/briefs/{bid}").json()["brief"]["lead_ids"][0]
    c.post(f"/briefs/{bid}/leads/{a}/keep")
    md = c.get(f"/briefs/{bid}/export.md")
    assert md.headers["content-type"].startswith("text/markdown")
    t = md.text
    assert t.startswith("# Perch brief: ") and "## Kept leads compared (1)" in t
    assert "PAR-25-268" in t and "(kept)" in t and "not endorsed or certified" in t
    assert "| Lead | Money | Closes |" in t and "https://www.grants.gov/" in t
    page = c.get(f"/briefs/{bid}/export.html", params={"status": "kept"}).text
    assert page.startswith("<!doctype html>") and "window.print()" in page
    assert "<table>" in page and "not endorsed or certified" in page
    assert c.get("/briefs/nope/export.md").status_code == 404
