"""People's names outside an award title are removed from Temple record text (SYNTHETIC)."""

from perch.temple_names import REMOVED, scrub_text

TITLE = "The Quillon-Varrow Scholars Program"


def test_names_outside_the_title_are_removed() -> None:
    t = "Created and funded by Tamsin and Orrin Quillon and Dr. Bexley Varrowind Jr., the program."
    out = scrub_text(t, TITLE)
    assert "Tamsin" not in out and "Orrin" not in out and "Bexley" not in out
    assert out.count(REMOVED) == 2


def test_title_donor_and_other_award_titles_stay() -> None:
    assert scrub_text("The Zorvath Fund honours Zorvath.", "Elwin Zorvath Fund") == \
        "The Zorvath Fund honours Zorvath."
    t = "Applicants may also apply for the Benjamin A. Gilman International Scholarship."
    assert scrub_text(t, TITLE) == t


def test_ordinary_phrases_places_and_dates_stay() -> None:
    for t in ("The Due Date is March 15.", "Open to Hospitality Management majors.",
              "Students in Port Richmond may apply.", "Doctoral students in Cellular Biosciences.",
              "All PhD students qualify.", "Join MyAmeriCorps first."):
        assert scrub_text(t, TITLE) == t, t
