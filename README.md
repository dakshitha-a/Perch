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
uv run perch resolve 0000-0001-6204-6475     # an ORCID iD, a name, or an OpenAlex author id
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

Route B lists up to five companies with at least two kinds of public signal: their papers cite the researcher's, they hold NIH SBIR/STTR awards in the researcher's topics, or their papers share those topics. No model is used, and every lead is labelled as inferred and not verified:

```sh
uv run perch brief A5026494099 --route B
```

Award links are matched by name. Fix a wrong or missed match in `data/overrides/award_links.csv`.

An OpenAlex API key is optional; see `.env.example`.

`make bench` runs the back-test and bench matrix (results in `bench/results/`). `make package` is a placeholder until S16.

## Demo deployment

`make demo` brings up the demo in one command, on a Linux node with two NVIDIA GPUs, Docker, Ollama and llama.cpp. It uses the `deploy-2gpu` profile: Gemma 4 26B-A4B and Clef-flash on GPU A, and Clef, the embedder and the reranker on GPU B.

```sh
make demo                          # models as systemd user units, the app in Docker on 127.0.0.1:8090
make demo DEMO_GPU_A=0 DEMO_GPU_B=1   # pick the two GPUs (default 6 and 7)
make gpus                          # GPU memory per service
make demo-status                   # units and container
make demo-down                     # stop everything
```

- **Why two halves:** Docker on the lab node has no GPU access, so the models run on the host and the app container reaches them over localhost.
- **The demo store:** briefs live in `data/demo/`, seeded once from `data/`. The three demo researchers' briefs are built every morning at 05:30, and a visitor's request for one is answered at once.
- **Limits:** each visitor can start 10 new briefs an hour (`PERCH_BRIEFS_PER_HOUR`).
- **Health:** `GET /health` answers when the app is up; `GET /health?deep=true` checks every model service.

### Public URL

The demo is published with Tailscale Funnel: `tailscale funnel --bg 8090`. Funnel needs HTTPS certificates, MagicDNS and Funnel turned on for the tailnet, and `sudo tailscale set --operator=$USER` once. HTTPS is decrypted on the node itself, not by Tailscale.

### Fallback: laptop and phone hotspot

If the lab node or its network is down on Demo Day:

1. **Use the replay demo:** `uv run python scripts/build_ui_preview.py` writes `build/artifacts/ui.html`, one self-contained page. Open it in the laptop's browser. It plays a saved brief with no server and no network; no real brief runs in this mode.
2. **Or run Perch on the laptop:** `uv run perch serve --models fake` serves the full app with fake models. With a hotspot and an `ANTHROPIC_API_KEY` in `.env`, `PERCH_LLM_DEFAULT=anthropic:claude-sonnet-5-5 uv run --extra ml perch serve` runs real briefs with search on the laptop's CPU. This path is UNVERIFIED on a laptop.
3. **Share it from the laptop:** a phone on the same hotspot opens `http://<laptop address>:8100` after `perch serve --host 0.0.0.0`.

## Secrets

API keys go in `.env`, which is gitignored. Copy `.env.example` to start. `make hooks` installs git hooks that refuse commits containing keys, tokens, local paths or emails.

## Data sources

This product uses the Grants.gov API but is not endorsed or certified by the U.S. Department of Health and Human Services.

## Licence

MIT. See `LICENSE`.
