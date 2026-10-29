"""Private-mode groundwork (S9; design in docs/design/PRIVATE_MODE.md, built in S13).

Settings, read from the environment:
  PERCH_PRIVATE_MODE       "1" turns private sessions on (default off)
  PERCH_PRIVATE_ENDPOINTS  hosts a private session may send model calls to, comma-separated
                           (default loopback: 127.0.0.1, localhost, ::1)
  PERCH_TLS_AT             where HTTPS is decrypted: "server" (on the Perch server, as with
                           Tailscale Funnel) or "tunnel:<provider>" (named to the user)
  PERCH_PUBLIC_URL         the public address, when the app is served on one

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

    @classmethod
    def from_env(cls) -> PrivateSettings:
        hosts = [h.strip().lower() for h in (env("PERCH_PRIVATE_ENDPOINTS") or "").split(",")
                 if h.strip()]
        return cls(enabled=env("PERCH_PRIVATE_MODE") == "1",
                   endpoints=tuple(hosts) or LOOPBACK,
                   tls_at=env("PERCH_TLS_AT"), public_url=env("PERCH_PUBLIC_URL"))

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
        if self.enabled:
            out.append("private mode is designed but not built yet (S13)")
        return out


def harden_process() -> None:
    """No core dumps from this process or its children."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
