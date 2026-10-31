"""Private mode (S13): session pipeline, gate, isolation and the canary.

Inputs are the SYNTHETIC persona-1 files; each holds a unique canary token. Models are
fakes, so no network and no GPU.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from perch.llm.fake import FakeProvider
from perch.privacy import PrivateSettings
from perch.private.cv import parse_cv
from perch.private.inputs import InputError, docx_text, make_doc, parse_bytes
from perch.private.session import YOU, PrivateSessions, add_document
from perch.retrieve import index_opportunities
from perch.schemas import Brief, Lead

from .test_api import make

PERSONA = Path(__file__).resolve().parent.parent / "data/synthetic/persona-1"
FILES = {"cv": "cv.md", "proposal": "specific_aims_draft.md",
         "manuscript": "unpublished_manuscript.md"}
CANARIES = ["PERCH-CANARY-CV-7Q4X", "PERCH-CANARY-AIMS-K2M9", "PERCH-CANARY-MS-T8V3"]
SETTINGS = PrivateSettings(enabled=True, endpoints=("127.0.0.1", "localhost", "::1"),
                           tls_at="server", public_url=None, operator="Test operator")


def fit_reply(messages, system, schema):
    """A valid fit explanation citing the opportunity and the private proposal."""
    if schema and "fit" in schema.get("properties", {}):
        return json.dumps({
            "reasoning": "r", "fit": 70,
            "opportunity_sentence": "The announcement funds research projects [PAR-25-268].",
            "research_findings": [{"paper_id": "private:proposal",
                                   "finding": "proposed a system that records ground "
                                              "reaction force at home"}],
            "link_sentence": "The proposal fits the announcement.",
            "cited_ids": ["PAR-25-268", "private:proposal"]})
    return ""


def persona_session(tmp_path, responder=fit_reply):
    _, service = make(tmp_path)
    with service.repo() as r:  # the public pipeline keeps the index; a session never writes it
        index_opportunities(r, service.models.get("index"), service.models.get("embedder"))
    service.models.provider = lambda spec: FakeProvider(responder=responder)
    sessions = PrivateSessions(service, SETTINGS)
    s = sessions.open()
    for kind, name in FILES.items():
        add_document(s, make_doc(kind, (PERSONA / name).read_text()))
    return service, sessions, s


def test_private_only_brief_returns_cited_routes(tmp_path):
    service, _, s = persona_session(tmp_path)
    b = s.service.create_private(None, as_of=date(2026, 10, 28))
    s.service.run(b.id)
    got = s.service.get(b.id)
    assert got, "the brief lives in the session"
    b, leads = got
    assert b.status == "done", b.error
    assert b.researcher_id == YOU
    assert [t["private"] for t in b.threads] == [True, True]  # proposal and manuscript
    assert abs(sum(t["weight"] for t in b.threads) - 1.0) < 1e-6
    assert leads and leads[0].explanation and "private:proposal" in leads[0].cited_ids
    # Nothing reached the shared store.
    with service.repo() as r:
        assert r.get(Brief, b.id) is None and not r.list(Lead)


def test_private_threads_take_their_share_beside_public_ones(tmp_path):
    _, _, s = persona_session(tmp_path)
    b = s.service.create_private("A5026494099", as_of=date(2026, 10, 28), explain=False)
    s.service.run(b.id)
    b, _ = s.service.get(b.id)
    assert b.status == "done", b.error
    private = [t["weight"] for t in b.threads if t["private"]]
    public = [t["weight"] for t in b.threads if not t["private"]]
    assert public and abs(sum(private) - 0.6) < 1e-3 and abs(sum(public) - 0.4) < 1e-3
    assert abs(private[0] / private[1] - 0.5 / 0.2) < 1e-2  # proposal : manuscript (Q21)


def test_cv_parse_reads_degree_rank_and_esi():
    f = parse_cv((PERSONA / "cv.md").read_text())
    assert f.degree_year == 2021 and f.rank == "Assistant Professor"
    assert f.nih_substantial == [] and f.esi_possible(date(2026, 10, 29))
    assert not f.esi_possible(date(2032, 1, 1))
    g = parse_cv("# CV\n## Education\n- PhD, Biology, 2019\n## Funding\n"
                 "- NIH R01 GM000000, 2022 to 2027\n- NSF CAREER award, 2020\n"
                 "- NIH R21 AG000000, 2020\n")
    assert g.nih_substantial == ["R01"] and not g.esi_possible(date(2026, 1, 1))
    assert g.sponsors == ["NIH", "NSF"]


def test_inputs_parse_from_bytes():
    import io
    import zipfile

    buf = io.BytesIO()
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body><w:p><w:r>'
                   "<w:t>SYNTHETIC aims</w:t></w:r></w:p><w:p><w:r><w:t>line two</w:t>"
                   "</w:r></w:p></w:body></w:document>")
    assert docx_text(buf.getvalue()) == "SYNTHETIC aims\nline two"
    assert parse_bytes("a.md", b"# SYNTHETIC") == "# SYNTHETIC"
    with pytest.raises(InputError):
        parse_bytes("a.exe", b"x")
    with pytest.raises(InputError):
        parse_bytes("a.pdf", b"not a pdf")
    with pytest.raises(InputError):
        make_doc("proposal", "x" * 70_000)


# --- through the API: canary, isolation, refusal, masking ---

def private_env(monkeypatch):
    monkeypatch.setenv("PERCH_PRIVATE_MODE", "1")
    monkeypatch.setenv("PERCH_TLS_AT", "server")
    monkeypatch.setenv("PERCH_PRIVATE_OPERATOR", "Test operator")
    monkeypatch.delenv("PERCH_PUBLIC_URL", raising=False)
    monkeypatch.delenv("PERCH_PRIVATE_ENDPOINTS", raising=False)


def private_app(tmp_path, monkeypatch, responder=fit_reply):
    private_env(monkeypatch)
    c, service = make(tmp_path)
    with service.repo() as r:
        index_opportunities(r, service.models.get("index"), service.models.get("embedder"))
    service.models.provider = lambda spec: FakeProvider(responder=responder)
    return c, service


def open_with_persona(c):
    tok = c.post("/private/session").json()["token"]
    h = {"X-Perch-Private": tok}
    for kind, name in FILES.items():
        assert c.post("/private/documents", headers=h,
                      json={"kind": kind, "text": (PERSONA / name).read_text()}).status_code == 201
    return h


def snapshot(root):
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in Path(root).rglob("*") if p.is_file()}


def files_with(root, tokens, since=None):
    hits = []
    for p in Path(root).rglob("*"):
        try:
            if not p.is_file() or p.is_symlink() or p.stat().st_size > 50_000_000:
                continue
            if since and p.stat().st_mtime < since:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        hits += [f"{p}: {t}" for t in tokens if t.encode() in data]
    return hits


def user_rows(db):
    import sqlite3

    with sqlite3.connect(db) as con:
        return con.execute("SELECT count(*) FROM records WHERE kind IN ('brief', 'lead', "
                           "'digest')").fetchone()[0]


@pytest.mark.parametrize("public_cache", [False, True])
def test_canary_leaves_no_trace(tmp_path, monkeypatch, capfd, public_cache):
    """S23: with the public cache on (the default), the researcher's public records may be
    written to the store, and nothing else: no brief, lead or other file changes."""
    import time

    import httpx

    start = time.time()
    monkeypatch.setenv("PERCH_PUBLIC_CACHE", "1" if public_cache else "0")
    c, service = private_app(tmp_path, monkeypatch)
    sent = []
    real_send = httpx.Client.send

    def spy(self, request, **kw):
        sent.append((request.url.host, request.content or b""))
        return real_send(self, request, **kw)

    monkeypatch.setattr(httpx.Client, "send", spy)
    before = snapshot(tmp_path)
    rows = user_rows(service.db)
    h = open_with_persona(c)
    assert c.post("/private/documents", headers=h, json={
        "kind": "direction", "text": "SYNTHETIC direction PERCH-CANARY-DIR-Z5P1: home gait "
        "sensing for early Parkinson's detection."}).status_code == 201
    for author in (None, "A5026494099"):  # private-only, then with a public profile
        assert c.post("/private/brief", headers=h, json={
            "author_id": author, "as_of": "2026-10-28"}).status_code == 202
        got = c.get("/private/brief", headers=h).json()
        assert got["brief"]["status"] == "done", got["brief"]["error"]
        lead = got["leads"][0]
        assert c.post(f"/private/leads/{lead['id']}/keep", headers=h).status_code == 200
        c.get("/private/compare", headers=h)
        for mask in (False, True):
            for ext in ("json", "md", "html"):
                c.get(f"/private/export.{ext}", headers=h, params={"mask": mask})
            c.post("/private/handoff", headers=h,
                   json={"office": "research_development", "mask": mask})
        sc = c.post("/private/scout", headers=h, json={"question": "Which lead fits best?"})
        assert sc.status_code == 202, sc.text
    assert c.post("/private/end", headers=h).json()["ended"]
    canaries = [*CANARIES, "PERCH-CANARY-DIR-Z5P1"]
    after = snapshot(tmp_path)
    if public_cache:  # only the store may change, and only with public records
        after.pop(service.db, None), before.pop(service.db, None)
        assert user_rows(service.db) == rows
        with service.repo() as r:
            assert r.works_by_author("https://openalex.org/A5026494099"), "public data cached"
    assert after == before, "a private session wrote to the data directory"
    assert files_with(tmp_path, canaries) == []
    assert files_with("/tmp", canaries, since=start) == []
    out, err = capfd.readouterr()
    assert not any(t in out + err for t in canaries)
    allowed = SETTINGS.endpoints
    leaks = [host for host, body in sent if any(t.encode() in body for t in canaries)
             and host not in allowed]
    assert leaks == [], f"private text sent off the allowlist: {leaks}"
    assert sent, "the spy saw the public fetches"


def test_default_exports_withhold_and_masking_round_trips(tmp_path, monkeypatch):
    c, _ = private_app(tmp_path, monkeypatch)
    h = open_with_persona(c)
    c.post("/private/brief", headers=h, json={"as_of": "2026-10-28"})
    got = c.get("/private/brief", headers=h).json()
    assert got["leads"][0]["explanation"]  # on screen in the session
    assert got["papers"]["private:proposal"]["private"] is True
    exp = c.get("/private/export.json", headers=h).json()
    assert exp["leads"][0]["explanation"].startswith("Withheld")
    assert not any(r["source"] == "private" for r in exp["records"])
    md = c.get("/private/export.md", headers=h).text
    assert "ground reaction" not in md and "Withheld" in md
    masked = c.get("/private/export.json", headers=h, params={"mask": True}).json()
    text = masked["leads"][0]["explanation"]
    assert "[PRIVATE-PHRASE-1]" in text and "ground reaction force" not in text
    back = c.post("/private/unmask", headers=h, json={"text": text}).json()["text"]
    assert back == got["leads"][0]["explanation"]


def test_sessions_are_isolated(tmp_path, monkeypatch):
    c, _ = private_app(tmp_path, monkeypatch)
    a = open_with_persona(c)
    b = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    c.post("/private/brief", headers=a, json={"as_of": "2026-10-28"})
    bid = c.get("/private/brief", headers=a).json()["brief"]["id"]
    assert c.get("/private/session", headers=b).json()["documents"] == []
    assert c.get("/private/brief", headers=b).status_code == 404
    assert c.get("/private/records/private:proposal", headers=b).status_code == 404
    assert c.get(f"/briefs/{bid}").status_code == 404  # not in the shared store
    assert c.get("/records/private:proposal").status_code == 404
    assert c.get("/private/session").status_code == 401  # no token
    c.post("/private/end", headers=a)
    assert c.get("/private/brief", headers=a).status_code == 401


def test_idle_sessions_end(tmp_path):
    _, service = make(tmp_path)
    service.models.provider = lambda spec: FakeProvider()
    now = [0.0]
    sessions = PrivateSessions(service, SETTINGS, clock=lambda: now[0], idle=60)
    s = sessions.open()
    add_document(s, make_doc("direction", "SYNTHETIC text"))
    now[0] = 61
    assert sessions.get(s.token) is None and s.docs == {}


def test_hosted_or_unlisted_models_are_refused(tmp_path, monkeypatch):
    import httpx

    c, service = private_app(tmp_path, monkeypatch)

    class Hosted(FakeProvider):
        name = "anthropic"

    service.models.provider = lambda spec: Hosted()
    r = c.post("/private/session")
    assert r.status_code == 403 and "hosted API" in r.json()["detail"]
    remote = FakeProvider()
    remote.http = httpx.Client(base_url="https://models.example.org")
    service.models.provider = lambda spec: remote
    r = c.post("/private/session")
    assert r.status_code == 403 and "not an allowed endpoint" in r.json()["detail"]


def test_private_mode_off_without_tls_location_on_a_public_url(tmp_path, monkeypatch):
    private_env(monkeypatch)
    monkeypatch.delenv("PERCH_TLS_AT")
    monkeypatch.setenv("PERCH_PUBLIC_URL", "https://perch.example.org")
    c, _ = make(tmp_path)
    assert c.get("/private").json()["enabled"] is False
    assert c.post("/private/session").status_code == 404


def test_upload_as_base64_and_caps(tmp_path, monkeypatch):
    import base64

    c, _ = private_app(tmp_path, monkeypatch)
    h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    data = base64.b64encode(b"# SYNTHETIC aims\n\nGait sensing.").decode()
    r = c.post("/private/documents", headers=h,
               json={"kind": "proposal", "filename": "aims.md", "data": data})
    assert r.status_code == 201 and r.json()["chars"] > 0
    r = c.post("/private/documents", headers=h,
               json={"kind": "proposal", "filename": "aims.exe", "data": data})
    assert r.status_code == 422 and "aims" not in r.text
    assert c.post("/private/documents", headers=h,
                  json={"kind": "proposal", "data": "!!"}).status_code == 422


# --- normal-mode context (task 7, Q16) ---

def test_normal_mode_context_steers_and_is_saved(tmp_path):
    from perch.service import brief_options

    c, _ = make(tmp_path)
    assert set(brief_options()) == {"as_of", "top", "explain", "min_amount", "agencies"}
    r = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                "explain": False, "direction": "SYNTHETIC home gait sensing",
                                "include_keywords": ["gait", " "],
                                "exclude_keywords": ["zebrafish"],
                                "career_stage": "early_stage"})
    bid = r.json()["id"]
    b = c.get(f"/briefs/{bid}").json()["brief"]
    assert b["status"] == "done", b["error"]
    o = b["options"]
    assert o["direction"] == "SYNTHETIC home gait sensing" and o["include_keywords"] == ["gait"]
    assert o["exclude_keywords"] == ["zebrafish"] and o["career_stage"] == "early_stage"
    said = [t for t in b["threads"] if t.get("said")]
    assert len(said) == 1 and abs(said[0]["weight"] - 0.3) < 1e-3
    # A brief without the fields is a different brief, not a reuse of this one.
    r2 = c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                                 "explain": False})
    assert r2.json()["id"] != bid and not r2.json().get("reused")
    plain = c.get(f"/briefs/{r2.json()['id']}").json()["brief"]
    assert not any(t.get("said") for t in plain["threads"])
    assert "direction" not in plain["options"]


def test_exclude_keyword_and_self_reported_stage_rules():
    from perch.eligibility import Constraints, check
    from perch.schemas import Opportunity, utcnow

    o = Opportunity(id="grants_gov:x", source="grants_gov", source_url="u", fetched_at=utcnow(),
                    opportunity_number="PAR-00-000", title="SYNTHETIC Early-Stage Investigator "
                    "award (R01)", agency="National Institutes of Health",
                    close_date=date(2027, 1, 1),
                    eligible_applicants=["Private institutions of higher education"],
                    description="Zebrafish models")
    base = Constraints(as_of=date(2026, 10, 28))
    assert any("career stage" in x for x in check(o, base))
    assert check(o, Constraints(as_of=date(2026, 10, 28), career_stage_ok=True)) == []
    assert any("zebrafish" in x for x in check(o, Constraints(
        as_of=date(2026, 10, 28), career_stage_ok=True, exclude_keywords=["zebrafish"])))


def test_private_screens_never_use_browser_storage():
    web = Path(__file__).resolve().parent.parent / "web"
    src = "".join((web / f).read_text() for f in ("private.js", "api.js", "student.js", "mode.js"))
    assert not any(x in src for x in ("localStorage", "sessionStorage", "indexedDB",
                                      "document.cookie"))


def test_a_brief_needs_no_document_and_carries_the_context_fields(tmp_path, monkeypatch):
    c, service = private_app(tmp_path, monkeypatch)
    h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    assert c.post("/private/brief", headers=h, json={}).status_code == 422
    rows = user_rows(service.db)
    r = c.post("/private/brief", headers=h, json={
        "author_id": "A5026494099", "as_of": "2026-10-28", "direction": "home gait sensing",
        "exclude_keywords": ["  "], "career_stage": "early_stage"})
    assert r.status_code == 202, r.text
    b = c.get("/private/brief", headers=h).json()["brief"]
    assert b["status"] == "done" and b["options"]["models"] == "local"
    assert b["options"]["direction"] == "home gait sensing" and "exclude_keywords" not in \
        b["options"] and b["options"]["career_stage"] == "early_stage"
    assert any(t.get("said") for t in b["threads"])  # "You said" steers as a query
    assert user_rows(service.db) == rows  # the brief stays in the session


def test_cloud_is_confirmed_by_name_and_never_takes_documents(tmp_path, monkeypatch):
    from perch.llm.fake import FakeProvider
    from perch.private.session import PrivateModels

    monkeypatch.setenv("PERCH_CLOUD", "anthropic:claude-sonnet-5-5")
    c, service = private_app(tmp_path, monkeypatch)
    info = c.get("/private").json()["cloud"]
    assert info["available"] and info["provider"] == "Anthropic" and "Anthropic" in info["warning"]
    h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    assert c.post("/private/cloud", headers=h, json={"on": True}).status_code == 422
    assert c.post("/private/cloud", headers=h,
                  json={"on": True, "confirm": "anthropic"}).json()["cloud"] is True
    assert c.post("/private/documents", headers=h, json={
        "kind": "direction", "text": "SYNTHETIC direction"}).status_code == 409
    assert c.post("/private/cloud", headers=h, json={"on": False}).json()["cloud"] is False
    assert c.post("/private/documents", headers=h, json={
        "kind": "direction", "text": "SYNTHETIC direction"}).status_code == 201
    assert c.post("/private/cloud", headers=h,
                  json={"on": True, "confirm": "Anthropic"}).status_code == 409

    # The gate: the cloud spec passes only while Cloud is on, and only that spec.
    class Hosted(FakeProvider):
        name = "anthropic"

    s = PrivateSettings(enabled=True, endpoints=("127.0.0.1",), tls_at=None, public_url=None,
                        cloud_spec="anthropic:claude-sonnet-5-5")
    service.models.provider = lambda spec: Hosted()
    on = {"v": False}
    m = PrivateModels(service.models, s, lambda: on["v"])
    with pytest.raises(PermissionError):
        m.provider("anthropic:claude-sonnet-5-5")
    on["v"] = True
    assert m.fit_spec == "anthropic:claude-sonnet-5-5"
    assert m.provider("anthropic:claude-sonnet-5-5").name == "anthropic"
    with pytest.raises(PermissionError):
        m.provider("anthropic:claude-opus-5-5")


def test_cloud_briefs_stop_at_the_daily_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("PERCH_CLOUD", "anthropic:claude-sonnet-5-5")
    monkeypatch.setenv("PERCH_CLOUD_BRIEFS_PER_DAY", "1")
    c, _ = private_app(tmp_path, monkeypatch)
    h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    c.post("/private/cloud", headers=h, json={"on": True, "confirm": "Anthropic"})
    body = {"author_id": "A5026494099", "as_of": "2026-10-28", "explain": False}
    assert c.post("/private/brief", headers=h, json=body).status_code == 202  # no model call
    body["explain"] = True
    statuses = [c.post("/private/brief", headers=h, json=body).status_code for _ in range(2)]
    assert statuses[1] == 429


def test_warm_demo_briefs_are_copied_into_each_session(tmp_path, monkeypatch):
    """Q31 (S24 task 9): a warm brief is built once and held in memory; each visitor gets
    their own copy at once, with their own keep state; nothing is written to the store."""
    c, service = private_app(tmp_path, monkeypatch)
    warm = c.app.state.warm_briefs
    warm.authors = ["A5026494099"]
    rows = user_rows(service.db)
    assert warm.build("A5026494099") is not None
    assert user_rows(service.db) == rows  # built in memory only
    hs = [{"X-Perch-Private": c.post("/private/session").json()["token"]} for _ in range(2)]
    got = [c.post("/private/brief", headers=h, json={"author_id": "A5026494099"}).json()
           for h in hs]
    assert all(g.get("warm") and g["status"] == "done" for g in got)
    leads = c.get("/private/brief", headers=hs[0]).json()["leads"]
    assert leads
    c.post(f"/private/leads/{leads[0]['id']}/keep", headers=hs[0])
    other = c.get("/private/brief", headers=hs[1]).json()["leads"]
    assert other[0]["status"] == "new"  # the second visitor's copy is untouched
    # Anything added (context, documents, Cloud) builds live instead.
    h3 = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    r = c.post("/private/brief", headers=h3, json={"author_id": "A5026494099",
                                                   "direction": "home gait sensing"}).json()
    assert not r.get("warm")
    assert user_rows(service.db) == rows


def test_documents_go_to_cloud_only_with_the_switch_and_a_second_confirm(tmp_path, monkeypatch):
    """Q30 (S24 task 8), SYNTHETIC text only. Off by default: standing rule 1 keeps
    documents local until Dakshitha changes it (Q33)."""
    monkeypatch.setenv("PERCH_CLOUD", "anthropic:claude-sonnet-5-5")
    c, _ = private_app(tmp_path, monkeypatch)
    h = open_with_persona(c)
    info = c.get("/private").json()["cloud"]
    assert not info["documents"]
    assert c.post("/private/cloud", headers=h, json={
        "on": True, "confirm": "Anthropic",
        "documents_confirm": "send my documents to anthropic"}).status_code == 409
    c.post("/private/end", headers=h)

    monkeypatch.setenv("PERCH_CLOUD_DOCUMENTS", "1")
    c, service = private_app(tmp_path / "on", monkeypatch)
    info = c.get("/private").json()["cloud"]
    assert info["documents"] and "second warning" in info["warning"]
    h = open_with_persona(c)
    r = c.post("/private/cloud", headers=h, json={"on": True, "confirm": "Anthropic"})
    assert r.status_code == 409 and "send my documents to anthropic" in r.json()["detail"]
    r = c.post("/private/cloud", headers=h, json={
        "on": True, "confirm": "Anthropic", "documents_confirm": "Send my documents to Anthropic"})
    assert r.json() == {"cloud": True, "documents": True}
    s = c.app.state.private_sessions.get(h["X-Perch-Private"])
    assert s.service.models.cloud()  # the skills now use the cloud spec
    assert c.post("/private/cloud", headers=h, json={"on": False}).json()["documents"] is False
    assert not s.service.models.cloud()


def test_failed_steps_read_in_plain_words_and_a_bad_id_costs_no_brief():
    """S25 QA rows 33 and 34."""
    import httpx

    from perch.service import plain_error

    assert plain_error(httpx.ConnectError("x")).startswith("A model server did not answer")
    assert "visitor text" not in plain_error(ValueError("visitor text"))


def test_hourly_caps_are_read_from_the_environment(tmp_path, monkeypatch):
    """W13: the session and private hand-off caps follow their variables."""
    monkeypatch.setenv("PERCH_SESSIONS_PER_HOUR", "2")
    monkeypatch.setenv("PERCH_HANDOFF_PER_HOUR", "1")
    c, _ = private_app(tmp_path, monkeypatch)
    assert [c.post("/private/session").status_code for _ in range(3)] == [201, 201, 429]
    assert "Too many private sessions" in c.post("/private/session").json()["detail"]
    monkeypatch.setenv("PERCH_SESSIONS_PER_HOUR", "25")
    monkeypatch.setenv("PERCH_SESSIONS_PER_ADDRESS", "50")  # S6's cap on open sessions
    c, _ = private_app(tmp_path / "b", monkeypatch)
    assert all(c.post("/private/session").status_code == 201 for _ in range(21))
    h = open_with_persona(c)
    c.post("/private/brief", headers=h, json={"as_of": "2026-10-28"})
    office = {"office": "research_development"}
    assert [c.post("/private/handoff", headers=h, json=office).status_code
            for _ in range(2)] == [200, 429]


def summary_reply(messages, system, schema):
    """S1: a summary that draws on the private proposal, then the usual fit reply."""
    if schema and "summary" in schema.get("properties", {}):
        return json.dumps({
            "topics": [{"label": "insole gait sensing", "work_ids": ["private:proposal"]},
                       {"label": "home monitoring", "work_ids": ["private:proposal"]},
                       {"label": "ground reaction force", "work_ids": ["private:proposal"]}],
            "summary": "The proposal builds an insole that records ground reaction force at "
                       "home [private:proposal]. It aims at early detection [private:proposal].",
            "cited_ids": ["private:proposal"]})
    return fit_reply(messages, system, schema)


def test_exports_withhold_the_summary_topics_and_private_threads(tmp_path, monkeypatch):
    """S1: the profile summary, its topics and the private threads' labels are drawn from
    the documents, so a default export leaves them out; a masked export masks them."""
    c, _ = private_app(tmp_path, monkeypatch, responder=summary_reply)
    h = open_with_persona(c)
    c.post("/private/brief", headers=h, json={"as_of": "2026-10-28"})
    got = c.get("/private/brief", headers=h).json()["brief"]
    assert "ground reaction force" in got["summary"]  # on screen in the session
    labels = [t["label"] for t in got["threads"] if t["private"]]
    assert labels
    for ext in ("json", "md", "html"):
        text = c.get(f"/private/export.{ext}", headers=h).text
        assert "ground reaction force" not in text, ext
        assert "insole gait sensing" not in text, ext
        assert not any(lbl in text for lbl in labels), ext
    exp = c.get("/private/export.json", headers=h).json()
    assert exp["brief"]["summary"].startswith("Withheld")
    masked = c.get("/private/export.json", headers=h, params={"mask": True}).json()
    assert "PRIVATE-PHRASE" in masked["brief"]["summary"]
    assert "ground reaction force" not in masked["brief"]["summary"]


PARAPHRASE = "records ground reaction force at home"  # from persona-1's draft aims


def public_paraphrase_reply(messages, system, schema):
    """S8: model text that paraphrases a document while citing only public records."""
    import re

    props = (schema or {}).get("properties", {})
    text = (system or "") + " ".join(m.content for m in messages)
    wid = re.search(r"\[(W\d+)\]", text)
    opp = re.search(r"\[(PAR-[\w-]+)\]", text)
    if "fit" in props and wid and opp:
        return json.dumps({
            "reasoning": "r", "fit": 70,
            "opportunity_sentence": f"The announcement funds research projects [{opp[1]}].",
            "research_findings": [{"paper_id": wid[1], "finding": f"built a sensor that "
                                   f"{PARAPHRASE}"}],
            "link_sentence": "The work fits the announcement.",
            "cited_ids": [opp[1], wid[1]]})
    if "paragraph" in props and wid and opp:
        return json.dumps({"paragraph": f"My work built an insole that {PARAPHRASE}. I would "
                                        "like to discuss the listed announcement.",
                           "cited_ids": [wid[1], opp[1]]})
    return ""


def test_documents_session_withholds_model_text_that_cites_only_public_ids(tmp_path,
                                                                           monkeypatch):
    """S8: in a session holding documents, every model-written text leaves the app as
    private-derived: withheld with a stated count by default, masked on opt-in. The
    screen still shows it."""
    c, _ = private_app(tmp_path, monkeypatch, responder=public_paraphrase_reply)
    h = open_with_persona(c)
    c.post("/private/brief", headers=h, json={"author_id": "A5026494099",
                                              "as_of": "2026-10-28"})
    got = c.get("/private/brief", headers=h).json()
    lead = got["leads"][0]
    assert PARAPHRASE in (lead["explanation"] or ""), lead  # on screen in the session
    assert not any(i.startswith("private:") for i in lead["cited_ids"])
    c.post(f"/private/leads/{lead['id']}/keep", headers=h)
    for ext in ("json", "md", "html"):
        text = c.get(f"/private/export.{ext}", headers=h).text
        assert PARAPHRASE not in text, ext
        assert "explanation withheld: this session holds documents" in text, ext
    exp = c.get("/private/export.json", headers=h).json()
    assert exp["withheld"]["explanations"] >= 1
    masked = c.get("/private/export.json", headers=h, params={"mask": True}).json()
    assert "[PRIVATE-PHRASE-" in masked["leads"][0]["explanation"]
    office = {"office": "research_development"}
    d = c.post("/private/handoff", headers=h, json=office).json()
    assert PARAPHRASE not in d["body"] and "this session holds documents" in d["withheld"]
    dm = c.post("/private/handoff", headers=h, json={**office, "mask": True}).json()
    assert PARAPHRASE not in dm["body"] and "[PRIVATE-PHRASE-" in dm["body"]
    # A session without documents is unchanged: its explanations leave as written.
    h2 = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    c.post("/private/brief", headers=h2, json={"author_id": "A5026494099",
                                               "as_of": "2026-10-28"})
    assert "withheld" not in c.get("/private/export.json", headers=h2).json()


def docx_of(xml: bytes) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_docx_bombs_and_broken_xml_are_input_errors(tmp_path, monkeypatch):
    """S2: a DOCX that inflates past the cap is refused before it is held in memory; a
    malformed document.xml is an InputError, not a crash (S5). Uploads are rate limited."""
    import base64

    from perch.private.inputs import MAX_BYTES, MAX_XML_BYTES

    w = b"http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    bomb = docx_of(b'<w:document xmlns:w="' + w + b'"><w:body><w:p><w:r><w:t>'
                   + b"0" * (MAX_XML_BYTES + 10) + b"</w:t></w:r></w:p></w:body></w:document>")
    assert len(bomb) < MAX_BYTES // 100  # a small upload
    with pytest.raises(InputError, match="once unpacked"):
        docx_text(bomb)
    with pytest.raises(InputError, match="not a readable DOCX"):
        docx_text(docx_of(b"<w:document><w:body><w:p>"))
    monkeypatch.setenv("PERCH_DOCUMENTS_PER_HOUR", "2")
    c, _ = private_app(tmp_path, monkeypatch)
    h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    up = {"kind": "proposal", "filename": "aims.docx", "data": base64.b64encode(bomb).decode()}
    r = c.post("/private/documents", headers=h, json=up)
    assert r.status_code == 422 and "once unpacked" in r.text
    assert c.post("/private/documents", headers=h, json={
        "kind": "direction", "text": "SYNTHETIC gait"}).status_code == 201
    assert c.post("/private/documents", headers=h, json={
        "kind": "direction", "text": "SYNTHETIC gait"}).status_code == 429


def test_pdf_parse_failures_are_input_errors(monkeypatch):
    """S3: any exception from the PDF parser is an InputError, never a 500."""
    import io

    import pypdf
    from pypdf import PdfWriter

    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    assert parse_bytes("a.pdf", buf.getvalue()) == ""
    with pytest.raises(InputError):
        parse_bytes("a.pdf", buf.getvalue()[:-200])

    def broken(self, *a, **k):
        raise TypeError("SYNTHETIC parser bug")

    monkeypatch.setattr(pypdf.PageObject, "extract_text", broken)
    with pytest.raises(InputError, match="not a readable PDF"):
        parse_bytes("a.pdf", buf.getvalue())


def test_private_scout_is_rate_limited_and_needs_a_question(tmp_path, monkeypatch):
    """S4: private Scout questions count per session and per visitor; an empty
    follow-up is refused as on the public route."""
    monkeypatch.setenv("PERCH_SCOUT_PER_HOUR", "2")
    c, _ = private_app(tmp_path, monkeypatch)

    def ready():
        h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
        assert c.post("/private/brief", headers=h, json={
            "author_id": "A5026494099", "as_of": "2026-10-28"}).status_code == 202
        return h

    h = ready()
    q = {"question": "Which lead fits best?"}
    first = c.post("/private/scout", headers=h, json=q)
    assert first.status_code == 202, first.text
    sid = first.json()["id"]
    assert c.post(f"/private/scout/{sid}/ask", headers=h,
                  json={"question": "  "}).status_code == 422
    assert c.post(f"/private/scout/{sid}/ask", headers=h, json=q).status_code == 202
    r = c.post(f"/private/scout/{sid}/ask", headers=h, json=q)
    assert r.status_code == 429 and "2 Scout questions an hour" in r.json()["detail"]
    h2 = ready()  # a new session from the same address: the visitor's cap still holds
    assert c.post("/private/scout", headers=h2, json=q).status_code == 429


def test_session_slots_are_capped_per_address_and_unused_ones_end_sooner(tmp_path,
                                                                        monkeypatch):
    """S6: sessions open at once are capped per visitor address (IPv6 by its /64), and a
    session opened and never used again ends after 10 minutes, not 30."""
    from fastapi.testclient import TestClient

    from perch.private.session import UNUSED_SECONDS

    monkeypatch.setenv("PERCH_SESSIONS_PER_ADDRESS", "2")
    c, _ = private_app(tmp_path, monkeypatch)
    a = TestClient(c.app, client=("2001:db8:1:2::10", 5000))
    b = TestClient(c.app, client=("2001:db8:1:2:ffff::99", 5000))  # the same /64
    other = TestClient(c.app, client=("2001:db8:1:3::10", 5000))
    t1 = a.post("/private/session").json()["token"]
    assert b.post("/private/session").status_code == 201
    r = a.post("/private/session")
    assert r.status_code == 429 and "at most 2 sessions" in r.json()["detail"]
    assert other.post("/private/session").status_code == 201
    a.post("/private/end", headers={"X-Perch-Private": t1})
    assert b.post("/private/session").status_code == 201  # a slot came back

    _, service = make(tmp_path / "s")
    service.models.provider = lambda spec: FakeProvider()
    now = [0.0]
    sessions = PrivateSessions(service, SETTINGS, clock=lambda: now[0])
    unused, used, held = sessions.open(), sessions.open(), sessions.open()
    sessions.get(used.token)
    add_document(held, make_doc("direction", "SYNTHETIC text"))
    now[0] = UNUSED_SECONDS + 1
    assert sessions.get(unused.token) is None
    assert sessions.get(used.token) is not None and sessions.get(held.token) is not None


def test_a_session_holds_one_brief_job_and_ending_it_drops_the_job(tmp_path, monkeypatch):
    """S7: on the one brief worker, a newer brief replaces the session's queued one, and
    ending the session drops its queued job; a brief that is running stops before its
    next stage once replaced."""
    import threading

    from fastapi.testclient import TestClient

    from perch.api import create_app
    from perch.jobs import InProcessRunner

    _, service = private_app(tmp_path, monkeypatch)
    runner = InProcessRunner()
    c = TestClient(create_app(service, runner, web_dir=None))
    gate = threading.Event()
    runner.submit("blocker", gate.wait)  # the worker is busy with someone else's brief
    ran = []
    real_run = type(service).run

    def spy(self, bid):
        ran.append(bid)
        return real_run(self, bid)

    monkeypatch.setattr(type(service), "run", spy)
    req = {"author_id": "A5026494099", "as_of": "2026-10-28", "explain": False}
    a = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    first = c.post("/private/brief", headers=a, json=req).json()["id"]
    second = c.post("/private/brief", headers=a, json=req).json()["id"]
    b = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    dropped = c.post("/private/brief", headers=b, json=req).json()["id"]
    assert c.post("/private/end", headers=b).json()["ended"]
    gate.set()
    runner.wait(f"private-{second}", timeout=60)
    runner.pool.shutdown(wait=True)
    assert ran == [second], (first, dropped)
    assert c.get("/private/brief", headers=a).json()["brief"]["status"] == "done"

    _, _, s = persona_session(tmp_path / "s")
    old = s.service.create_private(None, as_of=date(2026, 10, 28), explain=False)
    s.service.create_private(None, as_of=date(2026, 10, 28), explain=False)
    s.service.run(old.id)  # replaced before it ran: it stops at its first stage
    got, _ = s.service.get(old.id)
    assert got.status == "failed" and got.error.startswith("Stopped:")


def test_records_route_and_scout_never_serve_another_visitors_brief(tmp_path, monkeypatch):
    """S9: briefs and leads in the shared store (stored briefs, the bench) are not served
    through a session's record route or Scout's get_record; the session's own are."""
    from perch.scout.tools import ScoutContext, ToolError, get_record

    c, service = private_app(tmp_path, monkeypatch)
    other = Brief(id="otherBrief1", source="perch", source_url="https://example.org/x",
                  fetched_at="2026-10-28T00:00:00Z", researcher_id="https://openalex.org/A1")
    lead = Lead(id="otherBrief1:1", source="perch", source_url="https://example.org/x",
                fetched_at="2026-10-28T00:00:00Z", brief_id="otherBrief1", route="A",
                record_id="grants_gov:PAR-25-268")
    with service.repo() as r:
        r.upsert([other, lead])
    h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    c.post("/private/brief", headers=h, json={"author_id": "A5026494099",
                                              "as_of": "2026-10-28", "explain": False})
    mine = c.get("/private/brief", headers=h).json()["brief"]["id"]
    for rid in ("otherBrief1", "otherBrief1:1"):
        assert c.get(f"/private/records/{rid}", headers=h).status_code == 404
    assert c.get(f"/private/records/{mine}", headers=h).status_code == 200
    assert c.get("/private/records/PAR-25-268", headers=h).status_code == 200
    ctx = ScoutContext(service, date(2026, 10, 28), brief_id=mine)
    with pytest.raises(ToolError):
        get_record(ctx, "otherBrief1:1")
    assert get_record(ctx, "grants_gov:PAR-25-268")["kind"] == "opportunity"


