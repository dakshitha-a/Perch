"""Contact blanking: emails, phones, ORCIDs and links are replaced before any model sees text
(standing rule 5). Called wherever a user's text is parsed and before it reaches a prompt."""

from __future__ import annotations

import re

# Typed identifiers found by pattern. Names and institutions have no reliable pattern;
# the caller passes them as terms (S13: from the CV parse).
# Order matters: links come before ORCID iDs and phone numbers, so "orcid.org/0000-0002-1825-0097"
# is one link and the marker is never left inside a half-matched one.
BARE_DIGITS = re.compile(r"(?<![\w$.,])(?:\+?1)?\d{10}(?![\w]|[.,]\d)")
PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    # "jdoe at temple dot edu", "jdoe [at] temple [dot] edu" (S45 round 2)
    ("EMAIL", re.compile(r"\b[\w.+-]+\s*(?:\s|\[|\()at(?:\s|\]|\))\s*[\w-]+"
                         r"(?:\s*(?:\s|\[|\()dot(?:\s|\]|\))\s*[\w-]+)+\b", re.I)),
    ("URL", re.compile(r"https?://\S+")),
    ("URL", re.compile(r"(?<![\w@.-])www\.[\w-]+(?:\.[\w-]+)+(?:/\S*)?", re.I)),
    # A bare domain with a common ending ("lab.example.org/me"). "U.S." and decimals do not
    # match: the ending must be a whole word from the list.
    ("URL", re.compile(r"(?<![\w@.-])[a-z0-9][\w-]*(?:\.[\w-]+)*\.(?:com|org|edu|net|gov|io|"
                       r"us|uk|ca|info|dev|app)\b(?:/\S*)?", re.I)),
    # Any short domain written with a path ("x.ai/jdoe", "bit.ly/abc", "t.me/jdoe").
    ("URL", re.compile(r"(?<![\w@.-])[a-z0-9][\w-]*(?:\.[\w-]+)*\.[a-z]{2,6}/[\w~%.+-]+", re.I)),
    ("ORCID", re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")),
    # "(215) 204-1234", "(215)204-1234", "(215) 2041234", "215-2041234", "215.204.1234"
    ("PHONE", re.compile(r"(?<!\w)(?:\+?1[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])"
                         r"\d{3}[ .-]?\d{4}\b")),
    # No separators (ten digits, not part of a longer number or an amount) and international
    # numbers with a plus sign ("+44 20 7946 0958", "+49 (0)30 123456"). S45 S5.
    ("PHONE", BARE_DIGITS),
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?(?:\(\d{1,4}\)[ .-]?)?\d{1,4}"
                         r"(?:[ .-]?\d{2,4}){1,4}(?!\d)")),
    # A UK style number with a leading zero ("020 7946 0958").
    ("PHONE", re.compile(r"(?<![\w+])0\d{2,4}[ .-]\d{3,4}[ .-]\d{3,4}(?!\d)")),
    ("AWARD", re.compile(r"\b\d?[A-Z]\d{2}[A-Z]{2}\d{6}(?:-\d{2}[A-Z\d]*)?\b")),  # NIH
]
# A bare ten-digit number after one of these words is a grant, award or id number, not a phone.
ID_WORDS = re.compile(r"(?:grant|award|id|number|no\.?|#|proposal|contract|accession|pmid|"
                      r"project)\W{0,3}$", re.I)


# S33: a session's model may read the CV and documents (standing rule 5 as amended),
# with contact details blanked in every prompt view. The stored text is unchanged: the
# student rules and the CV parse read it.
CONTACT_KINDS = ("EMAIL", "PHONE", "ORCID", "URL")
CONTACT_REMOVED = "[contact removed]"


def blank_contacts(text: str) -> str:
    """The text with every email, phone number, ORCID and link replaced by a marker."""
    for kind, rx in PATTERNS:
        if kind not in CONTACT_KINDS:
            continue
        if rx is BARE_DIGITS:
            text = rx.sub(lambda m, t=text: m.group(0) if ID_WORDS.search(
                t[max(0, m.start() - 20):m.start()]) else CONTACT_REMOVED, text)
        else:
            text = rx.sub(CONTACT_REMOVED, text)
    return text
