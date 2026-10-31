"""Private-mode groundwork (S9; design in docs/design/PRIVATE_MODE.md, built in S13).

Since S23 every brief is a private session, so sessions are on by default.

Settings, read from the environment:
  PERCH_PRIVATE_MODE       "0" turns sessions off (default on); the web app then has no briefs
  PERCH_CLOUD              a cloud model spec a session may turn on, e.g.
                           "anthropic:claude-sonnet-5-5" (default none: Local only)
  PERCH_CLOUD_BRIEFS_PER_DAY  cloud briefs and hand-off drafts the whole server runs per day
                              (default 30)
  PERCH_CLOUD_DOCUMENTS    "1" lets a session send its documents to the cloud provider after
                           a second warning (S24, Q30). Default off: standing rule 1 keeps
                           private text on local models until Dakshitha changes it (Q33).
  PERCH_PUBLIC_CACHE       "0" stops sessions writing public records to the store (default on)
  PERCH_PRIVATE_ENDPOINTS  hosts a private session may send model calls to, comma-separated
                           (default loopback: 127.0.0.1, localhost, ::1)
  PERCH_TLS_AT             where HTTPS is decrypted: "server" (on the Perch server, as with
                           Tailscale Funnel) or "tunnel:<provider>" (named to the user)
  PERCH_PUBLIC_URL         the public address, when the app is served on one
  PERCH_PRIVATE_OPERATOR   who runs the Perch server; the privacy statement names them

`problems()` lists what stops private mode from starting; `perch serve` refuses to start
with private mode on while any remain. `harden_process()` turns core dumps off, so a
crash cannot write memory, which may hold private text, to disk.
"""

from __future__ import annotations

import resource
from dataclasses import dataclass
from urllib.parse import urlsplit

from perch.config import env

LOOPBACK = ("127.0.0.1", "localhost", "::1")


@dataclass(frozen=True)
class PrivateSettings:
    enabled: bool
    endpoints: tuple[str, ...]
    tls_at: str | None
    public_url: str | None
    operator: str | None = None
    cloud_spec: str | None = None
    public_cache: bool = False
    cloud_per_day: int = 30
    cloud_documents: bool = False

    @classmethod
    def from_env(cls) -> PrivateSettings:
        hosts = [h.strip().lower() for h in (env("PERCH_PRIVATE_ENDPOINTS") or "").split(",")
                 if h.strip()]
        return cls(enabled=env("PERCH_PRIVATE_MODE") != "0",
                   endpoints=tuple(hosts) or LOOPBACK,
                   tls_at=env("PERCH_TLS_AT"), public_url=env("PERCH_PUBLIC_URL"),
                   operator=env("PERCH_PRIVATE_OPERATOR"),
                   cloud_spec=env("PERCH_CLOUD") or None,
                   public_cache=env("PERCH_PUBLIC_CACHE") != "0",
                   cloud_per_day=int(env("PERCH_CLOUD_BRIEFS_PER_DAY") or 30),
                   cloud_documents=env("PERCH_CLOUD_DOCUMENTS") == "1")

    @property
    def cloud_provider(self) -> str | None:
        """The company a cloud spec sends text to, named in the warning."""
        if not self.cloud_spec:
            return None
        adapter = self.cloud_spec.partition(":")[0]
        return {"anthropic": "Anthropic"}.get(adapter, adapter)

    def endpoint_allowed(self, url: str) -> bool:
        """True when a model endpoint's host is on the allowlist. Hosted APIs never are,
        unless a deployer lists them, which the S13 refusal test forbids."""
        return (urlsplit(url).hostname or "").lower() in self.endpoints

    def problems(self) -> list[str]:
        out = []
        if self.tls_at and not (self.tls_at == "server" or (
                self.tls_at.startswith("tunnel:") and len(self.tls_at) > len("tunnel:"))):
            out.append('PERCH_TLS_AT must be "server" or "tunnel:<provider>"')
        if self.enabled and self.public_url and not self.tls_at:
            out.append("private mode on a public URL needs PERCH_TLS_AT, so users are told "
                       "where their connection is decrypted")
        if self.enabled and self.public_url and not self.operator:
            out.append("private mode needs PERCH_PRIVATE_OPERATOR, so the privacy statement "
                       "names who runs the server")
        return out

    def statement(self) -> str:
        """The promise shown in the UI (docs/design/PRIVATE_MODE.md)."""
        s = (f"Perch keeps nothing about you. Your brief and anything you add are held in memory "
             f"for this session only and are never saved or logged. Public records a brief "
             f"fetches, such as a researcher's OpenAlex profile, papers and awards, are cached "
             f"on the server with the time they were fetched, so the operator could see that "
             f"a researcher was looked up and when. With Local on, every model "
             f"runs on the Perch server, run by {self.operator or 'the operator of this server'}.")
        if self.tls_at and self.tls_at.startswith("tunnel:"):
            s += (f" Your connection is decrypted by {self.tls_at.split(':', 1)[1]} before it "
                  "reaches the server.")
        return s


LOCAL_ADAPTERS = ("ollama", "openai", "fake")  # self-hosted model servers and the test fake


def http_urls(obj: object, depth: int = 4) -> list[str]:
    """Base URLs of every httpx client reachable from a model object's attributes, so the
    gate sees the endpoint behind a wrapper (cache, decider, remote model)."""
    import httpx

    seen: set[int] = set()
    out: list[str] = []

    def walk(o: object, d: int) -> None:
        if id(o) in seen or d < 0:
            return
        seen.add(id(o))
        if isinstance(o, httpx.Client):
            out.append(str(o.base_url))
            return
        for v in getattr(o, "__dict__", {}).values():
            if not isinstance(v, str | int | float | bool | type(None)):
                walk(v, d - 1)

    walk(obj, depth)
    return out


def refuse_if_not_local(provider: object, private: PrivateSettings) -> None:
    """Private sessions use self-hosted models on allowed endpoints only. Raises
    PermissionError, never falls back."""
    name = getattr(provider, "name", "")
    if name not in LOCAL_ADAPTERS:
        raise PermissionError(f"private sessions cannot use {name}: hosted API (Local)")
    refuse_endpoints(provider, private)


def refuse_endpoints(obj: object, private: PrivateSettings) -> None:
    for url in http_urls(obj):
        if not private.endpoint_allowed(url):
            raise PermissionError(f"private sessions cannot send to {url}: not an allowed "
                                  "endpoint")


def harden_process() -> None:
    """No core dumps from this process or its children."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
