"""HTTP API (SPEC section 6). Run with `perch serve`.

  GET  /health
  GET  /authors/resolve?q=<name|orcid|id>      candidates for the Find screen
  POST /briefs                                  {"author_id", "as_of"?, "top"?, "explain"?, ...}
  GET  /briefs/{id}                             status, stages, profile, leads with records
  POST /briefs/{id}/leads/{lead_id}/keep        and /dismiss
  GET  /briefs/{id}/export.json                 brief, leads and every record they cite
  GET  /records/{id}                            any stored record, with provenance

Briefs run as background jobs; poll GET /briefs/{id}. Nothing is sent anywhere.
"""

from __future__ import annotations

import re
from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from perch import awards as aw
from perch.jobs import JobRunner
from perch.schemas import Award, Brief, Lead, Opportunity, Record, Researcher
from perch.service import BriefService
from perch.sources import grants_gov
from perch.sources import openalex as oa


class BriefRequest(BaseModel):
    author_id: str = Field(description="OpenAlex author id, e.g. A5023080104")
    as_of: date | None = None
    top: int = Field(10, ge=1, le=25)
    explain: bool = True
    min_amount: float | None = None
    agencies: list[str] = Field(default_factory=list)


def record_json(r: Record) -> dict:
    return {"kind": r.kind, **r.model_dump(mode="json")}


def lead_json(lead: Lead, opp: Opportunity | None) -> dict:
    return {**lead.model_dump(mode="json"),
            "opportunity": opp.model_dump(mode="json", exclude={"description"}) if opp else None}


def create_app(service: BriefService, runner: JobRunner,
               resolver: type[oa.OpenAlexClient] | None = None) -> FastAPI:
    app = FastAPI(title="Perch API", description="See every route to fund your work. "
                  + grants_gov.ATTRIBUTION, version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                       allow_headers=["*"])

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/authors/resolve")
    def resolve(q: str) -> dict:
        with service.clients.openalex() as c:
            if oa.parse_orcid(q):
                found = [c.resolve_by_orcid(q)]
            elif oa.parse_author_id(q) and " " not in q.strip():
                found = [c.get_author(q)]
            else:
                found = c.resolve_by_name(q)
        with service.repo() as r:
            r.upsert(found)
        return {"candidates": [record_json(x) for x in found]}

    @app.post("/briefs", status_code=202)
    def create_brief(req: BriefRequest) -> dict:
        try:
            b = service.create(req.author_id, as_of=req.as_of, top=req.top, explain=req.explain,
                               min_amount=req.min_amount, agencies=req.agencies)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        runner.submit(b.id, lambda: service.run(b.id))
        return {"id": b.id, "status": b.status, "poll": f"/briefs/{b.id}"}

    def load(brief_id: str) -> tuple[Brief, list[Lead]]:
        got = service.get(brief_id)
        if not got:
            raise HTTPException(404, f"no brief {brief_id!r}")
        return got

    @app.get("/briefs/{brief_id}")
    def get_brief(brief_id: str) -> dict:
        b, leads = load(brief_id)
        with service.repo() as r:
            res = r.get(Researcher, b.researcher_id)
            opps = {x.record_id: r.get(Opportunity, x.record_id) for x in leads}
            linked = aw.link_awards(res, r.list(Award), aw.load_overrides(res.id)) if res else []
        awards = [{"key": s.key, "award_number": s.award_number, "agency": s.agency,
                   "title": s.title, "start_date": s.start_date, "end_date": s.end_date,
                   "source_url": s.end_record.source_url if s.end_record else None}
                  for s in aw.summarise(linked) if s.key in set(b.award_ids)]
        return {"brief": b.model_dump(mode="json"),
                "researcher": record_json(res) if res else None, "awards": awards,
                "leads": [lead_json(x, opps.get(x.record_id)) for x in leads],
                "notice": grants_gov.ATTRIBUTION}

    def set_status(brief_id: str, lead_id: str, status: str) -> dict:
        lead = service.set_lead_status(brief_id, lead_id, status)
        if not lead:
            raise HTTPException(404, f"no lead {lead_id!r} in brief {brief_id!r}")
        return lead.model_dump(mode="json")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/keep")
    def keep(brief_id: str, lead_id: str) -> dict:
        return set_status(brief_id, lead_id, "kept")

    @app.post("/briefs/{brief_id}/leads/{lead_id}/dismiss")
    def dismiss(brief_id: str, lead_id: str) -> dict:
        return set_status(brief_id, lead_id, "dismissed")

    @app.get("/briefs/{brief_id}/export.json")
    def export(brief_id: str) -> dict:
        b, leads = load(brief_id)
        ids = {b.researcher_id, *(x.record_id for x in leads)}
        ids |= {f"https://openalex.org/{c}" for x in leads for c in x.cited_ids
                if c.startswith("W")}
        ids |= {f"grants_gov:{c}" for x in leads for c in x.cited_ids if not c.startswith("W")}
        with service.repo() as r:
            records = [record_json(x) for x in (r.get_any(i) for i in sorted(ids)) if x]
        return {"brief": b.model_dump(mode="json"),
                "leads": [x.model_dump(mode="json") for x in leads], "records": records,
                "notice": grants_gov.ATTRIBUTION}

    @app.get("/records/{record_id:path}")
    def get_record(record_id: str) -> dict:
        with service.repo() as r:
            x = r.get_any(record_id)
            if x is None and re.fullmatch(r"[AW]\d+", record_id):  # short OpenAlex id
                x = r.get_any(f"https://openalex.org/{record_id}")
            if x is None:  # an opportunity number, as cited in explanations
                x = r.get_any(f"grants_gov:{record_id}")
        if x is None:
            raise HTTPException(404, f"no record {record_id!r}")
        return record_json(x)

    return app
