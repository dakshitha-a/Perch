"""What a record asks for, quoted by code (S24 task 7, Q32).

Sentences from the record's own text that state a requirement or an expectation, chosen
by cue words. No model reads the record here: the checklist is the record's words.
"""

from __future__ import annotations

import re

CUES = re.compile(r"\b(must|should|required?|requires|expected|encouraged|are to|is to|"
                  r"need to|propose|proposals|applications? (?:should|must|may)|"
                  r"applicants? (?:should|must|may))\b", re.I)
SKIP = re.compile(r"\b(this (?:funding opportunity|notice|nofo|foa)|see section|"
                  r"grants\.gov|sam\.gov|era commons|deadline|due date|page limit)\b", re.I)
MAX_ITEMS = 6


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "")
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z])", text) if s.strip()]


def asks(text: str, cap: int = MAX_ITEMS) -> list[str]:
    """Cue sentences first; a record that states fewer than three gets its description's
    sentences instead, since then the description is all it asks for."""
    out = []
    for s in sentences(text):
        if 40 <= len(s) <= 400 and CUES.search(s) and not SKIP.search(s) and s not in out:
            out.append(s)
        if len(out) == cap:
            break
    if len(out) < 3:
        out = [s for s in sentences(text) if 40 <= len(s) <= 400][:cap]
    return out
