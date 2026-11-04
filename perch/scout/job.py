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
from perch.schemas import Lead, Opportunity, Record, Scholarship
from perch.scout import session
from perch.scout.answer import name_index
from perch.scout.read_tools import SavedRef, ScoutData
from perch.scout.turn import ESTIMATE_MICRO, Meter, TurnCancelled, TurnDeps, run_turn
from perch.store import pg
from perch.user import quota
from perch.user.briefs import read_user_brief
from perch.user.data import UserData
from perch.user.models import CvDoc, EntryDoc, SavedItem, UserDoc

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
        out = [(e.label, e.text) for _, e in ud.list(uid, "entry", aud, EntryDoc, limit=20)]
        out += [(d.title, d.abstract or "") for _, d in ud.list(uid, "doc", aud, UserDoc,
                                                                limit=20)]
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
              cancelled: Callable[[], bool] = lambda: False) -> TurnDeps:
    return TurnDeps(data=data, provider_for=providers(service),
                    grounder=lambda: service.models.get("grounder"),
                    names=lambda: award_names(service), meter=meter, handoff=handoff,
                    cancelled=cancelled)


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
        reply = run_turn(turn_deps(service, data, meter, cancelled=ctx.cancelled),
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
