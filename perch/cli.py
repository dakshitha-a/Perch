"""Command line: perch resolve <name|orcid|author id>, perch fetch openalex <author id>."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from perch.config import env, load_dotenv
from perch.schemas import Researcher
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


def cmd_fetch(args: argparse.Namespace, client: oa.OpenAlexClient) -> int:
    if args.source != "openalex":
        print(f"Unknown source {args.source!r}. Available: openalex.", file=sys.stderr)
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="perch", description="See every route to fund your work.")
    p.add_argument("--db", default=None, help=f"SQLite store (default $PERCH_DB or {DEFAULT_DB})")
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("resolve", help="find a Temple researcher in OpenAlex")
    r.add_argument("query", help="name, ORCID iD or OpenAlex author id")
    f = sub.add_parser("fetch", help="fetch records from a source into the store")
    f.add_argument("source", help="openalex")
    f.add_argument("author_id", help="OpenAlex author id, e.g. A5026494099")
    return p


def main(argv: Sequence[str] | None = None, client_factory: ClientFactory | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    args.db = args.db or env("PERCH_DB", DEFAULT_DB)
    commands = {"resolve": cmd_resolve, "fetch": cmd_fetch}
    with (client_factory or default_client)() as client:
        return commands[args.command](args, client)


if __name__ == "__main__":
    sys.exit(main())
