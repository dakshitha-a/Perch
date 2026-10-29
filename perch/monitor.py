"""Monitoring (S16): Perch tells you before you need it.

A weekly job. It first refreshes open NIH opportunities from Grants.gov as a delta: the
search lists every open one, and a full record is fetched only when it is new or its
close date or status changed. Then, for each watched researcher, it runs a fresh brief
(never a reused copy) and compares it with the last run. Two triggers:

- an award ending: a linked public award ends within 12 months of the run date;
- a new opportunity: one in the fresh brief's top 10 that was not a lead last run.
  Rerank scores are not on one scale across researchers (top scores from 0.015 to 0.98
  in the demo store), so the threshold is a position, the top 10, not a score.

When a trigger fires, code writes an email draft to the researcher. No model writes any
of it, every date and amount is copied from a record, and nothing is sent (standing
rule 7). Each run is stored as a Digest record; the What changed screen reads them.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime

import httpx

from perch import awards as aw
from perch.schemas import (
    Award,
    Brief,
    Change,
    Digest,
    Lead,
    Opportunity,
    Organisation,
    Record,
    Researcher,
)
from perch.service import BriefService, brief_options
from perch.skills.handoff import lead_lines
from perch.sources import grants_gov
from perch.sources import openalex as oa
from perch.store.base import Repository

NIH = "HHS-NIH11"  # the agency code the store's open opportunities were fetched with (S3)
TOP = 10


def now() -> datetime:
    return datetime.now(UTC)


def year_after(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 February
        return d.replace(year=d.year + 1, day=28)


# --- Grants.gov delta refresh ---

def refresh_opportunities(repo: Repository, gg: grants_gov.GrantsGovClient,
                          agencies: str = NIH, statuses: str = grants_gov.OPEN_STATUSES,
                          limit: int | None = None) -> dict[str, int]:
    """Fetch the full record only for hits that are new, or whose status or close date
    differs from the stored record. Returns counts; a record that fails to fetch is
    counted and left as it was."""
    n = {"listed": 0, "new": 0, "changed": 0, "unchanged": 0, "failed": 0}
    for h in gg.iter_hits(statuses, agencies, limit=limit):
        n["listed"] += 1
        old = repo.get(Opportunity, f"{grants_gov.SOURCE}:{h['number']}")
        if old and old.status == h.get("oppStatus") \
                and old.close_date == grants_gov.hit_close_date(h):
            n["unchanged"] += 1
            continue
        try:
            o = gg.fetch(h["id"], h.get("oppStatus"))
        except (httpx.HTTPError, RuntimeError):  # one bad record must not stop the week
            n["failed"] += 1
            continue
        same = old is not None and old.model_dump(exclude={"fetched_at"}) \
            == o.model_dump(exclude={"fetched_at"})
        n["new" if old is None else "unchanged" if same else "changed"] += 1
        repo.upsert([o])
    return n


# --- the last run ---

def digests_for(repo: Repository, researcher_id: str) -> list[Digest]:
    """Newest first."""
    return sorted((d for d in repo.list(Digest) if d.researcher_id == researcher_id),
                  key=lambda d: d.fetched_at, reverse=True)


def baseline(repo: Repository, researcher_id: str, options: dict,
             before: datetime) -> tuple[Brief | None, Digest | None]:
    """The last digest's brief, or else the newest finished brief for the same researcher
    and options (any as_of) made before this run. (None, None) on a first run."""
    last = next(iter(digests_for(repo, researcher_id)), None)
    if last and (b := repo.get(Brief, last.brief_id)):
        return b, last
    same = {k: v for k, v in options.items() if k != "as_of"}
    done = [b for b in repo.list(Brief) if b.researcher_id == researcher_id
            and b.status == "done" and b.created_at < before
            and {k: v for k, v in b.options.items() if k != "as_of"} == same]
    return (max(done, key=lambda b: b.created_at) if done else None), None


# --- what changed ---

def _leads(repo: Repository, b: Brief | None, route: str) -> list[Lead]:
    if b is None:
        return []
    return [x for x in (repo.get(Lead, i) for i in b.lead_ids) if x and x.route == route]


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _opp_title(o: Opportunity | None, record_id: str) -> str:
    return f"{o.opportunity_number}: {o.title}" if o else record_id


def changes_since(repo: Repository, brief: Brief, base: Brief | None,
                  last: Digest | None, as_of: date) -> list[Change]:
    out: list[Change] = []
    # Awards: every linked award whose latest record ends within 12 months.
    keys = set(brief.award_ids)
    told = {c.record_id for c in (last.changes if last else []) if c.kind == "award_ending"}
    for s in aw.summarise(a for a in repo.list(Award) if aw.award_key(a) in keys):
        if s.end_date and s.end_record and as_of <= s.end_date <= year_after(as_of):
            rid = s.end_record.id
            out.append(Change(kind="award_ending", record_id=rid,
                              title=f"{s.award_number}: {s.title}",
                              source_url=s.end_record.source_url, after=_iso(s.end_date),
                              trigger=rid not in told))
    if base is None:  # a first run is the baseline; nothing to compare with
        return out
    now_a = {x.record_id: x for x in _leads(repo, brief, "A")}
    was_a = {x.record_id: x for x in _leads(repo, base, "A")}
    for rid, x in now_a.items():
        if rid not in was_a and (x.rank or TOP + 1) <= TOP:
            o = repo.get(Opportunity, rid)
            out.append(Change(kind="new_lead", record_id=rid, title=_opp_title(o, rid),
                              source_url=x.source_url, after=_iso(o.close_date if o else None),
                              trigger=True))
    for rid, x in was_a.items():
        if rid not in now_a:
            o = repo.get(Opportunity, rid)
            closed = o and o.close_date and o.close_date < as_of
            out.append(Change(kind="dropped_lead", record_id=rid, title=_opp_title(o, rid),
                              source_url=x.source_url,
                              after=_iso(o.close_date) if closed and o else None))
    if last and last.brief_id == base.id:  # the snapshot holds last run's close dates
        before = {s["record_id"]: s.get("close_date") for s in last.snapshot}
        for rid in now_a.keys() & before.keys():
            o = repo.get(Opportunity, rid)
            if o and _iso(o.close_date) != before[rid]:
                out.append(Change(kind="close_date", record_id=rid, title=_opp_title(o, rid),
                                  source_url=o.source_url, before=before[rid],
                                  after=_iso(o.close_date)))
    was_b = {x.record_id for x in _leads(repo, base, "B")}
    for x in _leads(repo, brief, "B"):
        if x.record_id not in was_b:
            org = repo.get(Organisation, x.record_id)
            out.append(Change(kind="new_industry_lead", record_id=x.record_id,
                              title=org.name if org else x.record_id,
                              source_url=(x.record_id if x.record_id.startswith(
                                  "https://openalex.org/") else x.source_url)))
    return out


# --- the email draft (code only) ---

def draft(researcher: Researcher, brief: Brief, base: Brief | None, changes: list[Change],
          items: list[tuple[Lead, Record | None]]) -> tuple[str, str] | None:
    """(subject, body), or None when no trigger fired. `items`: the new leads with their
    records, for the hand-off drafter's code-written list."""
    if not any(c.trigger for c in changes):
        return None
    ending = [c for c in changes if c.kind == "award_ending" and c.trigger]
    new = [c for c in changes if c.kind == "new_lead"]
    moved = [c for c in changes if c.kind == "close_date"]
    parts = []
    if new:
        parts.append(f"{len(new)} new funding {'opportunity' if len(new) == 1 else 'opportunities'}"
                     " in your top 10")
    if ending:
        parts.append(f"{'a public award ends' if len(ending) == 1 else 'public awards end'} "
                     "within 12 months")
    subject = "Perch weekly watch: " + " and ".join(parts)
    since = (f" and compared it with the last run, for {base.options.get('as_of')}"
             if base else "")
    blocks = [f"Hello {researcher.display_name},",
              f"Perch re-ran your brief for {brief.options.get('as_of')}{since}."]
    if ending:
        blocks += ["Public awards ending within 12 months:", "\n".join(
            f"- {c.title}. Ends {c.after}.\n  Record: {c.source_url}" for c in ending)]
    if new:
        blocks += ["New in your top 10:", "\n".join(lead_lines(items))]
    if moved:
        blocks += ["Close dates that changed on your leads:", "\n".join(
            f"- {c.title}. Was {c.before or 'not stated'}, now {c.after or 'not stated'}.\n"
            f"  Record: {c.source_url}" for c in moved)]
    blocks += ["Open Perch's What changed screen for the full brief.",
               "Perch drafted this from public records and did not send it. Each date and "
               "amount above is copied from the linked record."]
    return subject, "\n\n".join(blocks)


