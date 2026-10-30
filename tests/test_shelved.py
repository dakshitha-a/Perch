"""Shelved code (S23) still imports, so it can be reconnected later."""


def test_shelved_monitor_still_imports():
    from perch.shelved.monitor import monitor

    assert callable(monitor.run) and callable(monitor.refresh_opportunities)
