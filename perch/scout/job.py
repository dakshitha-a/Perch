"""The `scout_turn` job and the account-backed inputs of a Scout turn (Phase 8).

Web stores the question as a message in the user's encrypted `scout_session` row and submits a
job whose payload holds two ids: the session row and the message. This worker reads the row,
runs `run_turn`, and appends the answer. The question, the CV text and the answer never enter
the job payload, the job events, the audit log or any log line (ARCHITECTURE_V1 3.5).

`RedisMeter` charges every model call to the account's daily budget in micro dollars and writes
the `spend_ledger` row: reserve before the call, settle after (the gate with a minimum of one
micro dollar, so repeated out-of-scope questions run out).
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

import redis
from psycopg_pool import ConnectionPool

from perch import jobs, redisx
from perch.jobs import JobContext, PermanentError, register
from perch.llm import ChatResult, Message, Provider, spec_for_role
from perch.llm.audit import AuditedProvider
from perch.llm.budget import call_cost
from perch.llm.contacts import blank_contacts
from perch.schemas import Lead, Opportunity, Record, Scholarship
from perch.scout import session
from perch.scout.answer import name_index
from perch.scout.read_tools import SavedRef, ScoutData
from perch.scout.turn import ESTIMATE_MICRO, Meter, TurnCancelled, TurnDeps, run_turn
from perch.store import pg
from perch.user import quota
from perch.user.briefs import read_user_brief
from perch.user.data import UserData
from perch.user.models import CoverPointSet, CvDoc, EntryDoc, SavedItem, UserDoc

if TYPE_CHECKING:
    from perch.service import BriefService

log = logging.getLogger("perch.scout")
NAMES_TTL_S = 600
_names: dict[str, tuple[float, set[str]]] = {}
_names_lock = threading.Lock()


class RedisMeter(Meter):
    """Reserve against the user's day and the global month, call, settle, write the ledger."""

    def __init__(self, r: redis.Redis, pool: ConnectionPool, uid: UUID, job_id: UUID | None
                 ) -> None:
        self.r, self.pool, self.uid, self.job_id = r, pool, uid, job_id

    def call(self, role: str, provider: Provider, messages: list[Message], **kw: object
             ) -> ChatResult:
        est = ESTIMATE_MICRO.get(role, ESTIMATE_MICRO["scout"])
        scopes = quota.reserve_call(self.r, self.uid, est)  # raises QuotaExceeded
        res: ChatResult | None = None
        try:
            res = provider.chat(messages, **kw)
            return res
        finally:
            cost = call_cost(res.model, res.usage) if res else 0.0
            micro = redisx.usd_micro(cost)
            gate = role == "gate"
            quota.settle_call(self.r, scopes, est, micro,
                              in_tok=res.usage.input_tokens if res else 0,
                              out_tok=res.usage.output_tokens if res else 0, gate=gate)
            if res is not None:
                self._ledger(role, res, max(cost, 1e-6) if gate else cost)

    def _ledger(self, role: str, res: ChatResult, cost: float) -> None:
        with pg.public_tx(self.pool) as c:
            c.execute(
                "INSERT INTO spend_ledger (user_id, job_id, role, provider, model, "
                "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (self.uid, self.job_id, role, res.provider, res.model, res.usage.input_tokens,
                 res.usage.output_tokens, res.usage.cache_read_tokens,
                 res.usage.cache_write_tokens, round(cost, 6)))


# --- inputs read from the account ---

def award_names(service: BriefService) -> set[str]:
    """Titles and numbers of every award record, for the General advice check. Cached."""
    now = time.monotonic()
    with _names_lock:
        hit = _names.get("k")
        if hit and now - hit[0] < NAMES_TTL_S:
            return hit[1]
    with service.repo() as r:
        recs: list[Record] = [*r.list(Opportunity), *r.list(Scholarship)]
    names = name_index(recs)
    with _names_lock:
        _names["k"] = (now, names)
    return names


