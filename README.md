# Perch

*See every route to fund your work.*

Perch reads a Temple researcher's public papers and lays out the routes to fund that work: grants and foundations, and industry leads. Every claim is cited to a public record. It then drafts a hand-off to the right Temple office; nothing is ever sent by the app. Built for the Temple AI Build Challenge, Fall 2026. So far the repository can find a Temple researcher in OpenAlex and store their public works with provenance. See `docs/SPEC.md` for the design and `docs/PLAN.md` for the build plan.

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
```

An OpenAlex API key is optional; see `.env.example`.

`make demo`, `make bench` and `make package` are placeholders until their sessions land.

## Secrets

API keys go in `.env`, which is gitignored. Copy `.env.example` to start. `make hooks` installs git hooks that refuse commits containing keys, tokens, local paths or emails.

## Licence

MIT. See `LICENSE`.
