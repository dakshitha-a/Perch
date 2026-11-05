"""Auth settings read from the environment (ARCHITECTURE_V1 sections 1.3 and 7.3).

Functions, not constants, so tests can change the environment between cases.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from perch.config import env

SESSION_COOKIE = "__Host-perch_sid"
SESSION_COOKIE_DEV = "perch_sid"
OIDC_COOKIE = "__Host-perch_oidc"
OIDC_COOKIE_DEV = "perch_oidc"
OIDC_COOKIE_MAX_AGE = 600


def cookie_insecure() -> bool:
    """Dev over plain HTTP. Refused when PERCH_ENV=prod (the doc's rule, enforced here too)."""
    on = env("PERCH_COOKIE_INSECURE") == "1"
    if on and env("PERCH_ENV") == "prod":
        raise RuntimeError("PERCH_COOKIE_INSECURE is refused when PERCH_ENV=prod")
    return on


def session_cookie_name() -> str:
    return SESSION_COOKIE_DEV if cookie_insecure() else SESSION_COOKIE


def oidc_cookie_name() -> str:
    return OIDC_COOKIE_DEV if cookie_insecure() else OIDC_COOKIE


def public_url() -> str:
    return (env("PERCH_PUBLIC_URL") or "").rstrip("/")


def public_origin() -> str | None:
    """scheme://host[:port] of PERCH_PUBLIC_URL, or None when unset."""
    u = public_url()
    p = urlsplit(u)
    if not p.scheme or not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}"


def accounts_open() -> bool:
    """PERCH_ACCOUNTS_OPEN (default 1). 0 when self-registration is off: the landing and the
    walls then lead guests to the sample and the example (S51 D4)."""
    return (env("PERCH_ACCOUNTS_OPEN", "1") or "1").strip() != "0"


def consent_version() -> int:
    return int(env("PERCH_CONSENT_VERSION", "1") or 1)


def consent_provider_name() -> str:
    return env("PERCH_CONSENT_PROVIDER_NAME") or "the contracted model provider"


def _names(var: str) -> frozenset[str]:
    return frozenset(x.strip().lower() for x in (env(var) or "").split(",") if x.strip())


def shared_accounts() -> frozenset[str]:
    """PERCH_SHARED_ACCOUNTS: comma-separated sign-in names (preferred_username) of shared demo
    accounts. Default empty, so no account is shared. Compared in lower case."""
    return _names("PERCH_SHARED_ACCOUNTS")


def is_shared(claims) -> bool:  # noqa: ANN001 - a mapping of OIDC claims
    """True when the sign-in name in the claims is a listed shared account."""
    name = claims.get("preferred_username") if claims else None
    return isinstance(name, str) and name.strip().lower() in shared_accounts()


def shared_subjects() -> list[str]:
    """PERCH_SHARED_SUBJECTS: the identity provider's user ids of the shared accounts, for the
    nightly wipe. The database holds only a hash of the id, never the sign-in name."""
    return [x.strip() for x in (env("PERCH_SHARED_SUBJECTS") or "").split(",") if x.strip()]
