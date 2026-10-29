# Perch

*See every route to fund your work.*

Perch reads a Temple researcher's public papers and lays out the routes to fund that work: grants and foundations, and industry leads. Every claim is cited to a public record. It then drafts a hand-off to the right Temple office; nothing is ever sent by the app. Built for the Temple AI Build Challenge, Fall 2026. So far the repository can find a Temple researcher in OpenAlex, store their public works and their public NIH and NSF awards with provenance, and print a research profile with the public award horizon. It also stores open and archived federal funding opportunities from Grants.gov. See `docs/SPEC.md` for the design and `docs/PLAN.md` for the build plan.

## Run

Requires [uv](https://docs.astral.sh/uv/) and `make`. uv installs Python 3.12 and the pinned dependencies on first run.

```sh
make hooks     # once per clone: blocks secrets and personal details at commit time
make test      # ruff + pytest
make tracker   # render docs/TRACKER.md to docs/tracker.html
```

Find a researcher and fetch their works into `data/perch.db`:

```sh
uv run perch resolve "Axel Kohlmeyer"          # or an ORCID iD, or an OpenAlex author id
uv run perch fetch openalex A5026494099
uv run perch fetch awards A5026494099          # NIH RePORTER and NSF, matched by name
uv run perch profile A5026494099               # key papers, awards, public award horizon
uv run perch fetch opportunities --agencies HHS-NIH11 --limit 40   # open NIH opportunities
uv run perch fetch opportunities --opp-num PA-20-185                # one, in any status
```

Route A leads use local models (Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B) from the optional `ml` extra:

```sh
uv sync --extra ml
CUDA_VISIBLE_DEVICES=3 uv run --extra ml perch brief A5026494099 --route A
```

`--models fake` runs the same pipeline with no model downloads.

Award links are matched by name. Fix a wrong or missed match in `data/overrides/award_links.csv`.

An OpenAlex API key is optional; see `.env.example`.

`make demo`, `make bench` and `make package` are placeholders until their sessions land.

## Secrets

API keys go in `.env`, which is gitignored. Copy `.env.example` to start. `make hooks` installs git hooks that refuse commits containing keys, tokens, local paths or emails.

## Data sources

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.

## Licence

MIT. See `LICENSE`.
