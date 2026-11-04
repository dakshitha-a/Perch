"""S47: the worker builds one BriefService and reuses it for every job. Building one per job
reloaded the GPU models per brief and failed at four briefs in flight."""

import inspect

from perch import cli


def test_cmd_worker_caches_the_brief_service():
    src = inspect.getsource(cli.cmd_worker)
    assert "built.append(make_brief_service())" in src
    assert "with lock:" in src and "return built[0]" in src
