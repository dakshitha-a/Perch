"""Command line.

  perch resolve <name|orcid|author id>
  perch fetch openalex <author id>
  perch fetch awards <author id>      NIH RePORTER and NSF awards at Temple, by name
  perch profile <author id>           key papers, awards and the public award horizon
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from perch import awards as aw
from perch.config import env, load_dotenv
from perch.profile import MAX_AUTHORS, key_papers
from perch.schemas import Award, Researcher
from perch.sources import nih_reporter, nsf
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


def cmd_fetch(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    if args.source == "awards":
        return fetch_awards(args, client)
    if args.source != "openalex":
        print(f"Unknown source {args.source!r}. Available: openalex, awards.", file=sys.stderr)
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="perch", description="See every route to fund your work.")
    p.add_argument("--db", default=None, help=f"SQLite store (default $PERCH_DB or {DEFAULT_DB})")
    p.add_argument("--overrides", default=str(aw.OVERRIDES), help="award link overrides CSV")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("resolve", help="find a Temple researcher in OpenAlex")
    r.add_argument("query", help="name, ORCID iD or OpenAlex author id")
    f = sub.add_parser("fetch", help="fetch records from a source into the store")
    f.add_argument("source", help="openalex or awards")
    f.add_argument("author_id", help="OpenAlex author id, e.g. A5026494099")
    pr = sub.add_parser("profile", help="key papers, awards and the public award horizon")
    pr.add_argument("author_id", help="OpenAlex author id")
    pr.add_argument("--papers", type=int, default=10, help="key papers to show (default 10)")
    return p


def main(argv: Sequence[str] | None = None, client_factory: ClientFactory | None = None,
         nih_factory: Callable[[], nih_reporter.NIHReporterClient] = nih_reporter.NIHReporterClient,
         nsf_factory: Callable[[], nsf.NSFClient] = nsf.NSFClient) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    args.db = args.db or env("PERCH_DB", DEFAULT_DB)
    args.nih_factory, args.nsf_factory = nih_factory, nsf_factory
    commands = {"resolve": cmd_resolve, "fetch": cmd_fetch, "profile": cmd_profile}
    with (client_factory or default_client)() as client:
        return commands[args.command](args, client)


if __name__ == "__main__":
    sys.exit(main())
