"""Redis layer (ARCHITECTURE_V1 section 4): sessions, CSRF, quotas, rate limits, the response
cache, the shred channel, and the client address.

Redis holds no durable truth. No user text goes in a key or a value: the only user-derived
value is the display name in the session hash. Nothing here logs a value.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode
from uuid import UUID

import redis

from perch.config import env

PREFIX = "perch"
SHRED_CHANNEL = f"{PREFIX}:shred"
DAY_TTL = 172_800
MONTH_TTL = 3_456_000


class QuotaExceeded(Exception):
    def __init__(self, scope: str = "quota") -> None:
        super().__init__(scope)
        self.scope = scope


def get_client(url: str | None = None) -> redis.Redis:
    """A client for PERCH_REDIS_URL. Strings come back as str."""
    u = url or env("PERCH_REDIS_URL")
    if not u:
        raise RuntimeError("PERCH_REDIS_URL is not set")
    return redis.Redis.from_url(u, decode_responses=True)


def _now() -> float:
    return time.time()


# --- sessions (4.1, 7.3) ---

def new_sid() -> str:
    return secrets.token_urlsafe(32)


def create_session(r: redis.Redis, *, uid: UUID | str | None = None, guest: bool = False,
                   roles: Iterable[str] = (), audience: str = "", name: str = "",
                   gsid_hash: str = "", idle_s: int | None = None, abs_s: int | None = None,
                   guest_ttl_s: int | None = None, now: float | None = None) -> tuple[str, str]:
    """Create a session; return (sid, csrf token). A fresh id each time, so a login never
    keeps a pre-login id (fixation). Guests get an absolute TTL and never slide."""
    t = now if now is not None else _now()
    idle = idle_s or int(env("PERCH_SESSION_IDLE_S", "1800") or 1800)
    absolute = abs_s or int(env("PERCH_SESSION_ABSOLUTE_S", "28800") or 28800)
    if guest:
        absolute = guest_ttl_s or int(env("PERCH_GUEST_TTL_S", "3600") or 3600)
    sid, csrf = new_sid(), secrets.token_urlsafe(32)
    key = f"{PREFIX}:sess:{sid}"
    ttl = absolute if guest else min(idle, absolute)
    pipe = r.pipeline()
    pipe.hset(key, mapping={
        "uid": str(uid) if uid else "", "guest": "1" if guest else "0",
        "roles": ",".join(roles), "audience": audience, "csrf": csrf, "name": name,
        "created": str(int(t)), "abs_exp": str(int(t) + absolute), "gsid_hash": gsid_hash,
        "idle_s": str(idle)})
    pipe.expire(key, ttl)
    if uid and not guest:
        pipe.sadd(f"{PREFIX}:usess:{uid}", sid)
        pipe.expire(f"{PREFIX}:usess:{uid}", absolute)
    pipe.execute()
    return sid, csrf


def get_session(r: redis.Redis, sid: str, *, now: float | None = None) -> dict[str, str] | None:
    if not sid:
        return None
    s = r.hgetall(f"{PREFIX}:sess:{sid}")
    if not s:
        return None
    if int(s.get("abs_exp", "0")) <= int(now if now is not None else _now()):
        destroy_session(r, sid)
        return None
    return s


def touch_session(r: redis.Redis, sid: str, *, now: float | None = None) -> bool:
    """Slide the idle timeout, capped by the absolute expiry. Guests never slide."""
    s = get_session(r, sid, now=now)
    if s is None:
        return False
    if s.get("guest") == "1":
        return True
    t = int(now if now is not None else _now())
    left = int(s["abs_exp"]) - t
    return bool(r.expire(f"{PREFIX}:sess:{sid}", max(1, min(int(s.get("idle_s", "1800")), left))))


def destroy_session(r: redis.Redis, sid: str) -> None:
    key = f"{PREFIX}:sess:{sid}"
    uid = r.hget(key, "uid")
    pipe = r.pipeline()
    pipe.delete(key)
    if uid:
        pipe.srem(f"{PREFIX}:usess:{uid}", sid)
    pipe.execute()


def destroy_user_sessions(r: redis.Redis, uid: UUID | str) -> int:
    """End every session of a user (delete-my-data step 3)."""
    ukey = f"{PREFIX}:usess:{uid}"
    sids = list(r.smembers(ukey))
    pipe = r.pipeline()
    for sid in sids:
        pipe.delete(f"{PREFIX}:sess:{sid}")
    pipe.delete(ukey)
    pipe.execute()
    return len(sids)


def csrf_ok(session: Mapping[str, str] | None, token: str | None) -> bool:
    """Synchronizer-token check, constant time."""
    if not session or not token or not session.get("csrf"):
        return False
    return hmac.compare_digest(session["csrf"].encode(), token.encode())


# --- quotas (4.2) ---

_RESERVE = """
-- KEYS: spend_1, inflight_1, spend_2, inflight_2, ...  ARGV: estimate, limit_1, limit_2, ...
local est = tonumber(ARGV[1])
local function used(k)
  local t = redis.call('TYPE', k).ok
  if t == 'hash' then return tonumber(redis.call('HGET', k, 'usd_micro') or '0') end
  if t == 'string' then return tonumber(redis.call('GET', k) or '0') end
  return 0
