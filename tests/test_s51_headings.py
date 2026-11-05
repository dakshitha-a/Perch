"""S51 H13: neutral comparison, side-by-side and soonest headings from the s49b replay are
section names; headings that state a rank or a judgment still are not."""

import pytest

from perch.scout.answer import STRUCTURAL_RE, norm_exempt


@pytest.mark.parametrize("h", [
    "Which closes soonest:", "Which one closes first:", "Comparison of your two leads:",
    "Comparison of the kept leads:", "Two leads, side by side:", "Your leads side by side:",
    "Main themes of your work:", "Key themes of your research:"])
def test_neutral_headings_are_section_names(h):
    assert STRUCTURAL_RE.fullmatch(norm_exempt(h)), h


@pytest.mark.parametrize("h", ["Your top lead:", "Closest matches:", "Best fit for you:",
                               "Comparison of your top two leads:"])
def test_rank_and_judgment_headings_are_not(h):
    assert not STRUCTURAL_RE.fullmatch(norm_exempt(h)), h
