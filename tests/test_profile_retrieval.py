"""v1 ranks briefs on dense retrieval only; the fallback GPU profiles keep hybrid."""

from perch.profiles import PROFILES
from perch.retrieve import MODES


def test_v1_profile_is_dense_only() -> None:
    assert PROFILES["cloud-gpu"].retrieval == "dense"
    assert PROFILES["cloud-cpu"].retrieval == "dense"


def test_fallback_profiles_keep_hybrid() -> None:
    for name in ("dev", "deploy-2gpu", "deploy-1gpu"):
        assert PROFILES[name].retrieval == "hybrid"


def test_every_profile_mode_is_valid() -> None:
    assert all(p.retrieval in MODES for p in PROFILES.values())
