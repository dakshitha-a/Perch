"""Contact blanking: emails, phones, ORCIDs and links are replaced before any model sees text
(standing rule 5). Called wherever a user's text is parsed and before it reaches a prompt."""

from __future__ import annotations

import re

# Typed identifiers found by pattern. Names and institutions have no reliable pattern;
# the caller passes them as terms (S13: from the CV parse).
PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("ORCID", re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
    # No separators (ten digits, not part of a longer number or an amount) and international
    # numbers with a plus sign ("+44 20 7946 0958", "+49 (0)30 123456"). S45 S5.
    ("PHONE", re.compile(r"(?<![\w$.,])(?:\+?1)?\d{10}(?![\w]|[.,]\d)")),
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?(?:\(\d{1,4}\)[ .-]?)?\d{1,4}"
                         r"(?:[ .-]?\d{2,4}){1,4}(?!\d)")),
    ("AWARD", re.compile(r"\b\d?[A-Z]\d{2}[A-Z]{2}\d{6}(?:-\d{2}[A-Z\d]*)?\b")),  # NIH
    ("URL", re.compile(r"https?://\S+")),
    ("URL", re.compile(r"(?<![\w@.-])www\.[\w-]+(?:\.[\w-]+)+(?:/\S*)?", re.I)),
    # A bare domain with a common ending ("lab.example.org/me"). "U.S." and decimals do not
    # match: the ending must be a whole word from the list.
    ("URL", re.compile(r"(?<![\w@.-])[a-z0-9][\w-]*(?:\.[\w-]+)*\.(?:com|org|edu|net|gov|io|"
                       r"us|uk|ca|info|dev|app)\b(?:/\S*)?", re.I)),
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
