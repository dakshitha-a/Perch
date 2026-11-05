"""Per-call spend metering for job model calls (ARCHITECTURE_V1 section 4.2, S48 review M2).

`SpendMeter` reserves an estimate against the counters that apply before each model call and
settles the true cost after it, then writes one `spend_ledger` row. The counters are the
account's day and the global month for a signed-in job, or the guest session's day, the guest
ceiling and the global month for a guest job (`redisx.quota_scopes`). The reservation is one
Lua call, so parallel calls cannot pass a cap together.

`current_meter` is set by a job handler for the length of the job. `BriefService._audited`
reads it when it builds a provider and binds the meter into the provider object, because the
fit step runs its calls on pool threads where a context variable is not visible.

Ids and numbers only: nothing here sees a prompt or an answer.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

import redis
from psycopg_pool import ConnectionPool

from perch import redisx
from perch.llm import ChatResult, Message, Provider
from perch.llm.base import JsonSchema, Tool
from perch.llm.budget import call_cost
from perch.redisx import QuotaExceeded, Scope
from perch.store import pg

# Micro dollars held before one call, by role; the true cost replaces it after the call.
# Upper estimates from the measured researcher brief (about 0.012 USD summary, 0.008 USD a fit
# call; ARCHITECTURE_V1 4.2.1), so a reservation rarely refuses a call that would have fitted.
ESTIMATE_MICRO: dict[str, int] = {
    "gate": 100, "scout": 30_000, "cover_points": 30_000, "handoff": 30_000,
    "profile_summary": 20_000, "fit_explainer": 15_000,
}
DEFAULT_ESTIMATE_MICRO = 30_000

__all__ = ["ESTIMATE_MICRO", "MeteredProvider", "QuotaExceeded", "SpendMeter", "current_meter",
           "for_job", "metered", "using_meter"]


class SpendMeter:
    """Reserve against every scope, call, settle, write the ledger row."""

    def __init__(self, r: redis.Redis, pool: ConnectionPool | None,
                 scopes: Callable[[], list[Scope]], *, user_id: UUID | None = None,
                 job_id: UUID | None = None) -> None:
        self.r, self.pool, self.scopes = r, pool, scopes
        self.uid, self.job_id = user_id, job_id

    def call(self, role: str, provider: Provider, messages: list[Message], **kw: object
             ) -> ChatResult:
        est = ESTIMATE_MICRO.get(role, DEFAULT_ESTIMATE_MICRO)
        scopes = self.scopes()
        redisx.reserve(self.r, scopes, est)  # raises QuotaExceeded: no call is made
        res: ChatResult | None = None
        timed_out = False
        try:
            res = provider.chat(messages, **kw)
            return res
        except Exception as e:
            timed_out = _timed_out(e)
            raise
        finally:
            gate = role == "gate"
            if res is not None:
                cost = call_cost(res.model, res.usage)
            elif timed_out:  # the provider may have charged for it: count the hold (S49 B25)
                cost = est / 1_000_000
            else:
                cost = 0.0
            redisx.settle(self.r, scopes, est, redisx.usd_micro(cost),
                          in_tok=res.usage.input_tokens if res else 0,
                          out_tok=res.usage.output_tokens if res else 0, gate=gate)
            if res is not None:
                self._ledger(role, res, max(cost, 1e-6) if gate else cost)
            elif timed_out:
                self._ledger(role, ChatResult(
                    text="", provider=getattr(provider, "name", "unknown"),
                    model=getattr(provider, "model", "unknown")), cost)

    def _ledger(self, role: str, res: ChatResult, cost: float) -> None:
        if self.pool is None:
            return
        with pg.public_tx(self.pool) as c:
            c.execute(
                "INSERT INTO spend_ledger (user_id, job_id, role, provider, model, "
                "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (self.uid, self.job_id, role, res.provider, res.model, res.usage.input_tokens,
                 res.usage.output_tokens, res.usage.cache_read_tokens,
                 res.usage.cache_write_tokens, round(cost, 6)))


def _timed_out(e: BaseException) -> bool:
    """A read or request timeout: the request was sent and may have been billed."""
    seen: BaseException | None = e
    for _ in range(4):
        if seen is None:
            break
        if "Timeout" in type(seen).__name__:
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def for_job(r: redis.Redis, pool: ConnectionPool | None, *, user_id: UUID | None,
            guest_sid_hash: bytes | None, job_id: UUID | None) -> SpendMeter | None:
    """The meter for a job's owner: an account, or a guest session. None for a job with
    neither (a public precache job), which the global file ledger still caps."""
    if user_id is not None:
        uid = user_id
        return SpendMeter(r, pool, lambda: redisx.quota_scopes(uid=uid), user_id=uid,
                          job_id=job_id)
    if guest_sid_hash is not None:
        gh = guest_sid_hash.hex()
        # the web stored the hashed address at admission; the worker holds no pepper
        ah = r.get(f"perch:gsess:{gh}:addr") or None
        return SpendMeter(r, pool, lambda: redisx.quota_scopes(gsid_hash=gh, addr_hash=ah),
                          job_id=job_id)
    return None


current_meter: contextvars.ContextVar[SpendMeter | None] = contextvars.ContextVar(
    "perch_spend_meter", default=None)


@contextmanager
def using_meter(meter: SpendMeter | None) -> Iterator[None]:
    reset = current_meter.set(meter)
    try:
        yield
    finally:
        current_meter.reset(reset)


class MeteredProvider(Provider):
    """A provider whose every call goes through one meter, bound when it was built."""

    def __init__(self, inner: Provider, meter: SpendMeter, role: str) -> None:
        self.inner, self.meter, self.role = inner, meter, role
        self.name, self.model, self.capabilities = inner.name, inner.model, inner.capabilities

    def chat(self, messages: list[Message], *, system: str | None = None,
             tools: list[Tool] | None = None, schema: JsonSchema | None = None,
             max_tokens: int = 2048, logprobs: int = 0, cache_system: bool = False
             ) -> ChatResult:
        return self.meter.call(self.role, self.inner, messages, system=system, tools=tools,
                               schema=schema, max_tokens=max_tokens, logprobs=logprobs,
                               cache_system=cache_system)

    def close(self) -> None:
        self.inner.close()


def metered(inner: Provider, role: str) -> Provider:
    """`inner` behind the current job's meter, or `inner` itself when no meter is set."""
    m = current_meter.get()
    return MeteredProvider(inner, m, role) if m is not None else inner
