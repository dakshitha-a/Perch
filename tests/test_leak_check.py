"""User-data leakage check (S42, standing rules 1 and 5; ARCHITECTURE_V1 3.7, 4.1 and 5).

Plants SYNTHETIC text with unique canary tokens through the real account path and scans every
place user text must never appear: logs, worker output, Redis, every plain-text column of the
perch database, the data directory. The scanners and the report are in scripts/leak_check.py.
Needs the test Postgres and Redis (`make test-user`).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from pathlib import Path

import pytest

from perch.llm.fake import FakeProvider
from tests.conftest import PG_URL
from tests.student_helpers import account_app, consent, run_brief, student_reply
from tests.test_user_account import REDIS_URL, env, job_state, rds, run_worker, sql  # noqa: F401

pytestmark = [pytest.mark.skipif(not PG_URL, reason="PERCH_TEST_DATABASE_URL is not set"),
              pytest.mark.skipif(not REDIS_URL, reason="PERCH_TEST_REDIS_URL is not set")]
ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("leak_check", ROOT / "scripts/leak_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lc = _load()


def test_the_scanners_find_a_token_in_every_kind_of_place(env, tmp_path):  # noqa: F811
    """A check that cannot find anything proves nothing: plant a token in a text, a json and a
    bytea column, a Redis string, hash and list, a file, and a log text, and find each."""
    import psycopg

    canary = lc.Canary()
    t = canary["cv"]
    with psycopg.connect(env.pg.admin, autocommit=True) as c:
        c.execute("CREATE TABLE leak_probe (t text, j jsonb, b bytea, n int)")
        c.execute("INSERT INTO leak_probe VALUES (%s, %s::jsonb, %s, 1)",
                  (f"x {t} y", json.dumps({"k": f"v {t}"}), f"zz{t}zz".encode()))
    try:
        got = lc.scan_postgres(env.pg.admin, canary)
    finally:
        with psycopg.connect(env.pg.admin, autocommit=True) as c:
            c.execute("DROP TABLE leak_probe")
    assert got["postgres leak_probe.t"] == ["cv"] and got["postgres leak_probe.j"] == ["cv"]
    assert got["postgres leak_probe.b"] == ["cv"] and "postgres leak_probe.n" not in got
    env.r.set("perch:probe:s", f"a {t}")
    env.r.hset("perch:probe:h", "f", f"a {t}")
    env.r.rpush("perch:probe:l", f"a {t}")
    env.r.set(f"perch:probe:{t}", "key only")
    assert next(iter(lc.scan_redis(env.r, canary).values())) == ["cv"]
    env.r.flushdb()
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/a.jsonl").write_text(f'{{"x": "{t}"}}')
    assert next(iter(lc.scan_files("f", [tmp_path], canary).values())) == ["cv"]
    assert lc.scan_text("logs", f"debug: parsing {t}", canary) == {"logs": ["cv"]}
    assert lc.scan_text("logs", "debug: nothing here", canary) == {"logs": []}


def test_user_text_never_leaves_its_encrypted_rows(env, tmp_path, monkeypatch, caplog,  # noqa: F811
                                                    capfd):
    canary = lc.Canary()
    caplog.set_level(logging.DEBUG)  # every logger, debug lines included
    consent(env, monkeypatch)
    post = env.client.post

    def answer(messages, system, schema):
        if system and system.startswith("You are Scout"):
            return "Your sample options are listed above."
        return student_reply(messages, system, schema)

    c, svc = account_app(env, tmp_path, monkeypatch, responder=answer)

    # 1. A student stores a CV, an interests note and an entry through the account routes.
    cv = lc.synthetic_cv(canary["cv"])
    assert post("/me/docs", json={"kind": "cv", "text": cv}).status_code == 200
    assert post("/me/docs", json={
        "kind": "interests",
        "text": f"SYNTHETIC interests: stream ecology and river health {canary['interests']}."
    }).status_code == 200
    assert post("/me/docs", json={
        "kind": "entry",
        "text": f"Presented a SYNTHETIC poster on stream ecology {canary['entry']}."
    }).status_code == 200

    # 2. The student brief runs on a worker with the fake model.
    got = run_brief(env, svc, c)
    assert got["brief"]["status"] == "done", got["brief"]["error"]
    bid = got["_id"]

    # 3. Scout answers a question that carries a token (the fake model; no log file here).
    r = c.post(f"/briefs/{bid}/scout", json={"question": f"What about {canary['question']}?"})
    assert r.status_code == 202, r.text

    # 4. A researcher brief reads a stored direction text, a proposal and the account's CV.
    env.session.audience = "researcher"
    assert post("/me/docs", json={"kind": "cv", "text": cv}).status_code == 200
    prop = post("/me/docs", json={
        "kind": "proposal",
        "text": f"SYNTHETIC aims on wearable gait sensing. {canary['direction']}"}).json()["id"]
    cvrow = next(d["id"] for d in env.client.get("/me/docs").json()
                 if d["kind"] == "cv")
    svc.models.provider = lambda spec: FakeProvider(responder=lambda m, s, sc: "")
    got = run_brief(env, svc, c, {"author_id": "A5026494099", "doc_ids": [prop, cvrow],
                                  "direction": f"gait sensing {canary['direction']}"})
    assert got["brief"]["status"] == "done", got["brief"]["error"]

    # 5. A student brief fails on purpose, with the CV text in the exception (a library that
    #    echoes its input), on the worker; the stored error, the job row and logs say no text.
    env.session.audience = "student"
    svc.models.provider = lambda spec: FakeProvider(responder=answer)
    bad_cv = lc.synthetic_cv(canary["failure"])
    assert post("/me/docs", json={"kind": "cv", "text": bad_cv}).status_code == 200

    def echo(text, *a, **k):
        raise ValueError(f"cannot parse: {text}")

    monkeypatch.setattr("perch.student.parse_student_cv", echo)
    failed = run_brief(env, svc, c)
    monkeypatch.undo()
    assert failed["brief"]["status"] == "failed"
    assert canary["failure"] not in json.dumps(failed)  # not even in the owner's own view
    assert sql(env.pg, "SELECT state FROM jobs ORDER BY created_at DESC LIMIT 1") == [("failed",)]

    # 6. The web process refuses a bad upload without echoing it, and logs no text.
    bad = post("/me/docs", json={"kind": "cv", "data": f"!!{canary['bad_upload']}!!",
                                 "filename": "cv.pdf"})
    assert bad.status_code == 422 and canary["bad_upload"] not in bad.text
    bad = post("/me/docs", json={"kind": "no-such-kind", "text": canary["bad_upload"]})
    assert bad.status_code == 422 and canary["bad_upload"] not in bad.text

    # --- scan every place ---
    out, err = capfd.readouterr()
    places: dict[str, list[str]] = {}
    places |= lc.scan_text("logs (captured records, debug level)", caplog.text, canary)
    places |= lc.scan_text("output (stdout and stderr of the web process and the worker)",
                           out + err, canary)
    places |= lc.scan_files("log files under data/logs", [tmp_path / "logs", ROOT / "data/logs"],
                            canary)
    places |= lc.scan_files("files under the data directory", [tmp_path], canary)
    places |= lc.scan_redis(env.r, canary)
    places |= lc.scan_postgres(env.pg.admin, canary)
    res = lc.report(places, planted=bool(os.environ.get("PERCH_LEAK_PLANTED")),
                    commit=os.environ.get("PERCH_LEAK_COMMIT") or None)
    if path := os.environ.get("PERCH_LEAK_RESULT"):
        Path(path).write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    assert res["passed"], f"a token was found in: {sorted(res['places_with_a_token'])}"
    # the explicitly named places were all scanned
    named = " ".join(places)
    for part in ("public_cache", "audit_log", "jobs.payload", "jobs.result_ref", "jobs.error",
                 "job_events", "user_data.blob", "redis", "logs", "output", "files"):
        assert part in named, part
    assert FakeProvider is not None and job_state is not None and run_worker is not None
