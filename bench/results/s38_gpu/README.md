# S38 GPU timings and throughput (one GPU, and the previous two-GPU build)

Script: `bench/gpu_timings.py`. Raw rows: `timings.csv` (one row per measurement; four runs:
runs 1 and 2 for each reranker). Public data only: queries are the topic threads of the 10
researchers in the migrated Postgres database (`perch_dev`); rerank documents are the
eligible funding opportunities retrieved for them; MiniCheck pairs are (public work or
opportunity text, one of its own sentences). No cloud call, no user text.

## Conditions (read before using the numbers)

- **Hardware:** GPU 3, NVIDIA RTX 5000 Ada, 32 GB. Every run went through
  `PERCH_LIMIT_GPU=3 scripts/run_limited.sh`: one GPU visible, 4 CPU cores, 24 GB RAM,
  nice 19. The node is shared: the 1-minute load average was about 31 before each run, and
  other users' jobs ran on other GPUs. Only GPU 3 was touched.
- **Warm, single process, one request at a time.** Models are loaded before timing and a
  warm-up call is made. There is no concurrency inside a run, so "latency" is the time with
  the GPU to itself.
- **Dtype (read from the loaded weights):** embedder bf16, reranker bf16 (both 0.6B and 4B),
  MiniCheck float32 (the shipped `MiniCheckGrounder` loads fp32; not tried in fp16).
- **Loaded together:** every run loads embedder, one reranker and MiniCheck on the same card,
  so the VRAM figures are for the layout "everything on one GPU".
- **Sample sizes:** 10 researchers (23 thread queries) for rerank, 10 query embeddings, 25
  MiniCheck pairs, 400 pairs for the saturation sweep. Runs 1 and 2 agree within about 1
  percent everywhere, so a third run was not made.
- **Rerank unit:** one `perch.rerank.rerank()` call over the top N eligible candidates of a
  researcher (grouped by thread, documents cut to 2,000 characters, as in a brief), no score
  cache. N = 14 is the `cloud-cpu` setting; 100 is the shipped GPU `RERANK_IN`.
- **Qwen3-Reranker-4B:** public weights, downloaded to the Hugging Face cache. It loads with
  the existing `CrossEncoderReranker` unchanged (no code change), in 7,725 MiB.
- **Not measured:** MiniCheck in fp16/bf16; several processes sharing the card at once;
  quality of the 4B reranker (this is speed only, not a back-test).

## Measured: latency (milliseconds, medians of runs 1 and 2 that agree to 1 percent)

| Stage | n per run | 0.6B reranker setup | 4B reranker setup |
|---|---|---|---|
| Query embed (Qwen3-Embedding-0.6B), one query | 10 | 27.4 median, p95 29.7 to 31.0 | 26.5 to 26.9 median, p95 29.4 to 31.4 |
| Thread build for a cold researcher (embeds the papers, no cache) | 10 | 1,272 to 1,284 median, p95 2,228 | 1,257 to 1,287 median, p95 2,233 |
| Rerank, 14 candidates | 10 | 147 median, p95 167 | 603 median, p95 671 to 675 |
| Rerank, 50 candidates | 10 | 468 median, p95 503 to 509 | 2,098 to 2,100 median, p95 2,212 to 2,215 |
| Rerank, 100 candidates | 10 | 787 median, p95 890 to 894 | 3,710 to 3,718 median, p95 4,150 to 4,158 |
| MiniCheck, one sentence per call | 25 | 31.5 to 31.7 median, p95 33.9 to 34.8 | 31.1 to 31.8 median, p95 33.6 to 34.3 |

The MiniCheck row is the same model in all four runs (it does not depend on the reranker);
the spread is run-to-run noise. Rerank on the 4B is 4.1 to 4.7 times the 0.6B.

## Measured: saturated throughput

Reranker pairs per second, 400 real (query, document) pairs from the 100-candidate pools,
by `predict` batch size (two repeats each agree within 0.3 percent):

