"""Command line.

  perch resolve <name|orcid|author id>
  perch fetch openalex <author id>
  perch fetch awards <author id>      NIH RePORTER and NSF awards at Temple, by name
  perch fetch opportunities           Grants.gov opportunities (nightly refresh: upsert by number)
  perch profile <author id>           key papers, awards and the public award horizon
  perch brief <author id> --route A   ranked, eligible Route A leads (record fields only)
  perch brief <author id> --route B   industry leads from public signals (inferred)
  perch brief <author id> --explain   plus profile summary and validated fit explanations
  perch serve                         the HTTP API (briefs as background jobs)
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from perch import awards as aw
from perch.config import env, load_dotenv
from perch.profile import MAX_AUTHORS, key_papers
from perch.schemas import Award, Opportunity, Researcher
from perch.sources import grants_gov, nih_reporter, nsf
from perch.sources import openalex as oa
from perch.store.base import Repository
from perch.store.sqlite import SQLiteRepository

DEFAULT_DB = "data/perch.db"

ClientFactory = Callable[[], oa.OpenAlexClient]


def default_client() -> oa.OpenAlexClient:
    return oa.OpenAlexClient(api_key=env("OPENALEX_API_KEY"))


def describe(r: Researcher) -> str:
    orcid = oa.parse_orcid(r.orcid) if r.orcid else "no ORCID"
    where = ", ".join(r.institutions) or "no institution listed"
    return f"{oa.short_id(r.id)}  {r.display_name}  ({orcid}; {where}; {r.works_count} works)"


def cmd_resolve(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    query = args.query
    if oa.parse_orcid(query):
        found = [client.resolve_by_orcid(query)]
    elif oa.parse_author_id(query) and " " not in query.strip():
        found = [client.get_author(query)]
    else:
        found = client.resolve_by_name(query)
    if not found:
        print(f"No OpenAlex author found for {query!r} at Temple University.", file=sys.stderr)
        return 1
    with SQLiteRepository(args.db) as repo:
        repo.upsert(found)
    print(f"{len(found)} candidate(s). Confirm the right one, then run "
          "`perch fetch openalex <id>`:")
    for i, r in enumerate(found, 1):
        print(f"  {i}. {describe(r)}")
    return 0


def researcher_for(args: argparse.Namespace, repo: SQLiteRepository,
                   client: oa.OpenAlexClient) -> Researcher:
    aid = oa.parse_author_id(args.author_id)
    found = repo.get(Researcher, f"https://openalex.org/{aid}") if aid else None
    return found or client.get_author(args.author_id)


def fetch_awards(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    if not args.author_id:
        print("perch fetch awards needs an author id.", file=sys.stderr)
        return 2
    with SQLiteRepository(args.db) as repo:
        r = researcher_for(args, repo, client)
        ov = aw.load_overrides(r.id, Path(args.overrides))
        with args.nih_factory() as nih_client, args.nsf_factory() as nsf_client:
            fetched, linked = aw.fetch_and_link(r, ov, nih_client, nsf_client)
        repo.upsert([r, *fetched])
    projects = {aw.award_key(a) for a in linked}
    print(f"{describe(r)}")
    print(f"Fetched {len(fetched)} award records; {len(linked)} linked by name "
          f"({len(projects)} awards). Run `perch profile {oa.short_id(r.id)}`.")
    return 0


def same_content(a: Opportunity, b: Opportunity) -> bool:
    return a.model_dump(exclude={"fetched_at"}) == b.model_dump(exclude={"fetched_at"})


def fetch_opportunities(args: argparse.Namespace) -> int:
    """Upsert by opportunity number; report what is new, changed and unchanged."""
    new = changed = unchanged = 0
    with SQLiteRepository(args.db) as repo, args.grants_factory() as gg:
        if args.opp_num:
            items = []
            for number in args.opp_num:
                hits = gg.search(statuses="forecasted|posted|closed|archived", keyword="",
                                 rows=5, opp_num=number).get("oppHits") or []
                items += [h for h in hits if h["number"] == number]
            opps = (gg.fetch(h["id"], h.get("oppStatus")) for h in items)
        else:
            opps = gg.iter_opportunities(args.statuses, args.agencies, limit=args.limit)
        for o in opps:
            old = repo.get(Opportunity, o.id)
            if old is None:
                new += 1
            elif same_content(old, o):
                unchanged += 1
            else:
                changed += 1
            repo.upsert([o])
        total = len(repo.list(Opportunity))
    print(f"{new} new, {changed} changed, {unchanged} unchanged; "
          f"{total} opportunities in {args.db}.")
    print(grants_gov.ATTRIBUTION)
    return 0


def cmd_fetch(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    if args.source == "awards":
        return fetch_awards(args, client)
    if args.source == "opportunities":
        return fetch_opportunities(args)
    if args.source == "temple":
        return fetch_temple(args)
    if args.source == "fellowship-details":
        return fetch_fellowship_details(args)
    if args.source == "temple-pages":
        return fetch_temple_pages(args)
    if args.source != "openalex":
        print(f"Unknown source {args.source!r}. Available: openalex, awards, opportunities, "
              "temple, fellowship-details, temple-pages.", file=sys.stderr)
        return 2
    if not args.author_id:
        print("perch fetch openalex needs an author id.", file=sys.stderr)
        return 2
    author = client.get_author(args.author_id)
    works = list(client.iter_works(args.author_id))
    with SQLiteRepository(args.db) as repo:
        repo.upsert([author])
        repo.upsert(works)
        stored = len(repo.works_by_author(author.id))
    with_abstract = sum(1 for w in works if w.abstract)
    print(f"{describe(author)}")
    print(f"Fetched {len(works)} works ({with_abstract} with abstracts); "
          f"{stored} stored for this author in {args.db}.")
    return 0


def fetch_temple(args: argparse.Namespace) -> int:
    """Temple SDFA's public fellowship list into the public store (student mode, S18).
    One page, read live; the sample scholarships never go here (perch.scholarships)."""
    from perch.sources import temple

    recs = temple.parse_listing(temple.fetch(temple.SDFA_LIST))
    with SQLiteRepository(args.db) as repo:
        repo.upsert(recs)
    print(f"Stored {len(recs)} awards from {temple.SDFA_NAME} ({temple.SDFA_LIST}) in "
          f"{args.db}. The page states no amounts or deadlines.")
    return 0


def fetch_temple_pages(args: argparse.Namespace) -> int:
    """Read the inventoried Temple pages once (REBUILD_PLAN Phase 4 task 1). Network only:
    one request a second per host, robots.txt honoured, `<main>` kept, contacts scrubbed.
    Cleaned pages go to data/cache/temple_pages/ (gitignored)."""
    from pathlib import Path

    from perch.sources import temple_pages as tp

    rows = tp.read_inventory(Path(args.inventory))
    rep = tp.read_pages(rows, Path(args.cache_dir), limit=args.limit, refresh=args.refresh)
    print("\n".join(rep.lines()))
    return 0


def cmd_temple(args: argparse.Namespace) -> int:
    """Build the versioned Temple awards dataset, or load one into a store."""
    from perch import temple_dataset as td

    try:
        if args.temple_command == "build-dataset":
            path, man, rep = td.build_dataset(Path(args.input), Path(args.out_dir),
                                              version=args.version)
            print("\n".join(rep.lines()))
            print(f"Wrote {path} (version {man['version']}, {man['records']} records, "
                  f"sha256 {man['sha256'][:12]}...).")
            return 0
        dsn = args.dsn
        if dsn:
            from perch.store.postgres import PostgresRepository

            repo: Repository = PostgresRepository(dsn, role="worker")
        else:
            repo = SQLiteRepository(args.db)
        with repo:
            n = td.load_dataset(Path(args.file), repo)
        print(f"Loaded {n} records from {args.file} into {'Postgres' if dsn else args.db}.")
        return 0
    except (td.DatasetError, OSError) as e:
        print(f"temple {args.temple_command} stopped: {e}", file=sys.stderr)
        return 1


def cmd_extract(args: argparse.Namespace) -> int:
    """Propose award records from the cached Temple pages with the `extract` model role;
    code keeps a value only when it is in a quoted sentence of the page."""
    from pathlib import Path

    from perch import temple_extract as te

    out = args.out or ("data/temple/extracted.jsonl" if args.all else "data/temple/pilot_s39.jsonl")
    return te.run_extract(Path(args.cache_dir), Path(out), pilot=args.pilot, run_all=args.all,
                          budget_usd=args.budget, restart=args.restart)


def fetch_fellowship_details(args: argparse.Namespace) -> int:
    """Deadlines and amounts for the public fellowship records, read from each record's
    own page (one GET per record, robots.txt respected, no crawl). Run `fetch temple` first."""
    from perch.schemas import Scholarship
    from perch.sources import fellowship_details as fd

    with SQLiteRepository(args.db) as repo:
        recs = repo.list(Scholarship)
        if not any(r.source == "temple_sdfa" for r in recs):
            print("No temple_sdfa records in the store. Run `perch fetch temple` first.",
                  file=sys.stderr)
            return 2
        updated, rep = fd.fill_details(recs, pages_dir=args.pages_dir)
        repo.upsert([r for r in updated if r.source == "temple_sdfa"])
    print("\n".join(rep.lines()))
    return 0


def cmd_samples(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    from perch.scholarships import ensure_samples, sample_db

    n = ensure_samples()
    print(f"Sample store {sample_db()}: {n} SYNTHETIC records (student mode only).")
    return 0


def fmt_date(d: object) -> str:
    return d.isoformat() if d else "no date"


def cmd_profile(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    aid = oa.parse_author_id(args.author_id)
    with SQLiteRepository(args.db) as repo:
        r = repo.get(Researcher, f"https://openalex.org/{aid}") if aid else None
        if not r:
            print(f"{args.author_id} is not in the store. Run `perch fetch openalex "
                  f"{args.author_id}` and `perch fetch awards {args.author_id}` first.",
                  file=sys.stderr)
            return 1
        works = repo.works_by_author(r.id)
        ov = aw.load_overrides(r.id, Path(args.overrides))
        linked = aw.link_stored(r, repo.list(Award), ov)
    print(describe(r))
    print(f"\nKey papers (most cited of {len(works)} works in the store; papers with more "
          f"than {MAX_AUTHORS} authors skipped):")
    for w in key_papers(works, args.papers):
        venue = w.venue or "venue not listed"
        print(f"  {w.publication_year or 'n.d.'}  {w.title}  ({venue}; "
              f"{w.cited_by_count or 0} citations)  {w.doi or w.id}")
    summaries = aw.summarise(linked, r, ov)
    print(f"\nPublic federal awards ({len(summaries)}), latest end date first:")
    for s in summaries:
        foa = ", ".join(s.opportunity_numbers) or "no opportunity number in record"
        print(f"  {s.award_number}  {s.agency}  {fmt_date(s.start_date)} to "
              f"{fmt_date(s.end_date)}  {foa}  {s.title}"
              + ("  [matched by initial: check it is theirs]" if s.matched_by_initial else ""))
    h = aw.award_horizon(summaries)
    print()
    if h and h.end_record:
        print(f"Public award horizon: {h.end_date.isoformat()} (end of {h.award_number}, "
              f"from {h.end_record.source_url})")
    else:
        print("Public award horizon: none (no public federal award with an end date found)")
    print("This is the end date of the last public award. It says nothing about lab finances.")
    return 0


def money(v: float | None) -> str:
    return f"${v:,.0f}" if v is not None else "not stated in the record"


def cmd_brief(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    from datetime import date

    from perch.brief import route_a
    from perch.eligibility import Constraints
    from perch.embed import get_embedder
    from perch.rerank import CrossEncoderReranker, FakeReranker, RerankCache
    from perch.store.lance import LanceIndex

    if args.route == "B":
        return cmd_route_b(args, client)
    if args.route != "A":
        print("--route is A or B.", file=sys.stderr)
        return 2
    aid = oa.parse_author_id(args.author_id)
    fake = args.models == "fake"
    with SQLiteRepository(args.db) as repo:
        r = repo.get(Researcher, f"https://openalex.org/{aid}") if aid else None
        if not r:
            print(f"{args.author_id} is not in the store. Run `perch fetch openalex "
                  f"{args.author_id}` first.", file=sys.stderr)
            return 1
        cache_dir = Path(args.db).parent / "cache"
        embedder = get_embedder("fake-256" if fake else args.embedder,
                                cache=cache_dir / "embeddings.db")
        reranker = FakeReranker() if fake else CrossEncoderReranker(args.reranker)
        index = LanceIndex(Path(args.db).parent / ("lance-fake" if fake else "lance"))
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
        c = Constraints(as_of=as_of, min_amount=args.min_amount, agencies=args.agency,
                        include_forecasted=args.include_forecasted,
                        include_restricted=args.include_restricted)
        b = route_a(r, repo, index, embedder, reranker, c, RerankCache(cache_dir / "rerank.db"),
                    top=args.top, timings_log=Path(args.db).parent / "logs/brief_timings.jsonl")
    print(describe(r))
    print(f"As of {as_of.isoformat()}. {len(b.profile.work_ids)} papers, "
          f"{len(b.profile.threads)} research threads:")
    for t in b.profile.threads:
        print(f"  thread {t.index + 1} ({t.weight:.0%} of recent work): {t.label}")
    print(f"\nRoute A: {b.retrieved} retrieved, {len(b.rejected)} ineligible removed, "
          f"top {len(b.leads)} after rerank:")
    for i, lead in enumerate(b.leads, 1):
        o = lead.opportunity
        print(f"\n{i:2}. {o.opportunity_number}  {o.title}")
        print(f"    {o.agency}; activity code {o.activity_code or 'not in record'}; "
              f"status {o.status}")
        print(f"    opens {fmt_date(o.open_date)}; closes {fmt_date(o.close_date)}; "
              f"award ceiling {money(o.award_ceiling)}")
        print(f"    matched thread {lead.candidate.best_thread + 1}; rerank "
              f"{lead.rerank_score:.3f}; {o.source_url}")
    if args.explain:
        explain_brief(b, args)
    ms = b.timings_ms
    print("\nTimings (ms): " + ", ".join(f"{k} {v:,.0f}" for k, v in ms.items()
                                         if not k.startswith("retrieve_")) +
          f"; rerank cache hits {b.rerank_cache_hits}")
    print(grants_gov.ATTRIBUTION)
    return 0


def cmd_route_b(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    from datetime import date

    from perch import route_b as rb
    from perch.sources import nih_reporter

    aid = oa.parse_author_id(args.author_id)
    with SQLiteRepository(args.db) as repo:
        r = repo.get(Researcher, f"https://openalex.org/{aid}") if aid else None
        if not r:
            print(f"{args.author_id} is not in the store. Run `perch fetch openalex "
                  f"{args.author_id}` first.", file=sys.stderr)
            return 1
        works = repo.works_by_author(r.id)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    with nih_reporter.NIHReporterClient() as nc:
        g = rb.gather(client, nc, works, as_of)
    leads = rb.score_leads(r.id, g.seeds, g.citing, g.topical, g.sbir, g.topics, as_of,
                           own=g.own)
    print(describe(r))
    print(f"As of {as_of.isoformat()}. Main topics: "
          + "; ".join(name for name, _ in g.topics.values()))
    print(f"Read {len(g.citing)} company works citing these papers, {len(g.topical)} company "
          f"works in these topics and {len(g.sbir)} NIH SBIR/STTR records.")
    print(f"\nRoute B: {len(leads)} companies with two or more kinds of signal. {rb.LABEL}")
    for i, x in enumerate(leads, 1):
        print(f"\n{i}. {x.org.name}  ({x.relationship}; {x.confidence}; score {x.score:.2f})")
        if len(x.org.aliases) > 1:
            print(f"   merged: {'; '.join(x.org.aliases)}")
        for s, text in zip(x.signals, x.sentences, strict=True):
            print(f"   - {text}")
            print(f"     records: {', '.join(oa.short_id(i) for i in s.record_ids[:5])}"
                  + (" ..." if len(s.record_ids) > 5 else ""))
        print(f"   {x.org.source_url}")
    return 0


def explain_brief(b: object, args: argparse.Namespace) -> None:
    """Skills 1 and 2 with validator layers 1 and 2; prints rejection rates and spend."""
    import time

    from perch.grounding import FakeGrounder, MiniCheckGrounder
    from perch.llm import get_provider, spec_for_role
    from perch.llm.audit import AuditedProvider, AuditLog
    from perch.skills.fit import explain_leads
    from perch.skills.summary import summarise_profile

    fake = args.models == "fake"
    log = AuditLog(Path(args.db).parent / "logs/model_calls.jsonl")
    summ_spec = "fake:fake-1" if fake else (args.llm or spec_for_role("profile_summary"))
    fit_spec = "fake:fake-1" if fake else (args.llm or spec_for_role("fit_explainer"))
    grounder = None if args.grounder == "none" else (
        FakeGrounder() if fake or args.grounder == "fake" else MiniCheckGrounder(device="cpu"))
    with SQLiteRepository(args.db) as repo:
        works = {w.id: w for w in repo.works_by_author(b.researcher.id)}
    t0 = time.perf_counter()
    summary = summarise_profile(b.profile, works,
                                AuditedProvider(get_provider(summ_spec), log, "profile_summary"))
    t1 = time.perf_counter()
    fits = explain_leads([lead.opportunity for lead in b.leads], b.profile, works,
                         AuditedProvider(get_provider(fit_spec), log, "fit_explainer"),
                         grounder=grounder)
    t2 = time.perf_counter()
    print(f"\n== Explanations (models: summary {summ_spec}; fit {fit_spec}; "
          f"grounding {grounder.name if grounder else 'off'})")
    if summary.value:
        print("Research profile: " + "; ".join(t for t, _ in summary.value.topics))
        print("  " + summary.value.summary)
    else:
        print("Research profile summary withheld: it failed validation twice.")
    for i, (lead, v) in enumerate(zip(b.leads, fits, strict=True), 1):
        o = lead.opportunity
        if not v.value:
            print(f"\n{i:2}. {o.opportunity_number}: explanation withheld (failed validation "
                  "twice; flagged for review)")
            continue
        f = v.value
        print(f"\n{i:2}. {o.opportunity_number}  fit {f.fit}/100  (cites {', '.join(f.cited_ids)})")
        mark = "  [not supported by the cited record]"
        print(f"    {f.opportunity_sentence}"
              f"{mark if f.opportunity_sentence in f.unsupported else ''}")
        print(f"    {f.research_sentence}")
        for pid, clause in f.findings:
            if f"{pid} {clause}" in f.unsupported:
                print(f"      {pid}: \"{clause}\"{mark}")
        if f.link_sentence:
            print(f"    Inference: {f.link_sentence}")
    rej1, n1 = log.rejection_rate(layer=1)
    rej2, n2 = log.rejection_rate(layer=2)
    flagged = sum(v.flagged for v in fits) + summary.flagged
    tin, tout, cost = log.spend()
    print(f"\nValidator layer 1: {rej1} of {n1} outputs rejected; {flagged} withheld after "
          f"a second failure. Layer 2: {rej2} of {n2} explanations have an unsupported "
          f"factual statement.")
    print(f"Model calls: {sum(e['kind'] == 'call' for e in log.events)}; tokens in {tin:,}, "
          f"out {tout:,}; cost ${cost:.4f}; summary {t1 - t0:.1f} s, explanations "
          f"{t2 - t1:.1f} s.")


def cmd_mcp(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    """MCP server on stdio (S14). Nothing may be printed to stdout: it carries the protocol."""
    from perch.mcp_server import create_server, make_context, serve_stdio
    from perch.service import BriefService, Clients, default_models

    data = Path(args.db).parent
    service = BriefService(args.db, default_models(args.models == "fake", data, args.llm),
                           Clients(openalex=default_client), Path(args.overrides))
    ctx = make_context(service, args.author)
    serve_stdio(create_server(ctx))
    return 0


def cmd_serve(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    import uvicorn

    from perch.api import SERVE_OPTIONS, create_app
    from perch.jobs import InProcessRunner
    from perch.service import BriefService, Clients, default_models

    data = Path(args.db).parent
    repo_factory = None
    if env("PERCH_DATABASE_URL"):
        # v1: public records (browse lists, lead cards, evidence) come from Postgres, as in the
        # worker; only scratch briefs stay in SQLite. Without this the web read the empty
        # SQLite file and every list was empty on a fresh deployment (S48, found on the deploy).
        from perch.store import pg
        from perch.store.hybrid import HybridRepository

        pool = pg.make_pool(env("PERCH_DATABASE_URL"), 4)
        scratch = Path(args.db).with_name("briefs.db")
        repo_factory = lambda: HybridRepository(pool, scratch)  # noqa: E731
    service = BriefService(args.db, default_models(args.models == "fake", data, args.llm),
                           Clients(openalex=default_client), Path(args.overrides),
                           repo_factory=repo_factory)
    from perch.hardening import harden_process

    harden_process()
    # Warning level: no access log, so no request paths or addresses are written.
    from perch.scout.log import ScoutLog

    app = create_app(service, InProcessRunner(), scout_runner=InProcessRunner(workers=2),
                     scout_log=ScoutLog(data / "logs/scout.jsonl"))
    from perch.logs import uvicorn_log_config

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level,
                log_config=uvicorn_log_config(args.log_level),
                **SERVE_OPTIONS)
    return 0


def cmd_scout(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    from perch.scout import make_scout
    from perch.scout.log import ScoutLog, replay
    from perch.scout.tools import ScoutContext
    from perch.service import BriefService, Clients, default_models

    data = Path(args.db).parent
    service = BriefService(args.db, default_models(args.models == "fake", data),
                           Clients(openalex=default_client), Path(args.overrides))
    log = ScoutLog(data / "logs/scout.jsonl")
    if args.action == "replay":
        rows = replay(log, args.target, lambda r, a: ScoutContext(
            service, date.fromisoformat(a), r))
        for row in rows:
            mark = {True: "same result", False: "DIFFERENT result", None: row.get("note")}
            print(f"turn {row['turn']}  {row['tool']:<22} {mark[row['match']]}")
        return 0 if all(r["match"] is not False for r in rows) else 1
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    scout = make_scout(service, args.target, as_of=as_of, brief_id=args.brief, llm=args.llm,
                       policy=args.policy, log=log)
    s = scout.start(args.question)
    for c in s.cards:
        print(f"[{c.status}] {c.tool}({json.dumps(c.arguments)}): {c.detail}")
    print()
    print(s.answer if s.answer else f"(no answer: {'; '.join(s.errors)})")
    print(f"\nsession {s.id} · {s.model} · {s.policy} · {s.tokens:,} tokens · ${s.usd:.4f}")
    return 0 if s.answer else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="perch", description="See every route to fund your work.")
    p.add_argument("--db", default=None, help=f"SQLite store (default $PERCH_DB or {DEFAULT_DB})")
    p.add_argument("--overrides", default=str(aw.OVERRIDES), help="award link overrides CSV")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("resolve", help="find a Temple researcher in OpenAlex")
    r.add_argument("query", help="name, ORCID iD or OpenAlex author id")
    f = sub.add_parser("fetch", help="fetch records from a source into the store")
    f.add_argument("source", help="openalex, awards, opportunities, temple, fellowship-details "
                   "or temple-pages")
    f.add_argument("author_id", nargs="?", help="OpenAlex author id, e.g. A5026494099")
    f.add_argument("--statuses", default=grants_gov.OPEN_STATUSES,
                   help="opportunities: Grants.gov statuses (default forecasted|posted)")
    f.add_argument("--agencies", default="", help="opportunities: agency codes, e.g. HHS-NIH11")
    f.add_argument("--limit", type=int, default=None, help="opportunities: stop after N")
    f.add_argument("--opp-num", action="append", default=[],
                   help="opportunities: fetch this number in any status (repeatable)")
    f.add_argument("--inventory", default="data/temple/inventory.csv",
                   help="temple-pages: the inventory CSV")
    f.add_argument("--cache-dir", default="data/cache/temple_pages",
                   help="temple-pages: where cleaned pages are cached")
    f.add_argument("--refresh", action="store_true", help="temple-pages: refetch cached pages")
    f.add_argument("--pages-dir", default=None,
                   help="fellowship-details: save each page's extracted text here (hand-checks)")
    ex = sub.add_parser("extract", help="propose award records from cached pages")
    ex.add_argument("source", choices=["temple-pages"])
    ex.add_argument("--cache-dir", default="data/cache/temple_pages")
    ex.add_argument("--out", default=None,
                    help="default data/temple/pilot_s39.jsonl, or extracted.jsonl with --all")
    ex.add_argument("--all", action="store_true",
                    help="every cached page; appends to --out and skips pages already done")
    ex.add_argument("--restart", action="store_true", help="with --all: discard earlier output")
    ex.add_argument("--pilot", type=int, default=20,
                    help="pages to extract, spread across owners")
    ex.add_argument("--budget", type=float, default=1.0,
                    help="stop when this many USD have been spent in the run")
    tp = sub.add_parser("temple", help="the versioned Temple awards dataset")
    tsub = tp.add_subparsers(dest="temple_command", required=True)
    bd = tsub.add_parser("build-dataset", help="dedupe an extraction file into the next "
                         "temple_awards_v<N>.jsonl with a manifest")
    bd.add_argument("--input", default="data/temple/extracted.jsonl")
    bd.add_argument("--out-dir", default="data/temple/dataset")
    bd.add_argument("--version", type=int, default=None, help="default: the next free number")
    ld = tsub.add_parser("load-dataset", help="load a dataset file into the store (idempotent)")
    ld.add_argument("file")
    ld.add_argument("--dsn", default=None, help="load into this Postgres URL instead of --db")
    pr = sub.add_parser("profile", help="key papers, awards and the public award horizon")
    pr.add_argument("author_id", help="OpenAlex author id")
    pr.add_argument("--papers", type=int, default=10, help="key papers to show (default 10)")
    b = sub.add_parser("brief", help="ranked Route A leads")
    b.add_argument("author_id", help="OpenAlex author id")
    b.add_argument("--route", default="A",
                   help="A (grants and foundations) or B (industry leads, public signals)")
    b.add_argument("--top", type=int, default=10)
    b.add_argument("--as-of", default=None, help="date, YYYY-MM-DD (default today)")
    b.add_argument("--min-amount", type=float, default=None, help="drop if ceiling is below")
    b.add_argument("--agency", action="append", default=[], help="keep only this agency")
    b.add_argument("--include-forecasted", action="store_true")
    b.add_argument("--include-restricted", action="store_true",
                   help="keep limited-competition and career-stage-restricted opportunities")
    b.add_argument("--models", choices=["local", "fake"], default="local",
                   help="fake: no model downloads (tests)")
    b.add_argument("--embedder", default="Qwen/Qwen3-Embedding-0.6B")
    b.add_argument("--reranker", default="Qwen/Qwen3-Reranker-0.6B")
    b.add_argument("--explain", action="store_true",
                   help="add the profile summary and fit explanations (model calls)")
    b.add_argument("--llm", default=None, help="provider spec for both skills, e.g. "
                   "ollama:qwen3.8:27b (default: PERCH_LLM_<ROLE>)")
    b.add_argument("--grounder", choices=["minicheck", "fake", "none"], default="minicheck",
                   help="validator layer 2")
    sc = sub.add_parser("scout", help="ask Scout a question (runs every step), or replay a "
                        "session's tool calls")
    sc.add_argument("action", choices=["ask", "replay"])
    sc.add_argument("target", help="ask: OpenAlex author id; replay: session id")
    sc.add_argument("question", nargs="?", default="")
    sc.add_argument("--brief", default=None, help="brief id the question is about")
    sc.add_argument("--as-of", default=None, help="date, YYYY-MM-DD (default today)")
    sc.add_argument("--llm", default=None, help="provider spec (default PERCH_LLM_SCOUT)")
    sc.add_argument("--policy", choices=["native", "structured"], default=None,
                    help="structured: JSON steps for models that tool-call poorly")
    sc.add_argument("--models", choices=["local", "fake"], default="local")
    m = sub.add_parser("mcp", help="run Perch's tools as an MCP server on stdio")
    m.add_argument("--author", help="OpenAlex author id the tools default to")
    m.add_argument("--models", choices=["local", "fake"], default="local")
    m.add_argument("--llm", default=None, help="provider spec for the model-backed tools")
    sub.add_parser("samples", help="load the SYNTHETIC sample scholarships into their own "
                   "store (student mode)")
    dbp = sub.add_parser("db", help="database tasks (Postgres)")
    dbsub = dbp.add_subparsers(dest="db_command", required=True)
    mg = dbsub.add_parser("migrate", help="apply the SQL migrations to the perch database")
    mg.add_argument("--dsn", default=None, help="admin or owner URL; default PERCH_DATABASE_URL")
    mc = dbsub.add_parser("migrate-corpus", help="copy the public corpus into Postgres")
    mc.add_argument("--dsn", default=None, help="write URL; default PERCH_DATABASE_URL")
    mc.add_argument("--sqlite", default=None, help="record store; default the --db store")
    mc.add_argument("--lance", default=None, help="Lance dir; default <store dir>/lance")
    mc.add_argument("--samples", default=None, help="SYNTHETIC sample store; default "
                    "PERCH_SAMPLE_DB or <store dir>/sample.db; 'none' skips it")
    mc.add_argument("--cache", default=None, help="embedding cache; default "
                    "<store dir>/cache/embeddings.db")
    wk = sub.add_parser("worker", help="run job threads against the Postgres queue")
    wk.add_argument("--concurrency", type=int, default=None, help="job threads; default "
                    "PERCH_WORKER_CONCURRENCY or 16")
    wk.add_argument("--kinds", default=None, help="comma list; default PERCH_WORKER_KINDS or all")
    wk.add_argument("--check", action="store_true", help="health check: exit 0 if this worker's "
                    "heartbeat row is under 90 seconds old, else 1; starts nothing")
    pc = sub.add_parser("precache", help="enqueue the nightly researcher pre-cache jobs")
    pc.add_argument("--limit", type=int, default=None, help="only the first N researchers")
    pc.add_argument("--dry-run", action="store_true", help="count, enqueue nothing")
    ky = sub.add_parser("keys", help="key tasks")
    kysub = ky.add_subparsers(dest="keys_command", required=True)
    rm = kysub.add_parser("rotate-master", help="re-wrap data keys under the current master key")
    rm.add_argument("--old", default=None, help="default PERCH_MASTER_KEY_PREV_ID")
    rm.add_argument("--new", default=None, help="default PERCH_MASTER_KEY_ID")
    rm.add_argument("--dry-run", action="store_true", help="count rows on the old id, "
                    "change nothing")
    rk = kysub.add_parser("rekey", help="re-encrypt stored blobs under each user's newest data "
                          "key version (the old versions stay readable)")
    rk.add_argument("--user", default=None, help="one user id; default every user whose data "
                    "key was rotated")
    rk.add_argument("--dry-run", action="store_true", help="count stale rows, change nothing")
    tb = kysub.add_parser("tombstones", help="tombstone retention")
    tbsub = tb.add_subparsers(dest="tombstones_command", required=True)
    tp = tbsub.add_parser("purge", help="remove tombstones older than the retention (default "
                          "400 days, never less than the longest backup); counts only. Without "
                          "--apply it is a dry run.")
    tp.add_argument("--apply", action="store_true", help="really delete; default is a dry run")
    tp.add_argument("--days", type=int, default=None, help="retention; default "
                    "PERCH_TOMBSTONE_RETENTION_DAYS or 400; refused below 400")
    sub.add_parser("reconcile-shreds", help="after a restore: re-assert tombstones from all "
                   "three sources, delete the restored rows of shredded users, clear the "
                   "restore marker. Run in the worker container (perch_worker reads shred_log)")
    sub.add_parser("restore-mark", help="before a restore: write the restore marker on the "
                   "shred ledger volume; the web answers 503 on user routes until the worker "
                   "has reconciled")
    sv = sub.add_parser("serve", help="run the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8100)
    sv.add_argument("--models", choices=["local", "fake"], default="local")
    sv.add_argument("--llm", default=None, help="provider spec for both skills")
    sv.add_argument("--log-level", default="warning",
                    choices=["critical", "error", "warning", "info", "debug"])
    return p


def worker_check(max_age_s: int = 90) -> int:
    """Compose health check: this container's worker wrote a heartbeat row recently. The
    worker id is `<hostname>-<pid>`, and the hostname is unique per container."""
    import socket

    import psycopg

    dsn = env("PERCH_DATABASE_DIRECT_URL") or env("PERCH_DATABASE_URL")
    if not dsn:
        return 1
    try:
        with psycopg.connect(dsn, connect_timeout=5) as c:
            row = c.execute(
                "SELECT count(*) FROM worker_heartbeat WHERE worker LIKE %s "
                "AND at > now() - make_interval(secs => %s)",
                (socket.gethostname() + "-%", max_age_s)).fetchone()
    except Exception:  # noqa: BLE001
        return 1
    return 0 if row and row[0] > 0 else 1


def cmd_worker(args: argparse.Namespace) -> int:
    import logging
    import os
    import signal
    import socket
    import threading

    if args.check:
        return worker_check()
    if env("PERCH_ENV") == "prod" and not (env("PERCH_AUDIT_KEY") or "").strip():
        print("refusing to start: PERCH_AUDIT_KEY must be set when PERCH_ENV=prod "
              "(for example `openssl rand -base64 32`); see .env.example", file=sys.stderr)
        return 2

    from perch.jobs import PostgresRunner, set_brief_service
    from perch.redisx import get_client

    n = args.concurrency or int(env("PERCH_WORKER_CONCURRENCY", "16") or 16)
    runner = PostgresRunner(pool_size=2 * n + 4)

    built: list[object] = []
    lock = threading.Lock()

    def brief_service() -> object:
        """One BriefService per worker process, built on first use. The job handlers call
        this for every job; building it each time reloaded the embedder, reranker and
        MiniCheck per brief and ran the GPU out of memory at four briefs in flight (S47)."""
        with lock:
            if not built:
                built.append(make_brief_service())
            return built[0]

    def make_brief_service() -> object:
        from dataclasses import replace

        from perch.service import BriefService, Clients, default_models
        from perch.store.hybrid import HybridRepository
        from perch.store.postgres import PgVectorIndex

        models = default_models(False, Path(args.db).parent, None)
        # Public records and the vector index come from Postgres; briefs stay in scratch
        # SQLite until they become encrypted user data. Ingest fills the index.
        from perch.profiles import current

        models = replace(models, index=lambda: PgVectorIndex(
            index_name="opportunities", embedder=current().embedder, pool=runner.pool))
        scratch = Path(args.db).with_name("briefs.db")
        svc = BriefService(args.db, models, Clients(openalex=default_client),
                           Path(args.overrides),
                           repo_factory=lambda: HybridRepository(runner.pool, scratch),
                           index_new=False)
        from perch.cache import PublicCache

        svc.public_cache = PublicCache(
            runner.pool, get_client() if env("PERCH_REDIS_URL") else None)
        return svc

    set_brief_service(brief_service)
    from perch.logs import configure as configure_logs

    configure_logs(logging.INFO)
    kinds = [k for k in (args.kinds or env("PERCH_WORKER_KINDS", "") or "").split(",") if k]
    import perch.scout.job  # noqa: F401 - registers the `scout_turn` handler (S44)
    import perch.user.delete  # noqa: F401 - registers the `purge` handler (S41 part B)
    from perch import shredhooks

    stop_sub = shredhooks.install(runner.pool, get_client() if env("PERCH_REDIS_URL") else None,
                                  runner)  # refuses to start without the shred ledger (S48 M3)
    try:  # reconcile before any job runs when a restore is marked or the copies disagree
        shredhooks.reconcile_at_start(env("PERCH_KEYS_DATABASE_URL"), runner.pool)
    except shredhooks.LedgerMissing as e:
        print(str(e), file=sys.stderr)
        return 2
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    scheduler = None
    if (env("PERCH_SCHEDULER", "1") or "1") != "0":  # daily purges and the nightly precache
        from perch.jobs import Scheduler
        from perch.precache import enqueue_nightly

        scheduler = Scheduler.from_env(enqueue_nightly)
    runner.run_forever(f"{socket.gethostname()}-{os.getpid()}", kinds, n, stop,
                       scheduler=scheduler)
    stop_sub()
    runner.close()
    return 0


def cmd_precache(args: argparse.Namespace) -> int:
    """Enqueue one `precache` job per Temple-affiliated researcher (a worker runs them)."""
    from datetime import date

    from perch.jobs import PostgresRunner
    from perch.precache import enqueue_nightly

    runner = PostgresRunner()
    try:  # the date in the key makes a second run the same day a no-op
        n = enqueue_nightly(runner, date.today().isoformat(), limit=args.limit,
                            dry_run=args.dry_run)
        print(f"{'would enqueue' if args.dry_run else 'enqueued'} {n} precache jobs")
    finally:
        runner.close()
    return 0


def _audit_pool():  # noqa: ANN202
    """A pool for the audit row, or None when no database is configured."""
    from perch.store.pg import make_pool

    return make_pool(max_size=2) if env("PERCH_DATABASE_URL") else None


def cmd_keys(args: argparse.Namespace) -> int:
    from uuid import UUID

    from perch import crypto, keyops
    from perch.store.pg import make_pool

    if args.keys_command == "rotate-master":
        old = args.old or env("PERCH_MASTER_KEY_PREV_ID")
        new = args.new or env("PERCH_MASTER_KEY_ID")
        if not old or not new:
            print("Set PERCH_MASTER_KEY_ID and PERCH_MASTER_KEY_PREV_ID, or pass --old/--new.",
                  file=sys.stderr)
            return 2
        try:
            n = crypto.rotate_master(old, new, dry_run=args.dry_run)
        except crypto.CryptoError as e:
            print(f"rotate-master stopped: {type(e).__name__}", file=sys.stderr)
            return 1
        if args.dry_run:
            print(f"Dry run: {n} rows are wrapped under {old}. Nothing changed.")
            return 0
        pool = _audit_pool()
        if pool is not None:
            try:
                keyops.audit(pool, "key_rotate_master", old_id=old, new_id=new, rows=n)
            finally:
                pool.close()
        print(f"Rewrapped {n} rows from {old} to {new}. Remove the old key when this reads 0.")
    elif args.keys_command == "rekey":
        try:
            uid = UUID(args.user) if args.user else None
        except ValueError:
            print("--user must be a user id.", file=sys.stderr)
            return 2
        if not env("PERCH_DATABASE_URL"):
            print("Set PERCH_DATABASE_URL.", file=sys.stderr)
            return 2
        pool = make_pool(max_size=4)
        try:
            if uid is not None:
                res = {"users": 1, **keyops.rekey_user(pool, uid, dry_run=args.dry_run)}
            else:
                res = keyops.rekey_all(pool, dry_run=args.dry_run)
            if not args.dry_run:
                keyops.audit(pool, "key_rotate_data", **res)
        except crypto.CryptoError as e:
            print(f"rekey stopped: {type(e).__name__}", file=sys.stderr)
            return 1
        finally:
            pool.close()
        verb = "Dry run, nothing changed" if args.dry_run else "Rekeyed"
        print(f"{verb}: users {res['users']}, stale rows {res['stale']}, re-encrypted "
              f"{res['done']}, failed {res['failed']}.")
        return 1 if res["failed"] else 0
    elif args.keys_command == "tombstones":
        if not env("PERCH_DATABASE_URL"):
            print("Set PERCH_DATABASE_URL.", file=sys.stderr)
            return 2
        pool = make_pool(max_size=2)
        try:
            res = keyops.purge_old_tombstones(pool, dry_run=not args.apply, days=args.days)
            if args.apply:
                keyops.audit(pool, "tombstones_purge", **res)
        except crypto.CryptoError as e:
            print(f"tombstones purge stopped: {type(e).__name__}", file=sys.stderr)
            return 1
        finally:
            pool.close()
        print(("Removed" if args.apply else "Dry run, would remove")
              + f" tombstones older than {res['retention_days']} days: key database "
              f"{res['key_tombstones']}, shred_log {res['shred_log']}, ledger {res['ledger']}.")
    return 0


def cmd_reconcile_shreds(args: argparse.Namespace) -> int:
    from perch import shredhooks
    from perch.store.pg import make_pool

    keys_dsn = env("PERCH_KEYS_DATABASE_URL")
    if not keys_dsn:
        print("Set PERCH_KEYS_DATABASE_URL.", file=sys.stderr)
        return 2
    pool = make_pool()
    try:
        res = shredhooks.reconcile(keys_dsn, pool)
    finally:
        pool.close()
    print(f"Reconciled {res['ids']} shredded users; {res['key_rows_revived']} had key rows "
          f"and {res['user_rows_removed']} had user rows that were removed. Restore marker "
          "cleared.")
    return 0


def cmd_restore_mark(args: argparse.Namespace) -> int:
    from perch import shredhooks

    try:
        shredhooks.mark_restore()
    except shredhooks.LedgerMissing as e:
        print(str(e), file=sys.stderr)
        return 2
    print("Restore marker written. User routes answer 503 until the worker has reconciled.")
    return 0


def cmd_db(args: argparse.Namespace) -> int:
    from perch.db.migrate import migrate

    dsn = args.dsn or env("PERCH_DATABASE_URL")
    if not dsn:
        print("Set PERCH_DATABASE_URL or pass --dsn.", file=sys.stderr)
        return 2
    if args.db_command == "migrate-corpus":
        from perch.db.corpus import CorpusError, format_report, migrate_corpus

        base = Path(args.sqlite or args.db)
        sample = args.samples or env("PERCH_SAMPLE_DB") or str(base.parent / "sample.db")
        try:
            rep = migrate_corpus(dsn, base, Path(args.lance or base.parent / "lance"),
                                 None if sample == "none" else Path(sample),
                                 Path(args.cache or base.parent / "cache/embeddings.db"))
        except CorpusError as e:
            print(f"migrate-corpus stopped: {e}", file=sys.stderr)
            return 1
        print(format_report(rep))
        return 1 if rep["verify"]["mismatches"] else 0
    applied = migrate(dsn)
    print("Applied: " + (", ".join(applied) if applied else "nothing, already current"))
    return 0


def main(argv: Sequence[str] | None = None, client_factory: ClientFactory | None = None,
         nih_factory: Callable[[], nih_reporter.NIHReporterClient] = nih_reporter.NIHReporterClient,
         nsf_factory: Callable[[], nsf.NSFClient] = nsf.NSFClient,
         grants_factory: Callable[[], grants_gov.GrantsGovClient] = grants_gov.GrantsGovClient,
         ) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    args.db = args.db or env("PERCH_DB", DEFAULT_DB)
    if args.command == "db":
        return cmd_db(args)
    if args.command == "worker":
        return cmd_worker(args)
    if args.command == "precache":
        return cmd_precache(args)
    if args.command == "keys":
        return cmd_keys(args)
    if args.command == "extract":
        return cmd_extract(args)
    if args.command == "temple":
        return cmd_temple(args)
    if args.command == "reconcile-shreds":
        return cmd_reconcile_shreds(args)
    if args.command == "restore-mark":
        return cmd_restore_mark(args)
    args.nih_factory, args.nsf_factory = nih_factory, nsf_factory
    args.grants_factory = grants_factory
    commands = {"resolve": cmd_resolve, "samples": cmd_samples,
                "fetch": cmd_fetch, "profile": cmd_profile,
                "brief": cmd_brief, "serve": cmd_serve, "scout": cmd_scout,
                "mcp": cmd_mcp}
    with (client_factory or default_client)() as client:
        return commands[args.command](args, client)


if __name__ == "__main__":
    sys.exit(main())
