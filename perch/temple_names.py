"""Remove people's names from Temple award records outside the award's own title.

The public-ready convention allows a person's name only inside an award title copied from
Temple's public pages, such as a donor in an endowed scholarship's title (CLAUDE.md,
Dakshitha 2026-11-03). Quoted page sentences, eligibility notes and other text often name
donors, co-funders, past winners or staff as well. `scrub_record` replaces every
person-like name in those strings with "[name removed]", unless every word of the name is in
the record's title. It runs after extraction and dedupe, so the quote checks that kept each
value have already passed; the scrub only changes the evidence text shown to users.

It is a heuristic and errs towards removing: a run of two to four capitalised words, or an
honorific with a name, that contains no organisation, award, place or calendar word. The
dataset build is followed by an independent read-only check (S40), so a name the pattern
misses is found and the pattern is widened.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from perch.schemas import Opportunity, Scholarship

REMOVED = "[name removed]"

_HONORIFIC = r"(?:Dr|Mr|Mrs|Ms|Mx|Prof|Professor|Rev|Hon|Judge|Dean)\.?"
_WORD = r"(?:[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?|[A-Z]\.|Mc[A-Z][a-z]+|O'[A-Z][a-z]+)(?![A-Za-z])"
_NAME = re.compile(
    # "Mitch and Debra Sonkin": a first name joined to a full name by "and" is part of it.
    rf"\b(?:{_HONORIFIC}\s+(?:and\s+(?:Mrs|Mr|Ms)\.?\s+)?)?(?:{_WORD}\s+and\s+)?"
    rf"{_WORD}(?:\s+{_WORD}){{1,3}}"
    r"(?:,?\s+(?:Jr|Sr|II|III|IV)\b\.?)?"
)
_HONORIFIC_START = re.compile(rf"^{_HONORIFIC}\s")

# A capitalised run containing any of these is an organisation, award, place, program or
# date, not a person.
NOT_PERSON = {
    w.lower() for w in """
    Temple University College School Schools Department Program Programs Office Center Centre
    Institute Foundation Fund Funds Scholarship Scholarships Scholar Scholars Award Awards
    Grant Grants Fellowship Fellowships Prize Prizes Society Association Council Committee
    Board Club Chapter Alliance Network Corps Service Services Union League Academy Hospital
    Health Medicine Medical Law Business Engineering Science Sciences Arts Art Architecture
    Education Pharmacy Dentistry Nursing Studies Research Graduate Undergraduate Honors
    Student Students Faculty Alumni Campus Library Hall Building Street Avenue City County
    State States United America American Americas National International Global World
    Port River Ward Biosciences Bioscience Township Borough County Counties Parish Region
    District Valley Heights Park Square Village
    Philadelphia Pennsylvania Japan Rome Ambler Tokyo Italy Europe European Africa Asia Latin
    January February March April May June July August September October November December
    Monday Tuesday Wednesday Thursday Friday Saturday Sunday Spring Summer Fall Winter
    The This That These Those Applicants Applications Recipients Eligible Eligibility
    Financial Aid Fee Fees Tuition Office Officer Dean's Provost President Vice Chair
    Public Private Community Communities Family Families Children Youth Women Men Veterans
    First Second Third Year Years Semester Term Day Week Month Full Part Time Online
    GPA FAFSA PhD MD MBA BA BS MA MS JD DMD PharmD Bachelor Master Masters Doctor Doctoral
    English Spanish French German Chinese Korean Arabic Black African Hispanic Asian Native
    Christian Jewish Catholic Muslim Peace Freedom Liberty Democracy Global Leadership
    Training Development Career Careers Professional Professionals Industry Company Inc
    Association's Society's Institute's Foundation's Inc LLC Corporation Bank Group Partners
    Kappa Alpha Beta Gamma Delta Phi Sigma Pi Omega Lambda Theta Tau Rho Chi Psi Epsilon Zeta
    Eta Iota Mu Nu Xi Omicron Upsilon
    """.split()
}


WORDLIST = Path("/usr/share/dict/words")


@cache
def common_words() -> frozenset[str]:
    """Lower-case entries of the system word list: ordinary English words. Capitalised
    entries (proper names) are left out, so "Robert" is not a common word and "long" is."""
    if not WORDLIST.exists():
        raise RuntimeError(f"{WORDLIST} is needed to scrub names (Debian package wamerican)")
    return frozenset(w.strip() for w in WORDLIST.read_text("utf-8", "ignore").splitlines()
                     if w.strip() and w.strip().islower())


def _is_common(word: str) -> bool:
    w = word.lower().removesuffix("'s")
    cw = common_words()
    return (w in cw or w.rstrip("s") in cw or w.removesuffix("es") in cw
            or w.removesuffix("ies") + "y" in cw or "-" in w and all(p in cw for p in w.split("-")))


def _person_like(m: re.Match[str], title_words: set[str]) -> bool:
    text = m.group(0)
    words = [w.strip(".,'") for w in re.split(r"\s+", text)]
    words = [w for w in words if w]
    if any(w.lower() in NOT_PERSON for w in words):
        return False
    name_words = [w for w in words if not _HONORIFIC_START.match(w + " ")
                  and w.lower() not in {"and", "jr", "sr", "ii", "iii", "iv"} and len(w) > 1]
    if not name_words:
        return False
    if all(w.lower() in title_words for w in name_words):
        return False  # the award's own title names this person (the allowed exception)
    full = [w for w in name_words if not re.fullmatch(r"[A-Z]\.?", w)]
    if not full:
        return False
    uncommon = [w for w in full if not _is_common(w)]
    honorific = bool(_HONORIFIC_START.match(m.group(0)))
    # A person's name has at least one word that is not ordinary English, and ordinary
    # words are no more than half of it ("Rosemary Poole", "Abigail Long"); "Due Date" and
    # "Hospitality Management" are all ordinary words. An honorific always marks a person.
    if not honorific and (not uncommon or len(uncommon) * 2 < len(full)):
        return False
    tail = m.string[m.end():m.end() + 40]
    # "Benjamin A. Gilman International Scholarship": a name that is part of an award title.
    return not re.match(r"\s*(?:\w+\s+){0,3}?(?:Scholarship|Award|Prize|Fellowship|Grant|"
                        r"Fund|Program|Endowment|Lecture|Chair)\b", tail)


def scrub_text(text: str, title: str) -> str:
    title_words = {w.strip(".,'").lower() for w in re.split(r"\s+", title) if w}
    return _NAME.sub(lambda m: REMOVED if _person_like(m, title_words) else m.group(0), text)


# Top-level fields that are identifiers, URLs or the title itself. Nested strings (the quoted
# sentences in field_quotes, eligibility notes) are always scrubbed, whatever their key, and
# so is any top-level value with spaces in it: a sentence stored in a URL field by mistake
# is scrubbed like any other sentence.
_KEEP_FIELDS = {"id", "title", "name", "source", "source_url", "fetched_at", "kind", "url",
                "apply_url", "details_url", "page_owner", "schools", "scope", "agency"}


def _is_url(v: str) -> bool:
    return v.startswith(("http://", "https://", "mailto:")) and " " not in v


Json = str | int | float | bool | None | list["Json"] | dict[str, "Json"]


def _walk(v: Json, title: str, top_key: str | None = None) -> Json:
    if isinstance(v, str):
        if _is_url(v) or (top_key in _KEEP_FIELDS and " " not in v) or top_key in {
                "title", "name", "id"}:
            return v
        return scrub_text(v, title)
    if isinstance(v, list):
        return [_walk(x, title, top_key) for x in v]
    if isinstance(v, dict):
        return {k: _walk(x, title, None) for k, x in v.items()}
    return v


def scrub_record(rec: Scholarship | Opportunity) -> Scholarship | Opportunity:
    title = getattr(rec, "title", None) or getattr(rec, "name", "") or ""
    data = rec.model_dump(mode="json")
    data = {k: _walk(v, title, k) for k, v in data.items()}
    return type(rec).model_validate(data)
