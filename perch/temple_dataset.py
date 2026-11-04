"""The versioned Temple awards dataset (REBUILD_PLAN Phase 4 task 5).

`build_dataset` reads the extraction output (`perch extract temple-pages`), merges records
that are the same award (perch.temple_dedupe), and writes
`data/temple/dataset/temple_awards_v<N>.jsonl` with a manifest beside it. The file is
deterministic: rows are in id order, keys in a fixed order, and nothing in it depends on the
build time. The manifest holds the version, build time, input page count, counts by kind,
scope and school, the sha256 of the file, the extraction model id and the code commit.

Every row carries source="temple_pages", source_url and fetched_at (rule 4). Rows that are
synthetic, or whose id starts with "sample:", are refused (rule 11): the dataset is public
records only. Names of people outside an award's title are removed (perch.temple_names).

`load_dataset` reads a dataset file into a Repository through `upsert`, which is idempotent
by (kind, id). When the manifest sits beside the file, its sha256 must match.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from perch.schemas import Opportunity, Scholarship
from perch.store.base import Repository
from perch.temple_dedupe import DedupeReport, dedupe
from perch.temple_extract import SOURCE, read_done
from perch.temple_names import scrub_record

DATASET_DIR = Path("data/temple/dataset")
Rec = Scholarship | Opportunity
_CLASSES = {"scholarship": Scholarship, "opportunity": Opportunity}


class DatasetError(ValueError):
    pass


def parse_row(line: str) -> Rec:
    """One JSONL row to a record, refusing anything that is not a public temple_pages row."""
    d = json.loads(line)
    cls = _CLASSES.get(d.pop("kind", ""))
    if cls is None:
        raise DatasetError("row without a known kind")
    rec = cls.model_validate(d)
    if rec.source != SOURCE or not rec.source_url or rec.fetched_at is None:
        raise DatasetError(f"{rec.id}: not a {SOURCE} row with source_url and fetched_at")
    if rec.id.startswith("sample:") or rec.source == "synthetic":
        raise DatasetError(f"{rec.id}: sample records never enter the dataset")
    return rec


def read_records(path: Path) -> list[Rec]:
    return [parse_row(ln) for ln in path.read_text("utf-8").splitlines() if ln.strip()]


def row_json(r: Rec) -> str:
    return json.dumps({"kind": r.kind, **r.model_dump(mode="json")}, ensure_ascii=False,
                      sort_keys=True)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_commit() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                           timeout=10, check=False)
        return r.stdout.strip() or "UNKNOWN"
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def next_version(out_dir: Path) -> int:
    nums = [int(m.group(1)) for p in out_dir.glob("temple_awards_v*.jsonl")
            if (m := re.fullmatch(r"temple_awards_v(\d+)\.jsonl", p.name))]
    return max(nums, default=0) + 1


def dataset_path(out_dir: Path, version: int) -> Path:
    return out_dir / f"temple_awards_v{version}.jsonl"


def manifest_path(dataset: Path) -> Path:
    return dataset.with_suffix(".manifest.json")


def build_dataset(extracted: Path, out_dir: Path = DATASET_DIR, *, version: int | None = None,
                  model_id: str | None = None, commit: str | None = None,
                  now: datetime | None = None) -> tuple[Path, dict, DedupeReport]:
    """Write the next dataset version from an extraction file. Returns the dataset path,
    the manifest and the dedupe report."""
    recs = read_records(extracted)
    if not recs:
        raise DatasetError(f"no records in {extracted}")
    merged, rep = dedupe(recs)
    # People's names outside award titles are removed from the evidence text (temple_names).
    merged = [scrub_record(r) for r in merged]
    out_dir.mkdir(parents=True, exist_ok=True)
    version = version or next_version(out_dir)
    path = dataset_path(out_dir, version)
    if path.exists():
        raise DatasetError(f"{path} exists; versions are never overwritten")
    path.write_text("".join(row_json(r) + "\n" for r in merged), encoding="utf-8")
    done = read_done(extracted)
    pages = len(done) or len({r.source_url for r in recs})
    models = sorted({d.get("model", "") for d in done.values()} - {""})
    man = {
        "version": version,
        "built_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "file": path.name,
        "input_pages": pages,
        "input_records": rep.input_records,
        "records": len(merged),
        "by_kind": dict(sorted(Counter(r.kind for r in merged).items())),
        "by_scope": dict(sorted(Counter(r.scope or "unstated" for r in merged).items())),
        "by_school": dict(sorted(Counter(s for r in merged for s in r.schools).items())),
        "merged_groups": rep.merged_groups,
        "conflicting_pairs": len(rep.conflicts),
        "sha256": sha256_file(path),
        "extraction_model": model_id or ", ".join(models) or "UNKNOWN",
        "code_commit": commit or code_commit(),
    }
    manifest_path(path).write_text(json.dumps(man, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
    if rep.conflicts:
        cpath = path.with_suffix(".conflicts.jsonl")
        cpath.write_text("".join(json.dumps(c.as_dict(), sort_keys=True) + "\n"
                                 for c in rep.conflicts), encoding="utf-8")
    return path, man, rep


def load_dataset(path: Path, repo: Repository) -> int:
    """Upsert every row into repo. Idempotent: a second load changes nothing."""
    mp = manifest_path(path)
    if mp.is_file():
        want = json.loads(mp.read_text("utf-8")).get("sha256")
        if want and want != sha256_file(path):
            raise DatasetError(f"{path.name} does not match its manifest sha256")
    recs = read_records(path)
    return repo.upsert(recs)
