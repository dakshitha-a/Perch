"""Save the example briefs the static example page plays back (web/example.html, S52).

  export KEYCLOAK_ADMIN_PASSWORD="$(grep ^KEYCLOAK_ADMIN_PASSWORD= .env | cut -d= -f2-)"
  export PERCH_LIVE_BASE=<the deploy URL, kept out of the repository>
  uv run python scripts/export_example.py [--side researcher|student|both] [--from-raw]

Over HTTP against the deploy. Researcher: the SYNTHETIC e2e user signs in, builds a brief for
PI-1 (A5063022331), keeps the top two grant leads, reads the comparison, drafts one hand-off to
research_development and asks Scout one question. Student: a guest builds the SYNTHETIC sample
student brief. Each side's raw answers go to build/s52_example/raw_<side>.json first (the only
step that spends), then are assembled into the shape web/api.js replayApi reads and written to
web/example/<side>.json (gitignored; the deploy serves it). --from-raw reassembles without
calling the deploy.

Every real name in data/overrides/pi_aliases.csv is swapped for its alias. The export fails if
a real name is left (accent-folded search) or a SYNTHETIC canary token sits outside the
synthetic records and user documents that must carry it. Prints no secrets.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from tour.names import swap_names  # noqa: E402

RAW = ROOT / "build/s52_example"
OUT = ROOT / "web/example"
ALIASES = ROOT / "data/overrides/pi_aliases.csv"
AUTHOR = "A5063022331"
QUESTION = "Which of my leads close soonest?"
OFFICE = "research_development"
CANARY = re.compile(r"PERCH-CANARY-[A-Z0-9-]+")
# Where a canary token belongs (rules 11 and 12): synthetic records and the guest's invented
# documents carry one by design.
SYNTHETIC_PREFIXES = ("sample:", "user:", "private:", "synthetic:")


class ExportError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- names


def alias_map(path: Path = ALIASES) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        return {
            r["name"].strip(): r["alias"].strip() for r in csv.DictReader(f) if r["name"].strip()
        }


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def names_left(text: str, names: dict[str, str]) -> list[str]:
    """Each real name (full, or surname of three letters or more) still in `text`, compared
    with accents folded away, as whole words."""
    folded = fold(text)
    hits = []
    for real in names:
        for n in {real, real.split()[-1]}:
            n = fold(n)
            if len(n) > 2 and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", folded):
                hits.append(n)
    return sorted(set(hits))


# ----------------------------------------------------------------------------- canaries


def _allowed(path: tuple) -> bool:
    """A canary may sit in a synthetic record or user document, or in a `canary` field."""
    if "canary" in path:
        return True
    keys = [p for p in path if isinstance(p, str)]
    if len(path) >= 2 and path[0] == "records" and str(path[1]).startswith(SYNTHETIC_PREFIXES):
        return True
    if (
        len(path) >= 3
        and path[:2] == ("brief", "papers")
        and str(path[2]).startswith(SYNTHETIC_PREFIXES)
    ):
        return True
    # A lead's embedded record when the lead points at a synthetic record.
    return any(k in ("record", "opportunity") for k in keys) and "_synthetic_lead" in path


def canaries_misplaced(data: object, path: tuple = ()) -> list[str]:
    out = []
    if isinstance(data, dict):
        mark = (
            ("_synthetic_lead",)
            if str(data.get("record_id", "")).startswith(SYNTHETIC_PREFIXES)
            else ()
        )
        for k, v in data.items():
            out += canaries_misplaced(v, path + mark + (k,))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            out += canaries_misplaced(v, path + (i,))
    elif isinstance(data, str) and CANARY.search(data) and not _allowed(path):
        out.append("/".join(str(p) for p in path if p != "_synthetic_lead"))
    return out


# ----------------------------------------------------------------------------- assembly


def record_ids(body: dict) -> tuple[set[str], set[str]]:
    """(ids every lead needs, ids the evidence panel may also open) from GET /briefs/{id}."""
    b = body["brief"]
    must = {x["record_id"] for x in body["leads"] if x.get("record_id")}
    may = {b.get("researcher_id")} | set(body.get("papers") or {})
    may |= {a["record_id"] for a in body.get("awards") or [] if a.get("record_id")}
    for lead in body["leads"]:
        # A citation opens by the id as written (replayApi looks it up as given first), so a
        # bare id is kept bare: the server resolves it as the live panel would ask.
        for c in lead.get("cited_ids") or []:
            may.add(f"https://openalex.org/{c}" if re.fullmatch(r"W\d+", c) else c)
        may |= {r["id"] for it in lead.get("signal_items") or [] for r in it.get("records") or []}
    may |= {f"https://openalex.org/{w}" for w in re.findall(r"\bW\d{5,}\b", b.get("summary") or "")}
    return must, {i for i in may if i} - must


def assemble(raw: dict, names: dict[str, str]) -> dict:
    """The replay file: what replayApi(data) reads."""
    body = raw["brief"]
    records = dict(raw["records"])
    b = body["brief"]
    res_id = b.get("researcher_id")
    data: dict = {"version": 3, "brief": body, "records": records, "candidates": []}
    if raw["side"] == "researcher":
        res = records.get(res_id) or body.get("researcher")
        if not res:
            raise ExportError("the researcher record is missing")
        res = dict(res, orcid=None)
        records[res_id] = res
        body["researcher"] = res
        data["candidates"] = [res]
        alias = next(
            (a for n, a in names.items() if fold(n) == fold(res.get("display_name", ""))), None
        )
        if b.get("stages") and alias:
            b["stages"][0]["detail"] = alias
        for r in records.values():
            if r.get("kind") == "award":
                r["pi_names"] = []
        kept = raw["kept"]
        data["kept"] = kept
        data["compare"] = raw["compare"]
        data["handoffs"] = {OFFICE: {"lead_ids": kept, "draft": raw["handoff"]}}
        data["scout"] = {"question": QUESTION, "session": raw["scout"]}
    else:
        data["student"] = True
        if raw.get("compare"):
            data["compare"] = raw["compare"]
        if body.get("offices"):
            data["offices"] = body["offices"]
    return data


def public_titles(data: object, names: dict[str, str], kind: str = "") -> set[str]:
    """Titles of public award and opportunity records that hold a researcher's surname but no
    full name, such as a program named for someone else who shares it. CLAUDE.md lets award
    titles copied from public pages name people; the swap would garble them."""
    out: set[str] = set()
    full = [fold(n) for n in names]
    if isinstance(data, dict):
        kind = data.get("kind", kind)
        for k, v in data.items():
            if (
                k in ("title", "name")
                and isinstance(v, str)
                and kind not in ("researcher", "work")
                and names_left(v, names)
                and not any(f in fold(v) for f in full)
            ):
                out.add(v)
            else:
                out |= public_titles(v, names, kind)
    elif isinstance(data, list):
        for v in data:
            out |= public_titles(v, names, kind)
    return out


def finish(data: dict, names: dict[str, str]) -> str:
    """Swap names, then gate. ensure_ascii=False so accented names stay letters to match.
    Public titles (see public_titles) are held aside during the swap and the name check."""
    text = json.dumps(data, indent=1, ensure_ascii=False)
    held = {}
    for i, t in enumerate(sorted(public_titles(data, names), key=len, reverse=True)):
        key = f"@@TITLE{i}@@"
        held[key] = json.dumps(t, ensure_ascii=False)[1:-1]
        text = text.replace(held[key], key)
    text = swap_names(text, names)
    left = names_left(text, names)
    if left:
        raise ExportError(
            f"real names left after the swap: {len(left)} (initials {[n[:1] for n in left[:5]]})"
        )
    for key, t in held.items():
        text = text.replace(key, t)
    bad = canaries_misplaced(json.loads(text))
    if bad:
        raise ExportError(f"canary tokens in visible fields: {bad[:10]}")
    if held:
        print(f"kept {len(held)} public title(s) as written: {sorted(held.values())}", flush=True)
    return text


# ----------------------------------------------------------------------------- capture


class Client:
    def __init__(self, client: httpx.Client, base: str) -> None:
        self.c, self.base, self.csrf = client, base, ""

    def refresh(self) -> dict:
        d = self.c.get("/auth/session").json()
        self.csrf = d.get("csrf", "")
        return d

    def call(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        ok: tuple = (200, 201, 202),
        **kw: object,
    ) -> dict:
        r = self.c.request(
            method, path, json=body, headers={"Origin": self.base, "X-CSRF-Token": self.csrf}, **kw
        )
        if r.status_code not in ok:
            raise ExportError(
                f"{method} {path.split('?')[0]} answered {r.status_code}: {r.text[:300]}"
            )
        return r.json()


def poll(
    c: Client, path: str, done: Callable[[dict], bool], limit: int = 600, **kw: object
) -> dict:
    t0 = time.time()
    while True:
        last = c.call("GET", path, **kw)
        if done(last):
            return last
        if time.time() - t0 > limit:
            raise ExportError(f"timed out polling {path.split('?')[0]}")
        time.sleep(4)


def brief_done(d: dict) -> bool:
    st = (d.get("brief") or {}).get("status")
    if st in ("failed", "cancelled"):
        raise ExportError(f"the brief ended {st}: {(d.get('brief') or {}).get('error')}")
    return st == "done"


def build_brief(c: Client, req: dict) -> tuple[str, dict]:
    bid = c.call("POST", "/briefs", req)["id"]
    print(f"brief started ({req.get('audience')})", flush=True)
    return bid, poll(c, f"/briefs/{bid}", brief_done, limit=900)


def fetch_records(c: Client, body: dict) -> dict:
    must, may = record_ids(body)
    records = {}
    for i in sorted(must | may):
        r = c.c.get(f"/records/{i}")
        if r.status_code == 200:
            records[i] = r.json()
        elif i in must:
            raise ExportError(f"a lead's record did not open ({r.status_code})")
    print(f"records: {len(records)} of {len(must | may)}", flush=True)
    return records


def capture_researcher(base: str) -> dict:
    spec = importlib.util.spec_from_file_location("e2e", ROOT / "scripts/e2e_oidc_login.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    client = mod.login(base)
    client.follow_redirects = False
    c = Client(client, base)
    s = c.refresh()
    if "researcher" not in (s.get("roles") or []):
        c.call(
            "POST",
            "/me/roles",
            {"roles": sorted(set(s.get("roles") or []) | {"researcher"} - {"staff"})},
        )
    cons = s.get("consent") or {}
    if cons.get("required"):
        c.call("POST", "/me/consent", {"version": cons.get("current_version")})
    if s.get("audience") != "researcher":
        c.call("POST", "/me/audience", {"audience": "researcher"})
    c.refresh()
    bid, body = build_brief(c, {"author_id": AUTHOR, "audience": "researcher"})
    grants = sorted(
        # The federal grant list: not the Temple internal group, which the hand-off leaves out.
        (
            x
            for x in body["leads"]
            if x.get("route", "A") == "A" and x.get("group") != "temple_internal"
        ),
        key=lambda x: x["rank"],
    )[:2]
    if len(grants) < 2:
        raise ExportError("the brief has fewer than two grant leads")
    for x in grants:
        c.call("POST", f"/briefs/{bid}/leads/{x['id']}/keep")
    kept = [x["id"] for x in grants]
    # The deploy may hand back a brief kept from an earlier run: only these two stay kept.
    for x in body["leads"]:
        if x["status"] == "kept" and x["id"] not in kept:
            c.call("POST", f"/briefs/{bid}/leads/{x['id']}/restore")
    body = c.call("GET", f"/briefs/{bid}")  # the leads now carry status "kept"
    compare = c.call("GET", f"/briefs/{bid}/compare", params={"status": "all"})
    h = c.call("POST", f"/briefs/{bid}/handoff", {"office": OFFICE})
    if "subject" in h:
        draft = h
    else:
        got = poll(
            c,
            f"/briefs/{bid}/handoff",
            lambda d: (
                d.get("result") is not None
                or (d.get("job") or {}).get("state") in ("failed", "dead", "cancelled")
            ),
            limit=300,
            params={"office": OFFICE, "job_id": h.get("job_id")},
        )
        if got.get("result") is None:
            raise ExportError(f"the hand-off job ended {(got.get('job') or {}).get('state')}")
        draft = got["result"]
    print("hand-off drafted", flush=True)
    sid = c.call("POST", f"/briefs/{bid}/scout", {"question": QUESTION})["id"]
    scout = poll(c, f"/scout/{sid}", lambda d: not d.get("busy"), limit=300)
    print(f"scout: {scout.get('status')}", flush=True)
    return {
        "side": "researcher",
        "brief": body,
        "records": fetch_records(c, body),
        "kept": kept,
        "compare": compare,
        "handoff": draft,
        "scout": scout,
    }


def capture_student(base: str) -> dict:

    c = Client(httpx.Client(base_url=base, timeout=60, follow_redirects=False), base)
    c.csrf = c.call("POST", "/auth/guest", {"audience": "student"}).get("csrf", "")
    bid, body = build_brief(c, {"audience": "student"})
    r = c.c.get(f"/briefs/{bid}/compare", params={"status": "all"})
    compare = r.json() if r.status_code == 200 else None
    return {"side": "student", "brief": body, "records": fetch_records(c, body), "compare": compare}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--side", choices=("researcher", "student", "both"), default="both")
    ap.add_argument(
        "--from-raw", action="store_true", help="reassemble build/s52_example/raw_<side>.json"
    )
    ap.add_argument(
        "--refetch", action="store_true", help="with --from-raw: fetch the records again"
    )
    args = ap.parse_args(argv[1:])
    base = os.environ.get("PERCH_LIVE_BASE", "")
    if (args.refetch or not args.from_raw) and not base:
        print("set PERCH_LIVE_BASE to the deploy URL", file=sys.stderr)
        return 2
    names = alias_map()
    sides = ("researcher", "student") if args.side == "both" else (args.side,)
    RAW.mkdir(parents=True, exist_ok=True)
    for side in sides:
        raw_path = RAW / f"raw_{side}.json"
        try:
            if args.from_raw:
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                if args.refetch:  # public records only: a guest session opens them
                    c = Client(httpx.Client(base_url=base, timeout=60), base)
                    c.csrf = c.call("POST", "/auth/guest", {"audience": side}).get("csrf", "")
                    raw["records"] = fetch_records(c, raw["brief"])
                    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            else:
                raw = (capture_researcher if side == "researcher" else capture_student)(base)
                raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            text = finish(assemble(raw, names), names)
        except ExportError as e:
            print(f"{side}: FAILED: {e}", file=sys.stderr)
            return 1
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{side}.json").write_text(text, encoding="utf-8")
        d = json.loads(text)
        groups: dict[str, int] = {}
        for x in d["brief"]["leads"]:
            g = x.get("group") or x.get("route", "A")
            groups[g] = groups.get(g, 0) + 1
        print(
            f"{side}: wrote web/example/{side}.json; leads by group {groups};"
            f" records {len(d['records'])}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
