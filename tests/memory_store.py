"""An in-memory brief store for tests of code that reads a user's inputs through
`perch.user.briefs.current_store` (the Scout tools, the student stages). SYNTHETIC text only."""

from perch.user.briefs import MemoryBriefStore as MemoryStore

__all__ = ["MemoryStore"]
