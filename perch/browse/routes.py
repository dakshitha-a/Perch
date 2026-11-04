"""Public browse routes (ARCHITECTURE_V1 sections 7.4 and 9.2, S43 design section 10).

GET /awards, /opportunities, /filters and /samples need no session: a guest or a signed-out
visitor may read them. They are thin wrappers over `Repository.browse` and `facets`.

Rules kept here:
  * Rule 3: every amount, date and deadline in a response is a record field or a column code
    derived from one. A field a record does not state is null, never filled in.
  * Rule 4: every item carries source, source_url and fetched_at.
  * Rule 11: /awards and /opportunities read the public store, which never lists a sample;
    /samples reads only the committed SYNTHETIC file. The two never share a response.
  * Fork F5: with a school selected, /awards and /opportunities return two labelled groups,
    the school's own records and then the records open across Temple, never one mixed list.
  * Fork F2: a record on a Temple page with no stated scope has scope "unstated" and
    scope_not_stated true, so the card can say "Scope not stated on the page".

Unauthenticated reads are rate limited per client address (section 4.3, scope api_read) when
the app has Redis; the fallback app, which has none, is not limited here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Annotated, Literal

import redis
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from perch import redisx
from perch.schemas import Opportunity, Record, Scholarship
from perch.scholarships import read_samples
from perch.store.base import Repository
from perch.store.denorm import columns

log = logging.getLogger("perch.browse")

OPEN_SCOPES = ("temple_wide", "unstated")  # "Open across Temple" (F5; unstated per F2)
OPEN_LABEL = "Open across Temple"
SAMPLE_NOTE = "These are invented records from a test corpus. Do not apply to them."
Audience = Literal["student", "researcher"]
KINDS: dict[str, type[Record]] = {"student": Scholarship, "researcher": Opportunity}

Q = Query(default=None, max_length=200)


def item(r: Record) -> dict:
    """One record for a list: its own fields, provenance included, plus the filter columns
    code derived from them. `scope` is the derived value ("unstated" when the page states
    none), so the stated scope is not lost: it is the same unless it is "unstated"."""
    c = columns(r)
    out = r.model_dump(mode="json", exclude={"description"})
    out.update(kind=r.kind, scope=c.scope, scope_not_stated=c.scope == "unstated",
               schools=c.schools, levels=c.audience_level,
               deadline=c.deadline.isoformat() if c.deadline else None,
               amount_max=c.amount_max, sample=r.source == "synthetic")
    return out


def make_router(repo_factory: Callable[[], Repository]) -> APIRouter:
    router = APIRouter()

    def limited(request: Request) -> None:
        store = getattr(request.app.state, "sessions", None)
        if store is None:
            return
        try:
            ok, retry = redisx.rate_limit(store.r, "api_read",
                                          redisx.hash_subject(redisx.client_addr(request)))
        except redis.RedisError as e:  # a read is not worth a 500; say so in the log
            log.warning("read rate limit skipped err=%s", type(e).__name__)
            return
        if not ok:
            raise HTTPException(429, {"error": "rate_limited"},
                                headers={"Retry-After": str(retry)})

    def listing(cls: type[Record], *, temple_only: bool, school: str | None,
                scope: str | None, level: list[str], q: str | None, closes_after: date | None,
                group: str | None, cursor: str | None, limit: int) -> JSONResponse:
        scopes = [s for s in (scope or "").split(",") if s]
        common = dict(audience_level=level, q=q, closes_after=closes_after, limit=limit)
        specs: list[tuple[str, str, dict]]  # key, label, browse arguments
        if school:
            specs = [("school", school, {"schools": [school], "temple_only": temple_only}),
                     ("open", OPEN_LABEL, {"scopes": OPEN_SCOPES, "exclude_schools": [school],
                                           "temple_only": temple_only})]
        else:
            specs = [("all", "", {"scopes": scopes, "temple_only": temple_only})]
        groups = []
        with repo_factory() as repo:
            for key, label, args in specs:
                if len(specs) > 1 and group and group != key:
                    continue  # a "load more" for one group asks for that group alone
                page = repo.browse(cls, **common, **args,
                                   cursor=cursor if group == key or len(specs) == 1 else None)
                groups.append({"key": key, "label": label or None, "total": page.total,
                               "next_cursor": page.next_cursor,
                               "items": [item(r) for r in page.items]})
        if not groups:  # only a name that matches neither group of a school view
            raise HTTPException(422, {"error": "unknown_group"})
        return JSONResponse({"kind": cls.kind, "groups": groups})

    def route(cls: type[Record]):  # noqa: ANN202
        def handler(request: Request,
                    temple_only: bool = False,
                    school: Annotated[str | None, Query(max_length=120)] = None,
                    scope: Annotated[str | None, Query(max_length=80)] = None,
                    level: Annotated[list[str] | None, Query(max_length=10)] = None,
                    q: Annotated[str | None, Query(max_length=200)] = None,
                    closes_after: date | None = None,
                    group: Annotated[str | None, Query(max_length=10)] = None,
                    cursor: Annotated[str | None, Query(max_length=400)] = None,
                    limit: Annotated[int, Query(ge=1, le=100)] = 50) -> JSONResponse:
            limited(request)
            try:
                return listing(cls, temple_only=temple_only, school=school, scope=scope,
                               level=level or [], q=q, closes_after=closes_after, group=group,
                               cursor=cursor, limit=limit)
            except (ValueError, UnicodeError) as e:  # a cursor that is not ours
                raise HTTPException(422, {"error": "bad_cursor"}) from e
        return handler

    router.add_api_route("/awards", route(Scholarship), methods=["GET"])
    router.add_api_route("/opportunities", route(Opportunity), methods=["GET"])

    @router.get("/filters")
    def filters(request: Request, audience: Audience = "student") -> JSONResponse:
        limited(request)
        with repo_factory() as repo:
            f = repo.facets(KINDS[audience])
        return JSONResponse({"audience": audience,
                             "schools": [{"name": n, "count": c} for n, c in f.schools],
                             "levels": f.levels, "total": f.total,
                             "temple_total": f.temple_total})

    @router.get("/samples")
    def samples(request: Request, audience: Audience = "student",
                cursor: Annotated[str | None, Query(max_length=400)] = None,
                limit: Annotated[int, Query(ge=1, le=100)] = 50) -> JSONResponse:
        limited(request)
        # Only the committed SYNTHETIC file: no public store is read, so no public record can
        # reach this list (rule 11). There are no sample funding opportunities, so the
        # researcher list is empty.
        recs = sorted(read_samples(), key=lambda r: r.id) if audience == "student" else []
        recs = [r for r in recs if cursor is None or r.id > cursor]
        page = recs[:limit]
        return JSONResponse({"audience": audience, "sample": True, "notice": SAMPLE_NOTE,
                             "total": len(recs) if cursor is None else None,
                             "next_cursor": page[-1].id if len(recs) > limit else None,
                             "items": [item(r) for r in page]})

    return router
