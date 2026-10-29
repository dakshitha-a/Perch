"""Single-card validation (PLAN S8 task 5): the deploy-1gpu stack on one clean GPU.

For one chat model at a time, everything the deploy-1gpu profile puts on GPU 0 is
started on a bench GPU instead: a private Ollama instance (8k context) with the chat
model, Clef-flash on llama.cpp, and in this process the embedder, the reranker and
the grounding model. Three briefs with explanations then run at once for the three
demo PIs, from a copy of the demo store with empty caches, while nvidia-smi is
polled for that GPU's memory. Recorded: the peak, the p50 brief time, and the share
of leads explained. The validator pass rate on a fixed lead set comes from
bench/skill2.py; QA agreement and the Scout gates cannot be measured before a QA
log exists and Scout is built (S10), and are written as such.

Run once per model, with the bench GPU visible as the only device:

  CUDA_VISIBLE_DEVICES=5 uv run --extra ml python -m bench.single_card qwen3:14b
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

from bench.backtest import RESULTS
from bench.skill2 import DB
from perch.schemas import Brief, Lead
from perch.service import BriefService, Clients, default_models
from perch.sources import openalex as oa

WORK = Path("data/bench/single_card")
OLLAMA_PORT = 11436
CLEF_PORT = 8096
PIS = ["A5034175589", "A5026494099", "A5057472361"]  # the demo briefs' researchers
AS_OF = date(2026, 10, 28)
LLAMA = Path.home() / ".local/bin/llama"


def physical_gpu() -> str:
    gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not gpu or "," in gpu:
        raise SystemExit("set CUDA_VISIBLE_DEVICES to exactly one bench GPU")
    return gpu


def used_mib(gpu: str) -> int:
    out = subprocess.run(["nvidia-smi", "-i", gpu, "--query-gpu=memory.used",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True)
    return int(out.stdout.strip())


class PeakMonitor(threading.Thread):
    def __init__(self, gpu: str, every: float = 0.5) -> None:
        super().__init__(daemon=True)
        self.gpu, self.every, self.peak, self.stop = gpu, every, 0, threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            self.peak = max(self.peak, used_mib(self.gpu))
            time.sleep(self.every)


def wait_up(url: str, seconds: float = 300) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError(f"{url} did not come up")


# Clef-flash: the whole prompt must fit one micro-batch (a 1,502-token prompt fails at
# -ub 512). 2048 covers Perch's longest decide prompt (about 1,100 tokens) and uses
# 7.44 GB against 7.99 GB at the dev units' 4096 (measured 2026-10-29, same answers).
def start_servers(log_dir: Path) -> list[subprocess.Popen]:
    env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{OLLAMA_PORT}",
           "OLLAMA_MODELS": "/usr/share/ollama/.ollama/models", "OLLAMA_NOPRUNE": "1",
           "OLLAMA_CONTEXT_LENGTH": "8192"}
    ollama = subprocess.Popen(["/usr/local/bin/ollama", "serve"], env=env,
                              stdout=(log_dir / "ollama.log").open("w"), stderr=subprocess.STDOUT)
    clef = subprocess.Popen([str(LLAMA), "serve", "-hf", "ggml-org/Clef-Flash-GGUF", "--port",
                             str(CLEF_PORT), "-ngl", "99", "-ub", "2048", "-b", "2048",
                             "--host", "127.0.0.1"], env=os.environ,
                            stdout=(log_dir / "clef.log").open("w"), stderr=subprocess.STDOUT)
    wait_up(f"http://127.0.0.1:{OLLAMA_PORT}/api/tags")
    wait_up(f"http://127.0.0.1:{CLEF_PORT}/health")
    return [ollama, clef]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="single-card validation, one chat model")
    ap.add_argument("model", help="Ollama model, e.g. qwen3:14b")
    a = ap.parse_args(argv)
    gpu = physical_gpu()
    work = WORK / a.model.replace(":", "-")
    shutil.rmtree(work, ignore_errors=True)
    (work / "logs").mkdir(parents=True)
    shutil.copy(DB, work / "perch.db")
    procs = start_servers(work / "logs")
    try:
        os.environ["OLLAMA_BASE_URL"] = f"http://127.0.0.1:{OLLAMA_PORT}"
        # Load the chat model and Clef-flash before the clock starts, as a server would be.
        httpx.post(f"http://127.0.0.1:{OLLAMA_PORT}/api/generate",
                   json={"model": a.model, "prompt": "", "keep_alive": "30m"}, timeout=300)
        idle = used_mib(gpu)
        models = default_models(data_dir=work, llm=f"ollama:{a.model}")
        from perch.grounding import MiniCheckGrounder

        models.grounder = lambda: MiniCheckGrounder(device="cuda")
        svc = BriefService(work / "perch.db", models, Clients(openalex=oa.OpenAlexClient))
        for name in ("embedder", "reranker", "index", "grounder"):
            models.get(name)
        loaded = used_mib(gpu)
        mon = PeakMonitor(gpu)
        mon.start()
        briefs = [svc.create(pid, as_of=AS_OF) for pid in PIS]

        def one(b: Brief) -> float:
            t = time.perf_counter()
            svc.run(b.id)
            return time.perf_counter() - t

        with ThreadPoolExecutor(len(briefs)) as pool:
            secs = list(pool.map(one, briefs))
        mon.stop.set()
        mon.join()
        with svc.repo() as r:
            done = [r.get(Brief, b.id) for b in briefs]
            leads = [r.get(Lead, i) for b in done for i in b.lead_ids]
        row = {"model": a.model, "gpu": gpu, "briefs": len(briefs),
               "briefs_done": sum(b.status == "done" for b in done),
               "leads": len(leads),
               "explained": round(sum(bool(x.explanation) for x in leads) / max(len(leads), 1), 3),
               "p50_brief_s": round(statistics.median(secs), 1),
               "max_brief_s": round(max(secs), 1),
               "idle_mib_chat_and_clef": idle, "all_loaded_mib": loaded, "peak_mib": mon.peak,
               "qa_agreement": "not measured: no QA log yet",
               "scout_gates": "not measured: Scout is S10"}
        print(row, flush=True)
        path = RESULTS / "single_card.csv"
        RESULTS.mkdir(parents=True, exist_ok=True)
        with path.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, list(row))
            if f.tell() == 0:
                w.writeheader()
            w.writerow(row)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(30)


if __name__ == "__main__":
    main()
