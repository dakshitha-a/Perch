# Running Perch

> **v1 and the fallback.** `uv run perch serve --models fake` runs the app on SQLite with no accounts. The v1 stack (Postgres with pgvector, Redis, Keycloak for development, the web app and the worker) runs with `make v1-up` from `deploy/compose/docker-compose.v1.yml`; its worker is the GPU image on the `cloud-gpu` profile, and `docker-compose.cpu.yml` switches it to `cloud-cpu` on a host with no GPU. A host with no NVIDIA container runtime runs the worker natively (see deploy.md section 3b). Operations (health, backups, capacity, upgrades) are in [deploy.md](deploy.md). Parts of this page, such as the sample store and private mode, describe the fallback build at the tag `v0.1-demo-fallback`.

[Back to the README](../README.md)

## Setup

Perch needs [uv](https://docs.astral.sh/uv/) and `make`. uv installs Python 3.12 and the pinned dependencies on first run.

```sh
make hooks     # once per clone: blocks secrets and personal details at commit time
make test      # ruff + pytest
make tracker   # render docs/TRACKER.md to docs/tracker.html
```

Find a researcher and fetch their works into `data/perch.db`:

```sh
uv run perch resolve 0000-0001-6204-6475     # an ORCID iD, a name, or an OpenAlex author id
uv run perch fetch openalex A5026494099
uv run perch fetch awards A5026494099          # NIH RePORTER and NSF, matched by name
uv run perch profile A5026494099               # key papers, awards, public award horizon
uv run perch fetch opportunities --agencies HHS-NIH11 --limit 40   # open NIH opportunities
uv run perch fetch opportunities --opp-num PA-20-185                # one, in any status
```

Student mode reads two more stores. Load them once:

```sh
uv run perch fetch temple      # Temple SDFA's public fellowship list into the public store
uv run perch samples           # the SYNTHETIC sample scholarships into their own store
```

The sample store is `data/sample.db` (`PERCH_SAMPLE_DB`). This is the fallback build's way of loading it. In v1 the Temple awards dataset is loaded into Postgres with `perch temple load-dataset` (see "Loading the v1 data" below), and the SYNTHETIC samples are a separate screen.

## Loading the v1 data

The v1 stack reads its public records from Postgres. Both loads need the write URL of the `perch` database in `--dsn` or `PERCH_DATABASE_URL`.

```sh
uv run perch db migrate-corpus --dsn <write url>      # public records, vectors, SYNTHETIC samples, embedding cache
uv run perch temple load-dataset data/temple/dataset/temple_awards_v3.jsonl --dsn <write url>
```

`migrate-corpus` copies from the fallback stores (`data/perch.db` and `data/lance`) and exits 1 when row counts differ. Building the index without those stores is UNVERIFIED. The worker is started with `uv run --extra ml --extra anthropic perch worker`; `perch worker --check` exits 0 when a heartbeat is under 90 seconds old. Backups, restore and the key commands (`perch keys rekey`, `perch keys tombstones purge`, `perch reconcile-shreds`, `perch restore-mark`) are in [deploy.md](deploy.md).

Route A leads use local models (Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B) from the optional `ml` extra:

```sh
uv sync --extra ml
CUDA_VISIBLE_DEVICES=3 uv run --extra ml perch brief A5026494099 --route A
```

`--models fake` runs the same pipeline with no model downloads.

Route B lists up to five companies with at least two kinds of public signal: their papers cite the researcher's, they hold NIH SBIR/STTR awards in the researcher's topics, or their papers share those topics. No model is used, and every lead is labelled as inferred and not verified:

```sh
uv run perch brief A5026494099 --route B
```

`perch brief` on the command line stores its brief in your store: it is an operator tool. In the fallback build the web app kept nothing about visitors (see [the retired private-mode page](private-mode.md)). In v1, signed-in users' CVs, entries and briefs are stored encrypted per user and guests' briefs live in Redis for one hour; see the README and [ARCHITECTURE_V1.md](ARCHITECTURE_V1.md). The weekly watch (S16) was removed in v1; it remains in the fallback build.

Award links are matched by name. Fix a wrong or missed match in `data/overrides/award_links.csv`.

An OpenAlex API key is optional; see `.env.example`.

`make bench` runs the v1 back-test on Postgres (the S50 setup, results in `bench/results/`). `make bench-v0` runs the old bench matrix of the fallback build. `make demo` starts a local v1 demo without a GPU, and `make demo-v0` starts the fallback build. `make package` builds the submission ZIP.

## Settings and scripts for a v1 deploy

These are the names an operator meets. The reasons and the defaults are in [deploy.md](deploy.md).

- **Accounts:** `PERCH_ACCOUNTS_OPEN=0` turns self-registration off.
- **Guest limits:** the guest model budgets, the sessions an hour per address and the rate table are deploy settings. `PERCH_RATE_LIMITS` overrides the per-address rate limits as JSON.
- **Worker:** the scheduler runs in the worker and `PERCH_SCHEDULER=0` turns it off. `PERCH_WORKER_FAST_THREADS` reserves job threads for Scout, cover points and hand-offs.
- **Units:** `deploy/systemd/v1/` holds a web and a worker unit.
- **Scripts:** `scripts/refresh_v1.py` refreshes the federal records. `scripts/redenorm.py` recomputes the filter columns. `scripts/smoke_deploy.py --base <url>` checks a running deploy as a guest. `scripts/live_capture.py` needs `PERCH_LIVE_BASE` and records real model text for a SYNTHETIC user. `scripts/demo_reset.py` clears the guest limits before a demo. `scripts/export_example.py` saves the researcher and student example briefs that `/example.html` plays back, and `scripts/export_replay.py` saves one brief as a replay file. `scripts/build_ui_example.py` stages the example page for the tracker.
- **Shared demo account:** `perch user prepare-shared --subject <id>` gives the account both roles and current consent once. `perch user wipe-data --all-shared` deletes the CV, entries, briefs and Scout sessions of every id in `PERCH_SHARED_SUBJECTS` and keeps the account. Both need an admin database URL in `PERCH_ADMIN_DATABASE_URL`. `deploy/systemd/v1/perch-demo-wipe.service` and `.timer` run the wipe at 03:30 each night. `PERCH_SHARED_ACCOUNTS` turns on the banner. The comments in `.env.example` say how.
- **Films, screenshots and figures:** `scripts/tour/demo_films.py` films the four Demo Day films into `docs/films`. `scripts/screenshots.py --base <url> --env-file <file>` retakes the 76 screenshots in `docs/screenshots`, as [that folder's README](screenshots/README.md) explains. `scripts/render_figures.py` renders the architecture, roadmap and cost figures into `docs/architecture`. `scripts/cost_model.py` computes the figures behind [COST_MODEL.md](COST_MODEL.md). The films and screenshots need a running deploy and a browser. The figures need a browser. The cost model reads a committed ledger snapshot unless you give it ledgers. None of them is part of `make test`.
- **Demo Day:** the run sheet is [DEMO.md](DEMO.md).

## Secrets

API keys go in `.env`, which is gitignored. Copy `.env.example` to start. `make hooks` installs git hooks that refuse commits containing keys, tokens, local paths or emails.

## Data sources

Every source, its endpoints, fields, limits and terms are in [SOURCES.md](SOURCES.md).


This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.
