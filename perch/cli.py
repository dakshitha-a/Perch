"""Command line.

  perch resolve <name|orcid|author id>
  perch fetch openalex <author id>
  perch fetch awards <author id>      NIH RePORTER and NSF awards at Temple, by name
  perch fetch opportunities           Grants.gov opportunities (nightly refresh: upsert by number)
  perch profile <author id>           key papers, awards and the public award horizon
  perch brief <author id> --route A   ranked, eligible Route A leads (record fields only)
  perch brief <author id> --route B   industry leads from public signals (inferred)
  perch brief <author id> --explain   plus profile summary and validated fit explanations
  perch monitor --author <id> ...     weekly watch: refresh, re-run, compare, draft (S16)
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
        fetched: list[Award] = []
        with args.nih_factory() as nih_client, args.nsf_factory() as nsf_client:
            for name in aw.query_names(r, ov):
                first, last = aw.search_name(name)
                fetched += nih_client.awards_for_pi(first, last)
                fetched += nsf_client.awards_for_pi(f"{first} {last}")
        repo.upsert([r, *fetched])
        linked = aw.link_awards(r, fetched, ov)
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
    if args.source != "openalex":
        print(f"Unknown source {args.source!r}. Available: openalex, awards, opportunities.",
              file=sys.stderr)
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
        linked = aw.link_awards(r, repo.list(Award), ov)
    print(describe(r))
    print(f"\nKey papers (most cited of {len(works)} works in the store; papers with more "
          f"than {MAX_AUTHORS} authors skipped):")
    for w in key_papers(works, args.papers):
        venue = w.venue or "venue not listed"
        print(f"  {w.publication_year or 'n.d.'}  {w.title}  ({venue}; "
              f"{w.cited_by_count or 0} citations)  {w.doi or w.id}")
    summaries = aw.summarise(linked)
    print(f"\nPublic federal awards ({len(summaries)}), latest end date first:")
    for s in summaries:
        foa = ", ".join(s.opportunity_numbers) or "no opportunity number in record"
        print(f"  {s.award_number}  {s.agency}  {fmt_date(s.start_date)} to "
              f"{fmt_date(s.end_date)}  {foa}  {s.title}")
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
    audit = None
    if args.private:
        from perch.llm.audit import AuditLog
        from perch.privacy import PrivateSettings, harden_process
        from perch.private.session import PrivateSessions

        settings = PrivateSettings.from_env()
        problems = settings.problems() if settings.enabled else ["PERCH_PRIVATE_MODE is not 1"]
        if problems:
            print("perch mcp --private: private mode cannot start:\n  " + "\n  ".join(problems),
                  file=sys.stderr)
            return 2
        harden_process()
        try:
            service = PrivateSessions(service, settings).open().service
        except PermissionError as e:
            print(f"perch mcp --private: {e}", file=sys.stderr)
            return 2
        audit = AuditLog(None)
    ctx = make_context(service, args.author, audit=audit)
    serve_stdio(create_server(ctx, private=args.private))
    return 0


def cmd_serve(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    import uvicorn

    from perch.api import create_app
    from perch.jobs import InProcessRunner
    from perch.service import BriefService, Clients, default_models

    data = Path(args.db).parent
    service = BriefService(args.db, default_models(args.models == "fake", data, args.llm),
                           Clients(openalex=default_client), Path(args.overrides))
    from perch.privacy import PrivateSettings, harden_process

    private = PrivateSettings.from_env()
    if private.enabled and (problems := private.problems()):
        print("perch serve: private mode cannot start:\n  " + "\n  ".join(problems))
        return 2
    harden_process()
    # Warning level: no access log, so no request paths or addresses are written.
    from perch.scout.log import ScoutLog

    app = create_app(service, InProcessRunner(), scout_runner=InProcessRunner(workers=2),
                     scout_log=ScoutLog(data / "logs/scout.jsonl"))
    uvicorn.run(app, host=args.host, port=args.port,
                log_level=args.log_level)
    return 0


def cmd_monitor(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    from perch import monitor
    from perch.service import BriefService, Clients, default_models

    authors = args.author or [a for a in (env("PERCH_WATCH") or "").split(",") if a.strip()]
    if not authors:
        print("perch monitor needs --author, or PERCH_WATCH set to author ids.",
              file=sys.stderr)
        return 2
    data = Path(args.db).parent
    service = BriefService(args.db, default_models(args.models == "fake", data, args.llm),
                           Clients(openalex=default_client, nih=args.nih_factory,
                                   nsf=args.nsf_factory), Path(args.overrides))
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    digests = monitor.run(service, [a.strip() for a in authors],
                          None if args.no_refresh else args.grants_factory, as_of,
                          not args.no_explain, args.limit)
    if digests and digests[0].refresh:
        n = digests[0].refresh
        print(f"Grants.gov: {n['listed']} open listed; {n['new']} new, {n['changed']} changed, "
              f"{n['failed']} failed.")
        print(grants_gov.ATTRIBUTION)
    for d in digests:
        fired = [c for c in d.changes if c.trigger]
        print(f"{d.researcher_id.rsplit('/', 1)[-1]}: brief {d.brief_id}, "
              f"{len(d.changes)} changes, {len(fired)} triggers, "
              + ("first run (baseline)" if d.baseline_brief_id is None else
                 f"compared with brief {d.baseline_brief_id}")
              + (f"; draft: {d.draft_subject}" if d.draft_subject else "; no draft"))
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
                       mode="run", policy=args.policy, log=log)
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
    f.add_argument("source", help="openalex, awards or opportunities")
    f.add_argument("author_id", nargs="?", help="OpenAlex author id, e.g. A5026494099")
    f.add_argument("--statuses", default=grants_gov.OPEN_STATUSES,
                   help="opportunities: Grants.gov statuses (default forecasted|posted)")
    f.add_argument("--agencies", default="", help="opportunities: agency codes, e.g. HHS-NIH11")
    f.add_argument("--limit", type=int, default=None, help="opportunities: stop after N")
    f.add_argument("--opp-num", action="append", default=[],
                   help="opportunities: fetch this number in any status (repeatable)")
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
    m.add_argument("--private", action="store_true",
                   help="private session: no writes or logs; self-hosted models only")
    m.add_argument("--models", choices=["local", "fake"], default="local")
    m.add_argument("--llm", default=None, help="provider spec for the model-backed tools")
    mo = sub.add_parser("monitor", help="weekly watch: refresh opportunities, re-run briefs, "
                        "compare with the last run, draft an email (never sent)")
    mo.add_argument("--author", action="append", default=[],
                    help="OpenAlex author id to watch (repeatable; default PERCH_WATCH)")
    mo.add_argument("--as-of", default=None, help="run date, YYYY-MM-DD (default today)")
    mo.add_argument("--no-refresh", action="store_true", help="skip the Grants.gov refresh")
    mo.add_argument("--limit", type=int, default=None, help="refresh: stop after N listings")
    mo.add_argument("--no-explain", action="store_true", help="briefs without explanations")
    mo.add_argument("--models", choices=["local", "fake"], default="local")
    mo.add_argument("--llm", default=None, help="provider spec for the skills")
    sv = sub.add_parser("serve", help="run the HTTP API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8100)
    sv.add_argument("--models", choices=["local", "fake"], default="local")
    sv.add_argument("--llm", default=None, help="provider spec for both skills")
    sv.add_argument("--log-level", default="warning",
                    choices=["critical", "error", "warning", "info", "debug"])
    return p


def main(argv: Sequence[str] | None = None, client_factory: ClientFactory | None = None,
         nih_factory: Callable[[], nih_reporter.NIHReporterClient] = nih_reporter.NIHReporterClient,
         nsf_factory: Callable[[], nsf.NSFClient] = nsf.NSFClient,
         grants_factory: Callable[[], grants_gov.GrantsGovClient] = grants_gov.GrantsGovClient,
         ) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    args.db = args.db or env("PERCH_DB", DEFAULT_DB)
    args.nih_factory, args.nsf_factory = nih_factory, nsf_factory
    args.grants_factory = grants_factory
    commands = {"resolve": cmd_resolve, "fetch": cmd_fetch, "profile": cmd_profile,
                "brief": cmd_brief, "serve": cmd_serve, "monitor": cmd_monitor, "scout": cmd_scout,
                "mcp": cmd_mcp}
    with (client_factory or default_client)() as client:
        return commands[args.command](args, client)


if __name__ == "__main__":
    sys.exit(main())
