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
