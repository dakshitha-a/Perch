"""The v1 Compose file holds the S48 security settings (M2, M3, S2). No Docker needed."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import yaml

from perch.redisx import client_addr_from

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "deploy/compose/docker-compose.v1.yml").read_text())
SVC = COMPOSE["services"]


def _default(value: str) -> str:
    """`${NAME:-default}` -> default; a plain value as is."""
    m = re.fullmatch(r"\$\{[A-Z_]+:-(.*)\}", value)
    return m.group(1) if m else value


def _env(service: str) -> dict[str, str]:
    return {k: str(v) for k, v in SVC[service]["environment"].items()}


def _mounts(service: str) -> dict[str, str]:
    return dict(v.split(":")[:2][::-1] for v in SVC[service].get("volumes", []))


def test_trusted_proxy_is_the_compose_gateway_and_forwarded_addresses_count():
    net = COMPOSE["networks"]["default"]["ipam"]["config"][0]
    trusted = _default(_env("web")["PERCH_TRUSTED_PROXIES"])
    gw = ipaddress.ip_address(net["gateway"])
    assert ipaddress.ip_network(trusted) == ipaddress.ip_network(f"{gw}/32")
    assert gw in ipaddress.ip_network(net["subnet"])
    # a request through the host proxy arrives from the gateway with the visitor in XFF
    assert client_addr_from(str(gw), "198.51.100.7", trusted) == "198.51.100.7"
    # any other peer cannot set its own address
    assert client_addr_from("172.29.190.9", "198.51.100.7", trusted) == "172.29.190.9"


def test_the_shred_ledger_has_its_own_volume_on_web_and_worker():
    for s in ("web", "worker"):
        d = _env(s)["PERCH_SHRED_LEDGER_URI"]
        assert d.startswith("/") and _mounts(s).get(d) == "shred-ledger", s
    used_elsewhere = {v for s in SVC if s not in ("web", "worker") for v in _mounts(s).values()}
    assert "shred-ledger" not in used_elsewhere  # not the database or a backup volume
    assert "shred-ledger" in COMPOSE["volumes"]


def test_the_spend_file_is_on_a_named_volume():
    path = _env("worker")["PERCH_SPEND_LEDGER"]
    assert path.startswith("/")
    assert _mounts("worker").get(str(Path(path).parent)) == "spend"


def test_the_shipped_realm_imports_no_user_and_the_e2e_user_is_synthetic():
    import json

    kc = ROOT / "deploy/compose/keycloak"
    realm = json.loads((kc / "perch-realm.json").read_text())
    assert "users" not in realm  # S48 S9: no account with a known password ships
    mounted = " ".join(SVC["keycloak"]["volumes"])
    assert "e2e-user.json" not in mounted
    user = json.loads((kc / "e2e-user.json").read_text())
    assert user["firstName"] == "SYNTHETIC" and "SYNTHETIC" in user["_comment"]


def _seconds(text: str) -> float:
    m = re.fullmatch(r"(\d+)(s|m)", str(text))
    assert m, text
    return int(m.group(1)) * (60 if m.group(2) == "m" else 1)


def test_the_worker_can_drain_before_docker_kills_it():
    """S49 B13: Docker's default 10 s stop grace was shorter than the 30 s drain, so every
    deploy killed in-flight jobs."""
    from perch.jobs import Timing

    assert _seconds(SVC["worker"]["stop_grace_period"]) > Timing().drain_s + 5
    unit = (ROOT / "deploy/systemd/v1/perch-worker.service").read_text()
    stop = re.search(r"^TimeoutStopSec=(\d+)", unit, re.M)
    assert stop and int(stop.group(1)) > Timing().drain_s + 5
