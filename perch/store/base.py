"""Repository interface. SQLite (demo) and Postgres (Temple) implement it."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import TypeVar

from perch.schemas import Record, Work

R = TypeVar("R", bound=Record)


class Repository(ABC):
    """Stores records by (kind, id). Every write keeps the record's provenance."""

    @abstractmethod
    def upsert(self, records: Iterable[Record]) -> int:
        """Insert or replace records; return how many were written."""

    @abstractmethod
    def get(self, cls: type[R], id: str) -> R | None:
        """Return one record of type cls, or None."""

    @abstractmethod
    def list(self, cls: type[R]) -> list[R]:
        """Return every record of type cls, ordered by id."""

    @abstractmethod
    def get_any(self, id: str) -> Record | None:
        """Return the record with this id, whatever its kind, or None."""

    @abstractmethod
    def works_by_author(self, author_id: str) -> list[Work]:
        """Return works that list author_id among their authors, newest first."""

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
    def dense(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        """(id, cosine similarity), best first."""

    @abstractmethod
    def bm25(self, query: str, k: int) -> list[tuple[str, float]]:
        """(id, BM25 score), best first."""

    @abstractmethod
    def ids(self) -> set[str]:
        """Every id in the index."""
