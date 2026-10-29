# Deploying the demo

[Back to the README](../README.md)

## Two GPUs, one command

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
- **The weekly watch:** every Monday at 06:00, `perch-demo-monitor.timer` runs `perch monitor` in the app container for the researchers in `PERCH_WATCH`. It refreshes open NIH opportunities from Grants.gov, re-runs their briefs and stores what changed, with an email draft that is never sent. The What changed screen shows the latest run. `make demo-monitor` runs it at once.
- **Limits:** each visitor can start 10 new briefs an hour (`PERCH_BRIEFS_PER_HOUR`).
- **Health:** `GET /health` answers when the app is up; `GET /health?deep=true` checks every model service.

## Public URL

The demo is published with Tailscale Funnel: `tailscale funnel --bg 8090`. Funnel needs HTTPS certificates, MagicDNS and Funnel turned on for the tailnet, and `sudo tailscale set --operator=$USER` once. HTTPS is decrypted on the node itself, not by Tailscale.

## Fallback: laptop and phone hotspot

If the lab node or its network is down on Demo Day:

1. **Use the replay demo:** `uv run python scripts/build_ui_preview.py` writes `build/artifacts/ui.html`, one self-contained page. Open it in the laptop's browser. It plays a saved brief with no server and no network; no real brief runs in this mode.
2. **Or run Perch on the laptop:** `uv run perch serve --models fake` serves the full app with fake models. With a hotspot and an `ANTHROPIC_API_KEY` in `.env`, `PERCH_LLM_DEFAULT=anthropic:claude-sonnet-5-5 uv run --extra ml perch serve` runs real briefs with search on the laptop's CPU. This path is UNVERIFIED on a laptop.
3. **Share it from the laptop:** a phone on the same hotspot opens `http://<laptop address>:8100` after `perch serve --host 0.0.0.0`.
