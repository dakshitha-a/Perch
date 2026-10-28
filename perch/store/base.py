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
    def works_by_author(self, author_id: str) -> list[Work]:
        """Return works that list author_id among their authors, newest first."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources."""

    def __enter__(self) -> Repository:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
