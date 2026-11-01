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
    return TestClient(create_app(service, InlineRunner(), stored_briefs=True)), service


def test_brief_end_to_end_reports_stages_and_leads(tmp_path):
    c, _ = make(tmp_path)
    r = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"})
    assert r.status_code == 202
    bid = r.json()["id"]
    got = c.get(f"/briefs/{bid}").json()
    b = got["brief"]
    assert b["status"] == "done", b["error"]
    assert [s["name"] for s in b["stages"]] == ["researcher", "works", "awards", "profile",
                                                "route_a", "route_b", "explanations", "summary"]
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
    c, service = make(tmp_path)
    cands = c.get("/authors/resolve", params={"q": NAME}).json()["candidates"]
    assert [x["id"] for x in cands] == ["https://openalex.org/A5026494099"]
    from perch.schemas import Researcher

    with service.repo() as r:  # S13: a search writes nothing
        assert r.get(Researcher, "https://openalex.org/A5026494099") is None


def test_failed_stage_is_recorded(tmp_path):
    c, service = make(tmp_path)

    def boom():
        raise RuntimeError("OpenAlex unreachable")

    service.clients.openalex = boom
    bid = c.post("/briefs", json={"author_id": "A5000000001"}).json()["id"]
    b = c.get(f"/briefs/{bid}").json()["brief"]
    assert b["status"] == "failed" and "OpenAlex unreachable" in b["error"]
    assert b["stages"][0]["status"] == "failed"


def test_a_repeat_brief_is_a_new_job_never_a_reused_copy(tmp_path):
    c, _ = make(tmp_path)
    req = {"author_id": "A5026494099", "as_of": "2026-10-28"}
    first = c.post("/briefs", json=req).json()["id"]
    r = c.post("/briefs", json=req)  # S23: no reuse; each brief is its own run
    assert r.status_code == 202 and r.json()["id"] != first and "reused" not in r.json()


def test_stored_brief_routes_are_off_by_default(tmp_path):
    from perch.api import create_app
    from perch.jobs import InlineRunner

    c, service = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"}).json()["id"]
    off = TestClient(create_app(service, InlineRunner()))
    assert off.post("/briefs", json={"author_id": "A5026494099"}).status_code == 404
    assert off.get(f"/briefs/{bid}").status_code == 404
    assert off.get(f"/briefs/{bid}/export.json").status_code == 404
    assert off.get(f"/records/{bid}").status_code == 404  # a brief is a visitor's record
    assert off.get("/watch").status_code in (404, 405)  # monitoring shelved (S23)


def test_rate_limit_counts_new_briefs_per_forwarded_visitor(tmp_path, monkeypatch):
    monkeypatch.setenv("PERCH_BRIEFS_PER_HOUR", "2")
    c, _ = make(tmp_path)
    # As uvicorn hands requests on: the visitor's address is already in request.client
    # (test_client_key_is_the_forwarded_address_under_uvicorn).
    one = TestClient(c.app, client=("198.51.100.7", 50000))
    req = {"author_id": "A5026494099", "as_of": "2026-10-28"}
    assert [one.post("/briefs", json=req).status_code for _ in range(3)] == [202, 202, 429]
    r = one.post("/briefs", json=req, headers={"x-forwarded-for": "198.51.100.9"})
    assert "2 new briefs an hour" in r.json()["detail"] and int(r.headers["retry-after"]) > 0
    two = TestClient(c.app, client=("198.51.100.8", 50000))
    assert two.post("/briefs", json=req).status_code == 202


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
    s = r.json()  # each step runs at once (S28): no approval
    assert "mode" not in s and not s["busy"]
    x = s["exchanges"][0]
    assert x["status"] == "done" and x["answer"].startswith("It closes 2026-11-17")
    assert x["cards"][0]["status"] == "done" and "grants_gov:PAR-25-268" in x["cards"][0]["records"]
    s = c.post(f"/scout/{s['id']}/ask", json={"question": "Thanks"}).json()
    assert len(s["exchanges"]) == 2 and c.get(f"/scout/{s['id']}").json()["id"] == s["id"]
    assert c.post(f"/scout/{s['id']}/ask", json={"question": " "}).status_code == 422
    assert c.get("/scout/nope").status_code == 404
    assert c.post(f"/scout/{s['id']}/delete", json={}).status_code == 422
    for gone in ("approve", "skip", "mode"):  # the ask-first gate is gone (S28)
        assert c.post(f"/scout/{s['id']}/{gone}", json={}).status_code == 422
    assert c.post(f"/scout/{s['id']}/stop", json={}).status_code == 202  # idle: nothing to stop
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
                            "newest was published 2 Jan 2026.")
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
    # F26: an office with nothing kept on its route gets no empty draft
    empty = c.post(f"/briefs/{bid}/handoff", json={"office": "technology_commercialization"})
    assert empty.status_code == 422 and empty.json()["detail"] == "No kept industry leads."
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


