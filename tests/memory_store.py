"""An in-memory brief store for tests of code that reads a user's inputs through
`perch.user.briefs.current_store` (the Scout tools, the student stages). SYNTHETIC text only."""

from __future__ import annotations

from perch.schemas import Work
from perch.user.briefs import BriefStore, StudentInputs


class MemoryStore(BriefStore):
    reads_user_data = True

    def __init__(self, brief_id: str = "mem", *, cv: str | None = None,
                 docs: list[Work] | None = None, student: StudentInputs | None = None) -> None:
        super().__init__(brief_id)
        self.cv, self.docs, self.student = cv, docs or [], student

    @property
    def result_ref(self) -> str:
        return "memory"

    def load(self) -> bool:
        return True

    def _write(self, sb) -> None:  # noqa: ANN001
        self.written = sb

    def user_docs(self) -> list[Work]:
        return list(self.docs)

    def cv_text(self) -> str | None:
        return self.cv

    def student_inputs(self) -> StudentInputs:
        if self.student is None:
            raise ValueError("no student inputs")
        return self.student
