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


def test_canary_leaves_no_trace(tmp_path, monkeypatch, capfd):
    import time

    import httpx

    start = time.time()
    c, service = private_app(tmp_path, monkeypatch)
    sent = []
    real_send = httpx.Client.send

    def spy(self, request, **kw):
        sent.append((request.url.host, request.content or b""))
        return real_send(self, request, **kw)

    monkeypatch.setattr(httpx.Client, "send", spy)
    before = snapshot(tmp_path)
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
    assert snapshot(tmp_path) == before, "a private session wrote to the data directory"
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
