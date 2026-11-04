"""Importer for the versioned Temple dataset file (perch.temple_dataset)."""

from __future__ import annotations

import json
from pathlib import Path

from perch import temple_dataset as td
from perch.schemas import Opportunity, Scholarship


class DatasetImporter:
    """Reads temple_awards_v<N>.jsonl. The sha256 in the manifest beside it, when there is
    one, must match. Every row is public temple_pages data with provenance (rules 4, 11)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def read(self) -> list[Scholarship | Opportunity]:
        mp = td.manifest_path(self.path)
        if mp.is_file():
            want = json.loads(mp.read_text("utf-8")).get("sha256")
            if want and want != td.sha256_file(self.path):
                raise td.DatasetError(f"{self.path.name} does not match its manifest sha256")
        return td.read_records(self.path)