| Batch size | 0.6B pairs/s | 4B pairs/s |
|---|---|---|
| 2 | 67 | 27.8 |
| 4 | 117 | **28.5** |
| 8 | **124** | 25.0 |
| 16 | 98.5 | 22.1 |
| 32 | 78.5 | 20.9 |
| 64 | 70.0 | 19.6 |

Larger batches are slower here: the CrossEncoder pads every pair in a batch to the longest
one (documents run to 2,000 characters), so big batches waste work. Best batch: 8 for the
0.6B, 4 for the 4B. Using these: 0.6B 124 pairs/s, 4B 28.5 pairs/s. (Cross-check: rerank of
100 candidates in 787 ms is 127 pairs/s; of 100 on the 4B in 3,710 ms is 27 pairs/s.)

MiniCheck, sentences per second, 25 documents with 8 claims each: 48 at forward batch 8,
49.5 at batch 32. One call at a time (the way the validator calls it) is 1 / 0.0315 s = 32
sentences/s.

## Measured: VRAM (MiB, this process only unless noted)

| Item | 0.6B setup | 4B setup |
|---|---|---|
| Embedder weights | 1,136 | 1,136 |
| Reranker weights | 1,136 | 7,725 |
| MiniCheck weights (fp32) | 1,356 | 1,356 |
| Weights of all three | 3,628 | 10,217 |
| Peak allocated during rerank at the default batch of 8 | 3,805 | 10,683 |
| Peak allocated after the MiniCheck stage | 3,950 | 10,538 |
| Reserved by torch after the batch sweep (up to batch 64) | 7,304 | 24,682 |
| `nvidia-smi` for the card, all loaded, after the sweep | 7,688 | 25,066 |

It fits one 32 GB card either way. With the 0.6B reranker about 3.6 GB of weights and under
8 GB of cache after the largest batch leave about 24 GB free for a chat model. With the 4B,
weights plus activations at a batch of 4 to 8 need about 10.7 GB; the 24.7 GB reserved is
the caching allocator keeping memory freed after the batch-64 test, not a need, so at the
batch sizes that are fastest the headroom is about 21 GB (32,760 MiB card minus 10.7 GB).

## Per-brief load, from the code

- **Fit-explainer calls:** one per lead, 10 leads per brief (`top=10`), plus one regeneration
  in some cases. Recorded: 31 Sonnet calls for 30 leads over 3 briefs
  (`bench/results/RESULTS.md`, Fit explanation table, claude-sonnet-5-5 row). One profile
  summary call per brief besides (`cost.csv`: 2 summary calls in that log).
- **Grounding calls:** `perch/skills/fit.py` `ground()` checks the opportunity sentence
  (1 call) and each research finding against its one paper. The prompt asks for 1 to 3
  findings per lead. So 2 to 4 MiniCheck calls per lead, 20 to 40 per brief. The
  arithmetic below uses 3 per lead (2 findings), 30 per brief. The typical findings count
  per lead is UNVERIFIED (no result file stores it).
- **Rerank pairs:** N per brief (one pair per candidate against its best thread), when the
  thread scores are not already cached.
- **Embed:** about 2.3 thread queries per researcher (23 queries over 10 researchers) at
  27 ms is 0.06 s. A cold researcher also needs the thread build, 1.28 s; this is cached for
  7 days (`bench/results/s38_cpu/README.md`), so the warm column is the steady state.

## (A) One GPU, cloud explainer: GPU seconds per brief and briefs per minute

GPU seconds per brief = N / pairs per second (reranker at its best batch) + 30 MiniCheck
sentences + 0.063 s for query embeds. Two rows per case for grounding: one call at a time
(30 x 0.0315 = 0.945 s, how the validator runs today) and saturated batches (30 / 49.5 =
0.606 s, an upper bound that needs the grounding calls batched).
Briefs per minute = 60 / seconds. "Cold" adds the 1.28 s thread build.

