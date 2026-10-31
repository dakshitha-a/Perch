"""The student brief (S18): fellowships (public) and scholarships (sample), in a private
session only.

A student's input is always personal, so there is no public student path: these stages
run inside PrivateService, with every write in the session's memory. Stages:

- profile: the CV is parsed by rule (perch.student); the interests note becomes one query
  thread (the direction share); each achievement becomes a session record
  `private:achievement-a`, `-b`, ... that an explanation may cite.
- fellowships: Temple SDFA's public list plus NIH F-series listings from the public store.
- scholarships: the SYNTHETIC sample store. The chosen records are copied into the
  session overlay, so the session can show them and nothing else can.
- explanations: skill 2 on each eligible or may-be-eligible lead, citing the student's
  records and the scholarship record; both validator layers, as for grants.
Each route: embed, take the nearest RETRIEVE by cosine to the query thread, rerank them,
then check every one by rule. Leads keep the TOP best that are not ruled out; records
ruled out among the retrieved are kept too, ranked after, so the student sees why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import numpy as np

from perch.embed import normalise
from perch.private.inputs import PrivateDoc
from perch.profile import Profile, Thread
from perch.schemas import Lead, Opportunity, Scholarship, utcnow
from perch.scholarships import NIH_FELLOWSHIP_LEVEL, sample_records
from perch.score import match_score
from perch.student import StudentFacts, Verdict, check, check_nih, gaps

STUDENT_STAGES = ("student_profile", "fellowships", "scholarships", "student_explanations")
# 40 until S27: the SYNTHETIC student bench retrieved 23 of 24 planted records at 100, 19 at 40.
RETRIEVE = 100
TOP = 10
SAMPLE_BADGE = "Sample data: an invented record, not a real scholarship"


def achievements(text: str) -> list[str]:
    """The numbered or bulleted items of the achievements note, at most five."""
    items = [m.group(1).strip() for m in re.finditer(
        r"(?ms)^\s*(?:\d+[.)]|[-*•])\s+(.+?)(?=^\s*(?:\d+[.)]|[-*•])\s+|\Z)", text)]
    items = [" ".join(i.split()) for i in items if len(i.split()) >= 3]
    if not items:
        items = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 3][1:]
    return items[:5]


def achievement_docs(text: str) -> list[PrivateDoc]:
    return [PrivateDoc(id=f"private:achievement-{chr(97 + i)}", source="private",
                       source_url="private://session", fetched_at=utcnow(),
                       title=f"Your achievement {chr(65 + i)} (private)", type="private",
                       abstract=a) for i, a in enumerate(achievements(text))]


def record_text(s: Scholarship) -> str:
    """What is embedded and reranked: name, sponsor, purpose without its canary line,
    fields and the page notes."""
    purpose = re.sub(r"\s*SYNTHETIC sample record, canary \S+$", "", s.purpose or "")
    parts = [s.name, s.sponsor or "", purpose, ", ".join(s.field_of_study),
             ", ".join(s.level_of_study), s.eligibility.notes or ""]
    return ". ".join(p for p in parts if p)


def as_opportunity(s: Scholarship) -> Opportunity:
    """A scholarship in the shape skill 2 reads. The citation id is the record's short
    id; amounts and the deadline are copied, so the validator can check them."""
    return Opportunity(id=s.id, source=s.source, source_url=s.source_url,
                       fetched_at=s.fetched_at, opportunity_number=short_id(s.id),
                       title=s.name, agency=s.sponsor or "", close_date=s.deadline,
                       award_ceiling=s.amount_max, award_floor=s.amount_min,
                       description=record_text(s))


def short_id(record_id: str) -> str:
    return record_id.split(":", 1)[-1]


@dataclass
class Scored:
    record: Scholarship
    opp: Opportunity | None  # the NIH listing behind a fellowship, if any
    score: float
    verdict: Verdict


def student_profile(facts: StudentFacts, interests: PrivateDoc | None,
                    achieved: list[PrivateDoc], embedder: object, as_of: date) -> Profile:
    """One query thread from the interests note (or the achievements without one); the
    achievements ride on it as records an explanation may cite."""
    query_docs = [interests] if interests else achieved
    text = "\n\n".join(d.abstract or "" for d in query_docs)
    if facts.major:
        text = f"{facts.major}. {text}"
    vec = normalise(embedder.embed_queries([text]).mean(0, keepdims=True))[0]
    ids = [d.id for d in ([interests] if interests else []) + achieved]
    from perch.private.threads import label

    return Profile("private:you", as_of, getattr(embedder, "name", "embedder"),
                   [Thread(0, vec, ids, 1.0, label(text), [text[:600]])], ids)


def rank(records: list[Scholarship], profile: Profile, embedder: object, reranker: object,
         judge: callable, retrieve: int = RETRIEVE) -> list[Scored]:
    """Cosine to the query thread, the nearest `retrieve` reranked, every one judged."""
    if not records:
        return []
    texts = [record_text(s) for s in records]
    docs = normalise(np.asarray(embedder.embed_documents(texts)))
    sims = docs @ profile.threads[0].vector
    near = list(np.argsort(-sims)[:retrieve])
    scores = reranker.score(profile.threads[0].titles[0], [texts[i] for i in near])
    out = [Scored(records[i], None, float(sc), judge(records[i])) for i, sc in zip(
        near, scores, strict=True)]
    return sorted(out, key=lambda x: -x.score)


def choose(scored: list[Scored], top: int = TOP) -> list[Scored]:
    """The best `top` not ruled out, then the ruled-out ones among those retrieved."""
    ok = [x for x in scored if x.verdict.verdict != "not eligible"][:top]
    out = [x for x in scored if x.verdict.verdict == "not eligible"]
    return ok + out


def to_leads(brief_id: str, route: str, chosen: list[Scored], facts: StudentFacts,
             start: int = 1) -> list[Lead]:
    leads = []
    for i, x in enumerate(chosen, start):
        s, v = x.record, x.verdict
        g = gaps(s, facts) if v.verdict != "not eligible" and not x.opp else []
        src = x.opp or s
        leads.append(Lead(
            id=f"{brief_id}:{route}{i}", source=src.source, source_url=src.source_url,
            fetched_at=src.fetched_at, brief_id=brief_id, route=route, record_id=src.id,
            rank=i, rerank_score=round(x.score, 4), match_score=match_score(x.score),
            verdict=v.verdict,
            verdict_reason=v.reason, verdict_lines=v.lines, gaps=[t for _, t in g],
            gap_keys=[k for k, _ in g], sample=s.synthetic))
    return leads


def judge_for(facts: StudentFacts, as_of: date, nih: dict[str, Opportunity]) -> callable:
    def judge(s: Scholarship) -> Verdict:
        if s.id in nih:
            return check_nih(nih[s.id], facts, as_of)
        return check(s, facts, as_of)
    return judge


def nih_records(repo: object) -> dict[str, tuple[Scholarship, Opportunity]]:
    """NIH F-series listings as rule inputs, keyed by the listing id."""
    out = {}
    for o in repo.list(Opportunity):
        if (o.activity_code or "") not in NIH_FELLOWSHIP_LEVEL:
            continue
        s = Scholarship(id=o.id, source=o.source, source_url=o.source_url,
                        fetched_at=o.fetched_at, name=o.title, sponsor=o.agency,
                        purpose=(o.description or "")[:1500], award_type="fellowship",
                        deadline=o.close_date)
        out[o.id] = (s, o)
    return out


def samples() -> list[Scholarship]:
    return sample_records()
