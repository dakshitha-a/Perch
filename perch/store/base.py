"""Repository interface. SQLite (unit tests, fallback) and Postgres (v1) implement it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date
from typing import TypeVar

from pydantic import BaseModel

from perch.schemas import Record, Work

R = TypeVar("R", bound=Record)


class Page[T: Record](BaseModel):
    """One page of browse results. next_cursor is None on the last page."""

    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


class Facets(BaseModel):
    """What the filter bar needs: a count per school (highest first), the audience levels in
    use, every public record of the kind, and how many are listed on a Temple page."""

    schools: list[tuple[str, int]]
    levels: list[str]
    total: int
    temple_total: int


def sorted_counts(c: Counter[str]) -> list[tuple[str, int]]:
    """Highest count first, ties by name."""
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))


class Repository(ABC):
    """Stores records by (kind, id). Every write keeps the record's provenance."""

    @abstractmethod
    def upsert(self, records: Iterable[Record]) -> int:
        """Insert or replace records; return how many were written."""

    @abstractmethod
    def get(self, cls: type[R], id: str) -> R | None:
        """Return one record of type cls, or None."""

    @abstractmethod
    def list(self, cls: type[R], *, include_samples: bool = False) -> list[R]:
        """Return every record of type cls, ordered by id. Records with source 'synthetic'
        are left out unless include_samples is set (standing rule 11)."""

    @abstractmethod
    def get_any(self, id: str) -> Record | None:
        """Return the record with this id, whatever its kind, or None."""

    @abstractmethod
    def works_by_author(self, author_id: str) -> list[Work]:
        """Return works that list author_id among their authors, newest first."""

    # browse, epoch and bump_epoch are not abstract, so older subclasses
    # (OverlayRepository) keep working until they are retired.
    def browse(self, cls: type[R], *, temple_only: bool = False, schools: Sequence[str] = (),
               audience_level: Sequence[str] = (), q: str | None = None,
               closes_after: date | None = None, limit: int = 50,
               cursor: str | None = None, scopes: Sequence[str] = (),
               exclude_schools: Sequence[str] = ()) -> Page[R]:
        """Filtered, paged listing of public records ordered by id. Samples never appear.
        `temple_only` keeps records listed on a Temple page (their source decides, fork F1).
        `scopes` keeps records whose derived scope is in the list; `schools` keeps records that
        name any of the schools. Empty means no filter."""
        raise NotImplementedError

    def facets(self, cls: type[R]) -> Facets:
        """Counts for the filter bar, from the stored rows. Samples never count."""
        from perch.store.denorm import TEMPLE_SOURCES, columns

        records = self.list(cls)
        schools: Counter[str] = Counter()
        levels: set[str] = set()
        for r in records:
            c = columns(r)
            schools.update(c.schools)
            levels.update(c.audience_level)
        return Facets(schools=sorted_counts(schools), levels=sorted(levels), total=len(records),
                      temple_total=sum(r.source in TEMPLE_SOURCES for r in records))

    def epoch(self) -> int:
        """Current ingest epoch (section 4.4); 0 before the first bump."""
        raise NotImplementedError

    def bump_epoch(self) -> int:
        """Increment the ingest epoch and return the new value."""
        raise NotImplementedError

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources."""

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class VectorIndex(ABC):
    """Dense and BM25 search over one kind of record (e.g. opportunities).

    Rows hold a record id, the text that was embedded, and its vector. Records
    themselves (and their provenance) stay in the Repository.
    """

    @abstractmethod
    def upsert(self, ids: list[str], texts: list[str], vectors: list[list[float]]) -> int:
        """Insert or replace rows by id; return how many were written."""

    @abstractmethod
    def dense(self, vector: list[float], k: int, *, temple_only: bool = False,
              schools: Sequence[str] = (), include_samples: bool = False
              ) -> list[tuple[str, float]]:
        """(id, cosine similarity), best first."""

    @abstractmethod
    def bm25(self, query: str, k: int, *, temple_only: bool = False,
             schools: Sequence[str] = (), include_samples: bool = False
             ) -> list[tuple[str, float]]:
        """(id, sparse score), best first. BM25 in Lance, ts_rank_cd in Postgres."""

    @abstractmethod
    def ids(self) -> set[str]:
        """Every id in the index."""