end
local n = #KEYS / 2
for i = 1, n do
  local spent = used(KEYS[2 * i - 1])
  local fly = tonumber(redis.call('GET', KEYS[2 * i]) or '0')
  if spent + fly + est > tonumber(ARGV[i + 1]) then return i end
end
for i = 1, n do
  redis.call('INCRBY', KEYS[2 * i], est)
  redis.call('EXPIRE', KEYS[2 * i], 900)
end
return 0
"""

_SETTLE = """
-- KEYS: spend_1, inflight_1, ...  ARGV: estimate, cost, in_tok, out_tok, gate, kind_1, ...
local est, cost = tonumber(ARGV[1]), tonumber(ARGV[2])
local n = #KEYS / 2
for i = 1, n do
  local fk, sk = KEYS[2 * i], KEYS[2 * i - 1]
  local left = tonumber(redis.call('GET', fk) or '0') - est
  if left > 0 then redis.call('SET', fk, left, 'EX', 900) else redis.call('DEL', fk) end
  if ARGV[5 + i] == 'h' then
    redis.call('HINCRBY', sk, 'usd_micro', cost)
    redis.call('HINCRBY', sk, 'in_tok', tonumber(ARGV[3]))
    redis.call('HINCRBY', sk, 'out_tok', tonumber(ARGV[4]))
    redis.call('HINCRBY', sk, 'calls', 1)
    redis.call('HINCRBY', sk, 'gate_calls', tonumber(ARGV[5]))
  else
    redis.call('INCRBY', sk, cost)
  end