# --- one run ---

def watch(service: BriefService, author_id: str, as_of: date | None = None,
          explain: bool = True, refresh: dict | None = None) -> Digest:
    """Run a fresh brief for one researcher, compare it with the last run, store and
    return the Digest. The brief uses the web app's default options, so visitors reuse it."""
    aid = oa.parse_author_id(author_id)
    if not aid:
        raise ValueError(f"not an OpenAlex author id: {author_id!r}")
    rid = f"https://openalex.org/{aid}"
    as_of = as_of or date.today()
    options = brief_options(as_of, explain=explain)
    started = now()
    with service.repo() as r:
        base, last = baseline(r, rid, options, started)
    b = service.create(aid, as_of=as_of, explain=explain)  # never service.reuse
    service.run(b.id)
    got = service.get(b.id)
    if not got or got[0].status != "done":
        raise RuntimeError(f"brief {b.id} did not finish: {got[0].error if got else 'missing'}")
    brief, leads = got
    with service.repo() as r:
        res = r.get(Researcher, rid)
        if res is None:
            raise RuntimeError("researcher missing from the store")
        changes = changes_since(r, brief, base, last, as_of)
        new_ids = {c.record_id for c in changes if c.kind == "new_lead"}
        items = [(x, r.get(Opportunity, x.record_id)) for x in leads
                 if x.route == "A" and x.record_id in new_ids]
        snap = []
        for x in leads:
            if x.route == "A":
                o = r.get(Opportunity, x.record_id)
                snap.append({"record_id": x.record_id, "rank": x.rank,
                             "close_date": _iso(o.close_date) if o else None})
        mail = draft(res, brief, base, changes, items)
        did = secrets.token_urlsafe(9)
        d = Digest(id=did, source="perch", source_url=f"perch://digests/{did}",
                   fetched_at=now(), researcher_id=rid, brief_id=brief.id,
                   baseline_brief_id=base.id if base else None, as_of=as_of,
                   changes=changes, snapshot=snap, refresh=refresh or {},
                   draft_subject=mail[0] if mail else None,
                   draft_body=mail[1] if mail else None)
        r.upsert([d])
    return d


def run(service: BriefService, authors: Iterable[str],
        grants: Callable[[], grants_gov.GrantsGovClient] | None = grants_gov.GrantsGovClient,
        as_of: date | None = None, explain: bool = True,
        limit: int | None = None) -> list[Digest]:
    """The weekly job: refresh opportunities (unless grants is None), then watch each
    researcher in turn."""
    counts: dict = {}
    if grants is not None:
        with service.repo() as r, grants() as gg:
            counts = refresh_opportunities(r, gg, limit=limit)
    return [watch(service, a, as_of, explain, counts) for a in authors]


def latest(repo: Repository) -> list[Digest]:
    """The newest digest per watched researcher."""
    out: dict[str, Digest] = {}
    for d in sorted(repo.list(Digest), key=lambda d: d.fetched_at):
        out[d.researcher_id] = d
    return list(out.values())