| Reranker | rerank_in N | Rerank s | Ground s (seq / sat) | GPU s per brief, warm (seq / sat) | Briefs per min, warm (seq / sat) | Briefs per min, cold (seq / sat) |
|---|---|---|---|---|---|---|
| 0.6B | 14 | 0.113 | 0.945 / 0.606 | 1.12 / 0.78 | **53.5 / 76.7** | 25.0 / 29.1 |
| 0.6B | 50 | 0.403 | 0.945 / 0.606 | 1.41 / 1.07 | 42.5 / 56.0 | 22.3 / 25.5 |
| 0.6B | 100 | 0.806 | 0.945 / 0.606 | 1.81 / 1.47 | 33.1 / 40.7 | 19.4 / 21.8 |
| 4B | 14 | 0.491 | 0.945 / 0.606 | 1.50 / 1.16 | 40.0 / 51.7 | 21.6 / 24.6 |
| 4B | 50 | 1.754 | 0.945 / 0.606 | 2.76 / 2.42 | 21.7 / 24.8 | 14.8 / 16.2 |
| 4B | 100 | 3.509 | 0.945 / 0.606 | 4.52 / 4.18 | 13.3 / 14.4 | 10.4 / 11.0 |

Users: briefs per minute times the minutes between one user's briefs. Using the sequential
warm column (the conservative one):

| Reranker | N | Briefs/min | Users at 1 brief per 2 min | Users at 1 brief per 5 min |
|---|---|---|---|---|
| 0.6B | 14 | 53.5 | 107 | 267 |
| 0.6B | 50 | 42.5 | 85 | 212 |
| 0.6B | 100 | 33.1 | 66 | 165 |
| 4B | 14 | 40.0 | 80 | 200 |
| 4B | 50 | 21.7 | 43 | 108 |
| 4B | 100 | 13.3 | 27 | 66 |

Cold (every user a new researcher, nothing cached): 10 to 25 briefs per minute, so 21 to 50
users at one per 2 minutes.

**The cloud explainer bound** (Sonnet 5.5 start tier as given: 4,000 requests per minute,
2M input tokens per minute, 400K output tokens per minute). Recorded use for the 3-brief
Sonnet run (`bench/results/RESULTS.md`, Fit explanation, claude-sonnet-5-5 row): 31 calls,
10,832 input tokens, 17,528 output tokens, so per brief about 10.3 calls, 3,611 input and
5,843 output tokens (the summary call, a Haiku call, is not in these figures).

- **Requests:** 4,000 / 10.3 = about 387 briefs per minute.
- **Input tokens:** 2,000,000 / 3,611 = about 554 briefs per minute. The recorded input
  count looks low next to the local models' 59,348 tokens for the same 30 leads
  (1,978 per lead); whether the Anthropic figure leaves out cached prompt tokens is
  UNVERIFIED. With the local count, 2,000,000 / 19,783 per brief = 101 briefs per minute.
- **Output tokens:** 400,000 / 5,843 = **about 68 briefs per minute**. This is the binding
  limit in both readings of the input count.

So the cloud limit is about 68 briefs per minute (137 users at one brief per 2 minutes, 342
at one per 5). The combined limit is the smaller of the GPU figure and 68. For the 0.6B at
N = 14 the sequential GPU figure (53.5) is below 68, so the GPU binds, but only by a factor
of 1.3; with batched grounding (76.7) the cloud limit binds instead. Every other row is
GPU-bound. Cover-letter points, hand-offs and Scout also call Sonnet and are not in this
figure.

## (B) Previous build, two GPUs fully local (`deploy-2gpu`)

Layout (`perch/profiles.py` `_TWO_GPU`, `docs/TRACKER.md` Deployment row): GPU A has
gemma4:26b-a4b through Ollama with two slots at a 12,288 context plus Clef-flash; GPU B has
Clef (grounder), the embedder and the reranker. The chat model writes the fit text.

Recorded numbers (not re-measured):

