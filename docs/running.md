# Running Perch

> **v1 and the fallback.** `uv run perch serve --models fake` runs the app on SQLite with no accounts. The v1 stack (Postgres with pgvector, Redis, Keycloak for development, the web app and the worker) runs with `make v1-up` from `deploy/compose/docker-compose.v1.yml`; its worker is on the `cloud-cpu` profile today. Operations (health, backups, capacity, upgrades) are in [deploy.md](deploy.md). Parts of this page, such as the sample store and private mode, describe the fallback build at the tag `v0.1-demo-fallback`.

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

The sample store is `data/sample.db` (`PERCH_SAMPLE_DB`). This is the fallback build's way of loading it. In v1 the Temple awards dataset is loaded into Postgres with `perch temple load-dataset` (see below), and the SYNTHETIC samples are a separate screen.

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

`perch brief` on the command line stores its brief in your store: it is an operator tool. In the fallback build the web app kept nothing about visitors (see [the retired private-mode page](private-mode.md)). In v1, signed-in users' CVs, entries and briefs are stored encrypted per user and guests' briefs live in Redis for one hour; see the README and [ARCHITECTURE_V1.md](ARCHITECTURE_V1.md). The weekly watch (S16) is shelved in `perch/shelved/monitor/`.

Award links are matched by name. Fix a wrong or missed match in `data/overrides/award_links.csv`.

An OpenAlex API key is optional; see `.env.example`.

`make bench` runs the back-test and bench matrix (results in `bench/results/`). `make package` builds the submission ZIP in S28.

## Secrets

API keys go in `.env`, which is gitignored. Copy `.env.example` to start. `make hooks` installs git hooks that refuse commits containing keys, tokens, local paths or emails.

## Data sources

Every source, its endpoints, fields, limits and terms are in [SOURCES.md](SOURCES.md).


This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.
