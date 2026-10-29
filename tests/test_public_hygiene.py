import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_public", ROOT / "scripts/check_public.py")
check_public = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = check_public
spec.loader.exec_module(check_public)


def test_tracked_files_are_public_ready():
    os.chdir(ROOT)
    paths = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.split()
    assert check_public.check_files(paths, staged=False) == []


def test_catches_secrets_and_personal_details():
    key = "sk-" + "ant-api03-" + "x" * 30
    assert check_public.scan_text(f"ANTHROPIC_API_KEY={key}")
    assert check_public.scan_text("/" + "home/someone/project")
    assert check_public.scan_text("someone" + "@example.com")
    assert check_public.scan_text("https://claude" + ".ai/code/session_abc")


def test_allows_normal_text():
    trailer = "Co-Authored-By: Claude <noreply@anthropic.com>"
    assert check_public.scan_text(f"ANTHROPIC_API_KEY=\n{trailer}") == []
    assert check_public.scan_text("1+dakshitha-a@users.noreply.github.com") == []
    assert check_public.scan_text("see data/backtest/pis.csv and docs/SPEC.md") == []


def test_researcher_names_stay_out_of_shareable_docs():
    """Docs, the tracker and the README use aliases (PI-1 ...); names live only in
    data/overrides/pi_aliases.csv."""
    import csv
    import unicodedata

    def fold(s):
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()

    with (ROOT / "data/overrides/pi_aliases.csv").open(newline="", encoding="utf-8") as f:
        last_names = {fold(row["name"].split()[-1]) for row in csv.DictReader(f)}
    shareable = [ROOT / "README.md", *ROOT.glob("docs/**/*.md"), *ROOT.glob("docs/**/*.html"),
                 ROOT / "bridge/QUESTIONS.md"]
    hits = [(p.name, n) for p in shareable for n in last_names if n in fold(p.read_text("utf-8"))]
    assert hits == []


def test_vendor_sdks_only_inside_perch_llm():
    """Standing rule 6."""
    import re

    vendors = re.compile(r"^\s*(?:import|from)\s+(anthropic|openai|ollama|google\.genai|mistralai)\b",
                         re.M)
    offenders = [str(p.relative_to(ROOT)) for p in ROOT.glob("**/*.py")
                 if ".venv" not in p.parts and "llm" not in p.relative_to(ROOT).parts[:2]
                 and vendors.search(p.read_text("utf-8"))]
    assert offenders == []
