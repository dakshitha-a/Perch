"""S47 operations: JSON logs without user text, loopback-only metrics, the worker health check."""

from __future__ import annotations

import json
import logging
import socket

from perch import cli
from perch.logs import JsonFormatter, uvicorn_log_config
from perch.metrics import local_only, render


def test_json_log_line_has_class_name_but_no_exception_text() -> None:
    canary = "SYNTHETIC-CV-TEXT-CANARY"
    try:
        raise ValueError(canary)
    except ValueError:
        import sys

        rec = logging.LogRecord("perch.x", logging.ERROR, __file__, 1, "job failed id=%s",
                                ("abc",), sys.exc_info())
    line = JsonFormatter().format(rec)
    out = json.loads(line)
    assert out["msg"] == "job failed id=abc" and out["exc"] == "ValueError"
    assert out["level"] == "ERROR" and out["logger"] == "perch.x"
    assert canary not in line


def test_uvicorn_log_config_filters_access_in_plain_mode_too(monkeypatch) -> None:
    import logging
    from logging.config import dictConfig

    monkeypatch.delenv("PERCH_LOG_FORMAT", raising=False)
    plain = uvicorn_log_config("warning")
    assert plain and plain["handlers"]["access"]["filters"] == ["access"]
    assert "formatters" in plain and "json" not in plain["formatters"]
    try:
        dictConfig(plain)
        h = logging.getLogger("uvicorn.access").handlers[0]
        rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0,
                                '%s - "%s %s HTTP/%s" %d',
                                ("203.0.113.9:5", "GET", "/auth/callback?code=SYNTH&state=S",
                                 "1.1", 200), None)
        assert all(f.filter(rec) for f in h.filters)
        out = rec.getMessage()
        assert out == "GET /auth/callback 200"
        assert "203.0.113.9" not in out and "SYNTH" not in out
    finally:
        logging.getLogger("uvicorn.access").handlers.clear()
    monkeypatch.setenv("PERCH_LOG_FORMAT", "json")
    cfg = uvicorn_log_config("warning")
    assert cfg and cfg["formatters"]["json"]["()"] == "perch.logs.JsonFormatter"


def test_metrics_only_for_loopback_without_proxy_headers() -> None:
    assert local_only("127.0.0.1", []) and local_only("::1", [])
    assert not local_only("172.18.0.1", [])
    assert not local_only("127.0.0.1", [(b"X-Forwarded-For", b"203.0.113.9")])
    assert not local_only(None, [])


def test_metrics_route_hides_from_outside_and_counts(tmp_path) -> None:
    from pathlib import Path

    from fastapi.testclient import TestClient

    from perch.api import create_app
    from perch.jobs import InlineRunner
    from perch.service import BriefService, Clients, default_models

    d = tmp_path
    svc = BriefService(d / "perch.db", default_models(fake=True, data_dir=d),
                       Clients(openalex=lambda: None), overrides=Path("none.csv"))
    app = create_app(svc, InlineRunner())
    with TestClient(app, client=("127.0.0.1", 5000)) as c:
        assert c.get("/health").status_code == 200
        r = c.get("/metrics")
        assert r.status_code == 200
        assert 'perch_http_requests_total{status="2xx"}' in r.text
        assert "perch_uptime_seconds" in r.text
        assert c.get("/metrics", headers={"X-Forwarded-For": "1.2.3.4"}).status_code == 404
    with TestClient(app, client=("10.0.0.5", 5000)) as c:
        assert c.get("/metrics").status_code == 404
    assert "path" not in render()


def test_render_is_prometheus_text() -> None:
    text = render({"perch_workers_alive": 2})
    assert text.endswith("\n") and "perch_workers_alive 2" in text


def test_worker_check_fails_without_a_database(monkeypatch) -> None:
    monkeypatch.delenv("PERCH_DATABASE_URL", raising=False)
    monkeypatch.delenv("PERCH_DATABASE_DIRECT_URL", raising=False)
    assert cli.worker_check() == 1


def test_worker_check_reads_this_hosts_heartbeat(pg_clean, monkeypatch) -> None:
    import psycopg

    monkeypatch.setenv("PERCH_DATABASE_URL", pg_clean.worker)
    monkeypatch.delenv("PERCH_DATABASE_DIRECT_URL", raising=False)
    assert cli.worker_check() == 1  # no heartbeat row yet
    host = socket.gethostname()
    with psycopg.connect(pg_clean.admin, autocommit=True) as c:
        c.execute("INSERT INTO worker_heartbeat (worker, at) VALUES (%s, now() - interval '5 min')",
                  (f"{host}-1",))
        c.execute("INSERT INTO worker_heartbeat (worker, at) VALUES ('other-1', now())")
    assert cli.worker_check() == 1  # stale, and the fresh row is another host's
    with psycopg.connect(pg_clean.admin, autocommit=True) as c:
        c.execute("UPDATE worker_heartbeat SET at = now() WHERE worker = %s", (f"{host}-1",))
    assert cli.worker_check() == 0


def test_access_log_drops_query_and_address() -> None:
    import logging

    from perch.logs import AccessFilter, JsonFormatter
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("203.0.113.9:5555", "GET", "/auth/callback?code=SECRETCODE&state=s",
                             "1.1", 302), None)
    assert AccessFilter().filter(rec)
    line = JsonFormatter().format(rec)
    assert "SECRETCODE" not in line and "203.0.113.9" not in line and "code=" not in line
    assert "/auth/callback" in line and "302" in line
