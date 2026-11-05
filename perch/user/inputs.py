"""User inputs: pasted text or an uploaded file, parsed from bytes in memory (moved from
perch/private/inputs.py in S41; contact details are blanked at parse time).

No temp files: DOCX is a zip read from a BytesIO, PDF goes through pypdf from a BytesIO.
Each input has a size cap, checked before parsing; a PDF is also capped in pages, characters
and time.
"""

from __future__ import annotations

import concurrent.futures
import io
import re
import threading
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from perch.llm.contacts import blank_contacts
from perch.schemas import Work, utcnow

# Kinds of user document. The CV is parsed for eligibility and sponsor history only;
# the other three become query threads (shares in perch.threads).
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
# PDF bounds (S48 S6): pages, seconds, and parses at once (each on its own thread).
MAX_PDF_PAGES = 30
PDF_TIMEOUT_S = 15.0
PDF_PARALLEL = 2
_PDF_SLOTS = threading.BoundedSemaphore(PDF_PARALLEL)
_PDF_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=PDF_PARALLEL,
                                                  thread_name_prefix="perch-pdf")
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class InputError(ValueError):
    """Shown to the user as is; never quotes the input."""


class UserDoc(Work):
    """A user's document as a Work-shaped record the profile code can read, and the blob model of
    a `doc` row. `source: user`, id `user:<kind>`. Stored only encrypted (perch/user/data.py)."""

    kind = "user"  # type: ignore[assignment]
    filename: str | None = None


# Every InputError is a plain sentence for the person, shown beside the box they used, on
# the student form and on Your documents alike (R4). A file is named by its own name.
def _name(filename: str | None) -> str:
    name = " ".join((filename or "").split())
    return (name[:77] + "...") if len(name) > 80 else name or "That file"


def make_doc(kind: str, text: str, filename: str | None = None,
             keep_name: bool = False) -> UserDoc:
    if kind not in KINDS:
        raise InputError(f"Unknown document kind: use one of {', '.join(KINDS)}.")
    text = blank_contacts(clean(text))
    if not text:
        raise InputError(f"{_name(filename)} is empty: it holds no text Perch can read."
                         if filename else "That text is empty: paste some text first.")
    if len(text) > MAX_CHARS:
        raise InputError(f"{_name(filename) if filename else 'That text'} is longer than "
                         f"{MAX_CHARS:,} characters: shorten it, then add it again.")
    return UserDoc(id=f"user:{kind}", source="user", source_url="perch://user",
                   fetched_at=utcnow(), title=KINDS[kind], type="user",
                   abstract=text, filename=_name(filename) if keep_name and filename else None)


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_bytes(filename: str, data: bytes) -> str:
    """Text from an uploaded file. The extension picks the parser."""
    shown = _name(filename)
    if len(data) > MAX_BYTES:
        raise InputError(f"{shown} is larger than {MAX_BYTES // 1_000_000} MB: choose a "
                         "smaller file.")
    name = filename.lower()
    if name.endswith((".txt", ".md")):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as e:
            raise InputError(f"{shown} could not be read: save it as UTF-8 text, Word (.docx) "
                             "or PDF, then add it again.") from e
    if name.endswith(".docx"):
        return docx_text(data, shown)
    if name.endswith(".pdf"):
        return pdf_text(data, shown)
    raise InputError(f"{shown} is not a file Perch reads: use a text (.txt), Markdown (.md), "
                     "Word (.docx) or PDF file.")


def docx_text(data: bytes, shown: str = "That file") -> str:
    too_big = InputError(f"{shown} holds more than {MAX_XML_BYTES // 1_000_000} MB of text "
                         "once unpacked: choose a smaller file.")
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
        raise InputError(f"{shown} could not be read as a Word file: save it again as .docx, "
                         "or as PDF or text.") from e
    paras = ["".join(t.text or "" for t in p.iter(f"{W_NS}t")) for p in root.iter(f"{W_NS}p")]
    return "\n".join(paras)


def _pdf_extract(data: bytes, shown: str) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        n = len(reader.pages)
        if n > MAX_PDF_PAGES:
            raise InputError(f"{shown} has {n} pages. Perch reads PDFs of up to "
                             f"{MAX_PDF_PAGES} pages: add the pages that matter, or paste the "
                             "text.")
        parts: list[str] = []
        total = 0
        for page in reader.pages:  # stop as soon as the text is too long to keep
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t) + 2
            if total > MAX_CHARS + MAX_CHARS // 2:  # clean() trims some; this much never fits
                raise InputError(f"{shown} is longer than {MAX_CHARS:,} characters: shorten "
                                 "it, then add it again.")
        return "\n\n".join(parts)
    except InputError:
        raise
    except Exception as e:  # noqa: BLE001 - any parser failure is a bad upload (review S3)
        raise InputError(f"{shown} could not be read as a PDF: save it again, or as Word or "
                         "text.") from e


def pdf_text(data: bytes, shown: str = "That file", *, timeout_s: float | None = None) -> str:
    """Text of a PDF, bounded in pages, characters and time (S48 S6). pypdf runs on a small
    pool of its own threads. A Python thread cannot be stopped, so a parse past the time limit
    is abandoned, not killed: it keeps its slot until it ends, and with every slot held new
    PDFs are refused at once rather than queued, so slow files cannot pile up."""
    if not _PDF_SLOTS.acquire(timeout=1.0):
        raise InputError("Perch is reading other PDFs just now: try again in a minute, or "
                         "paste the text.")

    def run() -> str:
        try:
            return _pdf_extract(data, shown)
        finally:
            _PDF_SLOTS.release()

    try:
        fut = _PDF_POOL.submit(run)
    except RuntimeError:
        _PDF_SLOTS.release()
        raise
    try:
        return fut.result(timeout=PDF_TIMEOUT_S if timeout_s is None else timeout_s)
    except concurrent.futures.TimeoutError:
        raise InputError(f"{shown} took too long to read as a PDF: save it again, or as Word "
                         "or text.") from None


@dataclass
class Upload:
    kind: str
    text: str | None = None
    filename: str | None = None
    data: bytes | None = None

    def doc(self) -> UserDoc:
        if self.data is not None:
            return make_doc(self.kind, parse_bytes(self.filename or "", self.data),
                            self.filename or "That file", keep_name=bool(self.filename))
        return make_doc(self.kind, self.text or "")
