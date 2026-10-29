"""Seam for Temple's ScholarshipUniverse feed. Not built: no schema has been seen.

Temple's Student Financial Services runs ScholarshipUniverse (fixture
tests/fixtures/temple/sfs_scholarshipuniverse.html, read 2026-10-29). Students sign in with
AccessNet, answer profile questions, and are matched to internal (Temple) and external
awards. No public API, export format or field list was found on 2026-10-29 (Temple's
pages, other universities' guides, a web search), so this module invents none
(standing rule 2). Its field names are UNVERIFIED until a real export is in hand (Q26).

When Temple shares an export or API under its contract, the work is one function:
`to_scholarship(row)` maps one feed row onto perch.schemas.Scholarship, whose fields were
chosen to cover what any scholarship listing states (name, sponsor, amount range,
deadline, level, field, eligibility, application requirements). Student mode reads only
Scholarship records, so nothing else changes: the sample store is swapped for the feed,
`source` becomes "scholarshipuniverse", and the sample badge goes away for those records.
The feed's own match result, if it has one, would sit beside Perch's rule verdict, never
replace it silently.
"""

from __future__ import annotations

from perch.schemas import Scholarship

SOURCE = "scholarshipuniverse"
INFO_URL = ("https://sfs.temple.edu/financial-aid-types/scholarships/"
            "scholarship-opportunities-temple/scholarshipuniverse")


def to_scholarship(row: dict) -> Scholarship:
    """Map one feed row to a Scholarship. Needs a real export first (Q26)."""
    raise NotImplementedError("ScholarshipUniverse field names are UNVERIFIED; see Q26")
