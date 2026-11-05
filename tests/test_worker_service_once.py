"""S47: the worker builds one BriefService and reuses it for every job. Building one per job
reloaded the GPU models per brief and failed at four briefs in flight."""

import inspect

from perch import cli


def test_cmd_worker_caches_the_brief_service():
    src = inspect.getsource(cli.cmd_worker)
    assert "built.append(make_brief_service())" in src
    assert "with lock:" in src and "return built[0]" in src


def test_perch_serve_reads_public_records_from_postgres_when_configured():
    """S48 deploy: `perch serve` with PERCH_DATABASE_URL read browse lists and lead records
    from the empty SQLite file. It must use the Postgres-backed repository like the worker."""
    src = inspect.getsource(cli.cmd_serve)
    assert "repo_factory=v1_repo_factory()" in src  # Postgres only since S49 B10
    factory = inspect.getsource(cli.v1_repo_factory)
    assert 'env("PERCH_DATABASE_URL")' in factory and "PostgresRepository(" in factory
