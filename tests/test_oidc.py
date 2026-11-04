# ruff: noqa: E501
"""OidcProvider against the saved Keycloak discovery document and JWKS (tests/fixtures/keycloak,
fetched live from the dev realm; public data) and tokens signed here with generated keys.
No network, no secrets. Needs PERCH_TEST_REDIS_URL (DB 15 only)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from perch import redisx as rx
from perch.auth.base import AuthError
from perch.auth.oidc import OidcProvider, _jwk_public_key

URL = os.environ.get("PERCH_TEST_REDIS_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="PERCH_TEST_REDIS_URL is not set")
FIX = Path(__file__).parent / "fixtures" / "keycloak"
DISC = json.loads((FIX / "discovery.json").read_text())
REAL_JWKS = json.loads((FIX / "jwks.json").read_text())
ISS = DISC["issuer"]
CID = "perch-web"
NOW = 1_800_000_000.0
PUBLIC = "http://127.0.0.1:8190"


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jb64(o: object) -> str:
    return b64(json.dumps(o).encode())


def i2b(n: int) -> bytes:
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


class Key:
    def __init__(self, kind: str, kid: str) -> None:
        self.kind, self.kid = kind, kid
        if kind == "RS256":
            self.priv = rsa.generate_private_key(65537, 2048)
            n = self.priv.public_key().public_numbers()
            self.jwk = {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
                        "n": b64(i2b(n.n)), "e": b64(i2b(n.e))}
        else:
            self.priv = ec.generate_private_key(ec.SECP256R1())
            n = self.priv.public_key().public_numbers()
            self.jwk = {"kty": "EC", "kid": kid, "use": "sig", "alg": "ES256", "crv": "P-256",
                        "x": b64(n.x.to_bytes(32, "big")), "y": b64(n.y.to_bytes(32, "big"))}

    def sign(self, signing_input: bytes) -> bytes:
        if self.kind == "RS256":
            return self.priv.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        r, s = decode_dss_signature(self.priv.sign(signing_input, ec.ECDSA(hashes.SHA256())))
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")


RS = Key("RS256", "k-rs")
ES = Key("ES256", "k-es")


def claims(nonce: str, /, **over: object) -> dict:
    c = {"iss": ISS, "aud": CID, "azp": CID, "sub": "SYNTHETIC-sub", "iat": NOW - 10,
         "exp": NOW + 300, "nonce": nonce, "name": "SYNTHETIC User"}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def token(key: Key, payload: dict, header: dict | None = None) -> str:
    h = {"alg": key.kind, "kid": key.kid, "typ": "JWT"} | (header or {})
    si = f"{jb64(h)}.{jb64(payload)}"
    return f"{si}.{b64(key.sign(si.encode()))}"


class Idp:
    """A mock IdP behind httpx.MockTransport. `id_token` is built per call from the nonce."""

    def __init__(self) -> None:
        self.keys = [RS.jwk, ES.jwk]
        self.id_token = None  # callable(nonce) -> str
        self.token_status = 200
        self.calls: list[tuple[str, str]] = []
        self.forms: list[dict] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.method, req.url.path))
        if req.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json=DISC)
        if req.url.path.endswith("/certs"):
            return httpx.Response(200, json={"keys": self.keys})
        if req.url.path.endswith("/token"):
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            self.forms.append(form)
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            nonce = self._nonce
            return httpx.Response(200, json={"id_token": self.id_token(nonce), "access_token": "x"})
        return httpx.Response(404)

    _nonce = ""


@pytest.fixture
def r():
    assert URL.rstrip("/").endswith("/15")
    c = rx.get_client(URL)
    c.flushdb()
    yield c
    c.flushdb()
    c.close()


@pytest.fixture
def idp() -> Idp:
    return Idp()


def provider(r, idp: Idp, secret: str | None = "SYNTHETIC-not-a-real-secret") -> OidcProvider:
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    return OidcProvider(r, issuer=ISS, client_id=CID, client_secret=secret, public_url=PUBLIC,
                        http=http, clock=lambda: NOW)


async def start(p: OidcProvider, idp: Idp, return_to: str = "/briefs"):
    red = await p.begin(return_to)
    q = parse_qs(urlsplit(red.url).query)
    idp._nonce = q["nonce"][0]
    return red, q


def run(coro):
    return asyncio.run(coro)


async def full(p, idp, make, return_to="/briefs", binder_override=None, **params):
    red, q = await start(p, idp, return_to)
    idp.id_token = make
    return await p.complete({"code": "c", "state": red.state, **params},
                            red.binder if binder_override is None else binder_override)


# --- begin ---

def test_begin_builds_the_authorisation_request_and_stores_only_a_binder_hash(r, idp) -> None:
    async def go():
        p = provider(r, idp)
        red, q = await start(p, idp, "//evil.invalid")
        assert red.url.startswith(DISC["authorization_endpoint"] + "?")
        assert q["response_type"] == ["code"] and q["client_id"] == [CID]
        assert q["redirect_uri"] == [PUBLIC + "/auth/callback"]
        assert q["scope"] == ["openid profile"] and q["code_challenge_method"] == ["S256"]
        assert q["state"] == [red.state] and len(q["nonce"][0]) >= 32
        st = json.loads(r.get(f"perch:oidc:{red.state}"))
        assert r.ttl(f"perch:oidc:{red.state}") <= 600
        assert st["return_to"] == "/"  # an unsafe return_to is replaced before it is stored
        assert st["binder_sha256"] == hashlib.sha256(red.binder.encode()).hexdigest()
        assert red.binder not in json.dumps(st) and red.binder not in red.url
        verifier = st["code_verifier"]
        assert q["code_challenge"] == [b64(hashlib.sha256(verifier.encode()).digest())]
        assert verifier not in red.url
        assert len({red.state, red.binder, q["nonce"][0], verifier}) == 4

    run(go())


# --- the happy path ---

@pytest.mark.parametrize("key", [RS, ES])
def test_complete_returns_identity_and_return_to(r, idp, key: Key) -> None:
    async def go():
        p = provider(r, idp)
        ident, rt = await full(p, idp, lambda n: token(key, claims(n)), "/briefs/1")
        assert (ident.issuer, ident.subject, ident.display_name) == (ISS, "SYNTHETIC-sub", "SYNTHETIC User")
        assert ident.claims["sub"] == "SYNTHETIC-sub" and rt == "/briefs/1"
        form = idp.forms[0]
        assert form["grant_type"] == "authorization_code" and form["code"] == "c"
        assert form["redirect_uri"] == PUBLIC + "/auth/callback" and form["client_id"] == CID
        assert len(form["code_verifier"]) >= 43 and form["client_secret"].startswith("SYNTHETIC")

    run(go())


# --- state and binder ---

def test_state_is_single_use(r, idp) -> None:
    async def go():
        p = provider(r, idp)
        red, _ = await start(p, idp)
        idp.id_token = lambda n: token(RS, claims(n))
        await p.complete({"code": "c", "state": red.state}, red.binder)
        with pytest.raises(AuthError) as e:
            await p.complete({"code": "c", "state": red.state}, red.binder)
        assert e.value.code == "state_unknown"

    run(go())


def test_binder_mismatch_and_missing_burn_the_state(r, idp) -> None:
    async def go():
        p = provider(r, idp)
        for bad in ("someone-elses-binder", None, ""):
            red, _ = await start(p, idp)
            idp.id_token = lambda n: token(RS, claims(n))
            with pytest.raises(AuthError) as e:
                await p.complete({"code": "c", "state": red.state}, bad)
            assert e.value.code == "binder_mismatch"
            assert not r.exists(f"perch:oidc:{red.state}")  # the callback URL is spent
            with pytest.raises(AuthError):
                await p.complete({"code": "c", "state": red.state}, red.binder)
        assert not any(c[1].endswith("/token") for c in idp.calls)  # no code exchange was tried

    run(go())


def test_unknown_missing_and_odd_state(r, idp) -> None:
    async def go():
        p = provider(r, idp)
        for params, code in [({"code": "c", "state": "nope"}, "state_unknown"),
                             ({"code": "c"}, "state_missing"), ({"code": "c", "state": "x" * 500}, "state_missing")]:
            with pytest.raises(AuthError) as e:
                await p.complete(params, "b")
            assert e.value.code == code

    run(go())


def test_idp_error_and_missing_code(r, idp) -> None:
    async def go():
        p = provider(r, idp)
        red, _ = await start(p, idp)
        with pytest.raises(AuthError) as e:
            await p.complete({"error": "access_denied", "state": red.state}, red.binder)
        assert e.value.code == "idp_error"
        red, _ = await start(p, idp)
        with pytest.raises(AuthError) as e:
            await p.complete({"state": red.state}, red.binder)
        assert e.value.code == "code_missing"

    run(go())


def test_token_endpoint_failure(r, idp) -> None:
    async def go():
        idp.token_status = 400
        with pytest.raises(AuthError) as e:
            await full(provider(r, idp), idp, lambda n: "")
        assert e.value.code == "token_exchange_failed"

    run(go())


# --- token validation ---

def bad(r, idp, make, binder_override=None, p=None):
    async def go():
        with pytest.raises(AuthError) as e:
            await full(p or provider(r, idp), idp, make, binder_override=binder_override)
        assert e.value.code == "bad_token"

    run(go())


@pytest.mark.parametrize("over", [
    {"iss": "http://evil.invalid/realms/perch"}, {"aud": "other-client"}, {"aud": ["a", "b"]},
    {"azp": "other-client"}, {"aud": [CID, "b"], "azp": None},
    {"exp": NOW - 61}, {"exp": None}, {"iat": None}, {"iat": NOW + 61}, {"exp": "soon"},
    {"nonce": "another"}, {"nonce": None}, {"sub": None}, {"sub": ""}])
def test_claim_checks(r, idp, over) -> None:
    bad(r, idp, lambda n: token(RS, claims(n, **over)))


def test_clock_skew_of_sixty_seconds_is_allowed(r, idp) -> None:
    async def go():
        await full(provider(r, idp), idp, lambda n: token(RS, claims(n, exp=NOW - 59, iat=NOW + 59)))

    run(go())


def test_aud_list_with_azp_is_accepted(r, idp) -> None:
    async def go():
        await full(provider(r, idp), idp, lambda n: token(RS, claims(n, aud=[CID, "account"])))

    run(go())


def test_alg_none_and_symmetric_algorithms_are_refused(r, idp) -> None:
    def forged(alg: str, sig: bytes):
        return lambda n: f"{jb64({'alg': alg, 'kid': RS.kid})}.{jb64(claims(n))}.{b64(sig)}"

    bad(r, idp, forged("none", b""))
    bad(r, idp, lambda n: f"{jb64({'alg': 'none'})}.{jb64(claims(n))}.")
    bad(r, idp, forged("HS256", b"x" * 32))
    # the classic attack: HS256 signed with the RSA public modulus as the secret
    import hmac

    def hs(n):
        si = f"{jb64({'alg': 'HS256', 'kid': RS.kid})}.{jb64(claims(n))}".encode()
        return si.decode() + "." + b64(hmac.new(RS.jwk["n"].encode(), si, "sha256").digest())

    bad(r, idp, hs)
    bad(r, idp, forged("RS512", b"x"))
    bad(r, idp, forged("PS256", b"x"))


def test_signature_must_match_the_key(r, idp) -> None:
    other = Key("RS256", RS.kid)  # same kid, different key
    bad(r, idp, lambda n: token(other, claims(n)))

    def tampered(n):
        t = token(RS, claims(n))
        h, _, s = t.split(".")
        return f"{h}.{jb64(claims(n, sub='someone-else'))}.{s}"

    bad(r, idp, tampered)
    bad(r, idp, lambda n: token(RS, claims(n))[:-6] + "AAAAAA")
    bad(r, idp, lambda n: "not.a.jwt")
    bad(r, idp, lambda n: "onlyone")
    bad(r, idp, lambda n: "")


def test_es256_needs_a_64_byte_signature_and_the_right_key_type(r, idp) -> None:
    def short(n):
        si = f"{jb64({'alg': 'ES256', 'kid': ES.kid})}.{jb64(claims(n))}"
        return si + "." + b64(b"x" * 63)

    bad(r, idp, short)
    # an ES256 header naming the RSA key's kid is a key-type mismatch
    bad(r, idp, lambda n: token(ES, claims(n), {"kid": RS.kid}))


def test_unknown_kid_refreshes_the_jwks_once_a_minute(r, idp) -> None:
    async def go():
        clock = [NOW]
        http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
        p = OidcProvider(r, issuer=ISS, client_id=CID, client_secret=None, public_url=PUBLIC,
                         http=http, clock=lambda: clock[0])
        rolled = Key("RS256", "k-new")
        idp.keys = [RS.jwk]
        await full(p, idp, lambda n: token(RS, claims(n)))
        certs = lambda: sum(1 for c in idp.calls if c[1].endswith("/certs"))  # noqa: E731
        assert certs() == 1
        # the IdP rolls its key; a token under the new kid inside a minute does not refetch
        idp.keys = [RS.jwk, rolled.jwk]
        with pytest.raises(AuthError):
            await full(p, idp, lambda n: token(rolled, claims(n)))
        assert certs() == 1
        clock[0] += 61  # after a minute the unknown kid triggers exactly one refresh
        ident, _ = await full(p, idp, lambda n: token(rolled, claims(n, iat=clock[0] - 5, exp=clock[0] + 300)))
        assert ident.subject == "SYNTHETIC-sub" and certs() == 2
        # a flood of unknown kids cannot force more than one refresh a minute
        for _ in range(3):
            with pytest.raises(AuthError):
                await full(p, idp, lambda n: token(Key("RS256", "k-junk"), claims(n, iat=clock[0] - 5, exp=clock[0] + 300)))
        assert certs() == 2  # no further refresh inside the same minute

    run(go())


def test_the_realm_encryption_key_is_never_used_to_verify(r, idp) -> None:
    async def go():
        enc_only = [k for k in REAL_JWKS["keys"] if k.get("use") == "enc"]
        assert enc_only, "fixture should contain the realm's RSA-OAEP key"
        forged = Key("RS256", enc_only[0]["kid"])
        idp.keys = [enc_only[0]]
        with pytest.raises(AuthError):
            await full(provider(r, idp), idp, lambda n: token(forged, claims(n)))

    run(go())


# --- fixtures from the live realm ---

def test_live_discovery_and_jwks_fixtures_have_the_shape_the_code_needs() -> None:
    assert DISC["issuer"] == "http://127.0.0.1:8180/realms/perch"
    for k in ("authorization_endpoint", "token_endpoint", "jwks_uri", "end_session_endpoint"):
        assert DISC[k].startswith(ISS)
    assert "S256" in DISC["code_challenge_methods_supported"] and "RS256" in DISC["id_token_signing_alg_values_supported"]
    sig = [k for k in REAL_JWKS["keys"] if k.get("use") == "sig"]
    assert sig and sig[0]["alg"] == "RS256"
    assert _jwk_public_key(sig[0]).key_size >= 2048
    assert not any("d" in k or "p" in k for k in REAL_JWKS["keys"])  # public keys only


def test_end_session_url_uses_client_id_and_no_hint(r, idp) -> None:
    async def go():
        u = await provider(r, idp).end_session_url(PUBLIC + "/")
        q = parse_qs(urlsplit(u).query)
        assert u.startswith(DISC["end_session_endpoint"] + "?")
        assert q == {"client_id": [CID], "post_logout_redirect_uri": [PUBLIC + "/"]}

    run(go())


def test_discovery_with_a_different_issuer_is_refused(r) -> None:
    async def go():
        def h(req):
            return httpx.Response(200, json=DISC | {"issuer": "http://evil.invalid"})

        p = OidcProvider(r, issuer=ISS, client_id=CID, client_secret=None, public_url=PUBLIC,
                         http=httpx.AsyncClient(transport=httpx.MockTransport(h)))
        with pytest.raises(AuthError) as e:
            await p.begin("/")
        assert e.value.code == "idp_misconfigured"

    run(go())


def test_idp_down_is_a_fixed_code(r) -> None:
    async def go():
        def h(req):
            raise httpx.ConnectError("down")

        p = OidcProvider(r, issuer=ISS, client_id=CID, client_secret=None, public_url=PUBLIC,
                         http=httpx.AsyncClient(transport=httpx.MockTransport(h)))
        with pytest.raises(AuthError) as e:
            await p.begin("/")
        assert e.value.code == "idp_unreachable"

    run(go())
