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

from .test_openalex import fixture_transport

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
                                                "route_a", "summary", "explanations"]
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
    cands = c.get("/authors/resolve", params={"q": "Axel Kohlmeyer"}).json()["candidates"]
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
