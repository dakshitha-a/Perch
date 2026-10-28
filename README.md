# Perch

*See every route to fund your work.*

Perch reads a Temple researcher's public papers and lays out the routes to fund that work: grants and foundations, and industry leads. Every claim is cited to a public record. It then drafts a hand-off to the right Temple office; nothing is ever sent by the app. Built for the Temple AI Build Challenge, Fall 2026. This repository is at the skeleton stage: only the tooling and the project tracker exist so far. See `docs/SPEC.md` for the design and `docs/PLAN.md` for the build plan.

## Run

Requires [uv](https://docs.astral.sh/uv/) and `make`. uv installs Python 3.12 and the pinned dependencies on first run.

```sh
make test      # ruff + pytest
make tracker   # render docs/TRACKER.md to docs/tracker.html
```

`make demo`, `make bench` and `make package` are placeholders until their sessions land.

## Licence

MIT. See `LICENSE`.
