"""The verified-feed seam (REBUILD_PLAN Phase 4 task 6).

An `Importer` reads records from one feed and returns them as `Scholarship` or
`Opportunity` records. Implementations: a CSV file, a JSON file, the versioned Temple
dataset, and the ScholarshipUniverse module (whose field names stay UNVERIFIED, Q26).
A feed never writes anywhere: the caller upserts what `read()` returns.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from perch.schemas import Opportunity, Scholarship


@runtime_checkable
class Importer(Protocol):
    def read(self) -> Iterable[Scholarship | Opportunity]:
        """Every record the feed holds, validated. Rows that cannot be records are not
        returned; row feeds list them in `rejected`."""
        ...


from perch.feeds.dataset import DatasetImporter  # noqa: E402
from perch.feeds.rows import CsvImporter, JsonImporter  # noqa: E402

__all__ = ["CsvImporter", "DatasetImporter", "Importer", "JsonImporter"]
