"""Build the submission ZIP: dist/perch-<version>-<shortsha>.zip.

The ZIP holds every tracked file (`git ls-files`) plus a generated SUBMISSION.md,
all under one top folder `perch/`. Untracked and ignored files (.env, data stores,
build output, model weights) are never included. Standard library only.

    python scripts/package.py [--allow-dirty] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "perch"


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return out.stdout


def tracked_files() -> list[str]:
    raw = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    return sorted(p for p in raw.stdout.decode("utf-8").split("\0") if p)


def is_dirty() -> bool:
    return bool(git("status", "--porcelain", "--untracked-files=no").strip())


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    return str(data["project"]["version"])


def readme_name_and_tagline(readme: str) -> tuple[str, str]:
    name = re.search(r"^# (.+)$", readme, re.M)
    tagline = re.search(r"^\*\*(.+)\*\*\s*$", readme, re.M)
    if not name or not tagline:
        raise SystemExit("package: README.md has no '# Name' heading or bold tagline line")
    return name.group(1).strip(), tagline.group(1).strip()


def readme_section(readme: str, heading: str) -> str:
    """The body of a '## heading' section, up to the next '## ' heading."""
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", readme, re.M | re.S)
    if not m:
        raise SystemExit(f"package: README.md has no '## {heading}' section")
    return m.group(1).strip("\n")


def submission_md(sha: str, date: str) -> str:
    readme = (ROOT / "README.md").read_text("utf-8")
    name, tagline = readme_name_and_tagline(readme)
    running = readme_section(readme, "Quick start")
    return f"""# {name}: submission package

**{tagline}**

Temple AI Build Challenge prototype.

- **Commit:** `{sha}`
- **Commit date:** {date}

## How to run it

The text below is the README's Quick start, copied as it stands. This ZIP is already
the repository contents, so skip the `git clone` line and run the rest from this folder.

{running}

## What is in this ZIP

- **Included:** every file tracked in the repository at the commit above. That is the source
  in `perch/`, the web app in `web/`, the tests, the scripts, the curated inputs under `data/`,
  the benchmark results in `bench/`, and the documents in `docs/`.
- **Not included, data stores:** no database, vector index, cache or log. Perch builds them on
  first use from public sources.
- **Not included, model weights:** none are shipped. `--models fake` needs no model at all. Real
  models are set up as described in `docs/running.md`.
- **Not included, secrets:** no `.env` and no keys. `.env.example` lists every variable.

## Where to read more

- **Architecture:** `docs/ARCHITECTURE.md`.
- **Results:** `bench/results/SUMMARY.md`, with the method behind each number.
- **AI-use log:** `docs/AI_USE_LOG.md`.
- **Running every command:** `docs/running.md`. **The two-GPU demo:** `docs/deploy.md`.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--allow-dirty", action="store_true",
                    help="package even with uncommitted changes to tracked files")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "dist",
                    help="where to write the ZIP (default: dist/)")
    args = ap.parse_args()

    if is_dirty() and not args.allow_dirty:
        print("package: tracked files have uncommitted changes; commit them or pass --allow-dirty",
              file=sys.stderr)
        return 1

    sha = git("rev-parse", "--short", "HEAD").strip()
    date = git("show", "-s", "--format=%cI", "HEAD").strip()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"perch-{project_version()}-{sha}.zip"
    if out.exists():
        out.unlink()

    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in tracked_files():
            path = ROOT / rel
            if not path.is_file():  # deleted in the working tree (only with --allow-dirty)
                continue
            info = zipfile.ZipInfo.from_file(path, f"{TOP}/{rel}")
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
            count += 1
        z.writestr(f"{TOP}/SUBMISSION.md", submission_md(sha, date))
    print(f"{out}  ({out.stat().st_size / 1_000_000:.1f} MB, {count + 1} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
