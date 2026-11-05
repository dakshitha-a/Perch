"""Capture what the test deploy's real model writes (S50). Run:
   export KEYCLOAK_ADMIN_PASSWORD="$(grep ^KEYCLOAK_ADMIN_PASSWORD= .env | cut -d= -f2-)"
   .venv/bin/python scripts/live_capture.py [capture|render]
Writes build/s50_live/live.json and LIVE.md. SYNTHETIC user only; prints no secrets."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/s50_live"
BASE = "https://sn4622120437.tailf0654d.ts.net:8443"
AUTHOR = "A5063022331"
ALIAS = ("Tomasz Skórski", "Skórski", "Tomasz Skorski", "Skorski, Tomasz", "T. Skorski", "Skorski")
LOG: dict = {"notes": []}


def alias(text: str) -> str:
    for n in ALIAS:
        text = text.replace(n, "PI-1")
    return text


def note(s: str) -> None:
    LOG["notes"].append(s)
    print(s, flush=True)


class C:
    def __init__(self, client: httpx.Client) -> None:
        self.c = client
        self.csrf = ""

    def refresh(self) -> dict:
        d = self.c.get("/auth/session").json()
        self.csrf = d.get("csrf", "")
        return d

    def call(self, method: str, path: str, body: dict | None = None, **kw) -> dict:
        h = {"Origin": BASE, "X-CSRF-Token": self.csrf}
        r = self.c.request(method, path, json=body, headers=h, **kw)
        try:
            data = r.json()
        except ValueError:
            data = {"_text": r.text[:500]}
        if r.status_code >= 400:
            data = {"_http": r.status_code, "body": data}
        return data


def poll(c: C, path: str, done, limit=420, **kw) -> dict:
    t0, last = time.time(), {}
    while time.time() - t0 < limit:
        last = c.call("GET", path, **kw)
        if "_http" in last or done(last):
            return last
        time.sleep(4)
    last["_timeout"] = True
    return last


def capture() -> None:
    spec = importlib.util.spec_from_file_location("e2e", ROOT / "scripts/e2e_oidc_login.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    try:
        client = mod.login(BASE)
        client.follow_redirects = False
        note("signed in as the SYNTHETIC e2e user")
    except Exception as e:  # noqa: BLE001
        note(f"sign-in failed ({type(e).__name__}); account-only steps (keep, Scout, cover points, handoff) not captured")
        client = None
    if client is not None:
        c = C(client)
        s = c.refresh()
        LOG["session"] = {k: s.get(k) for k in ("roles", "audience", "needs_welcome")}
        cons = s.get("consent") or {}
        if "researcher" not in (s.get("roles") or []):
            LOG["roles"] = c.call("POST", "/me/roles", {"roles": sorted(set(s.get("roles") or []) | {"researcher"} - {"staff"})})
        if cons.get("required"):
            LOG["consent"] = c.call("POST", "/me/consent", {"version": cons.get("current_version")})
        if s.get("audience") != "researcher":
            LOG["audience"] = c.call("POST", "/me/audience", {"audience": "researcher"})
        c.refresh()
        r = c.call("POST", "/briefs", {"author_id": AUTHOR, "audience": "researcher"})
        LOG["brief_create"] = r
        bid = r.get("id")
        if bid:
            b = poll(c, f"/briefs/{bid}", lambda d: (d.get("brief") or {}).get("status") in ("done", "failed", "cancelled")
                     or (d.get("job") or {}).get("state") in ("failed", "cancelled"), limit=600)
            LOG["brief"] = b
            leads = [x for x in b.get("leads", []) if x.get("route", "A") == "A"]
            LOG["keep"] = [c.call("POST", f"/briefs/{bid}/leads/{x['id']}/keep") for x in leads[:2]]
            LOG["scout"] = []
            for q in ("Which of my leads close soonest?", "Which kept lead fits my work best, and why?"):
                r = c.call("POST", f"/briefs/{bid}/scout", {"question": q})
                sid = r.get("id")
                if sid:
                    r = poll(c, f"/scout/{sid}", lambda d: not d.get("busy"), limit=300)
                LOG["scout"].append({"question": q, "final": r})
            if leads:
                rec = leads[0].get("record_id")
                r = c.call("POST", f"/briefs/{bid}/cover-points", {"record_id": rec})
                job = (r.get("job") or {}).get("id") or r.get("job_id")
                LOG["cover_start"] = r
                LOG["cover"] = poll(c, f"/briefs/{bid}/cover-points", lambda d: d.get("result") is not None
                                    or (d.get("job") or {}).get("state") in ("failed", "cancelled", "succeeded", "done"),
                                    limit=300, params={"record_id": rec, **({"job_id": job} if job else {})})
            r = c.call("POST", f"/briefs/{bid}/handoff", {"office": "research_development", "lead_ids": [x["id"] for x in leads[:2]]})
            LOG["handoff_start"] = r
            job = r.get("job_id") or (r.get("job") or {}).get("id") or r.get("id")
            LOG["handoff"] = poll(c, f"/briefs/{bid}/handoff", lambda d: d.get("result") is not None
                                  or (d.get("job") or {}).get("state") in ("failed", "cancelled"),
                                  limit=300, params={"office": "research_development", **({"job_id": job} if job else {})})
    # student guest
    g = httpx.Client(base_url=BASE, timeout=30, follow_redirects=False)
    gc = C(g)
    LOG["guest"] = gc.call("POST", "/auth/guest", {"audience": "student"})
    gc.csrf = LOG["guest"].get("csrf", "")
    r = gc.call("POST", "/briefs", {"audience": "student"})
    LOG["student_create"] = r
    if r.get("id"):
        LOG["student_brief"] = poll(gc, f"/briefs/{r['id']}", lambda d: (d.get("brief") or {}).get("status") in ("done", "failed", "cancelled"), limit=600)
    redact()


def redact() -> None:
    for k in ("guest",):
        if isinstance(LOG.get(k), dict):
            LOG[k].pop("csrf", None)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "live.json").write_text(alias(json.dumps(LOG, indent=1, default=str, ensure_ascii=False)))


def lead_md(x: dict, student: bool = False) -> str:
    o = x.get("opportunity") or x.get("record") or {}
    t = [f"### {x.get('rank')}. {o.get('title') or o.get('name') or x.get('record_id')}  ({x.get('record_id')}, status {x.get('status')}, match {x.get('match_score')})"]
    t.append(f"- close: {o.get('close_date') or o.get('deadline')}; ceiling: {o.get('award_ceiling') or o.get('amount_max')}; sponsor: {o.get('sponsor')}")
    if student or x.get("verdict"):
        t.append(f"- verdict: {x.get('verdict')} | reason: {x.get('verdict_reason')}")
        for ln in x.get("verdict_lines") or []:
            t.append(f"  - verdict line: {ln}")
    t.append(f"- explanation: {x.get('explanation')}")
    t.append(f"- inference: {x.get('inference')}")
    t.append(f"- flags: flagged={x.get('flagged')} inferred={x.get('inferred')} unsupported={x.get('unsupported')} cited={x.get('cited_ids')} gaps={x.get('gaps')}")
    return "\n".join(t)


def render_md(d: dict) -> str:
    o = ["# Live capture, S50 (model text from the test deploy)", "", "Notes: " + "; ".join(d.get("notes", []))]
    b = d.get("brief") or {}
    o += ["", "## Researcher brief (PI-1, A5063022331)", f"Status: {(b.get('brief') or {}).get('status')}; leads: {len(b.get('leads', []))}",
          f"Summary: {(b.get('brief') or {}).get('summary')}", ""]
    for x in b.get("leads", []):
        o += [lead_md(x), ""]
    o += ["## Scout answers"]
    for q in d.get("scout", []):
        o += ["", f"### Q: {q['question']}"]
        for m in (q["final"].get("messages") or []):
            if m.get("role") == "assistant":
                o += [m.get("text", ""), "", f"- flagged={m.get('flagged')} withheld={m.get('withheld')} withheld_all={m.get('withheld_all')} removed={m.get('removed')} unsupported={m.get('unsupported')}",
                      "- sources: " + "; ".join(f"{s.get('id')} ({s.get('title')})" for s in m.get("sources", []))]
        o += [f"- status={q['final'].get('status')} error={q['final'].get('error')}"]
    c = (d.get("cover") or {}).get("result") or {}
    o += ["", "## Cover points (top lead)", f"Record: {c.get('record_id')} / {c.get('title')}"]
    for pt in c.get("points", []):
        o += [f"- ASKS: {pt.get('asks')} {pt.get('asks_ids')}", f"  YOU: {pt.get('you')} {pt.get('you_ids')}"]
    o += [f"- missing: {c.get('missing')}", f"- unsupported: {c.get('unsupported')}", f"- note: {c.get('note')}"]
    h = (d.get("handoff") or {}).get("result") or {}
    o += ["", "## Hand-off draft (research_development)", f"Subject: {h.get('subject')}", "", h.get("body", ""),
          "", f"- model={h.get('model')} opening_by={h.get('opening_by')} flagged={h.get('flagged')} cited={h.get('cited_ids')}"]
    sb = d.get("student_brief") or {}
    o += ["", "## Student brief (SYNTHETIC sample, guest)", f"Status: {(sb.get('brief') or {}).get('status')}; leads: {len(sb.get('leads', []))}", ""]
    for x in sb.get("leads", []):
        o += [lead_md(x, True), ""]
    return "\n".join(o) + "\n"


def render() -> None:
    d = json.loads((OUT / "live.json").read_text())
    (OUT / "LIVE.md").write_text(alias(render_md(d)))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "capture"
    if mode == "capture":
        capture()
    else:
        render()
