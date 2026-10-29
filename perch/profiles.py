"""Model choice per deployment profile (SPEC section 11), from the S8 bench.

`PERCH_PROFILE` selects one of: dev (the 8-GPU development layout), deploy-2gpu,
deploy-1gpu. Each winner is the best measured performer for its job in
bench/results/RESULTS.md; the runner-up is the commented line below it, so a
switch is one line. Environment variables (PERCH_LLM_<ROLE>) still override.
"""

from __future__ import annotations

from dataclasses import dataclass

from perch.config import env


@dataclass(frozen=True)
class ModelProfile:
    chat: str  # provider spec for skills 1 to 3 (profile summary, fit, hand-off)
    grounder: str  # validator layer 2: "minicheck", "systemone:clef-flash", "systemone:clef"
    embedder: str
    reranker: str


# Chat: gemma4:26b-a4b passed both validator layers on 28 of 30 leads, the same as
# qwen3.8:27b, with a p50 brief of 144 s against 272 s on one card (3 at once).
# Grounder: Clef separated supported from swapped-record sentences best (AUC 0.998,
# 40 pairs; every grounder tied at the 0.5 threshold). Embedder and reranker: the
# S4 defaults until the back-test matrix picks.
_TWO_GPU = ModelProfile(
    chat="ollama:gemma4:26b-a4b",
    # chat="ollama:qwen3.8:27b",
    grounder="systemone:clef",
    # grounder="systemone:clef-flash",
    embedder="Qwen/Qwen3-Embedding-0.6B",
    reranker="Qwen/Qwen3-Reranker-0.6B",
)

PROFILES: dict[str, ModelProfile] = {
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
        reranker="Qwen/Qwen3-Reranker-0.6B",
    ),
}
DEFAULT_PROFILE = "dev"


def current() -> ModelProfile:
    name = env("PERCH_PROFILE", DEFAULT_PROFILE)
    if name not in PROFILES:
        raise ValueError(f"PERCH_PROFILE must be one of {', '.join(PROFILES)}: {name!r}")
    return PROFILES[name]
