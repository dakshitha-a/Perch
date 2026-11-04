"""Model choice per deployment profile (SPEC section 11), from the S8 bench.

`PERCH_PROFILE` selects one of: cloud-cpu (the default, v1: cloud models, CPU
embedder, reranker and MiniCheck), and the GPU layouts kept for the fallback build: dev,
deploy-2gpu, deploy-1gpu. Each winner is the best measured performer for its job in
bench/results/RESULTS.md, or the incumbent where the bench cannot separate them;
the runner-up is the commented line below it, so a switch is one line.
Environment variables (PERCH_LLM_<ROLE>) still override.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from perch.config import env


@dataclass(frozen=True)
class ModelProfile:
    chat: str  # provider spec for skills 1 to 3 (profile summary, fit, hand-off)
    grounder: str  # validator layer 2: "minicheck", "systemone:clef-flash", "systemone:clef"
    embedder: str
    reranker: str
    # Provider spec per role where it differs from `chat` (D-12: gate and cover_points are
    # roles; decide is gone). Empty for the GPU profiles, which use `chat` for every role.
    roles: Mapping[str, str] = field(default_factory=dict)
    # Rerank candidates per brief. The plan's shrink rule lowers it if CPU rerank is slow.
    rerank_in: int = 50
    device: str | None = None  # "cpu": models run on CPU inside model slots (perch/compute.py)

    def spec_for(self, role: str) -> str:
        return self.roles.get(role, self.chat)


# Chat: gemma4:26b-a4b passed both validator layers on 28 of 30 leads, the same as
# qwen3.8:27b, with a p50 brief of 144 s against 272 s on one card (3 at once).
# Grounder: Clef separated supported from swapped-record sentences best (AUC 0.998,
# 40 pairs; every grounder tied at the 0.5 threshold).
# Embedder: no alternative separated from Qwen3-Embedding-0.6B on the back-test (48
# targeted awards; every MRR-difference interval contains 0). specter2_base with the
# Qwen3 reranker put 9 of 48 in the top 10 against 7 (+5 / -3), without its proximity
# adapter. Qwen3-4B was slower (4.75 s against 2.27 s per award) for no measured gain.
# The LanceIndex has one table for every model, so switching needs data/lance removed.
# Reranker: Qwen3-Reranker-0.6B; Clef as reranker was measurably worse (4 of 48, MRR
# interval [-0.023, -0.001], 12 s per award) and Clef-flash put 5 of 48 in the top 10.
_TWO_GPU = ModelProfile(
    chat="ollama:gemma4:26b-a4b",
    # chat="ollama:qwen3.8:27b",
    grounder="systemone:clef",
    # grounder="systemone:clef-flash",
    embedder="Qwen/Qwen3-Embedding-0.6B",
    # embedder="allenai/specter2_base",
    reranker="Qwen/Qwen3-Reranker-0.6B",
    # reranker="systemone:clef-flash",
)

# v1 default (docs/v1/PROVIDER_AND_SSO.md, recommended model per job): Haiku 5.5 for the
# scope gate and the profile summary, Sonnet 5.5 for fit, hand-off, cover points and Scout.
# Embedder, reranker and MiniCheck run on CPU in the worker (perch/compute.py limits how
# many jobs hold one at once). No GPU, no Clef.
_HAIKU, _SONNET = "anthropic:claude-haiku-5-5", "anthropic:claude-sonnet-5-5"
_CLOUD_CPU = ModelProfile(
    chat=_SONNET,
    grounder="minicheck",
    embedder="Qwen/Qwen3-Embedding-0.6B",
    reranker="Qwen/Qwen3-Reranker-0.6B",
    device="cpu",
    roles={"gate": _HAIKU, "profile_summary": _HAIKU, "fit_explainer": _SONNET,
           "handoff": _SONNET, "cover_points": _SONNET, "scout": _SONNET},
)

PROFILES: dict[str, ModelProfile] = {
    "cloud-cpu": _CLOUD_CPU,
    "dev": _TWO_GPU,
    "deploy-2gpu": _TWO_GPU,
    # One 32 GB card, peak under 28 GB. No chat model passed every S8 gate:
    # qwen3:14b fits (22.7 GB peak) but passed both layers on 26 of 30 leads, 2 short
    # of the gate; gemma4:26b-a4b and qwen3.8:27b peak above 31 GB.
    "deploy-1gpu": ModelProfile(
        chat="ollama:qwen3:14b",
        # chat="ollama:qwen3:8b",
        # Clef-flash is resident for `decide` anyway; 4x faster than MiniCheck and
        # frees its 2 GB.
        grounder="systemone:clef-flash",
        # grounder="minicheck",
        embedder="Qwen/Qwen3-Embedding-0.6B",
        # embedder="allenai/specter2_base",
        reranker="Qwen/Qwen3-Reranker-0.6B",
        # reranker="systemone:clef-flash",
    ),
}
DEFAULT_PROFILE = "cloud-cpu"


def current() -> ModelProfile:
    name = env("PERCH_PROFILE", DEFAULT_PROFILE)
    if name not in PROFILES:
        raise ValueError(f"PERCH_PROFILE must be one of {', '.join(PROFILES)}: {name!r}")
    return PROFILES[name]
