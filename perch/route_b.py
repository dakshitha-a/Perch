"""Route B, industry leads from public signals. Deterministic: no model output.

Three signals, each a set of public records about one company:

1. citing_works: works with a company author that cite the researcher's papers
   (OpenAlex `cites:`), minus works the researcher co-wrote.
2. sbir_sttr: NIH SBIR/STTR awards to the company whose text matches the researcher's
   main topics (NIH RePORTER; the SBIR.gov API was down, Q19, so NIH only).
3. topic_works: other works with a company author whose primary topic is one of the
   researcher's main topics, published in the last three years.

A record counts toward one signal only: a citing work is never also a topic work, so
"two signals" means two separate kinds of evidence, not one paper counted twice.

Score = sum over signals of WEIGHTS[kind] * log1p(raw), where raw sums a recency weight
(halving every RECENCY_HALF_LIFE years before as_of) over the signal's records, times
the overlap: papers cited (signal 1) or the topic's share of the researcher's papers
(signal 3). The weights are design defaults, not measured (docs/DECISIONS.md). A lead
needs at least MIN_SIGNALS signals. Every lead is labelled as an inference.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from perch.schemas import Award, Lead, Organisation, Signal, Work

WEIGHTS = {"citing_works": 3.0, "sbir_sttr": 2.0, "topic_works": 1.0}
RECENCY_HALF_LIFE = 2.0  # years
MIN_SIGNALS = 2
TOP = 5
TOPICS = 3
TOPIC_YEARS = 3
SBIR_YEARS = 3
if TYPE_CHECKING:
    from perch.sources.nih_reporter import NIHReporterClient
    from perch.sources.openalex import OpenAlexClient

LABEL = "Inferred from public signals; not verified."

# Trailing legal-form words dropped before names are compared. Exact match only after
# this: no fuzzy matching, because a wrong merge would make two companies look like one.
_LEGAL = {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co",
          "company", "plc", "gmbh", "ag", "sa", "lp", "llp", "pbc"}
_COUNTRY = re.compile(r"\s*\([^)]*\)\s*$")


def norm_name(name: str) -> str:
    """'BLACKSMITH MEDICINES, INC.' -> 'blacksmith medicines';
    'AstraZeneca (United Kingdom)' -> 'astrazeneca'."""
    s = _COUNTRY.sub("", name).lower()
    words = re.sub(r"[^a-z0-9]+", " ", s).split()
    while words and words[-1] in _LEGAL:
        words.pop()
    return " ".join(words)


def recency(d: date | None, as_of: date) -> float:
    if d is None:
        return 0.0
    years = max((as_of - d).days, 0) / 365.25
    return 0.5 ** (years / RECENCY_HALF_LIFE)


def main_topics(works: list[Work], n: int = TOPICS) -> dict[str, tuple[str, float]]:
    """The researcher's n most frequent primary topics (first listed topic) as
    {topic id: (name, share of their papers)}."""
    firsts = [w.topics[0] for w in works if w.topics]
    if not firsts:
        return {}
    counts = Counter(t.id for t in firsts)
    names = {t.id: t.display_name for t in firsts}
    return {tid: (names[tid], c / len(firsts)) for tid, c in counts.most_common(n)}


@dataclass
class OrgLead:
    org: Organisation
    signals: list[Signal]
    score: float
    relationship: str
    confidence: str
    sentences: list[str]
    cited_works: list[str] = field(default_factory=list)  # the researcher's papers cited


def _weight_date(shown: date | None, year: int | None, month: int) -> date | None:
    """Date for the recency weight only. A missing date falls back to a point in the
    record's year; the fallback is never shown (standing rule 3)."""
    return shown or (date(year, month, 1) if year else None)


def relationship(kinds: set[str]) -> str:
    if "sbir_sttr" in kinds:
        return "STTR or SBIR partner"
    if "citing_works" in kinds:
        return "Sponsored research or collaboration"
    return "Collaboration"


