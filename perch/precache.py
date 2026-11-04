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

import hashlib
import time
from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np

from perch.brief import RETRIEVE_K, RouteABrief
from perch.cache import InputContext, PublicCache, cache_key, is_public_input, profile_hash
from perch.eligibility import Constraints, split
from perch.embed import Embedder
from perch.profile import Profile, Thread, build_threads, research_works
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


def author_key(researcher: Researcher | None, author_id: str, work_ids: list[str],
               as_of: date, embedder: str) -> str:
    """Key of the cached public profile (threads) of one author. Parts: author id, the date
    the author record was fetched from OpenAlex, the as-of date, a hash of the work ids and the
    embedder name, so a new fetch, a new paper or a new embedder never reads an old profile."""
    fetched = researcher.fetched_at.date().isoformat() if researcher else "unknown"
    wh = hashlib.sha256("|".join(sorted(work_ids)).encode()).hexdigest()[:16]
    return cache_key("author", author_id, fetched, as_of.isoformat(), wh, embedder)


def profile_to_json(p: Profile) -> dict[str, Any]:
    return {"work_ids": p.work_ids, "threads": [
        {"index": t.index, "vector": [float(x) for x in t.vector],
         "work_ids": t.work_ids, "weight": t.weight, "label": t.label, "titles": t.titles,
         "topics": t.topics} for t in p.threads]}


def profile_from_json(author_id: str, as_of: date, embedder: str, v: dict) -> Profile:
    return Profile(author_id, as_of, embedder, [
        Thread(t["index"], np.array(t["vector"], dtype=np.float64), t["work_ids"], t["weight"],
               t["label"], t["titles"], t["topics"]) for t in v["threads"]], v["work_ids"])


def author_profile(cache: PublicCache | None, repo: Repository, embedder: Embedder,
                   author_id: str, as_of: date) -> Profile:
    """The author's public profile, from the 7-day `author` cache when present. Public input
    only: it is built from stored public works, never from added text."""
    works = repo.works_by_author(author_id)
    if cache is None:
        return build_threads(author_id, works, embedder, as_of)
    ids = [w.id for w in research_works(works)]
    key = author_key(repo.get(Researcher, author_id), author_id, ids, as_of, embedder.name)
    hit = cache.get("author", key)
    if hit:
        return profile_from_json(author_id, as_of, embedder.name, hit)
    p = build_threads(author_id, works, embedder, as_of)
    cache.put("author", key, profile_to_json(p),
              {"author_id": author_id, "as_of": as_of.isoformat(), "embedder": embedder.name})
    return p


def compute(repo: Repository, index: VectorIndex, reranker: Reranker,
            profile: Profile, as_of: date, rerank_in: int) -> dict[str, Any]:
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
        if not repo.works_by_author(author_id):
            return {"author_id": author_id, "stored": False, "reason": "no works"}
        profile = author_profile(cache, repo, service.models.get("embedder"), author_id, as_of)
        epoch = repo.epoch()
        value = compute(repo, service.models.get("index"),
                        service.models.get("reranker"), profile, as_of, service.rerank_in())
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