def test_cloud_hand_offs_count_against_the_daily_cap(tmp_path, monkeypatch):
    """S17: a Cloud hand-off draft is a cloud call too, so it takes one of the day's."""
    monkeypatch.setenv("PERCH_CLOUD", "anthropic:claude-sonnet-5-5")
    monkeypatch.setenv("PERCH_CLOUD_BRIEFS_PER_DAY", "1")
    c, _ = private_app(tmp_path, monkeypatch)
    h = {"X-Perch-Private": c.post("/private/session").json()["token"]}
    c.post("/private/cloud", headers=h, json={"on": True, "confirm": "Anthropic"})
    body = {"author_id": "A5026494099", "as_of": "2026-10-28", "explain": False}
    assert c.post("/private/brief", headers=h, json=body).status_code == 202  # no model call
    office = {"office": "research_development"}
    assert c.post("/private/handoff", headers=h, json=office).status_code == 200
    r = c.post("/private/handoff", headers=h, json=office)
    assert r.status_code == 429 and "hand-off drafts for today" in r.json()["detail"]
    c.post("/private/cloud", headers=h, json={"on": False})
    assert c.post("/private/handoff", headers=h, json=office).status_code == 200  # local


def test_parallel_cloud_calls_cannot_pass_the_cap_together(tmp_path):
    """S17: each call reserves its largest likely cost before it is sent, so calls in
    flight count against the cap."""
    from perch.llm.budget import Budget, BudgetExceeded

    b = Budget(limit=0.01, path=tmp_path / "spend.jsonl")
    with b.reserve(0.012):  # one call in flight that may cost more than what is left
        with pytest.raises(BudgetExceeded), b.reserve(0.001):
            pass
    with b.reserve(0.001):  # once it has finished, the next call may go
        pass
