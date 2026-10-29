"""Temple offices a hand-off can go to (SPEC section 1). Names are copied as
research.temple.edu/about-us writes them, checked on 2026-10-29 (docs/SOURCES.md).

Only the office name and its public page are kept. No person, email or phone is stored:
the hand-off's To line stays empty for the user to fill (Dakshitha, S12).
"""

from __future__ import annotations

from dataclasses import dataclass

LISTED_AT = "https://research.temple.edu/about-us"
CHECKED = "2026-10-29"


@dataclass(frozen=True)
class Office:
    key: str
    name: str  # as the about-us page writes it
    url: str  # the office's public page (final URL after redirects)
    route: str  # the route it owns: A grants, B industry, F fellowships, S scholarships


OFFICES: dict[str, Office] = {
    "research_development": Office(
        "research_development", "Research Development",
        "https://research.temple.edu/funding-support", "A"),
    "technology_commercialization": Office(
        "technology_commercialization", "Innovation and Technology Commercialization",
        "https://research.temple.edu/innovation/technology-commercialization", "B"),
    # Student mode (S17, checked 2026-10-29 on the pages themselves, not on about-us):
    # the office name is the SDFA home page's title; SFS is linked from SDFA's list for
    # "financial aid and need-based awards".
    "sdfa": Office(
        "sdfa", "Scholar Development and Fellowships Advising",
        "https://undergraduate.temple.edu/fellowships", "F"),
    "sfs": Office(
        "sfs", "Student Financial Services", "https://sfs.temple.edu/", "S"),
}


def for_route(route: str) -> Office:
    return next(o for o in OFFICES.values() if o.route == route)