| Quantity | Value | Source |
|---|---|---|
| One brief, live, public URL | 38.7 s | `docs/TRACKER.md`, Key numbers, Brief time row (S32) |
| One brief, dev server | 41.9 s | same row |
| 1 brief at once, Gemma, Clef-flash, one card | p50 52.2 s | `bench/results/single_card.csv`, row gemma4:26b-a4b / clef-flash / briefs 1 |
| 2 at once | p50 83.9 s, max 85.5 s | same file, briefs 2 |
| 3 at once | p50 136.2 s, max 139.9 s | same file, briefs 3 |
| Fit explanation, Gemma, per call and per brief | p50 10.9 s per call, 42.9 s per 10-lead brief | `bench/results/RESULTS.md`, Fit explanation table |
| Sonnet for comparison | p50 4.7 s per call, 25.7 s per brief | same table |
| Clef grounder per sentence | 0.194 s | `bench/results/grounders.csv`, Clef row |
| Clef-flash per sentence | 0.063 s | same file |
| MiniCheck on the old dev CPU | 0.268 s | same file |
| Rerank (hybrid plus 0.6B reranker) per award, whole path | 2.27 s p50 (at the time's 50 candidates) | `bench/results/SUMMARY.md`, back-test table |

Throughput. The chat model is the bottleneck: Ollama with two slots finishes about two
briefs per 85 seconds, and a third at once makes each brief slower without more output.

| Briefs at once | Wall time for the batch | Briefs per minute |
|---|---|---|
| 1 (bench) | 52.2 s | 60 / 52.2 = 1.15 |
| 1 (live) | 38.7 s | 60 / 38.7 = 1.55 |
| 2 | 85.5 s | 2 x 60 / 85.5 = 1.40 |
| 3 | 139.9 s | 3 x 60 / 139.9 = 1.29 |

Maximum about **1.4 briefs per minute**, so 2.8 users at one brief per 2 minutes and 7 users
at one per 5 minutes. Caveat: the concurrency rows come from the one-card bench (Gemma and
Clef-flash on one GPU), not the 2-GPU layout; the 2-GPU layout moves the grounder to a
second card, which should help slightly but was not measured at concurrency (UNVERIFIED).
The chat GPU is still the limit in either case.

## Comparison with CPU, 16 cores

From `bench/results/s38_cpu/README.md` (shared node, 16 cores, float32):

| Stage | CPU, 16 cores | GPU 3, 0.6B | GPU speedup |
|---|---|---|---|
| Query embed | 270 to 316 ms | 27.4 ms | about 10 to 12 times |
| Rerank, 14 candidates | 9,386 ms | 147 ms | about 64 times |
| Rerank, 50 candidates | 32,472 to 41,027 ms | 468 ms | about 69 to 88 times |
| Rerank, 100 candidates | 58,192 to 65,379 ms | 787 ms | about 74 to 83 times |
| MiniCheck, one sentence | 619 to 635 ms | 31.6 ms | about 20 times |

CPU brief at N = 14, sequential warm: 9.4 s rerank + 30 x 0.627 s grounding (18.8 s) + 0.3 s
embed = 28.5 s, or about 2.1 briefs per minute on 16 cores (arithmetic from the table
above, not a measured end-to-end run). The 4B reranker on GPU at N = 100 (3.7 s) is still
about 16 times faster than the 0.6B on CPU at N = 100.

## Bottlenecks

- **(A)** On the GPU, grounding is the biggest cost with the 0.6B reranker (0.6 to 0.95 s of
  1.1 s at N = 14), then rerank grows with N. With the 4B reranker, rerank dominates from N =
  50 up (1.75 s of 2.76 s). Past roughly 50 to 70 briefs per minute the cloud explainer's
  output-token limit takes over.
- **(B)** The local chat model: about 1.4 briefs per minute whatever the grounder and
  reranker do.

## Caveats

- Shared node, other users' load (1-minute load about 31); the GPU itself was exclusive
  (GPU lock), but CPU contention may add tokenizer time to these numbers.
- Single process, warm models, one request at a time. Concurrent requests to one process
  were not run; the throughput figures are saturated-batch arithmetic, not an end-to-end
  concurrent load test.
- Grounding calls per brief (30) is an assumption within the 20 to 40 range from the prompt;
  see "Per-brief load".
- The 4B reranker's ranking quality was not measured; this is speed only.
