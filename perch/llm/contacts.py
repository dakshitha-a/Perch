"""Contact blanking: emails, phones, ORCIDs and links are replaced before any model sees text
(standing rule 5). Moved from perch/egress.py in S41; egress re-exports it until Phase 6."""

from __future__ import annotations

import re

# Typed identifiers found by pattern. Names and institutions have no reliable pattern;
# the caller passes them as terms (S13: from the CV parse).
PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("ORCID", re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
    ("AWARD", re.compile(r"\b\d?[A-Z]\d{2}[A-Z]{2}\d{6}(?:-\d{2}[A-Z\d]*)?\b")),  # NIH
    ("URL", re.compile(r"https?://\S+")),
]


# S33: a session's model may read the CV and documents (standing rule 5 as amended),
# with contact details blanked in every prompt view. The stored text is unchanged: the
# student rules and the CV parse read it.
CONTACT_KINDS = ("EMAIL", "PHONE", "ORCID", "URL")
CONTACT_REMOVED = "[contact removed]"


def blank_contacts(text: str) -> str:
    """The text with every email, phone number, ORCID and link replaced by a marker."""
    for kind, rx in PATTERNS:
        if kind in CONTACT_KINDS:
            text = rx.sub(CONTACT_REMOVED, text)
    return text
