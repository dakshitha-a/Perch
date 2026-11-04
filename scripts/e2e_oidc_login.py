"""Live check of the sign-in path against the dev Keycloak (ARCHITECTURE_V1 section 7.2).

Run from the main checkout, where .env holds the dev settings:

    uv run python scripts/e2e_oidc_login.py

It starts a small app (the auth router only) on 127.0.0.1:8190, which the realm file allows as
a redirect URI, then drives one real login as the SYNTHETIC realm user through Keycloak's login
form with httpx. It prints one line per step and never prints a token, cookie, CSRF value or
the client secret. Exit code 0 when every step passes.

Needs in .env: PERCH_REDIS_URL, PERCH_DATABASE_URL (the perch_web role, migrated through
0008), PERCH_PEPPER, PERCH_PEPPER_GUEST, PERCH_OIDC_CLIENT_SECRET. The issuer, client id and
public URL default to the dev values. The OpenAlex link step runs only when the key store is
configured (PERCH_MASTER_KEY and PERCH_KEYS_DATABASE_URL) and uses a stubbed lookup, so the
step needs no OpenAlex call.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import httpx

from perch.config import env, load_dotenv

PORT = 8190
BASE = f"http://127.0.0.1:{PORT}"
REALM_FILE = Path("deploy/compose/keycloak/perch-realm.json")  # SYNTHETIC dev users
_USER = json.loads(REALM_FILE.read_text())["users"][0]
USER = _USER["username"]
PASSWORD = _USER["credentials"][0]["value"]
REQUIRED = ["PERCH_REDIS_URL", "PERCH_DATABASE_URL", "PERCH_PEPPER", "PERCH_PEPPER_GUEST",
            "PERCH_OIDC_CLIENT_SECRET"]
FAILED: list[str] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{(' - ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def main() -> int:
    load_dotenv(".env")
    os.environ.setdefault("PERCH_PUBLIC_URL", BASE)
    os.environ["PERCH_PUBLIC_URL"] = BASE
    os.environ["PERCH_COOKIE_INSECURE"] = "1"
    os.environ["PERCH_OIDC_ISSUER"] = "http://127.0.0.1:8180/realms/perch"
    os.environ["PERCH_OIDC_CLIENT_ID"] = "perch-web"
    os.environ.setdefault("PERCH_CONSENT_PROVIDER_NAME", "SYNTHETIC Provider")
    os.environ.setdefault("PERCH_CONSENT_VERSION", "1")
    os.environ.pop("PERCH_ENV", None)
    missing = [k for k in REQUIRED if not env(k)]
    if missing:
        print("missing in .env: " + ", ".join(missing))
        return 2

    import uvicorn
    from fastapi import FastAPI

    from perch.auth.wiring import install_auth

    app = FastAPI()
    install_auth(app)
    keys_ready = bool(env("PERCH_MASTER_KEY") and env("PERCH_KEYS_DATABASE_URL"))

    def lookup(author_id: str) -> None:  # stub: this script does not call OpenAlex
        return None

    app.state.author_lookup = lookup

    @app.get("/health")
    def health():  # noqa: ANN202
        from perch.auth.wiring import readiness

        return readiness(app)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    else:
        print("the app did not start")
        return 2
    try:
        run(keys_ready)
    finally:
        server.should_exit = True
    print("\nRESULT: " + ("all steps passed" if not FAILED else "FAILED: " + "; ".join(FAILED)))
    return 1 if FAILED else 0


class Kc:
    """Keycloak client with its own cookie handling. Keycloak marks AUTH_SESSION_ID `Secure`
    even over plain HTTP, which a browser accepts for 127.0.0.1 but httpx's jar will not send,
    so cookies are carried by hand in a Cookie header."""

    def __init__(self) -> None:
        self.c = httpx.Client(follow_redirects=False, timeout=15)
        self.jar: dict[str, str] = {}

    def _do(self, method: str, url: str, **kw) -> httpx.Response:  # noqa: ANN003
        hdr = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.jar.items())} if self.jar else {}
        r = self.c.request(method, url, headers=hdr, **kw)
        for line in r.headers.get_list("set-cookie"):
            name, _, rest = line.partition("=")
            val = rest.split(";", 1)[0]
            if val in ("", '""') or "max-age=0" in line.lower():
                self.jar.pop(name, None)
            else:
                self.jar[name] = val
        return r

    def get(self, url: str) -> httpx.Response:
        return self._do("GET", url)

    def post(self, url: str, data: dict) -> httpx.Response:
        return self._do("POST", url, data=data)


def kc_get(kc: Kc, url: str) -> httpx.Response:
    """GET within Keycloak, following redirects by hand and stopping at the first one that
    leaves Keycloak (the app callback), so the app is not called by the wrong client."""
    for _ in range(8):
        r = kc.get(url)
        loc = r.headers.get("location", "")
        if r.status_code in (301, 302, 303, 307) and loc and not loc.startswith(BASE):
            url = str(httpx.URL(url).join(loc))
            continue
        return r
    return r


FORM = (r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"',
        r'<form[^>]*action="([^"]+)"[^>]*id="kc-form-login"')


def form_action(text: str, containing: str | None = None) -> str | None:
    if containing:
        for m in re.finditer(r'<form[^>]*action="([^"]+)"', text):
            if re.search(containing, html.unescape(m.group(1))):
                return html.unescape(m.group(1))
        return None
    for pat in FORM:
        if m := re.search(pat, text):
            return html.unescape(m.group(1))
    return None


def submit_login(kc: Kc, action: str) -> str:
    """Post the login form and return the Location that leaves Keycloak. The dev realm user has
    no email, so Keycloak first asks for a profile once (VERIFY_PROFILE); this fills it in with
    SYNTHETIC values, which changes that dev user once. Returns "" when no redirect came."""
    post = kc.post(action, {"username": USER, "password": PASSWORD, "credentialId": ""})
    loc = post.headers.get("location", "")
    for _ in range(3):
        if loc.startswith(BASE) or not loc:
            break
        page = kc_get(kc, loc)
        form = form_action(page.text, r"required-action")
        if form is None:
            return loc
        print("note: Keycloak asked for a profile; filling SYNTHETIC values (dev realm user)")
        post = kc.post(form, {"email": USER + "@" + "example.invalid",
                              "firstName": "SYNTHETIC", "lastName": "User"})
        loc = post.headers.get("location", "")
    return loc


def run(keys_ready: bool) -> None:
    origin = {"Origin": BASE}
    app = httpx.Client(base_url=BASE, follow_redirects=False, timeout=15)
    kc = Kc()

    h = app.get("/health")
    step("health ready", h.status_code == 200 and h.json().get("ready") is True, str(h.json()))

    # 1. start
    r = app.get("/auth/login", params={"return_to": "/briefs"})
    loc = r.headers.get("location", "")
    step("login redirects to Keycloak with PKCE S256",
         r.status_code == 302 and loc.startswith("http://127.0.0.1:8180/")
         and "code_challenge_method=S256" in loc and "state=" in loc and "nonce=" in loc)
    step("binder cookie set (perch_oidc, HttpOnly, Max-Age=600)",
         "perch_oidc=" in r.headers.get("set-cookie", "")
         and "httponly" in r.headers["set-cookie"].lower()
         and "max-age=600" in r.headers["set-cookie"].lower())

    # 2. the Keycloak login form
    page = kc_get(kc, loc)
    action = form_action(page.text)
    step("Keycloak login form found", page.status_code == 200 and action is not None,
         f"http {page.status_code}")
    if not action:
        return
    cb = submit_login(kc, action)
    step("form post redirects back to the app callback", cb.startswith(BASE + "/auth/callback?"),
         cb.split("?")[0])
    if not cb.startswith(BASE + "/auth/callback?"):
        return

    # 3. callback with and without the binder
    stray = httpx.Client(base_url=BASE, follow_redirects=False, timeout=15)
    r0 = stray.get(cb[len(BASE):])  # a browser that never started this login: no binder cookie
    step("callback without the binder cookie is refused", r0.status_code == 400
         and r0.json().get("error") == "binder_mismatch", r0.text[:80])
    r1 = app.get(cb[len(BASE):])  # the state was burned by the attempt above, so this fails too
    step("state is single use (a refused callback spends it)", r1.status_code == 400
         and r1.json().get("error") == "state_unknown", r1.text[:80])

    # a fresh login, completed properly
    app.cookies.clear()
    r = app.get("/auth/login", params={"return_to": "/briefs"})
    page = kc_get(kc, r.headers["location"])
    action = form_action(page.text)
    if action is None:  # Keycloak may still hold its own session and skip the form
        cb = page.headers.get("location", "")
    else:
        cb = submit_login(kc, action)
    done = app.get(cb[len(BASE):]) if cb.startswith(BASE) else None
    step("callback with the binder signs in", done is not None and done.status_code == 302,
         f"http {done.status_code} {done.text[:80]}" if done is not None else "no redirect")
    if done is None or done.status_code != 302:
        return
    # The callback also clears the binder cookie (Max-Age=0), so check the session cookie's
    # own Set-Cookie header only.
    sids = [h.lower() for h in done.headers.get_list("set-cookie")
            if h.lower().startswith(("perch_sid=", "__host-perch_sid="))]
    sc = sids[0] if sids else ""
    step("session cookie: HttpOnly, SameSite=Lax, Path=/, no Max-Age, no Domain",
         bool(sc) and "httponly" in sc and "samesite=lax" in sc and "path=/" in sc
         and "max-age" not in sc and "domain" not in sc, sc.split(";", 1)[-1].strip())
    step("redirect target", done.headers["location"].startswith("/welcome?return_to=/briefs")
         or done.headers["location"] == "/briefs", done.headers["location"])

    # 4. session, roles, CSRF, consent
    me = app.get("/auth/session").json()
    step("session: signed in, not a guest, CSRF token present",
         me.get("signed_in") is True and me.get("guest") is False and bool(me.get("csrf")))
    step("display name came from the IdP", bool(me.get("display_name")), "name present")
    hdr = {**origin, "X-CSRF-Token": me["csrf"]}
    step("POST without a CSRF token is refused",
         app.post("/me/roles", json={"roles": ["researcher"]}, headers=origin).status_code == 403)
    step("POST from another origin is refused",
         app.post("/me/roles", json={"roles": ["researcher"]},
                  headers={"Origin": "http://evil.invalid", "X-CSRF-Token": me["csrf"]}
                  ).status_code == 403)
    step("roles cannot self-grant staff",
         app.post("/me/roles", json={"roles": ["staff"]}, headers=hdr).status_code == 422)
    rr = app.post("/me/roles", json={"roles": ["researcher"]}, headers=hdr)
    step("roles set to researcher", rr.status_code == 200 and "researcher" in rr.json()["roles"],
         str(rr.json()))
    aud = app.post("/me/audience", json={"audience": "student"}, headers=hdr)
    step("audience switch to an unheld side is 403", aud.status_code == 403)
    cons = app.post("/me/consent", json={"version": int(os.environ["PERCH_CONSENT_VERSION"])},
                    headers=hdr)
    step("consent stored", cons.status_code == 200, f"http {cons.status_code}")
    me2 = app.get("/auth/session").json()
    step("session shows consent accepted, no welcome needed",
         me2["consent"]["required"] is False and me2["needs_welcome"] is False)
    w = app.post("/me/consent/withdraw", headers=hdr)
    step("consent withdraw (needs migration 0008)", w.status_code == 200, f"http {w.status_code}")
    app.post("/me/consent", json={}, headers=hdr)  # leave the synthetic user consented
    if keys_ready:
        ol = app.put("/me/openalex", json={"author_id": "A5000000001"}, headers=hdr)
        step("OpenAlex link stored encrypted", ol.status_code == 200
             and app.get("/auth/session").json().get("openalex_linked") is True,
             f"http {ol.status_code}")
    else:
        print("skip OpenAlex link (key store not configured in .env)")

    # 5. logout
    out = app.post("/auth/logout", headers=hdr)
    end = out.json().get("end_session_url") if out.status_code == 200 else None
    step("logout returns the Keycloak end-session URL",
         bool(end) and end.startswith("http://127.0.0.1:8180/") and "client_id=perch-web" in end)
    step("session is gone after logout", app.get("/auth/session").json() == {"signed_in": False})
    if end:
        e = kc.get(end)
        step("Keycloak accepts the end-session request without an id token hint",
             e.status_code in (200, 302), f"http {e.status_code}")

    # 6. guest
    g = httpx.Client(base_url=BASE, follow_redirects=False, timeout=15)
    gr = g.post("/auth/guest", headers=origin)
    step("guest session created", gr.status_code == 200 and gr.json().get("guest") is True)
    step("guest cannot reach account routes",
         g.post("/me/consent", json={}, headers={**origin, "X-CSRF-Token": gr.json()["csrf"]}
                ).status_code == 403)


if __name__ == "__main__":
    sys.exit(main())
