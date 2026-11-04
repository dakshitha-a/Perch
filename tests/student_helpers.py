"""A student (or researcher) brief on the account path, run on a real worker. SYNTHETIC text only.

Needs the test Postgres and Redis (`make test-user`). The fixtures `env`, `rds` come from
tests/test_user_account.py; this module builds the app, adds a persona's CV and entries as the
signed-in user, and runs the brief job on a worker with the fake models.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from perch import jobs
from perch.auth import accounts, deps
from perch.llm.fake import FakeProvider
from perch.retrieve import index_opportunities
from perch.sources import temple
from perch.student import achievements
from perch.user import docs
from tests.test_api import make
from tests.test_user_account import REDIS_URL, job_state, run_worker

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data/synthetic"
PERSONAS = ("persona-ug", "persona-masters", "persona-phd")
AS_OF = "2026-11-06"


def student_reply(messages, system, schema):
    """A valid fit explanation citing the record shown and the first achievement."""
    if schema and "fit" in schema.get("properties", {}):
        rid = re.search(r"Opportunity:\n\[([^\]]+)\]", messages[-1].content).group(1)
        assert "[user:achievement-a]" in system
        pid = "achievement-a"  # models drop the "user:" prefix; the skill maps it back
        return json.dumps({
            "reasoning": "r", "fit": 60,
            "opportunity_sentence": f"The award supports students in this field [{rid}].",
            "research_findings": [{"paper_id": pid, "finding": "presented a poster"}],
            "link_sentence": "The student's work matches the award.",
            "cited_ids": [rid, pid]})
    return ""


def canaries(name: str) -> list[str]:
    files = ("cv.md", "interests.md", "achievements.md")
    return [re.search(r"PERCH-CANARY-[A-Z0-9-]+", (SYN / name / f).read_text()).group(0)
            for f in files]


def add_persona(env, name: str, audience: str = "student") -> None:
    """The persona's CV, interests note and each achievement as an entry, stored encrypted."""
    docs.add(env.ud, env.uid, audience, "cv", text=(SYN / name / "cv.md").read_text())
    docs.add(env.ud, env.uid, audience, "interests",
             text=(SYN / name / "interests.md").read_text())
    for item in achievements((SYN / name / "achievements.md").read_text()):
        docs.add(env.ud, env.uid, audience, "entry", text=item)


def consent(env, monkeypatch) -> None:
    monkeypatch.setenv("PERCH_CONSENT_PROVIDER_NAME", "SYNTHETIC Provider")
    accounts.add_consent(env.pool, env.uid, 1, "SYNTHETIC Provider")


def account_app(env, tmp_path, monkeypatch, responder=student_reply):
    """(client, service): the API with the test account's services and the fake models, a
    fellowship listing, an opportunity and the SYNTHETIC sample store in tmp_path."""
    from perch.api import create_app
    from perch.jobs import InlineRunner

    monkeypatch.setenv("PERCH_REDIS_URL", REDIS_URL)
    monkeypatch.setenv("PERCH_SAMPLE_DB", str(tmp_path / "sample.db"))
    _, svc = make(tmp_path)
    with svc.repo() as r:
        index_opportunities(r, svc.models.get("index"), svc.models.get("embedder"))
        r.upsert(temple.parse_listing((ROOT / "tests/fixtures/temple/sdfa_find_fellowship.html")
                                      .read_text()))
    svc.models.provider = lambda spec: FakeProvider(responder=responder)
    app = create_app(svc, InlineRunner(), stored_briefs=True, web_dir=None)
    app.state.user_services = env.client.app.state.user_services
    app.dependency_overrides[deps.session_optional] = lambda request: env.session
    app.dependency_overrides[deps.require_csrf] = lambda: None  # CSRF is tested in test_auth
    return TestClient(app), svc


def run_brief(env, svc, c, body: dict | None = None, timeout: int = 60) -> dict:
    """Submit a brief for the test session, run it on a worker, return the finished view."""
    r = c.post("/briefs", json={"as_of": AS_OF, **(body or {})})
    assert r.status_code == 202, r.text
    bid, job = r.json()["id"], r.json()["job_id"]
    jobs.set_brief_service(lambda: svc)
    try:
        run_worker(env.pg, ["brief"], lambda: job_state(env.pg, job) in ("succeeded", "failed"),
                   timeout=timeout)
    finally:
        jobs._brief_service = None
    got = c.get(f"/briefs/{bid}").json()
    got["_id"] = bid
    return got
