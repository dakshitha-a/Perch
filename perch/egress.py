"""Egress filter for private mode (docs/design/PRIVATE_MODE.md, "Leaving the app").

Default: nothing derived from private text leaves the app. A text that cites a private
record (source "private", ids like "private:aims#2") is withheld from exports and
hand-off drafts. S12 builds the filter and its hooks; S13 builds the private session
that produces such records.

Opt-in: a `Masker` replaces identifiers with typed placeholders ([PERSON-1], [AWARD-1],
the same placeholder each time) and phrases found in the private documents but in no
public record with [PRIVATE-PHRASE-n]. The key back to the originals lives only in the
Masker object, in memory, so the user can unmask on screen. Masking hides identifiers;
it cannot hide the research direction, and WARNING says so.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from perch.schemas import Record

PRIVATE = "private"
WITHHELD = "Withheld: this text draws on private documents, which never leave Perch."
WARNING = ("Masking hides names, contact details and identifiers, and phrases that appear "
           "only in your private documents. It cannot hide your research direction: a "
           "reader can still tell what the work is about.")
PHRASE_WORDS = 4  # a private phrase is at least this many words in a row

# Typed identifiers found by pattern. Names and institutions have no reliable pattern;
# the caller passes them as terms (S13: from the CV parse).
PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("ORCID", re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
    ("AWARD", re.compile(r"\b\d?[A-Z]\d{2}[A-Z]{2}\d{6}(?:-\d{2}[A-Z\d]*)?\b")),  # NIH
    ("URL", re.compile(r"https?://\S+")),
]


def is_private_id(i: str) -> bool:
    return i.startswith(f"{PRIVATE}:")


def is_private(r: Record) -> bool:
    return r.source == PRIVATE or is_private_id(r.id)


def public_only[R: Record](records: Iterable[R]) -> list[R]:
    return [r for r in records if not is_private(r)]


def uses_private(cited_ids: Iterable[str]) -> bool:
    return any(is_private_id(i) for i in cited_ids)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class Masker:
    """Typed placeholders with an in-memory key. Never written anywhere."""

    def __init__(self, private_texts: Iterable[str] = (), public_texts: Iterable[str] = (),
                 terms: dict[str, Iterable[str]] | None = None) -> None:
        self.key: dict[str, str] = {}  # placeholder -> original
        self._seen: dict[tuple[str, str], str] = {}  # (type, normalised original) -> ph
        self._terms = {t: sorted({x for x in xs if x.strip()}, key=len, reverse=True)
                       for t, xs in (terms or {}).items()}
        public = set()
        for t in public_texts:
            w = _words(t)
            public |= {tuple(w[i:i + PHRASE_WORDS]) for i in range(len(w) - PHRASE_WORDS + 1)}
        self._private_grams = set()
        for t in private_texts:
            w = _words(t)
            self._private_grams |= {g for i in range(len(w) - PHRASE_WORDS + 1)
                                    if (g := tuple(w[i:i + PHRASE_WORDS])) not in public}

    def _placeholder(self, kind: str, original: str) -> str:
        k = (kind, original.lower().strip())
        if k not in self._seen:
            n = 1 + sum(1 for t, _ in self._seen if t == kind)
            ph = f"[{kind}-{n}]"
            self._seen[k] = ph
            self.key[ph] = original
        return self._seen[k]

    def _phrases(self, text: str) -> str:
        """Replace runs of words that form private-only n-grams."""
        if not self._private_grams:
            return text
        toks = list(re.finditer(r"[A-Za-z0-9]+", text))
        low = [m.group(0).lower() for m in toks]
        hit = [False] * len(toks)
        for i in range(len(toks) - PHRASE_WORDS + 1):
            if tuple(low[i:i + PHRASE_WORDS]) in self._private_grams:
                for j in range(i, i + PHRASE_WORDS):
                    hit[j] = True
        out, pos, i = [], 0, 0
        while i < len(toks):
            if not hit[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(toks) and hit[j + 1]:
                j += 1
            start, end = toks[i].start(), toks[j].end()
            out += [text[pos:start], self._placeholder("PRIVATE-PHRASE", text[start:end])]
            pos, i = end, j + 1
        return "".join(out) + text[pos:]

    def mask(self, text: str) -> str:
        for kind, rx in PATTERNS:
            text = rx.sub(lambda m, k=kind: self._placeholder(k, m.group(0)), text)
        for kind, xs in self._terms.items():
            for x in xs:
                text = re.sub(re.escape(x), lambda m, k=kind: self._placeholder(k, m.group(0)),
                              text, flags=re.I)
        return self._phrases(text)

    def unmask(self, text: str) -> str:
        for ph, original in sorted(self.key.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(ph, original)
        return text


def withheld_note(n: int) -> str:
    """The stated count of model texts left out of an export (S8)."""
    return (f"{n} {'explanation' if n == 1 else 'explanations'} withheld: this session holds "
            "documents, and model text may draw on them. Choose masking to include them "
            "masked.")


HANDOFF_WITHHELD = ("1 explanation withheld: this session holds documents, so the model's "
                    "opening paragraph may draw on them and stays in Perch. Choose masking to "
                    "include it masked.")


def release_model(text: str | None, cited_ids: Iterable[str], masker: Masker | None = None,
                  documents: bool = False) -> str | None:
    """Model-written text as it may leave the app. In a session that holds documents, the
    documents sit in every model prompt, so the text may paraphrase them while citing only
    public records: it is treated as private-derived (withheld, or masked on opt-in)."""
    if text is not None and documents:
        return masker.mask(text) if masker else WITHHELD
    return release(text, cited_ids, masker)


def release_thread(t: dict, masker: Masker | None = None) -> dict:
    """A brief thread for export: a private thread's label is made of words from the
    documents, so it is withheld or masked, and its document ids are dropped."""
    if not t.get("private"):
        return t
    return {**t, "label": masker.mask(t.get("label") or "") if masker else WITHHELD,
            "work_ids": []}


def release(text: str | None, cited_ids: Iterable[str], masker: Masker | None = None
            ) -> str | None:
    """The text as it may leave the app: unchanged if it cites no private record;
    masked if the user opted in; otherwise WITHHELD."""
    if text is None or not uses_private(cited_ids):
        return text
    return masker.mask(text) if masker else WITHHELD
