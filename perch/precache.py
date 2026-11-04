"""Nightly researcher pre-cache (REBUILD_PLAN "Caching and pre-caching", ARCHITECTURE_V1 3.1).

For one public researcher, run the deterministic stages (threads, retrieval, eligibility,
rerank) and store the ranked record ids and scores in `public_cache`, namespace `precache`.
No model text, no user text. A researcher's first brief then reads the stored ranking and
needs only the model calls (profile summary, fit explanations).

The key is `cache_key("precache", author_id, profile_hash, ingest_epoch)`. The profile hash
holds the as-of date, so a pre-cache serves briefs built on the same day; the next nightly
run replaces it. A new ingest epoch changes the key, so a refreshed corpus is never served
from an old ranking.
"""

from __future__ import annotations

import time
from datetime import date
from typing import TYPE_CHECKING, Any

from perch.brief import RERANK_IN, RETRIEVE_K, RouteABrief
from perch.cache import InputContext, PublicCache, cache_key, is_public_input, profile_hash
from perch.eligibility import Constraints, split
from perch.profile import Profile, build_threads
from perch.rerank import Ranked, Reranker, rerank
from perch.retrieve import Candidate, retrieve
from perch.schemas import Opportunity, Researcher
from perch.store.base import Repository, VectorIndex

if TYPE_CHECKING:
    from perch.service import BriefService


def temple_affiliated(r: Researcher) -> bool:
    return any("temple university" in i.lower() for i in r.institutions)


def public_profile_hash(p: Profile) -> str:
    return profile_hash(p.researcher_id, p.work_ids, p.as_of.isoformat(),
                        [t.work_ids for t in p.threads])


def precache_key(p: Profile, epoch: int) -> str:
    return cache_key("precache", p.researcher_id, public_profile_hash(p), str(epoch))


def profile_is_public(p: Profile) -> bool:
    """A profile with added text (the `salt`) is not public input."""
    return is_public_input(InputContext(direction_text=bool(p.salt)))


def compute(repo: Repository, index: VectorIndex, reranker: Reranker,
            profile: Profile, as_of: date, rerank_in: int = RERANK_IN) -> dict[str, Any]:
    """The deterministic stages for one profile; returns the JSON value to store."""
    t0 = time.perf_counter()
    r = retrieve(profile, index, k=RETRIEVE_K)
    opps = {o.id: o for o in (repo.get(Opportunity, x.record_id) for x in r.candidates) if o}
    eligible, rejected = split([opps[x.record_id] for x in r.candidates if x.record_id in opps],
                               Constraints(as_of=as_of))
    ok = {o.id for o in eligible}
    pool = [x for x in r.candidates if x.record_id in ok][:rerank_in]
    ranked, _ = rerank(pool, opps, profile, reranker, None, top=len(pool))
    return {"as_of": as_of.isoformat(), "retrieved": len(r.candidates),
            "rejected": sum(len(v) for v in rejected.values()),
            "ranked": [{"record_id": x.opportunity.id, "score": x.candidate.score,
                        "best_thread": x.candidate.best_thread,
                        "rerank_score": x.rerank_score} for x in ranked],
            "seconds": round(time.perf_counter() - t0, 2)}


def precache_author(service: BriefService, author_id: str, as_of: date | None = None) -> dict:
    """Build and store one researcher's pre-cache. Returns a small report (ids and counts)."""
    cache = service.public_cache
    if cache is None:
        raise RuntimeError("no public cache configured")
    as_of = as_of or date.today()
    with service.repo() as repo:
        works = repo.works_by_author(author_id)
        if not works:
            return {"author_id": author_id, "stored": False, "reason": "no works"}
        profile = build_threads(author_id, works, service.models.get("embedder"), as_of)
        epoch = repo.epoch()
        value = compute(repo, service.models.get("index"),
                        service.models.get("reranker"), profile, as_of)
    key = precache_key(profile, epoch)
    cache.put("precache", key, value,
              {"author_id": author_id, "profile_hash": public_profile_hash(profile),
               "ingest_epoch": epoch, "as_of": as_of.isoformat()}, epoch=epoch)
    return {"author_id": author_id, "stored": True, "ranked": len(value["ranked"]),
            "seconds": value["seconds"]}


def lookup(cache: PublicCache | None, repo: Repository, profile: Profile) -> dict | None:
    if cache is None or not profile_is_public(profile):
        return None
    return cache.get("precache", precache_key(profile, repo.epoch()))


def route_a_from_precache(stored: dict, researcher: Researcher, profile: Profile,
                          repo: Repository, constraints: Constraints, top: int
                          ) -> RouteABrief | None:
    """A Route A brief from a stored ranking, with this brief's constraints applied.
    None when fewer than `top` stored records survive them, so the caller runs live."""
    t0 = time.perf_counter()
    rows = stored["ranked"]
    opps = {o.id: o for o in (repo.get(Opportunity, x["record_id"]) for x in rows) if o}
    eligible, rejected = split(list(opps.values()), constraints)
    ok = {o.id for o in eligible}
    kept = [x for x in rows if x["record_id"] in ok]
    if len(kept) < top:
        return None
    leads = [Ranked(opps[x["record_id"]],
                    Candidate(x["record_id"], x["score"], x["best_thread"]),
                    x["rerank_score"]) for x in kept[:top]]
    ms = round((time.perf_counter() - t0) * 1000, 1)
    return RouteABrief(researcher, profile, leads, stored["retrieved"], rejected,
                       {"precache": ms, "total": ms}, len(rows))