end
return 1
"""


class Scope:
    """One counter a model call is charged to: a spend key, its in-flight key and a limit."""

    __slots__ = ("hash", "inflight", "limit", "name", "spend", "ttl")

    def __init__(self, name: str, spend: str, limit: int, ttl: int, is_hash: bool) -> None:
        self.name, self.spend, self.limit, self.ttl, self.hash = name, spend, limit, ttl, is_hash
        self.inflight = f"{PREFIX}:inflight:{spend.removeprefix(PREFIX + ':q:')}"


def usd_micro(usd: float) -> int:
    return round(usd * 1_000_000)


def _f(name: str, default: str) -> float:
    return float(env(name, default) or default)


def quota_scopes(*, uid: UUID | str | None = None, gsid_hash: str | None = None,
                 now: datetime | None = None, daily_usd: float | None = None,
                 guest_usd: float | None = None, guest_global_usd: float | None = None,
                 month_usd: float | None = None, addr_hash: str | None = None,
                 guest_addr_usd: float | None = None) -> list[Scope]:
    """The counters that apply to a call: the user, or the guest session plus the guest
    ceiling (and the address's day when `addr_hash`, the hashed client address, is known),
    and always the global month. Defaults come from the environment (section 1.3). The guest
    ceiling times 30 days must stay under the month, or guests alone can spend it."""
    t = now or datetime.now(UTC)
    d = t.strftime("%Y%m%d")
    out: list[Scope] = []
    if uid:
        usd = daily_usd if daily_usd is not None else _f("PERCH_DAILY_BUDGET_USD", "0.50")
        out.append(Scope("user", f"{PREFIX}:q:u:{uid}:{d}", usd_micro(usd), DAY_TTL, True))
    elif gsid_hash:
        usd = guest_usd if guest_usd is not None else _f("PERCH_GUEST_DAILY_BUDGET_USD", "0.10")
        out.append(Scope("guest", f"{PREFIX}:q:gs:{gsid_hash}:{d}", usd_micro(usd), DAY_TTL,
                         True))
        g = (guest_global_usd if guest_global_usd is not None
             else _f("PERCH_GUEST_GLOBAL_DAILY_BUDGET_USD", "3.00"))
        out.append(Scope("guest_global", f"{PREFIX}:q:gglobal:{d}", usd_micro(g), DAY_TTL,
                         False))
        if addr_hash:
            a = (guest_addr_usd if guest_addr_usd is not None
                 else _f("PERCH_GUEST_ADDR_DAILY_BUDGET_USD", "0.30"))
            out.append(Scope("guest_addr", f"{PREFIX}:q:ga:{addr_hash}:{d}", usd_micro(a),
                             DAY_TTL, True))
    m = month_usd if month_usd is not None else _f("PERCH_ANTHROPIC_BUDGET_USD", "100")
    out.append(Scope("global", f"{PREFIX}:q:global:{t.strftime('%Y%m')}", usd_micro(m),
                     MONTH_TTL, False))
    return out


def seed_counter(r: redis.Redis, scope: Scope, usd_micro_spent: int) -> bool:
    """Rebuild a missing counter from the ledger with NX, never overwriting a live one."""
    if scope.hash:
        made = r.hsetnx(scope.spend, "usd_micro", usd_micro_spent)
    else:
        made = r.set(scope.spend, usd_micro_spent, nx=True)
    if made:
        r.expire(scope.spend, scope.ttl)
    return bool(made)


def _keys(scopes: list[Scope]) -> list[str]:
    return [k for s in scopes for k in (s.spend, s.inflight)]


def reserve(r: redis.Redis, scopes: list[Scope], estimate_micro: int) -> None:
    """Reserve `estimate_micro` against every counter, or raise QuotaExceeded."""
    bad = r.eval(_RESERVE, len(scopes) * 2, *_keys(scopes), estimate_micro,
                 *[s.limit for s in scopes])
    if bad:
        raise QuotaExceeded(scopes[int(bad) - 1].name)


def settle(r: redis.Redis, scopes: list[Scope], estimate_micro: int, cost_micro: int, *,
           in_tok: int = 0, out_tok: int = 0, gate: bool = False) -> None:
    """Release the reservation and add the true cost. A gate call costs at least 1."""
    cost = max(cost_micro, 1) if gate else cost_micro
    r.eval(_SETTLE, len(scopes) * 2, *_keys(scopes), estimate_micro, cost, in_tok, out_tok,
           1 if gate else 0, *["h" if s.hash else "s" for s in scopes])
    for s in scopes:
        r.expire(s.spend, s.ttl)


def spent_micro(r: redis.Redis, scope: Scope) -> int:
    v = r.hget(scope.spend, "usd_micro") if scope.hash else r.get(scope.spend)
    return int(v or 0)


# --- rate limits (4.3) ---

# The two *_global caps are only a runaway backstop. Set low, a few addresses could lock out
# everyone (S2); the per-address limits do the real work, and they need PERCH_TRUSTED_PROXIES
# set behind a proxy, else every visitor shares one address.
RATE_DEFAULTS: dict[str, tuple[int, int]] = {
    "login_start": (600, 600), "login_callback": (5, 600), "login_global": (100000, 600),
    "api_read": (300, 60), "api_write": (60, 60), "submit_job": (10, 60), "upload": (20, 600),
    "guest_job": (5, 600), "guest_new_global": (100000, 3600),
}

_RL = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


def rate_table() -> dict[str, tuple[int, int]]:
    t = dict(RATE_DEFAULTS)
    t["guest_new"] = (int(env("PERCH_GUEST_SESSIONS_PER_ADDRESS_HOUR", "60") or 60), 3600)
    if raw := env("PERCH_RATE_LIMITS"):
        for k, v in json.loads(raw).items():
            t[k] = (int(v[0]), int(v[1]))
    return t


def rate_limit(r: redis.Redis, scope: str, subject: str, *, now: float | None = None,
               table: Mapping[str, tuple[int, int]] | None = None) -> tuple[bool, int]:
    """Fixed window. Returns (allowed, retry_after_seconds); retry_after is 0 when allowed."""
    limit, window = (table or rate_table())[scope]
    t = now if now is not None else _now()
    slot = int(t // window)
    n = int(r.eval(_RL, 1, f"{PREFIX}:rl:{scope}:{subject}:{slot}", window))
    if n > limit:
        return False, max(1, int((slot + 1) * window - t))
    return True, 0


def rate_refund(r: redis.Redis, scope: str, subject: str, *, now: float | None = None,
                table: Mapping[str, tuple[int, int]] | None = None) -> None:
    """Give back one hit of the current window, for a request that turned out to create
    nothing (S50 C18: the losing twin of two identical requests). Never below zero."""
    _, window = (table or rate_table())[scope]
    t = now if now is not None else _now()
    key = f"{PREFIX}:rl:{scope}:{subject}:{int(t // window)}"
    if int(r.get(key) or 0) > 0:
        r.decr(key)


# --- response cache (4.4) ---

def canonical_query(qs: str | Mapping[str, str]) -> str:
    pairs = parse_qsl(qs, keep_blank_values=True) if isinstance(qs, str) else list(qs.items())
    return urlencode(sorted(pairs))


def cache_key(epoch: int, route: str, qs: str | Mapping[str, str] = "") -> str:
    h = hashlib.sha256(canonical_query(qs).encode()).hexdigest()
    return f"{PREFIX}:rc:{epoch}:{route}:{h}"


def current_epoch(r: redis.Redis, from_db: Callable[[], int] | None = None) -> int:
    """The ingest epoch; a missing key is read back from Postgres and copied with NX."""
    v = r.get(f"{PREFIX}:epoch")
    if v is not None:
        return int(v)
    n = from_db() if from_db else 0
    r.set(f"{PREFIX}:epoch", n, nx=True)
    return int(r.get(f"{PREFIX}:epoch") or n)


def set_epoch(r: redis.Redis, n: int) -> None:
    """Called after Repository.bump_epoch(): old keys become unreachable at once."""
    r.set(f"{PREFIX}:epoch", n)


def cache_get(r: redis.Redis, epoch: int, route: str,
              qs: str | Mapping[str, str] = "") -> str | None:
    return r.get(cache_key(epoch, route, qs))


def cache_put(r: redis.Redis, epoch: int, route: str, qs: str | Mapping[str, str], body: str,
              ttl: int | None = None) -> None:
    r.set(cache_key(epoch, route, qs), body,
          ex=ttl or int(env("PERCH_RESPONSE_CACHE_TTL_S", "300") or 300))


# --- shred channel (6.6) ---

def publish_shred(r: redis.Redis, user_id: UUID | str) -> int:
    return int(r.publish(SHRED_CHANNEL, str(user_id)))


def listen_shreds(r: redis.Redis, on_user: Callable[[UUID], None]) -> Callable[[], None]:
    """Run a daemon thread that calls on_user for each perch:shred message. Returns stop()."""
    ps = r.pubsub(ignore_subscribe_messages=True)
    ps.subscribe(SHRED_CHANNEL)
    stop = threading.Event()

    def loop() -> None:
        while not stop.is_set():
            try:
                m = ps.get_message(timeout=0.5)
            except Exception:  # noqa: BLE001 - connection dropped; stop quietly
                return
            if m and m.get("type") == "message":
                try:
                    on_user(UUID(str(m["data"])))
                except ValueError:
                    pass

    th = threading.Thread(target=loop, daemon=True, name="perch-shred-sub")
    th.start()

    def close() -> None:
        stop.set()
        th.join(timeout=2)
        ps.close()
        r.close()  # also keeps the client alive: a collected client closes its connections

    return close


# --- client address (7.6) ---

def _nets(spec: str | None) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    return [ipaddress.ip_network(p.strip(), strict=False)
            for p in (spec or "").split(",") if p.strip()]


def _in(addr: str, nets: list[Any]) -> bool:
    try:
        a = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(a in n for n in nets if a.version == n.version)


def _norm(addr: str) -> str:
    try:
        a = ipaddress.ip_address(addr)
    except ValueError:
        return addr
    if a.version == 6:
        return str(ipaddress.ip_network(f"{a}/64", strict=False))
    return str(a)


def client_addr_from(peer: str, xff: str | None, trusted: str | None) -> str:
    """X-Forwarded-For counts only when the direct peer is inside the trusted proxies. Then
    walk from the right, skip trusted hops, and the first hop outside them is the client."""
    nets = _nets(trusted)
    if not nets or not _in(peer, nets) or not xff:
        return _norm(peer)
    for hop in reversed([h.strip() for h in xff.split(",") if h.strip()]):
        if not _in(hop, nets):
            return _norm(hop)
    return _norm(peer)


def client_addr(request: Any) -> str:  # noqa: ANN401
    """The client address for a Starlette or FastAPI request."""
    peer = request.client.host if getattr(request, "client", None) else "0.0.0.0"  # noqa: S104
    return client_addr_from(peer, request.headers.get("x-forwarded-for"),
                            env("PERCH_TRUSTED_PROXIES"))


def hash_subject(value: str, pepper: str | None = None) -> str:
    """Key for a rate limit: sha256(PERCH_PEPPER_GUEST + value), hex."""
    p = pepper if pepper is not None else (env("PERCH_PEPPER_GUEST", "") or "")
    if not p:
        raise RuntimeError("PERCH_PEPPER_GUEST is not set")  # an empty pepper makes keys reversible
    return hashlib.sha256((p + value).encode()).hexdigest()
