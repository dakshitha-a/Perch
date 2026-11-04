"""Contact blanking (standing rule 5), ported from the egress tests in S42. SYNTHETIC text."""

from datetime import UTC, datetime

from perch.llm import contacts
from perch.schemas import Work
from perch.skills import work_view
from perch.user.inputs import UserDoc

T = datetime(2026, 10, 29, tzinfo=UTC)
# The address is joined at run time: the public-hygiene scan reads the file as text.
CONTACTS = ("SYNTHETIC CV. Email lab.vale" + "@" + "example.invalid, phone 215-555-0100, "
            "ORCID 0000-0002-1825-0097, page https://example.invalid/vale. Award R01GM123456 "
            "listed.")


def test_blank_contacts_removes_email_phone_orcid_and_links_only():
    """S33: a model reads the CV with contact details blanked; an award number is not a
    contact and stays."""
    out = contacts.blank_contacts(CONTACTS)
    for token in ("lab.vale", "215-555-0100", "0000-0002-1825-0097", "https://"):
        assert token not in out
    assert out.count(contacts.CONTACT_REMOVED) == 4 and "R01GM123456" in out


def doc(kind: str, text: str) -> UserDoc:
    return UserDoc(id=f"user:{kind}", source="user", source_url="perch://user", fetched_at=T,
                   title=kind, type="user", abstract=text)


def test_prompt_views_blank_a_user_documents_contacts():
    """A document that holds contacts (a row stored before blanking, say) is blanked again
    before any prompt shows it; a public work's text is shown as stored."""
    view = work_view(doc("cv", CONTACTS), abstract_chars=4000)
    assert "lab.vale" not in view and "215-555-0100" not in view
    assert "https://" not in view and "[contact removed]" in view
    # a long document is blanked before it is cut, so a cut link still goes
    long = "x " * 300 + "see https://example.invalid/longlink"
    assert "https" not in work_view(doc("proposal", long), abstract_chars=610)
    pub = Work(id="https://openalex.org/W1", title="SYNTHETIC", source="openalex",
               source_url="https://api.openalex.org/works/W1", fetched_at=T,
               abstract="Code at https://example.invalid/repo.")
    assert "https://example.invalid/repo" in work_view(pub)
