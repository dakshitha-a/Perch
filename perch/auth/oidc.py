"""OpenID Connect sign-in (ARCHITECTURE_V1 sections 7.1 and 7.2): authorisation code flow with
PKCE S256, a browser binder, and ID token checks done here with `cryptography`.

The ID token is verified with an algorithm allowlist (RS256, ES256), the JWKS key chosen by
`kid` and `use`, and the claim checks of section 7.2. Nothing here logs a token, a code, a
verifier, a binder or a claim.

Deviation from section 4.1, noted in the report: `perch:oidc:<state>` holds one JSON string and
not a hash, because GETDEL works on strings only and single use is the point of the key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

import httpx
import redis
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from perch.auth import settings
from perch.auth.base import AuthError, AuthProvider, AuthRedirect, Identity, safe_return_to
from perch.config import env

ALLOWED_ALGS = ("RS256", "ES256")
SKEW_S = 60
JWKS_REFRESH_MIN_S = 60
STATE_TTL_S = 600


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwk_public_key(jwk: Mapping[str, Any]) -> rsa.RSAPublicKey | ec.EllipticCurvePublicKey:
    kty = jwk.get("kty")
    if kty == "RSA":
        return rsa.RSAPublicNumbers(int.from_bytes(_b64d(jwk["e"]), "big"),
                                    int.from_bytes(_b64d(jwk["n"]), "big")).public_key()
    if kty == "EC" and jwk.get("crv") == "P-256":
        return ec.EllipticCurvePublicNumbers(int.from_bytes(_b64d(jwk["x"]), "big"),
                                             int.from_bytes(_b64d(jwk["y"]), "big"),
                                             ec.SECP256R1()).public_key()
    raise AuthError("bad_token")


def _verify_signature(alg: str, jwk: Mapping[str, Any], signing_input: bytes, sig: bytes) -> None:
    key = _jwk_public_key(jwk)
    try:
        if alg == "RS256":
            if not isinstance(key, rsa.RSAPublicKey):
                raise AuthError("bad_token")
            key.verify(sig, signing_input, padding.PKCS1v15(), hashes.SHA256())
        else:  # ES256: the JWS signature is raw r||s, 64 bytes
            if not isinstance(key, ec.EllipticCurvePublicKey) or len(sig) != 64:
                raise AuthError("bad_token")
            der = encode_dss_signature(int.from_bytes(sig[:32], "big"),
                                       int.from_bytes(sig[32:], "big"))
            key.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise AuthError("bad_token") from e


def parse_header(token: str) -> tuple[dict[str, Any], bytes, bytes, dict[str, Any]]:
    """Split a compact JWS. Returns (header, signing_input, signature, payload). The algorithm
    is allowlisted here, before any key is looked at."""
    try:
        h64, p64, s64 = token.split(".")
        header = json.loads(_b64d(h64))
        payload = json.loads(_b64d(p64))
        sig = _b64d(s64)
    except (ValueError, TypeError) as e:
        raise AuthError("bad_token") from e
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise AuthError("bad_token")
    if header.get("alg") not in ALLOWED_ALGS:  # refuses none, HS256 and everything else
        raise AuthError("bad_token")
    return header, f"{h64}.{p64}".encode(), sig, payload


def check_claims(c: Mapping[str, Any], *, issuer: str, client_id: str, nonce: str,
                 now: float) -> None:
    if c.get("iss") != issuer:
        raise AuthError("bad_token")
    aud = c.get("aud")
    auds = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
    if client_id not in auds:
        raise AuthError("bad_token")
    if "azp" in c and c["azp"] != client_id:
        raise AuthError("bad_token")
    if len(auds) > 1 and c.get("azp") != client_id:
        raise AuthError("bad_token")
    exp, iat = c.get("exp"), c.get("iat")
    if not isinstance(exp, int | float) or not isinstance(iat, int | float):
        raise AuthError("bad_token")
    if exp < now - SKEW_S or iat > now + SKEW_S:
        raise AuthError("bad_token")
    n = c.get("nonce")
    if not isinstance(n, str) or not hmac.compare_digest(n.encode(), nonce.encode()):
        raise AuthError("bad_token")
    if not isinstance(c.get("sub"), str) or not c["sub"]:
        raise AuthError("bad_token")


class OidcProvider(AuthProvider):
    name = "oidc"

    def __init__(self, r: redis.Redis, *, issuer: str, client_id: str,
                 client_secret: str | None, public_url: str, scopes: str = "openid profile",
                 http: httpx.AsyncClient | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.r = r
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self._csec = client_secret
        self.public_url = public_url.rstrip("/")
        self.scopes = scopes
        self.http = http or httpx.AsyncClient(timeout=10.0, follow_redirects=False)
        self.clock = clock
        self._disc: dict[str, Any] | None = None
        self._keys: list[dict[str, Any]] = []
        self._keys_at = 0.0

    @classmethod
    def from_env(cls, r: redis.Redis, http: httpx.AsyncClient | None = None) -> OidcProvider:
        issuer, cid = env("PERCH_OIDC_ISSUER"), env("PERCH_OIDC_CLIENT_ID")
        if not issuer or not cid:
            raise RuntimeError("PERCH_OIDC_ISSUER and PERCH_OIDC_CLIENT_ID are required")
        if env("PERCH_ENV") == "prod" and not issuer.startswith("https://"):
            raise RuntimeError("PERCH_OIDC_ISSUER must be https in prod")
        return cls(r, issuer=issuer, client_id=cid, client_secret=env("PERCH_OIDC_CLIENT_SECRET"),
                   public_url=settings.public_url(),
                   scopes=env("PERCH_OIDC_SCOPES", "openid profile") or "openid profile", http=http)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"

    # --- discovery and keys ---

    async def discovery(self) -> dict[str, Any]:
        if self._disc is None:
            try:
                resp = await self.http.get(f"{self.issuer}/.well-known/openid-configuration")
                resp.raise_for_status()
                d = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                raise AuthError("idp_unreachable") from e
            if d.get("issuer") != self.issuer:
                raise AuthError("idp_misconfigured")
            self._disc = d
        return self._disc

    async def _refresh_keys(self) -> None:
        d = await self.discovery()
        try:
            resp = await self.http.get(d["jwks_uri"])
            resp.raise_for_status()
            self._keys = list(resp.json()["keys"])
        except (httpx.HTTPError, ValueError, KeyError) as e:
            raise AuthError("idp_unreachable") from e
        self._keys_at = self.clock()

    def _find(self, kid: str | None, alg: str) -> dict[str, Any] | None:
        for k in self._keys:
            if kid is not None and k.get("kid") != kid:
                continue
            if k.get("use") not in (None, "sig"):  # skip the realm's encryption key
                continue
            if k.get("alg") not in (None, alg):
                continue
            return k
        return None

    async def _key_for(self, header: Mapping[str, Any]) -> dict[str, Any]:
        kid, alg = header.get("kid"), header["alg"]
        if not self._keys:
            await self._refresh_keys()
        k = self._find(kid, alg)
        if k is None and self.clock() - self._keys_at >= JWKS_REFRESH_MIN_S:
            await self._refresh_keys()  # an unknown kid: refresh once a minute at most
            k = self._find(kid, alg)
        if k is None:
            raise AuthError("bad_token")
        return k

    # --- the interface ---

    async def begin(self, return_to: str) -> AuthRedirect:
        d = await self.discovery()
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, binder = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        self.r.set(f"perch:oidc:{state}", json.dumps({
            "nonce": nonce, "code_verifier": verifier, "return_to": safe_return_to(return_to),
            "binder_sha256": hashlib.sha256(binder.encode()).hexdigest()}), ex=STATE_TTL_S)
        challenge = _b64e(hashlib.sha256(verifier.encode()).digest())
        q = urlencode({"response_type": "code", "client_id": self.client_id,
                       "redirect_uri": self.redirect_uri, "scope": self.scopes, "state": state,
                       "nonce": nonce, "code_challenge": challenge,
                       "code_challenge_method": "S256"})
        return AuthRedirect(f"{d['authorization_endpoint']}?{q}", state, binder)

    async def complete(self, params: Mapping[str, str],
                       binder: str | None) -> tuple[Identity, str]:
        state = params.get("state")
        if not state or len(state) > 200:
            raise AuthError("state_missing")
        raw = self.r.getdel(f"perch:oidc:{state}")  # single use, even when a later check fails
        if raw is None:
            raise AuthError("state_unknown")
        try:
            st = json.loads(raw)
        except ValueError as e:
            raise AuthError("state_unknown") from e
        if not binder or not hmac.compare_digest(
                hashlib.sha256(binder.encode()).hexdigest().encode(),
                str(st.get("binder_sha256", "")).encode()):
            raise AuthError("binder_mismatch")
        if "error" in params:
            raise AuthError("idp_error")
        code = params.get("code")
        if not code:
            raise AuthError("code_missing")
        d = await self.discovery()
        form = {"grant_type": "authorization_code", "code": code,
                "redirect_uri": self.redirect_uri, "client_id": self.client_id,
                "code_verifier": st["code_verifier"]}
        if self._csec:
            form["client_secret"] = self._csec
        try:
            resp = await self.http.post(d["token_endpoint"], data=form)
            tok = resp.json() if resp.status_code == 200 else None
        except (httpx.HTTPError, ValueError) as e:
            raise AuthError("token_exchange_failed") from e
        if not isinstance(tok, dict) or not isinstance(tok.get("id_token"), str):
            raise AuthError("token_exchange_failed")
        claims = await self.validate_id_token(tok["id_token"], st["nonce"])
        name = claims.get("name") or claims.get("preferred_username")
        ident = Identity(self.issuer, claims["sub"],
                         str(name)[:100] if isinstance(name, str) and name else None, claims)
        return ident, safe_return_to(st.get("return_to"))

    async def validate_id_token(self, token: str, nonce: str) -> dict[str, Any]:
        header, signing_input, sig, payload = parse_header(token)
        _verify_signature(header["alg"], await self._key_for(header), signing_input, sig)
        check_claims(payload, issuer=self.issuer, client_id=self.client_id, nonce=nonce,
                     now=self.clock())
        return payload

    async def end_session_url(self, post_logout_redirect: str) -> str | None:
        d = await self.discovery()
        ep = d.get("end_session_endpoint")
        if not ep:
            return None
        return ep + "?" + urlencode({"client_id": self.client_id,
                                      "post_logout_redirect_uri": post_logout_redirect})
