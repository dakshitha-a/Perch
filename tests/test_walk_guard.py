import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "walk_server.py"


def _load(monkeypatch, dsn, allow=None):
    monkeypatch.setenv("PERCH_WALK_SUPER_DSN", dsn)
    if allow:
        monkeypatch.setenv("PERCH_WALK_ALLOW_REMOTE", allow)
    else:
        monkeypatch.delenv("PERCH_WALK_ALLOW_REMOTE", raising=False)
    spec = importlib.util.spec_from_file_location("walk_server_t", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["walk_server_t"] = mod
    spec.loader.exec_module(mod)


def test_walk_server_refuses_a_non_local_dsn(monkeypatch) -> None:
    with pytest.raises(SystemExit):
        _load(monkeypatch, "postgresql://db.example.org:5432/postgres")


def test_walk_server_override_and_local(monkeypatch) -> None:
    _load(monkeypatch, "postgresql://127.0.0.1:55432/postgres")
    _load(monkeypatch, "postgresql://db.example.org:5432/postgres", allow="1")
