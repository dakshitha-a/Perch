"""The student-mode bench runs a persona in process (S42): inputs from a memory store, the
pipeline on fake models, exports with the sample banner. SYNTHETIC text only; no database."""

from __future__ import annotations

from pathlib import Path

from bench import student_mode as sm
from perch.llm.fake import FakeProvider
from perch.retrieve import index_opportunities
from perch.scholarships import ensure_samples
from perch.sources import temple
from tests.student_helpers import student_reply
from tests.test_api import make

ROOT = Path(__file__).resolve().parents[1]


def test_a_persona_runs_in_process_and_is_scored_against_its_key(tmp_path, monkeypatch):
    monkeypatch.setenv("PERCH_SAMPLE_DB", str(tmp_path / "sample.db"))
    ensure_samples()
    _, svc = make(tmp_path)
    with svc.repo() as r:
        index_opportunities(r, svc.models.get("index"), svc.models.get("embedder"))
        r.upsert(temple.parse_listing((ROOT / "tests/fixtures/temple/sdfa_find_fellowship.html")
                                      .read_text()))
    svc.models.provider = lambda spec: FakeProvider(responder=student_reply)
    got = sm.run_persona(svc, "persona-ug", "2026-11-06")
    assert got["brief"]["brief"]["status"] == "done"
    assert {x["route"] for x in got["brief"]["leads"]} == {"F", "S"}
    assert sm.BANNER in got["exports"]["md"] and sm.BANNER in got["exports"]["html"]
    scored = sm.score("persona-ug", got)
    assert scored["status"] == "done" and len(scored["rows"]) == 8
    m = sm.metrics(scored["rows"])
    assert m["planted"] == 8 and m["retrieved"] > 0
    leak = sm.leakage({"persona-ug": got}, tmp_path)
    assert leak["persona_canary_in_export"] == []
    assert leak["export_without_banner"] == []
