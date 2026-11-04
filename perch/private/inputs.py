"""Private inputs: pasted text or an uploaded file, parsed from bytes in memory.

No temp files: DOCX is a zip read from a BytesIO, PDF goes through pypdf from a BytesIO.
Each input has a size cap, checked before parsing.
"""

from __future__ import annotations

from dataclasses import dataclass

from perch.schemas import Work, utcnow
from perch.user.inputs import (  # noqa: F401 - moved to perch/user/inputs.py in S41
    FORMATS,
    KINDS,
    MAX_BYTES,
    MAX_CHARS,
    MAX_XML_BYTES,
    W_NS,
    InputError,
    _name,
    clean,
    docx_text,
    parse_bytes,
    pdf_text,
)


class PrivateDoc(Work):
    """A private document as a session record (`source: private`). Never stored: the
    kind is not in RECORD_TYPES, and the id has no digits, so the validator never reads
    it as a number."""

    kind = "private"  # type: ignore[assignment]
    # The uploaded file's own name, held with the text in session memory only, so the
    # Cloud warning can name the document as the user added it (None: pasted text).
    filename: str | None = None


def make_doc(kind: str, text: str, filename: str | None = None,
             keep_name: bool = False) -> PrivateDoc:
    if kind not in KINDS:
        raise InputError(f"Unknown document kind: use one of {', '.join(KINDS)}.")
    text = clean(text)
    if not text:
        raise InputError(f"{_name(filename)} is empty: it holds no text Perch can read."
                         if filename else "That text is empty: paste some text first.")
    if len(text) > MAX_CHARS:
        raise InputError(f"{_name(filename) if filename else 'That text'} is longer than "
                         f"{MAX_CHARS:,} characters: shorten it, then add it again.")
    return PrivateDoc(id=f"private:{kind}", source="private", source_url="private://session",
                      fetched_at=utcnow(), title=f"{KINDS[kind]} (private)", type="private",
                      abstract=text, filename=_name(filename) if keep_name and filename else None)


@dataclass
class Upload:
    kind: str
    text: str | None = None
    filename: str | None = None
    data: bytes | None = None

    def doc(self) -> PrivateDoc:
        if self.data is not None:
            return make_doc(self.kind, parse_bytes(self.filename or "", self.data),
                            self.filename or "That file", keep_name=bool(self.filename))
        return make_doc(self.kind, self.text or "")
