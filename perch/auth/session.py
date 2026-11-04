"""Sessions in Redis (ARCHITECTURE_V1 sections 7.1 and 7.3). S41 seam: the dataclass fields are
fixed (one defaulted field, consent_version, was added at the end; see deps.require_consent)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import redis

from perch import redisx as rx

if TYPE_CHECKING:
    from perch.auth.base import Identity

Audience = Literal["researcher", "student"]


@dataclass
class Session:
    sid: str
    user_id: UUID | None  # None for a guest
    guest: bool
    roles: frozenset[str]  # any of "student", "researcher", "staff"; empty for a guest
    audience: Audience
    csrf: str
    display_name: str | None
    created: float
    abs_exp: float
    consent_version: int = 0  # accepted consent version, 0 when none or withdrawn


def guest_sid_hash(sid: str) -> bytes:
    """sha256(PERCH_PEPPER_GUEST + sid), the value in jobs.guest_sid_hash (section 4.1)."""
    return bytes.fromhex(rx.hash_subject(sid))


def _audience(v: str) -> Audience:
    return "student" if v == "student" else "researcher"


def _roles(v: str) -> frozenset[str]:
    return frozenset(x for x in v.split(",") if x)


class SessionStore:
    """The session hash perch:sess:<sid> (section 4.1) behind the section 7.1 interface.
    Redis calls are single round trips to a local server, so they run inline."""

    def __init__(self, r: redis.Redis) -> None:
        self.r = r

    async def create_user(self, user_id: UUID, roles: frozenset[str] | set[str] | list[str],
                          identity: Identity, *, audience: Audience | None = None,
                          consent_version: int = 0) -> Session:
        held = sorted(roles)
        aud = audience or ("student" if held == ["student"] else "researcher")
        sid, _ = rx.create_session(self.r, uid=user_id, roles=held, audience=aud,
                                   name=identity.display_name or "")
        self.r.hset(f"{rx.PREFIX}:sess:{sid}", "consent", str(consent_version))
        s = await self.get(sid)
        assert s is not None
        return s

    async def create_guest(self, audience: Audience) -> Session:
        sid, _ = rx.create_session(self.r, guest=True, audience=audience)
        self.r.hset(f"{rx.PREFIX}:sess:{sid}", "gsid_hash", rx.hash_subject(sid))
        s = await self.get(sid)
        assert s is not None
        return s

    async def get(self, sid: str, *, now: float | None = None) -> Session | None:
        """The session, with the idle timeout slid (guests never slide) and abs_exp checked."""
        if not sid or len(sid) > 128:
            return None
        h = rx.get_session(self.r, sid, now=now)
        if h is None:
            return None
        if not rx.touch_session(self.r, sid, now=now):
            return None
        guest = h.get("guest") == "1"
        return Session(
            sid=sid, user_id=None if guest or not h.get("uid") else UUID(h["uid"]), guest=guest,
            roles=_roles(h.get("roles", "")), audience=_audience(h.get("audience", "")),
            csrf=h.get("csrf", ""), display_name=h.get("name") or None,
            created=float(h.get("created", "0")), abs_exp=float(h.get("abs_exp", "0")),
            consent_version=int(h.get("consent", "0") or 0))

    async def set_audience(self, sid: str, audience: Audience) -> None:
        if self.r.exists(f"{rx.PREFIX}:sess:{sid}"):
            self.r.hset(f"{rx.PREFIX}:sess:{sid}", "audience", audience)

    async def set_roles(self, sid: str, roles: frozenset[str] | set[str]) -> None:
        if self.r.exists(f"{rx.PREFIX}:sess:{sid}"):
            self.r.hset(f"{rx.PREFIX}:sess:{sid}", "roles", ",".join(sorted(roles)))

    async def set_consent(self, sid: str, version: int) -> None:
        if self.r.exists(f"{rx.PREFIX}:sess:{sid}"):
            self.r.hset(f"{rx.PREFIX}:sess:{sid}", "consent", str(version))

    async def set_consent_all(self, user_id: UUID, version: int) -> None:
        """Every live session of the user, so a withdrawal in one browser binds the others."""
        for sid in self.r.smembers(f"{rx.PREFIX}:usess:{user_id}"):
            await self.set_consent(sid, version)

    async def destroy(self, sid: str) -> None:
        if sid:
            rx.destroy_session(self.r, sid)

    async def destroy_all(self, user_id: UUID) -> int:
        return rx.destroy_user_sessions(self.r, user_id)

    def csrf_ok(self, s: Session, token: str | None) -> bool:
        return rx.csrf_ok({"csrf": s.csrf}, token)


