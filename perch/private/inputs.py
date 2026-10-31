"""Private inputs: pasted text or an uploaded file, parsed from bytes in memory.

No temp files: DOCX is a zip read from a BytesIO, PDF goes through pypdf from a BytesIO.
Each input has a size cap, checked before parsing.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from perch.schemas import Work, utcnow

# Kinds of private document. The CV is parsed for eligibility and sponsor history only;
# the other three become private research threads (shares in perch.private.threads).
KINDS = {
    "cv": "Your CV",
    "proposal": "Draft proposal",
    "direction": "Research direction",
    "manuscript": "Unpublished work",
    # Student mode (S18): the CV is parsed by rule; interests become the query thread;
    # each achievement becomes a record an explanation may cite.
    "interests": "Your interests",
    "achievements": "Your achievements",
}
MAX_BYTES = 5_000_000  # one uploaded file
MAX_CHARS = 60_000  # one document's text after parsing
# A DOCX's document.xml once inflated. Zip compresses zeros about 1000:1, so the 5 MB
# upload cap alone lets one request inflate gigabytes (review S2).
MAX_XML_BYTES = 10_000_000
FORMATS = (".txt", ".md", ".docx", ".pdf")
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class InputError(ValueError):
    """Shown to the user as is; never quotes the input."""


class PrivateDoc(Work):
    """A private document as a session record (`source: private`). Never stored: the
    kind is not in RECORD_TYPES, and the id has no digits, so the validator never reads
    it as a number."""

    kind = "private"  # type: ignore[assignment]


def make_doc(kind: str, text: str) -> PrivateDoc:
    if kind not in KINDS:
        raise InputError(f"unknown document kind; use one of {', '.join(KINDS)}")
    text = clean(text)
    if not text:
        raise InputError("the document is empty")
    if len(text) > MAX_CHARS:
        raise InputError(f"the document is longer than {MAX_CHARS:,} characters")
    return PrivateDoc(id=f"private:{kind}", source="private", source_url="private://session",
                      fetched_at=utcnow(), title=f"{KINDS[kind]} (private)", type="private",
                      abstract=text)


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_bytes(filename: str, data: bytes) -> str:
    """Text from an uploaded file. The extension picks the parser."""
    if len(data) > MAX_BYTES:
        raise InputError(f"the file is larger than {MAX_BYTES // 1_000_000} MB")
    name = filename.lower()
    if name.endswith((".txt", ".md")):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise InputError("the file is not UTF-8 text") from e
    if name.endswith(".docx"):
        return docx_text(data)
    if name.endswith(".pdf"):
        return pdf_text(data)
    raise InputError(f"unsupported file type; use {', '.join(FORMATS)}")


def docx_text(data: bytes) -> str:
    too_big = InputError(f"the DOCX text is larger than {MAX_XML_BYTES // 1_000_000} MB "
                         "once unpacked")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.getinfo("word/document.xml").file_size > MAX_XML_BYTES:
                raise too_big
            # The header's size can lie, so the read itself is bounded too.
            with z.open("word/document.xml") as f:
                xml = f.read(MAX_XML_BYTES + 1)
        if len(xml) > MAX_XML_BYTES:
            raise too_big
        root = ElementTree.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, zipfile.LargeZipFile,
            NotImplementedError, EOFError, OSError, RuntimeError) as e:
        raise InputError("the file is not a readable DOCX") from e
    paras = ["".join(t.text or "" for t in p.iter(f"{W_NS}t")) for p in root.iter(f"{W_NS}p")]
    return "\n".join(paras)


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except (PdfReadError, ValueError, KeyError) as e:
        raise InputError("the file is not a readable PDF") from e


@dataclass
class Upload:
    kind: str
    text: str | None = None
    filename: str | None = None
    data: bytes | None = None

    def doc(self) -> PrivateDoc:
        if self.data is not None:
            return make_doc(self.kind, parse_bytes(self.filename or "", self.data))
        return make_doc(self.kind, self.text or "")
