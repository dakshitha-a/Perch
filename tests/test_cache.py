"""S38: cloud-cpu profile, model slots, public caches, nightly pre-cache, prompt caching.

Everything here is SYNTHETIC text. Tests marked with `pgdb` need the test Postgres.
"""

from __future__ import annotations

import hashlib
import threading
import time
from argparse import Namespace
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from perch import compute
from perch.cache import (
    InputContext,
    PublicCache,
    cache_key,
    is_public_input,
    profile_hash,
)
from perch.embed import FakeEmbedder
from perch.grounding import FakeGrounder
from perch.llm import Message, Tool, spec_for_role
from perch.llm.anthropic_provider import AnthropicProvider
from perch.profiles import PROFILES, current
from perch.rerank import FakeReranker
from perch.retrieve import index_opportunities
from perch.schemas import Opportunity, Researcher, Work
from perch.service import BriefService, Clients, Models
from perch.skills import fit, summary
from perch.store.lance import LanceIndex
from perch.store.sqlite import SQLiteRepository

T = datetime(2026, 10, 28, tzinfo=UTC)
AUTHOR = "https://openalex.org/A1"


# --- profile and roles ---

def test_cloud_cpu_is_the_default_and_names_the_provider_models(monkeypatch):
    monkeypatch.delenv("PERCH_PROFILE", raising=False)
    for k in ("PERCH_LLM_DEFAULT", "PERCH_LLM_GATE", "PERCH_LLM_FIT_EXPLAINER"):
        monkeypatch.delenv(k, raising=False)
    p = current()
    assert p is PROFILES["cloud-cpu"] and p.device == "cpu" and p.grounder == "minicheck"
    assert spec_for_role("gate") == "anthropic:claude-haiku-5-5"
    assert spec_for_role("profile_summary") == "anthropic:claude-haiku-5-5"
    for role in ("fit_explainer", "handoff", "cover_points", "scout"):
        assert spec_for_role(role) == "anthropic:claude-sonnet-5-5"
    with pytest.raises(ValueError):
        spec_for_role("decide")  # dropped by D-12
    assert {"dev", "deploy-2gpu", "deploy-1gpu"} <= set(PROFILES)  # fallback profiles remain


# --- model slots ---