def test_a_crash_answers_500_by_type_and_is_not_raised_to_the_server(tmp_path):
    """S5: Starlette re-raised after the catch-all handler, so uvicorn logged the
    traceback and its message. The middleware ends it at a typed 500."""
    _, service = make(tmp_path)
    app = create_app(service, InlineRunner(), web_dir=None)

    @app.get("/boom")
    def boom() -> dict:
        raise ValueError("SYNTHETIC request text PERCH-CANARY-ERR")

    c = TestClient(app)  # raise_server_exceptions: anything re-raised fails the test
    r = c.get("/boom")
    assert r.status_code == 500 and r.json() == {"detail": "internal error (ValueError)"}
    assert c.get("/health").json() == {"status": "ok"}


def test_client_key_is_the_forwarded_address_under_uvicorn(tmp_path):
    """W16: run as `perch serve` runs it. From loopback (the tunnel), uvicorn puts the
    X-Forwarded-For address in request.client; from any other address the header is
    ignored. client_key needs no forwarded-header branch of its own."""
    import socket
    import threading
    import time

    import uvicorn
    from fastapi import Request

    from perch.api import SERVE_OPTIONS, client_key

    _, service = make(tmp_path)
    app = create_app(service, InlineRunner(), web_dir=None)

    @app.get("/key")
    def key(request: Request) -> dict:
        return {"key": client_key(request)}

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                        **SERVE_OPTIONS))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    try:
        for _ in range(100):
            if srv.started:
                break
            time.sleep(0.05)
        url = f"http://127.0.0.1:{port}/key"
        assert httpx.get(url, headers={"X-Forwarded-For": "198.51.100.7"}).json() == \
            {"key": "198.51.100.7"}
        assert httpx.get(url).json() == {"key": "127.0.0.1"}
    finally:
        srv.should_exit = True
        t.join(5)


def test_client_key_groups_ipv6_by_its_64():
    """S6: one subscriber's IPv6 block is one visitor; an IPv4-mapped address is its IPv4."""
    from starlette.requests import Request

    from perch.api import client_key

    def key(host):
        return client_key(Request({"type": "http", "client": (host, 1), "headers": []}))

    assert key("2001:db8:1:2::10") == key("2001:db8:1:2:abcd::1") == "2001:db8:1:2::/64"
    assert key("2001:db8:1:3::10") != key("2001:db8:1:2::10")
    assert key("::ffff:198.51.100.7") == "198.51.100.7" == key("198.51.100.7")