def score_leads(researcher_id: str, researcher_works: list[Work],
                citing: list[tuple[Work, list[Organisation]]],
                topical: list[tuple[Work, list[Organisation]]],
                sbir: list[Award], topics: dict[str, tuple[str, float]],
                as_of: date, top: int = TOP) -> list[OrgLead]:
    mine = {w.id for w in researcher_works}
    orgs: dict[str, Organisation] = {}
    org_counts: dict[str, Counter] = defaultdict(Counter)
    records: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    dates: dict[str, date | None] = {}  # shown dates, copied from records
    by_id: dict[str, Organisation] = {}
    cited_by: dict[str, set[str]] = defaultdict(set)

    def add_org(o: Organisation) -> str:
        key = norm_name(o.name)
        if key not in orgs:
            orgs[key] = o.model_copy(update={"aliases": [], "institution_ids": []})
        m = orgs[key]
        if o.name not in m.aliases:
            m.aliases.append(o.name)
        for i in o.institution_ids:
            if i not in m.institution_ids:
                m.institution_ids.append(i)
        org_counts[key][o.id] += 1
        by_id.setdefault(o.id, o)
        return key

    citing_ids: set[str] = set()
    for w, os_ in citing:
        if researcher_id in w.author_ids:
            continue  # the researcher's own paper citing their earlier work
        hits = [x for x in w.referenced_works if x in mine]
        citing_ids.add(w.id)
        dates[w.id] = w.publication_date
        r = recency(_weight_date(w.publication_date, w.publication_year, 7), as_of)
        for o in os_:
            key = add_org(o)
            records[key]["citing_works"][w.id] = r * max(len(hits), 1)
            cited_by[key].update(hits)

    for w, os_ in topical:
        if w.id in citing_ids or researcher_id in w.author_ids:
            continue
        share = max((topics[t.id][1] for t in w.topics[:1] if t.id in topics), default=0.0)
        if not share:
            continue
        dates[w.id] = w.publication_date
        r = recency(_weight_date(w.publication_date, w.publication_year, 7), as_of)
        for o in os_:
            records[add_org(o)]["topic_works"][w.id] = r * share

    newest: dict[str, Award] = {}
    for a in sbir:  # one entry per project: the newest fiscal-year record
        old = newest.get(a.award_number)
        if old is None or (a.fiscal_year or 0) > (old.fiscal_year or 0):
            newest[a.award_number] = a
    for a in newest.values():
        if not a.institution:
            continue
        key = norm_name(a.institution)
        if key not in orgs:
            orgs[key] = Organisation(
                id=f"reporter-org:{key.replace(' ', '-')}", source=a.source,
                # RePORTER has no organisation record: the newest award naming the firm.
                source_url=a.source_url, fetched_at=a.fetched_at, name=a.institution,
                type="company (SBIR/STTR awardee)")
        if a.institution not in orgs[key].aliases:
            orgs[key].aliases.append(a.institution)
        dates[a.id] = a.start_date
        records[key]["sbir_sttr"][a.id] = recency(_weight_date(a.start_date, a.fiscal_year, 1),
                                                  as_of)

    leads = []
    for key, by_kind in records.items():
        kinds = {k for k, v in by_kind.items() if v}
        if len(kinds) < MIN_SIGNALS:
            continue
        org = orgs[key]
        if org_counts[key]:  # the OpenAlex entity with the most records names the merged org
            b = by_id[org_counts[key].most_common(1)[0][0]]
            # Several national entities merged: the counts cover all of them, so the
            # name drops the one entity's country.
            merged = len(org.institution_ids) > 1
            org = org.model_copy(update={
                "id": b.id, "source_url": b.source_url,
                "name": _COUNTRY.sub("", b.name) if merged else b.name,
                "country": None if merged else b.country})
        signals = []
        for kind in ("citing_works", "sbir_sttr", "topic_works"):
            recs = by_kind.get(kind) or {}
            if not recs:
                continue
            ids = sorted(recs, key=lambda i: dates.get(i) or date.min, reverse=True)
            signals.append(Signal(kind=kind, record_ids=ids, count=len(ids),
                                  latest=dates.get(ids[0]),
                                  score=round(WEIGHTS[kind] * math.log1p(sum(recs.values())), 4)))
        cited = sorted(cited_by.get(key, set()))
        leads.append(OrgLead(org=org, signals=signals,
                             score=round(sum(s.score for s in signals), 4),
                             relationship=relationship(kinds),
                             confidence="stronger" if len(kinds) >= 3 else "moderate",
                             sentences=[sentence(s, org.name, len(cited)) for s in signals],
                             cited_works=cited))
    leads.sort(key=lambda x: (-x.score, x.org.name))
    return leads[:top]