def account_data(ud: UserData, uid: UUID, audience: str, service: BriefService,
                 brief_id: str | None,
                 *, signed_in: bool = True) -> ScoutData:
    """The read callables of one signed-in user, over their encrypted rows."""
    aud: Any = audience

    def brief() -> tuple[Any, list[Lead]] | None:
        sb = read_user_brief(ud, uid, brief_id) if brief_id else None
        return (sb.brief, sb.leads) if sb is not None else None

    def cv_text() -> str | None:
        rows = ud.list(uid, "cv", aud, CvDoc, limit=1)
        return rows[0][1].text if rows else None

    def entries() -> list[tuple[str | None, str]]:
        # A label or a title is user text too: blanked before it can reach a prompt (S45 S5).
        out = [(blank_contacts(e.label) if e.label else e.label, e.text)
               for _, e in ud.list(uid, "entry", aud, EntryDoc, limit=20)]
        out += [(blank_contacts(d.title) if d.title else d.title, d.abstract or "")
                for _, d in ud.list(uid, "doc", aud, UserDoc, limit=20)]
        return out

    def saved() -> list[SavedRef]:
        return [SavedRef(s.record_id, s.note) for _, s in
                ud.list(uid, "saved_item", aud, SavedItem, limit=20)]

    as_of = date.today()
    got = brief()
    if got is not None and got[0].options.get("as_of"):
        as_of = date.fromisoformat(got[0].options["as_of"])
    return ScoutData(repo=service.repo, audience=audience, as_of=as_of, signed_in=signed_in,
                     brief=brief, cv_text=cv_text, entries=entries, saved=saved)


def providers(service: BriefService) -> Callable[[str], Provider]:
    def provider_for(role: str) -> Provider:
        return AuditedProvider(service.models.provider(spec_for_role(role)), service.audit,
                               role)

    return provider_for


def turn_deps(service: BriefService, data: ScoutData, meter: Meter,
              handoff: Callable[[], dict[str, Any] | None] | None = None,
              cancelled: Callable[[], bool] = lambda: False,
              free_gate: Callable[[], bool] = lambda: True) -> TurnDeps:
    return TurnDeps(data=data, provider_for=providers(service),
                    grounder=lambda: service.models.get("grounder"),
                    names=lambda: award_names(service), meter=meter, handoff=handoff,
                    cancelled=cancelled, free_gate=free_gate)


# --- the handler ---

def _redis() -> redis.Redis:
    return redisx.get_client()


@register("scout_turn", max_attempts=2, timeout_s=180, priority=0)
def scout_turn_handler(ctx: JobContext) -> str | None:
    """Answer one question of a Scout session. Buttons never come here: they are answered in the
    web process by code."""
    if ctx.user_id is None or jobs._brief_service is None:  # noqa: SLF001
        raise PermanentError("no_handler")
    try:
        sid, mid = UUID(ctx.payload["session_id"]), str(ctx.payload["message_id"])
    except ValueError:
        raise PermanentError("invalid_input") from None
    uid, service = ctx.user_id, jobs._brief_service()  # noqa: SLF001
    ud = UserData(ctx.pool)
    from perch.auth.accounts import consent_version_of
    from perch.config import env

    with ctx.user_tx() as c:
        if consent_version_of(c, uid) < int(env("PERCH_CONSENT_VERSION", "1") or 1):
            raise PermanentError("consent_required")
        got = session.load(ud, uid, sid, conn=c)
    if got is None:
        raise PermanentError("invalid_input")
    doc, _, audience = got
    ref = f"user_data:{sid}"
    if session.replied(doc, mid):  # a retry after the answer was written
        return ref
    ix = next((i for i, m in enumerate(doc.messages) if m["id"] == mid and m["role"] == "user"),
              None)
    if ix is None or doc.messages[ix]["kind"] != "question":
        raise PermanentError("invalid_input")
    data = account_data(ud, uid, audience, service, doc.brief_id)
    meter = RedisMeter(_redis(), ctx.pool, uid, ctx.job_id)
    ctx.stage("scout", "running")
    try:
        free = functools.partial(quota.free_gate, meter.r, uid)  # S45 S1
        reply = run_turn(turn_deps(service, data, meter, cancelled=ctx.cancelled, free_gate=free),
                         doc.messages[:ix], question=doc.messages[ix]["text"])
    except TurnCancelled:  # stopped between steps: write no answer; the view shows "stopped"
        ctx.stage("scout", "cancelled")
        return ref
    reply["reply_to"] = mid
    reply["at"] = datetime.now(UTC).isoformat()
    with ctx.user_tx() as c:  # lease-fenced: a stale attempt cannot write the answer
        session.append(ud, uid, sid, [reply], conn=c)
    ctx.stage("scout", "done", reply["kind"])
    return ref


# --- the cover_points job (S45) ---