def test_request_bodies_over_the_limit_answer_413(tmp_path, monkeypatch):
    """S10: Starlette buffers a whole body before pydantic's max_length runs, so a huge
    POST was held in memory. Declared and chunked bodies over 8 MB answer 413."""
    import perch.api as api

    monkeypatch.setattr(api, "MAX_BODY", 1000)
    c, _ = make(tmp_path)
    big = b'{"question": "' + b"x" * 2000 + b'"}'
    r = c.post("/private/session", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413
    chunks = (big[i:i + 300] for i in range(0, len(big), 300))
    assert c.post("/private/session", content=chunks).status_code == 413
    small = (x for x in [b"{}"])
    assert c.post("/private/end", content=small).status_code == 200  # chunked, under the limit
    assert c.get("/health").status_code == 200


def test_route_b_runs_beside_the_explanations(tmp_path, monkeypatch):
    """P2: Route B is network only, so it no longer holds up the explanations; the brief
    is done when both are."""
    import threading

    from perch.service import BriefService

    c, _ = make(tmp_path)
    started = threading.Event()
    seen = {}
    real_b, real_x = BriefService._run_route_b, BriefService._run_explanations

    def route_b(self, b):
        seen["beside"] = started.wait(5)  # explanations start while Route B runs
        return real_b(self, b)

    def explanations(self, b):
        started.set()
        return real_x(self, b)

    monkeypatch.setattr(BriefService, "_run_route_b", route_b)
    monkeypatch.setattr(BriefService, "_run_explanations", explanations)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"}).json()["id"]
    b = c.get(f"/briefs/{bid}").json()["brief"]
    assert b["status"] == "done", b["error"]
    assert seen["beside"] is True
    assert {s["name"]: s["status"] for s in b["stages"]}["route_b"] == "done"


def test_a_route_b_failure_beside_still_fails_the_brief(tmp_path, monkeypatch):
    from perch.service import BriefService

    c, _ = make(tmp_path)

    def boom(self, b):
        raise RuntimeError("SYNTHETIC NIH outage")

    monkeypatch.setattr(BriefService, "_run_route_b", boom)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28"}).json()["id"]
    b = c.get(f"/briefs/{bid}").json()["brief"]
    st = {s["name"]: s["status"] for s in b["stages"]}
    assert b["status"] == "failed" and st["route_b"] == "failed" and "NIH outage" in b["error"]
    assert st["explanations"] == "done"  # the model stages finished meanwhile


def test_request_models_are_defined_once():
    """Review W15: the session routes reuse the stored-brief API's request models."""
    from perch import api, request_models
    from perch.private import routes

    assert issubclass(api.BriefRequest, request_models.BriefOptions)
    assert issubclass(routes.PrivateBriefRequest, request_models.BriefOptions)
    assert issubclass(routes.PrivateHandoffRequest, request_models.HandoffRequest)
    assert api.ScoutRequest is request_models.ScoutRequest and not hasattr(routes, "ScoutReq")
    src = "".join(Path(m.__file__).read_text() for m in (api, routes, request_models))
    assert src.count("def context(self)") == 1
    assert routes.PrivateBriefRequest(author_id=None).author_id is None
    assert api.BriefRequest(author_id="A1").context()["include_keywords"] == []


def test_route_b_sends_up_to_the_cap_of_records_per_signal_and_counts_the_rest():
    from datetime import UTC, date, datetime

    from perch.api import SIGNAL_RECORDS, route_b_json
    from perch.schemas import Lead, Signal, Work

    t = datetime(2026, 10, 29, tzinfo=UTC)
    ids = [f"https://openalex.org/W{i}" for i in range(SIGNAL_RECORDS + 5)]
    works = {i: Work(id=i, source="openalex", source_url="u", fetched_at=t, title=f"SYNTHETIC {i}",
                     publication_date=date(2026, 1, 1)) for i in ids}

    class Repo:
        def get(self, cls, record_id):  # noqa: ANN001, ARG002
            return None

        def get_any(self, record_id):
            return works.get(record_id)

    lead = Lead(id="b:B1", source="openalex", source_url="u", fetched_at=t, brief_id="b", route="B",
                record_id="https://openalex.org/I1", rank=1, inferred=True, inference="x",
                cited_ids=[], signals=[Signal(kind="citing_works", record_ids=ids, count=len(ids))])
    item = route_b_json(lead, Repo())["signal_items"][0]  # type: ignore[arg-type]
    assert len(item["records"]) == SIGNAL_RECORDS and item["more"] == 5


def test_an_orcid_id_that_fails_its_check_is_refused_before_any_lookup(tmp_path):
    """Q18: the placeholder 0000-0000-0000-0000 found a stranger's profile."""
    c, _ = make(tmp_path)
    r = c.get("/authors/resolve", params={"q": "0000-0000-0000-0000"})
    assert r.status_code == 422 and "not a valid ORCID" in r.json()["detail"]


def test_an_id_that_is_not_an_openalex_id_is_refused_in_plain_words(tmp_path):
    """R5: "A12" reached OpenAlex, which answered 4xx, and the page showed "internal error
    (HTTPStatusError)". A short id is refused before any lookup, and an id OpenAlex does
    not know reads as a plain sentence."""
    c, service = make(tmp_path)
    for q in ("A12", "a1234567", "https://openalex.org/A12"):
        r = c.get("/authors/resolve", params={"q": q})
        assert r.status_code == 422, q
        assert r.json()["detail"].startswith("An OpenAlex author ID is an A followed by at least")
    service.clients.openalex = lambda: oa.OpenAlexClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(404, json={})), min_interval=0)
    r = c.get("/authors/resolve", params={"q": "A123456789"})
    assert r.status_code == 404 and "internal error" not in r.text
    assert r.json()["detail"].startswith("No OpenAlex author has that ID.")


def test_an_orcid_with_a_lower_case_x_finds_the_same_profile(tmp_path):
    """R16: an ORCID iD whose check character is X found nobody when typed as x."""
    base = "0000-0002-1694-233"  # 15 digits whose ISO 7064 check character is X
    assert oa.orcid_ok(base + "X") and oa.parse_orcid(base + "x") == base + "X"
    c, service = make(tmp_path)
    asked = []

    def answer(req):
        asked.append(req.url.path)
        return httpx.Response(404, json={})

    service.clients.openalex = lambda: oa.OpenAlexClient(transport=httpx.MockTransport(answer),
                                                          min_interval=0)
    for q in (base + "X", base + "x", f"https://orcid.org/{base}x"):
        c.get("/authors/resolve", params={"q": q})
    assert asked == [f"/authors/orcid:{base}X"] * 3


def test_the_brief_carries_every_paper_its_summary_cites(tmp_path):
    """T28: the Profile showed 3 paper chips where the export cited 4, because a paper the
    summary cites outside the threads' key papers and the leads was not in the papers map."""
    from perch.schemas import Brief, Work

    c, service = make(tmp_path)
    bid = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                  "explain": False}).json()["id"]
    from datetime import UTC, datetime

    extra = Work(id="https://openalex.org/W9999999901", source="openalex",
                 source_url="https://openalex.org/W9999999901",
                 fetched_at=datetime(2026, 10, 28, tzinfo=UTC), title="SYNTHETIC paper")
    with service.repo() as r:
        b = r.get(Brief, bid)
        r.upsert([extra, b.model_copy(update={
            "summary": "Works on a SYNTHETIC topic [W9999999901]."})])
    assert extra.id in c.get(f"/briefs/{bid}").json()["papers"]
