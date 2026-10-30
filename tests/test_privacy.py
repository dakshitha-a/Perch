"""Private-mode groundwork (S9): settings, refusals and the safe error answers."""

import resource

from fastapi.testclient import TestClient

from perch.privacy import PrivateSettings, harden_process

from .test_api import make


def settings(**kw):
    base = {"enabled": True, "endpoints": ("127.0.0.1", "localhost", "::1"), "tls_at": None,
            "public_url": None}
    return PrivateSettings(**{**base, **kw})


def test_defaults_are_sessions_on_local_only_and_loopback(monkeypatch):
    for k in ("PERCH_PRIVATE_MODE", "PERCH_PRIVATE_ENDPOINTS", "PERCH_TLS_AT", "PERCH_CLOUD",
              "PERCH_PUBLIC_CACHE"):
        monkeypatch.delenv(k, raising=False)
    s = PrivateSettings.from_env()  # S23: every brief is a session; no cloud unless set
    assert s.enabled and s.endpoints == ("127.0.0.1", "localhost", "::1")
    assert s.cloud_spec is None and s.cloud_provider is None and s.public_cache
    monkeypatch.setenv("PERCH_PRIVATE_MODE", "0")
    monkeypatch.setenv("PERCH_CLOUD", "anthropic:claude-sonnet-5-5")
    s = PrivateSettings.from_env()
    assert not s.enabled and s.cloud_provider == "Anthropic"
    assert s.endpoint_allowed("http://127.0.0.1:11437") and s.endpoint_allowed("http://[::1]:8094")
    assert not s.endpoint_allowed("https://api.anthropic.com/v1/messages")


def test_public_url_without_tls_location_is_refused():
    p = settings(public_url="https://perch.example.org").problems()
    assert any("PERCH_TLS_AT" in x for x in p)
    assert not any("PERCH_TLS_AT" in x for x in
                   settings(public_url="https://perch.example.org", tls_at="server").problems())
    assert any('"server"' in x for x in settings(tls_at="tunnel:").problems())


def test_a_public_url_needs_a_named_operator():
    pub = {"public_url": "https://perch.example.org", "tls_at": "server"}
    assert any("PERCH_PRIVATE_OPERATOR" in x for x in settings(**pub).problems())
    assert settings(tls_at="server").problems() == []  # a local server needs no name
    assert settings(**pub, operator="Lab IT").problems() == []
    assert settings(enabled=False).problems() == []
    assert "run by Lab IT" in settings(operator="Lab IT").statement()
    assert "decrypted by example" in settings(operator="x", tls_at="tunnel:example").statement()


def test_core_dumps_are_off_after_hardening():
    harden_process()
    assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)


def test_errors_never_echo_the_request(tmp_path, monkeypatch):
    c, service = make(tmp_path)
    canary = "PERCH-CANARY-SYNTHETIC-REQUEST"
    r = c.post("/briefs", json={"author_id": "A5026494099", "top": canary})
    assert r.status_code == 422 and canary not in r.text
    assert r.json()["detail"][0]["loc"] == ["body", "top"]

    def boom(brief_id):
        raise RuntimeError(canary)

    monkeypatch.setattr(service, "get", boom)
    r = TestClient(c.app, raise_server_exceptions=False).get("/briefs/x")
    assert r.status_code == 500 and canary not in r.text and "RuntimeError" in r.text
