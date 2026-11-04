"""User inputs and the CV parse (ported from the private-mode tests in S42): parse from bytes,
the DOCX and PDF guards, plain sentences for unreadable files, the CV rules, and a failed
step reading in plain words. SYNTHETIC text only."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from perch.user.cv import parse_cv
from perch.user.inputs import (
    MAX_BYTES,
    MAX_XML_BYTES,
    InputError,
    Upload,
    docx_text,
    make_doc,
    parse_bytes,
)

PERSONA = Path(__file__).resolve().parent.parent / "data/synthetic/persona-1"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx_of(xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_cv_parse_reads_degree_rank_and_esi():
    f = parse_cv((PERSONA / "cv.md").read_text())
    assert f.degree_year == 2021 and f.rank == "Assistant Professor"
    assert f.nih_substantial == [] and f.esi_possible(date(2026, 10, 29))
    assert not f.esi_possible(date(2032, 1, 1))
    g = parse_cv("# CV\n## Education\n- PhD, Biology, 2019\n## Funding\n"
                 "- NIH R01 GM000000, 2022 to 2027\n- NSF CAREER award, 2020\n"
                 "- NIH R21 AG000000, 2020\n")
    assert g.nih_substantial == ["R01"] and not g.esi_possible(date(2026, 1, 1))
    assert g.sponsors == ["NIH", "NSF"]


def test_inputs_parse_from_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body><w:p><w:r>'
                   "<w:t>SYNTHETIC aims</w:t></w:r></w:p><w:p><w:r><w:t>line two</w:t>"
                   "</w:r></w:p></w:body></w:document>")
    assert docx_text(buf.getvalue()) == "SYNTHETIC aims\nline two"
    assert parse_bytes("a.md", b"# SYNTHETIC") == "# SYNTHETIC"
    with pytest.raises(InputError):
        parse_bytes("a.exe", b"x")
    with pytest.raises(InputError):
        parse_bytes("a.pdf", b"not a pdf")
    with pytest.raises(InputError):
        make_doc("proposal", "x" * 70_000)


def test_docx_bombs_and_broken_xml_are_input_errors():
    """S2: a DOCX that inflates past the cap is refused before it is held in memory; a
    malformed document.xml is an InputError, not a crash (S5)."""
    bomb = docx_of(f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>'.encode()
                   + b"0" * (MAX_XML_BYTES + 10) + b"</w:t></w:r></w:p></w:body></w:document>")
    assert len(bomb) < MAX_BYTES // 100  # a small upload
    with pytest.raises(InputError, match="once unpacked"):
        docx_text(bomb)
    with pytest.raises(InputError, match="could not be read as a Word file"):
        docx_text(docx_of(b"<w:document><w:body><w:p>"))


def test_pdf_parse_failures_are_input_errors(monkeypatch):
    """S3: any exception from the PDF parser is an InputError, never a 500."""
    import pypdf
    from pypdf import PdfWriter

    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    assert parse_bytes("a.pdf", buf.getvalue()) == ""
    with pytest.raises(InputError):
        parse_bytes("a.pdf", buf.getvalue()[:-200])

    def broken(self, *a, **k):
        raise TypeError("SYNTHETIC parser bug")

    monkeypatch.setattr(pypdf.PageObject, "extract_text", broken)
    with pytest.raises(InputError, match="could not be read as a PDF"):
        parse_bytes("a.pdf", buf.getvalue())


def test_a_file_perch_cannot_read_gets_a_plain_sentence_with_its_name():
    """R4: each error is a sentence that names the file and says what to do."""
    cases = [("cv.txt", "SYNTHETIC café".encode("latin-1"),
              "cv.txt could not be read: save it as UTF-8 text, Word (.docx) or PDF, then add "
              "it again."),
             ("cv.png", b"\x89PNG", "cv.png is not a file Perch reads: use a text (.txt), "
              "Markdown (.md), Word (.docx) or PDF file."),
             ("cv.md", b"", "cv.md is empty: it holds no text Perch can read."),
             ("cv.docx", b"PK", "cv.docx could not be read as a Word file: save it again as "
              ".docx, or as PDF or text.")]
    for name, data, said in cases:
        with pytest.raises(InputError) as e:
            Upload("cv", filename=name, data=data).doc()
        assert str(e.value) == said
    with pytest.raises(InputError, match="^That text is empty: paste some text first.$"):
        Upload("cv", text="  ").doc()


def test_exclude_keyword_and_self_reported_stage_rules():
    from perch.eligibility import Constraints, check
    from perch.schemas import Opportunity, utcnow

    o = Opportunity(id="grants_gov:x", source="grants_gov", source_url="u", fetched_at=utcnow(),
                    opportunity_number="PAR-00-000", title="SYNTHETIC Early-Stage Investigator "
                    "award (R01)", agency="National Institutes of Health",
                    close_date=date(2027, 1, 1),
                    eligible_applicants=["Private institutions of higher education"],
                    description="Zebrafish models")
    base = Constraints(as_of=date(2026, 10, 28))
    assert any("career stage" in x for x in check(o, base))
    assert check(o, Constraints(as_of=date(2026, 10, 28), career_stage_ok=True)) == []
    assert any("zebrafish" in x for x in check(o, Constraints(
        as_of=date(2026, 10, 28), career_stage_ok=True, exclude_keywords=["zebrafish"])))


def test_failed_steps_read_in_plain_words_and_never_quote_the_input():
    """S25 QA rows 33 and 34."""
    import httpx

    from perch.service import InputProblem, plain_error

    assert plain_error(httpx.ConnectError("x")).startswith("A model server did not answer")
    assert "visitor text" not in plain_error(ValueError("visitor text"))
    assert plain_error(InputProblem("Add your CV first.")) == "Add your CV first."