def sentence(s: Signal, name: str, n_cited: int) -> str:
    """One factual sentence per signal. Counts and dates come from the records."""
    if s.kind == "citing_works":
        cite = "cites" if s.count == 1 else "cite"
        what = f"{cite} {n_cited} of your papers" if n_cited else f"{cite} your papers"
        head = f"{s.count} {'work' if s.count == 1 else 'works'} with an author at {name} {what}"
        tail = f"the newest was published {s.latest.isoformat()}" if s.latest else ""
    elif s.kind == "sbir_sttr":
        head = (f"{s.count} NIH SBIR/STTR {'project' if s.count == 1 else 'projects'} awarded "
                f"to {name} {'matches' if s.count == 1 else 'match'} your main topics")
        tail = f"the newest started {s.latest.isoformat()}" if s.latest else ""
    else:
        head = (f"{s.count} other {'work' if s.count == 1 else 'works'} with an author at "
                f"{name} {'shares' if s.count == 1 else 'share'} one of your main topics")
        tail = f"the newest was published {s.latest.isoformat()}" if s.latest else ""
    return f"{head}; {tail}." if tail else f"{head}."


@dataclass
class Gathered:
    seeds: list[Work]  # the researcher's papers used: dated by as_of, at most MAX_AUTHORS
    topics: dict[str, tuple[str, float]]
    citing: list[tuple[Work, list[Organisation]]]
    topical: list[tuple[Work, list[Organisation]]]
    sbir: list[Award]


MAX_CITED = 300  # the researcher's newest papers whose citing works are read
# Papers with more authors than this do not seed Route B. A citation of a 100-author
# consortium paper says little about the researcher's own work (S11 hand check: all
# five leads for PI-3 came from consortium papers). Design default, not measured.
MAX_AUTHORS = 30


def gather(openalex: OpenAlexClient, nih: NIHReporterClient, works: list[Work],
           as_of: date) -> Gathered:
    """Fetch the three signals for a researcher's works, as of a date. Clients are
    OpenAlexClient and NIHReporterClient (or fakes with the same methods). Only papers
    with at most MAX_AUTHORS authors seed the topics and the citing search."""
    works = [w for w in works if (w.publication_date is None or w.publication_date <= as_of)
             and len(w.author_ids) <= MAX_AUTHORS]
    newest = sorted(works, key=lambda w: w.publication_date or date.min, reverse=True)
    topics = main_topics(works)
    citing = openalex.company_works_citing([w.id for w in newest[:MAX_CITED]]) if works else []
    since = date(as_of.year - TOPIC_YEARS, as_of.month, min(as_of.day, 28))
    topical = (openalex.company_works_in_topics(list(topics), since, as_of) if topics else [])
    years = list(range(as_of.year - SBIR_YEARS + 1, as_of.year + 1))
    text = " ".join(name for name, _ in topics.values())
    sbir = nih.sbir_sttr(text, years) if text else []
    return Gathered(works, topics, citing, topical, sbir)


def make_leads(found: list[OrgLead], brief_id: str) -> list[Lead]:
    """Lead records for scored organisations. explanation holds the code-written signal
    sentences, so a citation of the lead supports its counts and dates."""
    return [Lead(id=f"{brief_id}:B{i}", source=x.org.source, source_url=x.org.source_url,
                 fetched_at=x.org.fetched_at, brief_id=brief_id, route="B",
                 record_id=x.org.id, rank=i, explanation=" ".join(x.sentences),
                 inference=LABEL, cited_ids=[w.rsplit("/", 1)[-1] for w in x.cited_works],
                 inferred=True, signals=x.signals, relationship=x.relationship,
                 confidence=x.confidence)
            for i, x in enumerate(found, 1)]


def evidence_records(found: list[OrgLead], g: Gathered) -> list[Work | Award]:
    """The company works and SBIR/STTR awards the leads cite, once each."""
    ids = {x for lead in found for s in lead.signals for x in s.record_ids}
    recs: dict[str, Work | Award] = {w.id: w for w, _ in g.citing + g.topical if w.id in ids}
    recs.update({a.id: a for a in g.sbir if a.id in ids})
    return list(recs.values())

