# Running Perch

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

Student mode (inside private mode) reads two more stores. Load them once:

```sh
uv run perch fetch temple      # Temple SDFA's public fellowship list into the public store
uv run perch samples           # the SYNTHETIC sample scholarships into their own store
```

The sample store is `data/sample.db` (`PERCH_SAMPLE_DB`). The app also loads it on start when private mode is on.

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

`perch brief` on the command line stores its brief in your store: it is an operator tool. The web app and its API keep nothing about visitors; see [Privacy](private-mode.md). The weekly watch (S16) is shelved in `perch/shelved/monitor/`.

Award links are matched by name. Fix a wrong or missed match in `data/overrides/award_links.csv`.

An OpenAlex API key is optional; see `.env.example`.

`make bench` runs the back-test and bench matrix (results in `bench/results/`). `make package` builds the submission ZIP in S26.

## Secrets

API keys go in `.env`, which is gitignored. Copy `.env.example` to start. `make hooks` installs git hooks that refuse commits containing keys, tokens, local paths or emails.

## Data sources

Every source, its endpoints, fields, limits and terms are in [SOURCES.md](SOURCES.md).


This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.
