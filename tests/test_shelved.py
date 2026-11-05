"""The weekly watch was shelved in S23 and removed from rebuild/v1 in S49 (B28). It is kept
on the fallback tag v0.1-demo-fallback."""

import importlib.util


def test_the_shelved_monitor_is_gone_from_the_package():
    assert importlib.util.find_spec("perch.shelved") is None