def test_model_slots_limit_concurrent_compute(monkeypatch):
    monkeypatch.setenv("PERCH_MODEL_SLOTS", "2")
    compute.reset_slots()
    live, peak, lock = [0], [0], threading.Lock()

    class Slow(FakeReranker):
        def score(self, query, docs):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            with lock:
                live[0] -= 1
            return [0.0] * len(docs)

    rr = compute.SlottedReranker(Slow())
    ts = [threading.Thread(target=rr.score, args=("q", ["d"])) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 2
    monkeypatch.delenv("PERCH_MODEL_SLOTS")
    compute.reset_slots()
    assert compute.model_slots() == 1


def test_torch_threads_default_uses_affinity_and_caps_at_four(monkeypatch):
    monkeypatch.delenv("PERCH_TORCH_THREADS", raising=False)
    assert 1 <= compute.torch_threads() <= 4
    monkeypatch.setenv("PERCH_TORCH_THREADS", "3")
    assert compute.torch_threads() == 3


# --- keys and the public-input gate ---

def test_cache_key_names_its_inputs_and_namespace():
    a = cache_key("fit", "r1", "t", "ph", "fit-1", "m", "1")
    assert a == hashlib.sha256(b"perch-cache-v1|fit|r1|t|ph|fit-1|m|1").hexdigest()
    assert a != cache_key("profile_summary", "r1", "t", "ph", "fit-1", "m", "1")
    assert a != cache_key("fit", "r1", "t", "ph", "fit-2", "m", "1")  # prompt version
    with pytest.raises(ValueError):
        cache_key("hand_off", "x")


def test_is_public_input_false_for_any_user_dependence():
    assert is_public_input(InputContext())
    for f in ("reads_user_data", "cv", "entries", "documents", "direction_text",
              "free_text_constraint"):
        assert not is_public_input(InputContext(**{f: True}))


def test_profile_hash_ignores_work_order_but_not_content():
    a = profile_hash("A", ["w2", "w1"], "2026-11-03", [["w1"], ["w2"]])
    assert a == profile_hash("A", ["w1", "w2"], "2026-11-03", [["w2"], ["w1"]])
    assert a != profile_hash("A", ["w1", "w2"], "2026-11-04", [["w1"], ["w2"]])
    assert a != profile_hash("A", ["w1", "w3"], "2026-11-03", [["w1"], ["w3"]])


def test_prompt_text_changes_need_a_version_bump():
    """Edit a prompt: this fails until you bump PROMPT_VERSION and update the pair here."""
    def h(*parts: object) -> str:
        return hashlib.sha256(repr(parts).encode()).hexdigest()[:12]

    seen = {"fit": (fit.PROMPT_VERSION, h(fit.INSTRUCTIONS, fit.SCHEMA)),
            "summary": (summary.PROMPT_VERSION, h(summary.SYSTEM, summary.SCHEMA))}
    assert seen == {"fit": ("fit-1", "41219072572e"), "summary": ("summary-1", "20e6e9da50ed")}


# --- Anthropic prompt cache prefixes ---

def test_anthropic_marks_system_and_tool_prefix_as_cacheable(tmp_path):
    from perch.llm.budget import Budget
    from tests.test_llm import FakeAnthropicClient, anthropic_response

    client = FakeAnthropicClient(anthropic_response())
    p = AnthropicProvider(client=client, budget=Budget(100.0, tmp_path / "l.jsonl"))
    tools = [Tool("a", "d", {"type": "object", "properties": {}}),
             Tool("b", "d", {"type": "object", "properties": {}})]
    p.chat([Message("user", "q")], system="stable", tools=tools, cache_system=True)
    kw = client.kw
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in kw["tools"][0]
    assert kw["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    p.chat([Message("user", "q")], system="stable", tools=tools)
    assert "cache_control" not in client.kw["system"][0]
    assert all("cache_control" not in t for t in client.kw["tools"])


# --- Postgres: PublicCache, pre-cache ---

def test_public_cache_ttl_epoch_and_overwrite(pg_clean):
    from perch.store.pg import make_pool

    pool = make_pool(pg_clean.worker)
    try:
        c = PublicCache(pool)
        k = cache_key("profile_summary", "p", "v", "m", "1")
        assert c.get("profile_summary", k) is None
        c.put("profile_summary", k, {"summary": "SYNTHETIC"}, {"profile_hash": "p"})
        assert c.get("profile_summary", k) == {"summary": "SYNTHETIC"}
        with pool.connection() as conn:  # a week-old TTL has passed
            conn.execute("UPDATE public_cache SET expires_at = now() - interval '1 second'")
        assert c.get("profile_summary", k) is None
        c.put("precache", "kp", {"ranked": []}, {}, epoch=3)
        assert c.get("precache", "kp", epoch=3) == {"ranked": []}
        assert c.get("precache", "kp", epoch=4) is None
        with pool.connection() as conn:
            exp = conn.execute("SELECT namespace, expires_at IS NULL FROM public_cache "
                               "ORDER BY namespace").fetchall()
        assert exp == [("precache", True), ("profile_summary", False)]
    finally:
        pool.close()


def _responder(messages, system, schema):
    import json
    import re

    if "topics" in (schema or {}).get("properties", {}):
        return json.dumps({"topics": [{"label": f"topic {n}", "work_ids": [f"W{i}"]}
                                      for i, n in enumerate(("one", "two", "three"))],
                           "summary": "SYNTHETIC studies of the brain. Focus on injury.",
                           "cited_ids": ["W0", "W1", "W2"]})
    pid = re.search(r"\[(PA-\d)\]", messages[0].content).group(1)
    return json.dumps({"reasoning": "r", "fit": 70,
                       "opportunity_sentence": f"{pid} is SYNTHETIC.",
                       "research_findings": [{"paper_id": "W0", "finding":
                                              "studied SYNTHETIC blood brain barrier injury"}],
                       "link_sentence": "Both concern the brain.",
                       "cited_ids": [pid, "W0"]})


def _service(tmp_path, pool) -> BriefService:
    repo = SQLiteRepository(str(tmp_path / "perch.db"))
    e = FakeEmbedder(256)
    repo.upsert([
        Researcher(id=AUTHOR, display_name="SYNTHETIC PI", institutions=["Temple University"],
                   source="openalex", source_url="https://api.openalex.org/authors/A1",
                   fetched_at=T),
        *[Work(id=f"W{i}", title="SYNTHETIC blood brain barrier injury in HIV",
               publication_date=date(2020, 1, i + 1), author_ids=[AUTHOR], source="openalex",
               source_url=f"https://api.openalex.org/works/W{i}", fetched_at=T)
          for i in range(3)],
        *[Opportunity(id=f"grants_gov:PA-{n}", opportunity_number=f"PA-{n}",
                      title=f"SYNTHETIC {t}", agency="SYNTHETIC agency", source="grants_gov",
                      source_url=f"https://www.grants.gov/search-results-detail/PA-{n}",
                      fetched_at=T, status="posted", open_date=date(2026, 1, 1),
                      close_date=date(2099, 1, 1), activity_code="R01",
                      eligible_applicants=["Private institutions of higher education"])
          for n, t in ((1, "blood brain barrier HIV research"), (2, "kidney transplant"),
                       (3, "astronomy telescope"))]])
    idx = LanceIndex(tmp_path / "lance")
    index_opportunities(repo, idx, e)
    repo.close()
    from perch.llm.fake import FakeProvider

    models = Models(embedder=lambda: e, reranker=FakeReranker, index=lambda: idx,
                    grounder=FakeGrounder, summary_spec="fake:fake-1", fit_spec="fake:fake-1",
                    provider=lambda spec: FakeProvider(responder=_responder))
    svc = BriefService(tmp_path / "perch.db", models, Clients(openalex=lambda: None))
    svc.public_cache = PublicCache(pool)
    return svc


def test_precache_stores_ids_and_scores_only_and_serves_a_brief(pg_clean, tmp_path):
    from perch import precache
    from perch.eligibility import Constraints
    from perch.profile import build_threads
    from perch.store.pg import make_pool

    pool = make_pool(pg_clean.worker)
    try:
        svc = _service(tmp_path, pool)
        today = date.today()
        report = precache.precache_author(svc, AUTHOR, today)
        assert report["stored"] and report["ranked"] == 3
        with pool.connection() as conn:
            ns, value, meta = conn.execute(
                "SELECT namespace, value, meta FROM public_cache WHERE namespace = 'precache'"
            ).fetchone()
            assert conn.execute("SELECT count(*) FROM public_cache WHERE namespace = 'author'"
                                ).fetchone()[0] == 1
        assert ns == "precache"
        assert set(value) == {"as_of", "retrieved", "rejected", "ranked", "seconds"}
        assert set(value["ranked"][0]) == {"record_id", "score", "best_thread", "rerank_score"}
        assert value["ranked"][0]["record_id"] == "grants_gov:PA-1"
        assert set(meta) == {"author_id", "profile_hash", "ingest_epoch", "as_of"}
        with svc.repo() as repo:
            works = repo.works_by_author(AUTHOR)
            profile = build_threads(AUTHOR, works, svc.models.get("embedder"), today)
            stored = precache.lookup(svc.public_cache, repo, profile)
            assert stored and stored["ranked"] == value["ranked"]
            res = repo.get(Researcher, AUTHOR)
            b = precache.route_a_from_precache(stored, res, profile, repo,
                                               Constraints(as_of=today), top=2)
            assert b and [x.opportunity.id for x in b.leads][0] == "grants_gov:PA-1"
            assert precache.route_a_from_precache(stored, res, profile, repo,
                                                  Constraints(as_of=today), top=9) is None
            # added text makes the profile non-public: no lookup
            assert precache.lookup(svc.public_cache, repo,
                                   build_threads(AUTHOR, works, svc.models.get("embedder"),
                                                 date(2020, 1, 1))) is None
    finally:
        pool.close()


def test_perch_precache_enqueues_one_job_per_temple_author_once_a_day(pg_clean, monkeypatch,
                                                                      tmp_path):
    from perch import jobs
    from perch.cli import cmd_precache
    from perch.store.postgres import PostgresRepository

    monkeypatch.setenv("PERCH_DATABASE_URL", pg_clean.worker)
    repo = PostgresRepository(pg_clean.worker, role="worker")
    repo.upsert([Researcher(id=AUTHOR, display_name="SYNTHETIC PI",
                            institutions=["Temple University"], source="openalex",
                            source_url="https://api.openalex.org/authors/A1", fetched_at=T),
                 Researcher(id="https://openalex.org/A2", display_name="SYNTHETIC PI 2",
                            institutions=["Other University"], source="openalex",
                            source_url="https://api.openalex.org/authors/A2", fetched_at=T)])
    for _ in range(2):
        assert cmd_precache(Namespace(limit=None, dry_run=False)) == 0
    import psycopg

    with psycopg.connect(pg_clean.admin) as c:
        rows = c.execute("SELECT kind, payload FROM jobs").fetchall()
    assert rows == [("precache", {"author_id": AUTHOR})]

    # the handler stores the result through the service
    pool = repo.pool
    svc = _service(tmp_path, pool)
    jobs.set_brief_service(lambda: svc)
    try:
        jobs.precache_handler(SimpleNamespace(payload={"author_id": AUTHOR}))  # type: ignore[arg-type]
    finally:
        jobs.set_brief_service(None)  # type: ignore[arg-type]
    with psycopg.connect(pg_clean.admin) as c:
        assert c.execute("SELECT count(*) FROM public_cache WHERE namespace = 'precache'"
                         ).fetchone()[0] == 1


def test_model_text_is_cached_on_public_input_only(pg_clean, tmp_path):
    """A second brief for the same public profile makes no summary or fit model call."""
    from perch.schemas import Lead
    from perch.store.pg import make_pool

    pool = make_pool(pg_clean.worker)
    try:
        svc = _service(tmp_path, pool)
        calls = []
        real = svc._audited

        def counting(role, spec):
            calls.append(role)
            return real(role, spec)

        svc._audited = counting  # type: ignore[method-assign]
        today = date.today()

        def run() -> tuple:
            b = svc.create("A1", as_of=today, top=2)
            b.stages = [s for s in b.stages if s.name not in ("researcher", "works", "awards",
                                                              "route_b")]
            with svc.repo() as r:
                r.upsert([b])
            assert svc.run(b.id) == "done"
            with svc.repo() as r:
                got = r.get(type(b), b.id)
                leads = [r.get(Lead, i) for i in got.lead_ids]
            return got, leads

        first, leads1 = run()
        n_first = len(calls)
        assert n_first >= 2
        second, leads2 = run()
        assert first.summary and any(x.explanation for x in leads1)
        used = [c for c in calls[n_first:]]
        assert "profile_summary" not in used and "fit_explainer" not in used
        assert second.summary == first.summary
        assert [x.explanation for x in leads2] == [x.explanation for x in leads1]
        with pool.connection() as c:
            kinds = {r[0] for r in c.execute("SELECT namespace FROM public_cache").fetchall()}
        assert kinds <= {"profile_summary", "fit", "author"}
    finally:
        pool.close()


def test_author_profile_is_cached_for_a_week_and_matches_a_fresh_build(pg_clean, tmp_path):
    import numpy as np

    from perch import precache
    from perch.profile import build_threads
    from perch.store.pg import make_pool

    pool = make_pool(pg_clean.worker)
    try:
        svc = _service(tmp_path, pool)
        e = svc.models.get("embedder")
        calls = []
        real = e.embed_queries
        e.embed_queries = lambda texts: (calls.append(len(texts)), real(texts))[1]  # type: ignore
        today = date.today()
        with svc.repo() as repo:
            first = precache.author_profile(svc.public_cache, repo, e, AUTHOR, today)
            n = len(calls)
            second = precache.author_profile(svc.public_cache, repo, e, AUTHOR, today)
            fresh = build_threads(AUTHOR, repo.works_by_author(AUTHOR), e, today)
        assert n >= 1 and len(calls) == n + 1  # only the uncached `fresh` build embedded
        assert second.work_ids == first.work_ids == fresh.work_ids
        assert [t.work_ids for t in second.threads] == [t.work_ids for t in fresh.threads]
        assert np.array_equal(second.threads[0].vector, first.threads[0].vector)
        with pool.connection() as c:
            assert c.execute("SELECT expires_at > now() + interval '6 days' FROM public_cache "
                             "WHERE namespace = 'author'").fetchone()[0]
    finally:
        pool.close()
