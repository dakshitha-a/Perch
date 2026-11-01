"""The submission packager builds a clean ZIP under one top folder."""

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (ROOT / ".git").exists(),
                    reason="the packager reads git; an unzipped submission has no .git")
def test_package_zip_layout(tmp_path: Path) -> None:
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "package.py"), "--allow-dirty",
         "--out-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    zips = list(tmp_path.glob("perch-*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as z:
        assert z.testzip() is None
        names = z.namelist()
        text = z.read("perch/SUBMISSION.md").decode("utf-8")
    for required in ("perch/README.md", "perch/SUBMISSION.md", "perch/pyproject.toml"):
        assert required in names
    assert all(n.startswith("perch/") for n in names)
    for banned in (".env", "data/perch.db", "build/", "dist/"):
        bad = [n for n in names if banned in n and n != "perch/.env.example"]
        assert bad == [], (banned, bad)
    assert "uv run perch serve" in text
