# S47 load tests (4 Nov 2026), every number measured on this node

Scripts: `bench/load/` (`gpu_briefs.py`, `worker_main.py`, `ground_batch.py`, `serve_v1.py`, `http_mix.py`). Nothing in `perch/` was edited.
Setup: cloud-gpu profile on GPU 3 (32 GB), the e2e Postgres, the fake provider with sleeps drawn from 51 real Sonnet fit-explainer calls (median 4.88 s, range 3.86 to 6.25 s, from `data/logs/*model_calls.jsonl`) and 2 summary calls (median 5.31 s). No real model calls. Caches were switched off in the worker, so every brief does full work.

## Finding first: the worker reloads the models for every job
`perch worker` builds a new `BriefService` for each job (`_brief_service()` in `perch/jobs.py` calls the factory in `cmd_worker` each time), so each brief reloads the embedder, reranker and MiniCheck. As shipped, 4 or more concurrent briefs fail (`NotImplementedError: Cannot copy out of meta tensor`), and GPU memory is 32.2 GB (full card) at 16 and 24. The cached rows below keep one service per worker, done inside the bench only. **A one-line fix in `perch/` is needed before the GPU target means anything.**

## Task 3: briefs on one GPU (3 briefs per client, closed loop; warm-up not counted)
| Concurrency | Per-job service (as shipped) | One service per worker |
|---|---|---|
| 1 | 2.02 /min, p50 30.3 s, p95 32.0 s, 0 errors, 4,394 MiB | 2.08 /min, p50 28.7, p95 29.3, 0 errors, 5,616 MiB |
| 2 | 3.78 /min, p95 34.1, 0 errors, 8,140 MiB | 4.20 /min, p95 30.4, 0 errors, 5,922 MiB |
| 4 | 12 of 12 failed | 7.98 /min, p95 33.3, 0 errors, 6,198 MiB |
| 8 | 24 of 24 failed | 15.54 /min, p95 37.1, 0 errors, 6,212 MiB |
| 16 | 48 of 48 failed | 28.54 /min, p95 41.2, 0 errors, 6,222 MiB |
| 24 | 72 of 72 failed | 37.13 /min, p95 49.0, 0 errors, 6,544 MiB |
| 32 | not run | 39.15 /min, p95 56.8, 0 errors, 6,954 MiB |
| 48 | not run | 41.21 /min, p95 80.4, 0 errors, 8,940 MiB |

- **Target:** the computed 33 briefs a minute is met at 24 in flight (37.1 /min, p95 49 s, under the 90 s goal). The card saturates near 40 to 41 /min; at 48 in flight p95 is 80 s.
- **Where time goes (per brief, seconds, one service):** model wait 54 summed over parallel calls, about 28 s of wall. GPU work (embed + rerank + MiniCheck, minus slot wait) is 1.76 s at 1 in flight and 1.36 s at 48, which is a ceiling of 34 to 44 /min with `PERCH_MODEL_SLOTS=1`. Slot wait per brief grows 0.1 s (1), 6.1 s (16), 18.4 s (24), 93.5 s (48).
- **MiniCheck batching:** worth little. 30 claims per brief: 0.470 s now, 0.444 s batched in 64s (1.07 times faster), identical probabilities (`ground_batch.json`). Not worth a change.
- Caveat: the closed loop starts all clients together, so the first wave inflates p95 slightly. Real briefs took 25 to 50 s in S38 versus this bench's 28 s; the gap includes regenerations and real-model variance.

## Task 4: HTTP, 1,000 simulated users, 300 s plus 30 s ramp
Mix: every user browses (3 to 10 s think time); 500 signed-in SYNTHETIC accounts also hit account pages and Scout buttons; 200 users (20%) build one brief, a quarter each signed-in researcher, signed-in student, guest researcher, guest student; builders poll every 1.5 s with ETag as `web/app.js` does. Web on 127.0.0.1:8195, load generator `asyncio` + `httpx` 0.28.1 (pinned in `uv.lock`), worker concurrency 24 on GPU 3.

| Web processes | Requests/s | Errors (30 s timeouts) | Browse p50 / p95 | Account p50 / p95 | Max queued / running |
|---|---|---|---|---|---|
| 1 (no ETag, 2 s poll) | 64.6 | 84 of 20,976 | 10.7 to 11.0 s / 56 to 62 s | 12.2 to 14.3 s / 55 to 66 s | 52 / 24 |
| 1 | 62.3 | 97 of 20,184 | 11.0 to 11.9 s / 59 to 62 s | 12.9 to 15.4 s / 58 to 65 s | 52 / 24 |
| 4 (6 DB connections each) | 156.0 | 4 of 48,255 | 77 to 167 ms / 15.1 to 15.5 s | 0.85 to 1.3 s / 15.6 to 16.3 s | 68 / 24 |

- **Target not met.** Browse p95 under 300 ms holds only at 250 users on one process (browse p95 132 to 190 ms, 58 requests/s, `knee1proc/`). At 1,000 users the web tier saturates: one process serves about 60 requests/s, four serve about 156/s, while the mix offers more. p95 is 15 s at four processes.
- **Caveat:** the node is shared and `run_limited.sh` runs at nice 19; web processes sat at 19 to 72% CPU while other tenants used the cores, so waits are not purely our code. Full per-path numbers: `http_paths_u1000_*.csv`.
- **Queue:** the worker drained 38 to 40 briefs a minute (143 to 157 succeeded in 300 s, 0 failed), against 200 briefs offered; queue peaked at 52 to 68 with 24 running. The poll counter in `http_mix.py` did not detect completion (fixed afterwards, not re-run), so completions come from the queue CSVs.
- **Tokens a minute implied:** offered 40 briefs/min over 300 s, about 67/min inside the 180 s posting window. Using the S38 means (7,076 output, 12,500 input, 31,492 cache-read tokens per researcher brief; student briefs UNMEASURED): the worker's 39.6/min is about 280K output tokens/min; the offered peak is about 474K. `docs/RESULTS.md` gives the start tier as 400K output tokens and 4,000 requests a minute, so the offered peak exceeds it and the worker rate fits. Input-token limits and higher tiers: UNVERIFIED (not in the repo).
- Not in the mix: hand-offs, cover points, Scout model turns, ingest.
