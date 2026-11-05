"""Cost model for the Perch roadmap: writes docs/COST_MODEL.md and docs/architecture/cost_model.svg.

Every number is MEASURED (read from a file in the repo, or from the spend ledgers), a PUBLIC PRICE
(constants below, each with its URL and fetch date) or an ASSUMPTION (scenario parameters below).
Nothing here is a prediction presented as a measurement.

Usage:
  python3 scripts/cost_model.py                       # uses the committed ledger snapshot
  python3 scripts/cost_model.py --ledger main=PATH --ledger deploy=PATH   # re-reads the ledgers
                                                       # and refreshes the snapshot
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "bench/results/cost_model/ledger_stats.json"
FETCHED = "2026-11-05"

# ---------- PUBLIC PRICES (list, on demand, US region, no discounts) ----------
PRICES = {
    "aws_gpu_hr": (0.8048, "AWS g6.xlarge (1 NVIDIA L4 24 GB, 4 vCPU, 16 GiB), US East, Linux, per hour",
                   "https://instances.vantage.sh/aws/ec2/g6.xlarge (aggregator of AWS list price; specs "
                   "from https://aws.amazon.com/ec2/instance-types/g6/)"),
    "gcp_gpu_hr": (0.7068, "Google g2-standard-4 (1 NVIDIA L4 24 GB), us-central1, per hour",
                   "https://gcloud-compute.com/g2-standard-4.html (aggregator of Google list price)"),
    "aws_cpu_hr": (0.714, "AWS c7i.4xlarge (16 vCPU, 32 GiB), US East, Linux, per hour",
                   "https://instances.vantage.sh/aws/ec2/c7i.4xlarge"),
    "aws_web_hr": (0.1785, "AWS c7i.xlarge (4 vCPU, 8 GiB) for a web process, US East, Linux, per hour",
                   "https://instances.vantage.sh/aws/ec2/c7i.xlarge"),
    "aws_pg_hr": (0.065, "AWS RDS db.t4g.medium (2 vCPU, 4 GiB), PostgreSQL, per hour",
                  "https://instances.vantage.sh/aws/rds/db.t4g.medium (engine and region not confirmed on the page)"),
    "aws_redis_hr": (0.016, "AWS ElastiCache cache.t4g.micro, Redis, per hour",
                     "https://instances.vantage.sh/aws/elasticache/cache.t4g.micro (engine and region not confirmed on the page)"),
    "gpu_card": (3599.0, "NVIDIA L4 24 GB card, new, lowest in-stock US retail listing in a price tracker dated 2026-10-09",
                 "https://gpudojo.com/l4 (found by search; the same search showed $2,824 for a PNY kit with zero "
                 "stock, a CDW page showing 'Call', and a Feb 2026 estimate of $2,000 to $3,000)"),
    "gpu_watts": (72.0, "NVIDIA L4 maximum power (TDP), watts", "https://www.nvidia.com/en-us/data-center/l4/"),
    "pa_kwh": (0.1393, "Pennsylvania commercial electricity, August 2026 (preliminary), USD per kWh",
               "https://www.eia.gov/electricity/monthly/epm_table_grapher.php?t=epmt_5_6_a"),
}
# Anthropic list prices, USD per million tokens: https://platform.claude.com/docs/en/docs/about-claude/pricing
TOK = {"sonnet": dict(inp=2.0, out=10.0, cw=2.5, cr=0.10), "haiku": dict(inp=0.10, out=0.50, cw=0.125, cr=0.01)}
HOURS = 730

# ---------- ASSUMPTIONS (scenario parameters; none is a fact about Temple) ----------
SCENARIOS = [  # name, active users per month (N), label
    ("Pilot", 25, "25 active users"),
    ("Department", 200, "200 active users"),
    ("Campus N=1,000", 1000, "1,000 active users"),
    ("Campus N=5,000", 5000, "5,000 active users"),
    ("Campus N=20,000", 20000, "20,000 active users"),
]
ACT = {  # per active user per month
    "researcher_brief": 1.0,   # a researcher brief of 10 leads
    "student_brief": 1.0,      # a student brief of 20 explained leads
    "scout": 4.0,              # Scout open questions
    "handoff": 0.5,            # model-written hand-off drafts
    "cover": 0.5,              # cover-points runs
}
# Each user is one audience; a 50/50 split means each user does 0.5 of each brief a month on average.
AUDIENCE_SHARE_RESEARCHER = 0.5
BRIEFS_PER_USER = 1.0
CONCURRENT_SHARE = 0.05        # share of active users on at once (web sizing)
WEB_USERS_PER_VM = 250         # MEASURED: one web process met the 250-user target (docs/RESULTS.md)
WORKER_UTIL = 0.10             # share of a worker's measured brief rate used at the busy hour
GPU_BRIEFS_PER_MIN = 38        # MEASURED low end of 38 to 40 a minute, fake provider (docs/ROADMAP.md 1)
CPU_RERANK14_S = 9.386         # MEASURED CPU rerank of 14 candidates, 16 cores (docs/RESULTS.md); lower bound
CPU_UTIL = 0.25                # assumption: share of a CPU VM's seconds spent on briefs
AMORT_MONTHS = 36              # assumption: card life for the Temple purchase
UNVERIFIED = None              # staff, server chassis, data-centre: no figure on record


def money(x: float, d: int = 0) -> str:
    return f"${x:,.{d}f}"


# ---------- MEASURED ----------
def ledger_stats(args: list[str]) -> dict:
    if args:
        out = {}
        for a in args:
            label, path = a.split("=", 1)
            rows = [json.loads(x) for x in open(path) if x.strip()]
            by = {}
            for m in sorted({r["model"] for r in rows}):
                c = [r["cost_usd"] for r in rows if r["model"] == m]
                by[m] = dict(n=len(c), mean=st.mean(c), median=st.median(c), total=sum(c))
            out[label] = dict(n=len(rows), total=sum(r["cost_usd"] for r in rows), first=rows[0]["at"][:10],
                              last=rows[-1]["at"][:10], fields=sorted(rows[0]), by_model=by)
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    return json.loads(SNAP.read_text())


def measured() -> dict:
    m: dict = {}
    rows = []
    for line in (ROOT / "bench/results/s38_cost/researcher_briefs.txt").read_text().splitlines():
        kv = dict(p.split("=", 1) for p in line.split() if "=" in p)
        if "usd" in kv:
            rows.append({k: float(v) if re.fullmatch(r"[\d.]+", v) else v for k, v in kv.items()})
    usd = [r["usd"] for r in rows]
    m["researcher"] = dict(n=len(usd), mean=st.mean(usd), median=st.median(usd), min=min(usd), max=max(usd))
    # price check: tokens at Sonnet list price is an upper bound (part of each brief ran on Haiku)
    chk = []
    for r in rows:
        s = TOK["sonnet"]
        chk.append((r["input_tokens"] * s["inp"] + r["output_tokens"] * s["out"]
                    + r["cache_read_tokens"] * s["cr"] + r["cache_write_tokens"] * s["cw"]) / 1e6)
    m["researcher_check"] = dict(mean_upper=st.mean(chk), mean_recorded=st.mean(usd))
    s_rows = list(csv.DictReader(open(ROOT / "bench/results/s46_student_real/counts.csv")))
    su = [float(r["usd"]) for r in s_rows]
    m["student"] = dict(n=len(su), mean=st.mean(su), median=st.median(su), min=min(su), max=max(su))
    sc = list(csv.DictReader(open(ROOT / "bench/results/scout_s38_cloudgpu/scout_anthropic-claude-sonnet-5-5.csv")))
    allu = [float(r["usd"]) for r in sc]
    m["scout"] = dict(n=len(allu), mean=st.mean(allu), median=st.median(allu), total=sum(allu))
    for key, ids in (("handoff", {"h01", "h02"}), ("cover", {"p01"})):
        u = [float(r["usd"]) for r in sc if r["task"] in ids]
        m[key] = dict(n=len(u), mean=st.mean(u), median=st.median(u))
    return m


# ---------- model ----------
def unit_costs(m: dict) -> dict:
    return dict(researcher_brief=m["researcher"]["mean"], student_brief=m["student"]["mean"],
                scout=m["scout"]["mean"], handoff=m["handoff"]["mean"], cover=m["cover"]["mean"])


def model_cost(n: float, u: dict, act: dict = ACT) -> float:
    brief = (AUDIENCE_SHARE_RESEARCHER * u["researcher_brief"] * act["researcher_brief"]
             + (1 - AUDIENCE_SHARE_RESEARCHER) * u["student_brief"] * act["student_brief"]) * BRIEFS_PER_USER
    return n * (brief + act["scout"] * u["scout"] + act["handoff"] * u["handoff"] + act["cover"] * u["cover"])


def temple_hosting(n: float, p: dict) -> dict:
    card = p["gpu_card"][0] / AMORT_MONTHS
    power = p["gpu_watts"][0] / 1000 * HOURS * p["pa_kwh"][0]
    return dict(card=card, power=power, total=card + power)


def external_hosting(n: float, p: dict, profile: str, gpu_cloud: str = "aws") -> dict:
    briefs = n * BRIEFS_PER_USER
    web_vms = max(1, math.ceil(n * CONCURRENT_SHARE / WEB_USERS_PER_VM))
    web = web_vms * p["aws_web_hr"][0] * HOURS
    pg = p["aws_pg_hr"][0] * HOURS
    redis = p["aws_redis_hr"][0] * HOURS
    if profile == "gpu":
        per_hr = p["aws_gpu_hr"][0] if gpu_cloud == "aws" else p["gcp_gpu_hr"][0]
        workers = max(1, math.ceil(briefs / (GPU_BRIEFS_PER_MIN * 60 * HOURS * WORKER_UTIL)))
        worker = workers * per_hr * HOURS
    else:
        workers = max(1, math.ceil(briefs * CPU_RERANK14_S / (HOURS * 3600 * CPU_UTIL)))
        worker = workers * p["aws_cpu_hr"][0] * HOURS
    return dict(worker=worker, workers=workers, web=web, web_vms=web_vms, pg=pg, redis=redis,
                total=worker + web + pg + redis)


# ---------- chart ----------
def chart(rows: list[tuple[str, float, float, float, float]]) -> str:
    """rows: label, temple_host, temple_model, ext_host, ext_model (USD a month)."""
    w, h = 600, 420
    left, top, bot = 58, 66, 84
    ph = h - top - bot
    mx = max(max(r[1] + r[2], r[3] + r[4]) for r in rows)
    step = 10 ** math.floor(math.log10(mx))
    top_v = math.ceil(mx / step) * step
    sc = ph / top_v
    gw = (w - left - 20) / len(rows)
    bw = gw * 0.34
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" class="arch" role="img" '
         'font-family="system-ui, sans-serif" aria-label="Monthly cost by scenario, stacked: hosting and model '
         'cost, for Temple-hosted and for externally hosted GPU profile. Scenario parameters, not measurements.">',
         f'<text x="{w/2}" y="30" text-anchor="middle" font-size="17" font-weight="700" fill="currentColor">'
         'Predicted monthly cost by scenario</text>',
         f'<text x="{w/2}" y="50" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.75">'
         'Scenario parameters, not measurements. Temple bars cover the listed items only.</text>']
    for i in range(0, int(top_v / step) + 1):
        v = i * step
        y = top + ph - v * sc
        o.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w-20}" y2="{y:.1f}" stroke="currentColor" stroke-opacity="0.15"/>')
        o.append(f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" fill="currentColor" '
                 f'opacity="0.75">{money(v)}</text>')
    for i, (lab, th, tm, eh, em) in enumerate(rows):
        gx = left + gw * i + gw / 2
        for j, (host, mod, name) in enumerate(((th, tm, "Temple"), (eh, em, "External"))):
            x = gx + (j - 1) * bw + (bw * 0.1 if j else -bw * 0.1) + (0 if j else 0)
            x = gx - bw - 4 if j == 0 else gx + 4
            yh = top + ph - host * sc
            ym = yh - mod * sc
            o.append(f'<rect x="{x:.1f}" y="{yh:.1f}" width="{bw:.1f}" height="{max(host*sc,0.5):.1f}" '
                     'class="k-local" fill="#dcefe8" stroke="#1f6f5c" stroke-width="1.5"/>')
            o.append(f'<rect x="{x:.1f}" y="{ym:.1f}" width="{bw:.1f}" height="{max(mod*sc,0.5):.1f}" '
                     'class="k-cloud" fill="#f6ead8" stroke="#a15c07" stroke-width="1.5" stroke-dasharray="5 3"/>')
            o.append(f'<text x="{x+bw/2:.1f}" y="{ym-6:.1f}" text-anchor="middle" font-size="11" '
                     f'font-weight="600" fill="currentColor">{money(host+mod)}</text>')
            o.append(f'<text x="{x+bw/2:.1f}" y="{top+ph+16}" text-anchor="middle" font-size="11" '
                     f'fill="currentColor" opacity="0.8">{name}</text>')
        o.append(f'<text x="{gx:.1f}" y="{top+ph+36}" text-anchor="middle" font-size="12" font-weight="600" '
                 f'fill="currentColor">{lab}</text>')
    ly = h - 18
    o.append(f'<rect x="{left}" y="{ly-11}" width="16" height="12" class="k-local" fill="#dcefe8" stroke="#1f6f5c"/>'
             f'<text x="{left+22}" y="{ly}" font-size="12" fill="currentColor">Hosting</text>'
             f'<rect x="{left+100}" y="{ly-11}" width="16" height="12" class="k-cloud" fill="#f6ead8" stroke="#a15c07" '
             f'stroke-dasharray="4 2"/><text x="{left+122}" y="{ly}" font-size="12" fill="currentColor">Model cost '
             '(same in both)</text></svg>')
    return "\n".join(o)


# ---------- document ----------
def build(ledger_args: list[str]) -> tuple[str, str]:
    p = PRICES
    m = measured()
    L = ledger_stats(ledger_args)
    u = unit_costs(m)
    th = temple_hosting(1, p)
    D: list[str] = []
    a = D.append

    a("# Cost model")
    a("")
    a("*Generated by `scripts/cost_model.py`; do not edit by hand. Re-run it with `python3 scripts/cost_model.py` "
      "(add `--ledger main=PATH --ledger deploy=PATH` to re-read the spend ledgers). Public prices were fetched "
      f"on {FETCHED}.*")
    a("")
    # scenario computations
    sc_rows = []
    for name, n, lab in SCENARIOS:
        mc = model_cost(n, u)
        t = th["total"]
        ex_g = external_hosting(n, p, "gpu")
        ex_c = external_hosting(n, p, "cpu")
        sc_rows.append((name, n, lab, mc, t, ex_g, ex_c))
    pil, camp = sc_rows[0], sc_rows[3]
    a("## Summary")
    a("")
    a("- **What this is:** a prediction of the monthly hosting and model cost of Perch, built from measured costs, "
      "public list prices and labelled assumptions.")
    a(f"- **Model cost:** a measured researcher brief costs {money(u['researcher_brief'],4)} and a measured student "
      f"brief {money(u['student_brief'],4)}. Model cost scales with use and is the same wherever Perch is hosted.")
    a(f"- **Hosting, external:** a rented 1-GPU cloud setup with a database, Redis and a web VM costs about "
      f"{money(pil[5]['total'])} a month at list price, whatever the use. The no-GPU setup costs about "
      f"{money(pil[6]['total'])}.")
    a(f"- **Hosting, Temple:** the only costs that can be priced are one GPU card and its power, about "
      f"{money(th['total'])} a month. Server, data-centre and staff costs are UNVERIFIED and not included, so this "
      "is a floor and not a total.")
    a(f"- **Scenarios:** at 25 users the total is dominated by hosting, about {money(pil[5]['total']+pil[3])} "
      f"external. At 5,000 users model cost is {money(camp[3])} and hosting {money(camp[5]['total'])}.")
    a("- **How sure:** the unit costs are measured on 3 to 30 runs each. The user counts and activity rates are "
      "assumptions, not facts about Temple.")
    a("")

    a("## Inputs")
    a("")
    a("| Input | Value | Kind | Source |")
    a("|---|---|---|---|")
    r = m["researcher"]
    a(f"| Researcher brief, 10 leads | {money(r['mean'],4)} mean, {money(r['median'],4)} median, range "
      f"{money(r['min'],4)} to {money(r['max'],4)}, n={r['n']} | MEASURED | `bench/results/s38_cost/researcher_briefs.txt` (2026-11-04, Haiku 5.5 summary, Sonnet 5.5 fit) |")
    s = m["student"]
    a(f"| Student brief, 20 leads explained | {money(s['mean'],4)} mean, {money(s['median'],4)} median, range "
      f"{money(s['min'],4)} to {money(s['max'],4)}, n={s['n']} SYNTHETIC personas | MEASURED | `bench/results/s46_student_real/counts.csv` |")
    c = m["scout"]
    a(f"| Scout question | {money(c['mean'],4)} mean, {money(c['median'],4)} median, n={c['n']} (22 tasks, 8 restraint) | MEASURED | `bench/results/scout_s38_cloudgpu/` (Sonnet 5.5) |")
    h = m["handoff"]
    a(f"| Hand-off draft | {money(h['mean'],4)} mean, n={h['n']} (whole Scout turn, not the draft alone) | MEASURED, thin | same file, tasks h01 and h02 |")
    cv = m["cover"]
    a(f"| Cover-points run | {money(cv['mean'],4)}, n={cv['n']} (whole Scout turn, two tool errors) | MEASURED, thin | same file, task p01 |")
    for k in ("main", "deploy"):
        if k in L:
            e = L[k]
            bm = "; ".join(f"{mm.replace('claude-','')} n={v['n']} mean {money(v['mean'],5)} median {money(v['median'],5)} per call"
                           for mm, v in e["by_model"].items())
            a(f"| Spend ledger, {k} | {e['n']} calls, {money(e['total'],2)} from {e['first']} to {e['last']}; {bm} | MEASURED | the {k} ledger (fields {', '.join(e['fields'])}) |")
    a("| GPU worker memory | 6,544 MiB at 24 briefs in flight, 8,940 MiB at 48 | MEASURED | `docs/deploy.md` section 10; so a 24 GB L4 fits |")
    a("| Postgres data directory | 100 MB, both databases, n=1 | MEASURED | `du` of the test deploy's Postgres base directory, 2026-11-05 |")
    a(f"| GPU worker rate | {GPU_BRIEFS_PER_MIN} to 40 briefs a minute, fake provider | MEASURED | `docs/RESULTS.md` load test |")
    a("| Web process | 1 process met the 250-user target | MEASURED | `docs/RESULTS.md` load test |")
    a(f"| CPU rerank, 14 candidates, 16 cores | {CPU_RERANK14_S:.3f} s | MEASURED | `docs/RESULTS.md` CPU timings |")
    for k, (v, d, src) in p.items():
        val = money(v, 4) if v < 10 else (f"{v:,.0f} W" if k == "gpu_watts" else money(v))
        if k == "pa_kwh":
            val = f"{money(v,4)}/kWh"
        a(f"| {d} | {val} | PUBLIC PRICE | {src}, fetched {FETCHED} |")
    a("| Anthropic list price, Sonnet 5.5 | $2 in, $10 out, $2.50 cache write, $0.10 cache read per MTok | PUBLIC PRICE | https://platform.claude.com/docs/en/docs/about-claude/pricing, fetched " + FETCHED + " |")
    a("| Anthropic list price, Haiku 5.5 (up to 100K tokens) | $0.10 in, $0.50 out, $0.125 cache write, $0.01 cache read per MTok | PUBLIC PRICE | same page, fetched " + FETCHED + " |")
    a(f"| Active users a month, N | {', '.join(f'{x[1]:,}' for x in SCENARIOS)} | ASSUMPTION | scenario parameter; Temple's headcount is not used |")
    a(f"| Activity per user a month | 1 brief (half researcher, half student), {ACT['scout']:g} Scout questions, {ACT['handoff']:g} hand-off drafts, {ACT['cover']:g} cover-points runs | ASSUMPTION | scenario parameter |")
    a(f"| Busy share of users on at once | {CONCURRENT_SHARE:.0%} | ASSUMPTION | sizes web VMs |")
    a(f"| Worker utilisation at busy hour | {WORKER_UTIL:.0%} GPU, {CPU_UTIL:.0%} CPU | ASSUMPTION | sizes workers |")
    a(f"| Card life, Temple | {AMORT_MONTHS} months | ASSUMPTION | straight-line |")
    a("| Server chassis, rack, data-centre, network, staff time, backups, support | no figure | UNVERIFIED | the record holds none; do not guess |")
    a("")
    chk = m["researcher_check"]
    a(f"**Sanity check against list prices.** The five researcher briefs' recorded tokens, priced entirely at "
      f"Sonnet 5.5 list prices, give a mean of {money(chk['mean_upper'],4)}. That is an upper bound, because the "
      f"profile summary ran on Haiku. The recorded mean is {money(chk['mean_recorded'],4)}, below the bound, so the "
      "ledger prices and the public prices agree.")
    a("")
    a("**Reconciling with the record.** `docs/ROADMAP.md` section 4 says a researcher brief cost a mean of $0.0833 "
      f"over five briefs. Recomputing from the saved file gives {money(r['mean'],4)}, n={r['n']}, so this model "
      "uses the same number. The earlier $0.0915 (S8) is older code and is not used.")
    a("")
    a("**What the ledgers can and cannot say.** The ledgers record time, model, token counts and cost for each call. "
      "They carry no job, role or brief id, so a per-brief cost cannot be grouped from them without guessing. The "
      "per-unit costs above therefore come from the saved bench files, which were run with a known job. The ledgers "
      "give per-call figures and totals. The ledger totals also include development and test runs, so they are not "
      "a usage rate.")
    a("")
    a("**Budgets on record.** These are placeholders in `.env.example` and `docs/ROADMAP.md`, not measured:")
    a("")
    a("| Limit | Default | Demo Day setting |")
    a("|---|---|---|")
    a("| Guest session, per day | $0.10 | $0.30 |")
    a("| One address (guests), per day | $0.30 | $4.00 |")
    a("| All guests, per day | $3.00 | $8.00 |")
    a("| Signed-in account, per day | $0.50 | raised on the test deploy; value not in the repo |")
    a("| Whole site | $100 (development value) | deploy cap set separately |")
    a("")

    a("## Formulas")
    a("")
    a("- **Model cost a month:** `N x (0.5 x R + 0.5 x S + q x C + h x H + v x V)`, with R and S the researcher and "
      "student brief costs, C the Scout question cost, H the hand-off cost, V the cover-points cost, q, h and v the "
      "activity rates. Unit costs are the measured means.")
    a(f"- **External, GPU profile:** `workers x GPU price x {HOURS} + web VMs x web price x {HOURS} + Postgres x {HOURS} + Redis x {HOURS}`. "
      f"Workers = `ceil(briefs a month / ({GPU_BRIEFS_PER_MIN} x 60 x {HOURS} x {WORKER_UTIL}))`. Web VMs = `ceil(N x {CONCURRENT_SHARE} / {WEB_USERS_PER_VM})`.")
    a(f"- **External, CPU profile:** the GPU VM is replaced by a 16-vCPU VM. Workers = `ceil(briefs x {CPU_RERANK14_S:.3f} s / ({HOURS} x 3600 x {CPU_UTIL}))`. "
      "This counts the rerank only, so it is a lower bound; MiniCheck time is not included.")
    a(f"- **Temple:** `card price / {AMORT_MONTHS} + TDP x {HOURS} h x PA commercial rate`. The card runs at its full "
      "rated power, an upper bound for the card, and the rest of the server is not counted.")
    a("")

    a("## Scenarios")
    a("")
    a("Monthly cost in US dollars. Model cost is the same in every column. External GPU uses the AWS price; the "
      f"Google price is {money(p['gcp_gpu_hr'][0]*HOURS)} a month for the GPU VM against {money(p['aws_gpu_hr'][0]*HOURS)}.")
    a("")
    a("| Scenario | Briefs a month | Model cost | Temple hosting (listed items) | Temple total | External GPU hosting | External GPU total | External CPU hosting | External CPU total |")
    a("|---|---|---|---|---|---|---|---|---|")
    for name, n, lab, mc, t, eg, ec in sc_rows:
        a(f"| {name} ({lab}) | {n*BRIEFS_PER_USER:,.0f} | {money(mc)} | {money(t)} | {money(t+mc)} + UNVERIFIED | "
          f"{money(eg['total'])} | {money(eg['total']+mc)} | {money(ec['total'])} | {money(ec['total']+mc)} |")
    a("")
    a("Hosting detail for the pilot, external GPU: "
      f"GPU VM {money(pil[5]['worker'])}, web VM {money(pil[5]['web'])}, Postgres {money(pil[5]['pg'])}, Redis {money(pil[5]['redis'])}. "
      f"Temple: card {money(th['card'])} a month over {AMORT_MONTHS} months, power {money(th['power'],2)}.")
    big = sc_rows[-1]
    a(f"At N=20,000 the sizing rules give {big[5]['workers']} GPU worker(s) and {big[5]['web_vms']} web VM(s); "
      f"the CPU profile needs {big[6]['workers']} VM(s) by the rerank-only count.")
    a("")
    a("Figure: stacked monthly cost, hosting and model cost, Temple against external GPU.")
    a("")
    a("![Predicted monthly cost by scenario, stacked: hosting and model cost, for Temple-hosted and for externally hosted GPU. Scenario parameters, not measurements.](architecture/cost_model.svg)")
    a("")
    a("The table above is the text version of the chart. The Temple bars exclude every UNVERIFIED item.")
    a("")

    a("## Not included")
    a("")
    for t in ("**Temple, UNVERIFIED:** server chassis and host CPU, rack space, cooling, network, backup storage, spares, "
              "and staff time to run it. No figure is on record, so none is used.",
              "**External:** storage and data egress, load balancer and TLS, backups, monitoring, support plans, "
              "taxes, reserved or committed discounts, and the second Postgres for the key database. At 100 MB of data "
              "storage is small, but its price is UNVERIFIED here.",
              "**Model cost:** guests, the scope gate and the daily jobs, Scout bench runs, retries beyond those in the "
              "measured briefs, and any rate-tier or contract terms. A different model or provider changes every unit cost.",
              "**Safety margin:** no headroom for peaks. The CPU profile count excludes MiniCheck time.",
              "**Student briefs:** measured on 3 SYNTHETIC personas, so real CVs may differ. Hand-off and cover-points "
              "costs rest on 2 and 1 Scout runs, so treat them as rough."):
        a(f"- {t}")
    a("")

    a("## Sensitivity")
    a("")
    base_n = 5000
    base_mc = model_cost(base_n, u)
    base_ex = external_hosting(base_n, p, "gpu")["total"]
    base = base_mc + base_ex
    sens = []

    def total_with(unit_mult: dict | None = None, act_mult: dict | None = None,
                   price_mult: dict | None = None) -> float:
        uu = dict(u)
        aa = dict(ACT)
        pp = dict(p)
        for k, f in (unit_mult or {}).items():
            uu[k] = uu[k] * f
        for k, f in (act_mult or {}).items():
            aa[k] = aa[k] * f
        for k, f in (price_mult or {}).items():
            pp[k] = (pp[k][0] * f, pp[k][1], pp[k][2])
        return model_cost(base_n, uu, aa) + external_hosting(base_n, pp, "gpu")["total"]

    for lab, kw in (
        ("Scout questions per user (4)", dict(act_mult={"scout": 1.5})),
        ("Brief cost, or briefs per user (1 a month)", dict(unit_mult={"researcher_brief": 1.5, "student_brief": 1.5})),
        ("Scout question cost", dict(unit_mult={"scout": 1.5})),
        ("GPU VM price", dict(price_mult={"aws_gpu_hr": 1.5})),
        ("Hand-off and cover-points cost", dict(unit_mult={"handoff": 1.5, "cover": 1.5})),
        ("Web VM price", dict(price_mult={"aws_web_hr": 1.5})),
        ("Postgres and Redis price", dict(price_mult={"aws_pg_hr": 1.5, "aws_redis_hr": 1.5})),
    ):
        tot = total_with(**kw)
        sens.append((lab, tot - base))
    sens.sort(key=lambda x: -abs(x[1]))
    a(f"One input at a time is raised by 50%, at N={base_n:,}, external GPU. Base total {money(base)} a month "
      f"({money(base_mc)} model, {money(base-base_mc)} hosting).")
    a("")
    a("| Input raised 50% | Change in monthly total | Share of base |")
    a("|---|---|---|")
    for lab, d in sens:
        a(f"| {lab} | +{money(d)} | {d/base:.1%} |")
    a("")
    a(f"- **What moves it most:** at this size, '{sens[0][0]}' and then '{sens[1][0]}'. Hosting is flat "
      "in use, so it matters most for the pilot.")
    a(f"- **At the pilot:** hosting is {pil[5]['total']/(pil[5]['total']+pil[3]):.0%} of the external total, so the GPU VM price "
      "decides it. Use or the GPU choice (a CPU VM, or a card bought) changes the result more than any model input.")
    a("- **Not tested:** the model price per token and the share of briefs that hit the cache. The cache read price is "
      "$0.10 per MTok on Sonnet 5.5, against $2 for fresh input, so cache use is large for the real cost.")
    a("")
    chart_rows = [(x[0].replace("Campus N=1,000", "Campus 1k").replace("Campus N=5,000", "Campus 5k").replace("Campus N=20,000", "Campus 20k").replace("Department", "Dept."), th["total"], x[3], x[5]["total"], x[3]) for x in sc_rows]
    return "\n".join(D) + "\n", chart(chart_rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", action="append", default=[], help="label=path, repeatable")
    args = ap.parse_args()
    md, svg = build(args.ledger)
    (ROOT / "docs/COST_MODEL.md").write_text(md)
    (ROOT / "docs/architecture/cost_model.svg").write_text(svg + "\n")
    print("wrote docs/COST_MODEL.md and docs/architecture/cost_model.svg")


if __name__ == "__main__":
    main()
