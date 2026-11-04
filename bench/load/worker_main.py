"""Bench-only worker entry point (S47): `perch worker` with the fake model provider made to
behave like the cloud model, without editing perch/.

Patches applied in this process only:
  * FakeProvider.chat returns a schema-valid summary or fit reply built from the prompt and
    sleeps a latency drawn from the measured Sonnet latencies (PERCH_LOAD_LATENCIES, JSON).
  * PublicCache.get and RerankCache.get return None, so every brief does the full work
    (the repeat briefs of a run cannot be served from a cache).
  * PERCH_LOAD_CACHE_SERVICE=1: one BriefService per worker instead of one per job.
  * perch.compute.model_slot and the Slotted* classes record time per stage to
    PERCH_LOAD_STATS (JSON lines): slot wait, embed, rerank, ground, model wait.
Usage: python bench/load/worker_main.py --db DB worker --concurrency N --kinds brief
"""
from __future__ import annotations

import contextlib
import json
import os
import random
import re
import sys
import threading
import time

STATS = os.environ.get("PERCH_LOAD_STATS", "")
_lock = threading.Lock()


def rec(kind: str, seconds: float) -> None:
    if STATS:
        line = json.dumps({"k": kind, "s": round(seconds, 5), "t": round(time.time(), 3)}) + "\n"
        with _lock, open(STATS, "a", encoding="utf-8") as f:
            f.write(line)


def reply(messages, system, schema) -> tuple[str, str]:
    props = (schema or {}).get("properties", {})
    text = messages[-1].content
    if "topics" in props:
        ids = re.findall(r"^\[([^\]]+)\]", text, re.M)[:6] or ["x"]
        labels = ["first topic area", "second topic area", "third topic area"]
        topics = [{"label": labels[i], "work_ids": [ids[i % len(ids)]]}
                  for i in range(3)]
        return "summary", json.dumps({"topics": topics, "summary": "The papers study related "
                                      "questions. They share methods and settings.",
                                      "cited_ids": ids[:3]})
    if "research_findings" in props:
        m = re.search(r"Opportunity:\n\[([^\]]+)\]", text)
        opp = m.group(1) if m else "x"
        pids = re.findall(r"^\[([^\]]+)\]", system or "", re.M)
        p1, p2 = (pids + ["p1", "p2"])[:2]
        return "fit", json.dumps({
            "reasoning": "compared aims", "fit": 50,
            "opportunity_sentence": "The opportunity supports research on a stated topic.",
            "research_findings": [{"paper_id": p1, "finding": "reported results in its abstract"},
                                  {"paper_id": p2, "finding": "described methods in its abstract"}],
            "link_sentence": "The work and the opportunity overlap in topic.",
            "cited_ids": [opp, p1, p2]})
    return "other", ""


def install() -> None:
    lat = json.load(open(os.environ["PERCH_LOAD_LATENCIES"], encoding="utf-8"))
    rnd = random.Random()
    from perch.llm.base import ChatResult, Usage
    from perch.llm.fake import FakeProvider

    def chat(self, messages, *, system=None, tools=None, schema=None, max_tokens=2048,
             logprobs=0, cache_system=False):
        kind, text = reply(messages, system, schema)
        pool = lat.get(kind) or lat["fit"]
        t0 = time.perf_counter()
        time.sleep(rnd.choice(pool))
        rec("model_wait", time.perf_counter() - t0)
        rec(f"model_calls_{kind}", 0)
        return ChatResult(text=text, model=self.model, provider=self.name,
                          usage=Usage(10, 10), tool_calls=[], stop_reason="stop")

    FakeProvider.chat = chat  # type: ignore[method-assign]

    from perch import compute

    orig_slot = compute.model_slot

    @contextlib.contextmanager
    def slot():
        t0 = time.perf_counter()
        with orig_slot():
            rec("slot_wait", time.perf_counter() - t0)
            yield

    compute.model_slot = slot  # type: ignore[assignment]

    def timed(cls, meth, kind):
        orig = getattr(cls, meth)

        def f(self, *a, **k):
            t0 = time.perf_counter()
            try:
                return orig(self, *a, **k)
            finally:
                rec(kind, time.perf_counter() - t0)  # includes the slot wait; subtract it

        setattr(cls, meth, f)

    timed(compute.SlottedEmbedder, "embed_queries", "embed_total")
    timed(compute.SlottedEmbedder, "embed_documents", "embed_total")
    timed(compute.SlottedReranker, "score", "rerank_total")
    timed(compute.SlottedGrounder, "support", "ground_total")

    if os.environ.get("PERCH_LOAD_CACHE_SERVICE") == "1":
        # Bench-side workaround for a finding: `perch worker` builds a new BriefService (and so
        # loads the embedder, reranker and MiniCheck again) for every job. This keeps one.
        from perch import jobs

        orig_set = jobs.set_brief_service

        def set_cached(factory):
            box, lk = [], threading.Lock()

            def once():
                with lk:
                    if not box:
                        box.append(factory())
                    return box[0]

            orig_set(once)

        jobs.set_brief_service = set_cached  # type: ignore[assignment]

    from perch.cache import PublicCache
    from perch.rerank import RerankCache

    PublicCache.get = lambda self, *a, **k: None  # type: ignore[method-assign]
    RerankCache.get = lambda self, *a, **k: None  # type: ignore[method-assign]


if __name__ == "__main__":
    install()
    from perch.cli import main

    sys.exit(main(sys.argv[1:]))