def _cover_target(service: BriefService, record_id: str) -> tuple[Opportunity, Record]:
    """(the record as an Opportunity the skill reads, the record itself)."""
    from perch.student import as_opportunity

    with service.repo() as r:
        rec = r.get_any(record_id)
    if rec is None:  # a SYNTHETIC sample scholarship lives in the sample store (rule 11)
        from perch.user.briefs import _sample

        rec = _sample(record_id)
    if isinstance(rec, Opportunity):
        return rec, rec
    if isinstance(rec, Scholarship):
        return as_opportunity(rec), rec
    raise PermanentError("invalid_input")


@register("cover_points", max_attempts=3, timeout_s=120, priority=1)
def cover_points_handler(ctx: JobContext) -> str | None:
    """Cover points for one lead of the user's brief. The payload holds ids only. The CV and
    entries are read from the user's encrypted rows with contact details blanked; the points
    pass the citation validator (regenerated once, then flagged) and are stored as an
    encrypted `cover_points` row. Nothing goes to `public_cache`."""
    if ctx.user_id is None or jobs._brief_service is None:  # noqa: SLF001
        raise PermanentError("no_handler")
    brief_id, record_id = str(ctx.payload["brief_id"]), str(ctx.payload["record_id"])
    uid, service = ctx.user_id, jobs._brief_service()  # noqa: SLF001
    ud = UserData(ctx.pool)
    from perch.auth.accounts import consent_version_of
    from perch.config import env
    from perch.schemas import Work
    from perch.skills.cover import cover_points
    from perch.student import achievement_docs
    from perch.user.inputs import InputError, make_doc

    with ctx.user_tx() as c:
        if consent_version_of(c, uid) < int(env("PERCH_CONSENT_VERSION", "1") or 1):
            raise PermanentError("consent_required")
    sb = read_user_brief(ud, uid, brief_id)
    lead = next((x for x in sb.leads if x.record_id == record_id), None) if sb else None
    if sb is None or lead is None:
        raise PermanentError("invalid_input")
    audience = "student" if sb.brief.options.get("student") else "researcher"
    o, rec = _cover_target(service, record_id)
    data = account_data(ud, uid, audience, service, brief_id)
    try:
        cv_text = data.cv_text()
        cv = make_doc("cv", cv_text) if cv_text else None  # blanks contact details again
    except InputError:
        cv = None
    others = achievement_docs([t for _, t in data.entries() if t][:5])
    wids = [c for c in lead.cited_ids if c.startswith("W")][:6]
    with service.repo() as r:
        papers = [w for w in (r.get(Work, f"https://openalex.org/{c}") for c in wids) if w]
    meter = RedisMeter(_redis(), ctx.pool, uid, ctx.job_id)
    from perch.scout.turn import Metered

    provider = AuditedProvider(
        Metered(service.models.provider(spec_for_role("cover_points")), meter, "cover_points",
                ctx.cancelled), service.audit, "cover_points")
    ctx.stage("cover_points", "running")
    try:
        v, records = cover_points(o, cv, others, papers, [], provider,
                                  grounder=service.models.get("grounder"),
                                  context=[*lead.verdict_lines, *lead.gaps], audience=audience)
    except redisx.QuotaExceeded:
        raise PermanentError("budget_exceeded") from None
    except TurnCancelled:
        return None
    ids = {k: (rec.id if k == o.opportunity_number else r.id) for k, r in records.items()}
    title = getattr(rec, "title", None) or getattr(rec, "name", None) or rec.id
    out = CoverPointSet(brief_id=brief_id, record_id=record_id, title=title,
                        sample=bool(rec.source == "synthetic"),
                        status="done" if v.value else "withheld")
    if v.value:
        p = v.value
        out.points = [{"asks": x.asks, "asks_ids": [ids.get(i, i) for i in x.asks_ids],
                       "you": x.you, "you_ids": [ids.get(i, i) for i in x.you_ids]}
                      for x in p.points]
        out.missing, out.unsupported = list(p.missing), list(p.unsupported)
        for k in p.used_ids():
            if k in records:
                rr = records[k]
                out.sources[ids[k]] = (getattr(rr, "title", None) or getattr(rr, "name", None)
                                       or rr.id)
    out.sources.setdefault(record_id, title)
    with ctx.user_tx() as c:  # lease-fenced; one stored set per brief and record
        for rid, old in ud.list(uid, "cover_points", audience, CoverPointSet,  # type: ignore[arg-type]
                                limit=100, conn=c):
            if old.brief_id == brief_id and old.record_id == record_id:
                ud.delete(uid, rid, kinds=("cover_points",), conn=c)
        row = ud.put(uid, "cover_points", audience, out, conn=c)  # type: ignore[arg-type]
    ctx.stage("cover_points", "done", out.status)
    return f"user_data:{row}"
