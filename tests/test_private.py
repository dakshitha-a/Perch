"""Private mode (S13): session pipeline, gate, isolation and the canary.

Inputs are the SYNTHETIC persona-1 files; each holds a unique canary token. Models are
fakes, so no network and no GPU.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from perch.llm.fake import FakeProvider
from perch.privacy import PrivateSettings
from perch.private.cv import parse_cv
from perch.private.inputs import InputError, docx_text, make_doc, parse_bytes
from perch.private.session import YOU, PrivateSessions, add_document
from perch.retrieve import index_opportunities
from perch.schemas import Brief, Lead

from .test_api import make

PERSONA = Path(__file__).resolve().parent.parent / "data/synthetic/persona-1"
FILES = {"cv": "cv.md", "proposal": "specific_aims_draft.md",
         "manuscript": "unpublished_manuscript.md"}
CANARIES = ["PERCH-CANARY-CV-7Q4X", "PERCH-CANARY-AIMS-K2M9", "PERCH-CANARY-MS-T8V3"]
SETTINGS = PrivateSettings(enabled=True, endpoints=("127.0.0.1", "localhost", "::1"),
                           tls_at="server", public_url=None, operator="Test operator")


def fit_reply(messages, system, schema):
    """A valid fit explanation citing the opportunity and the private proposal."""
    if schema and "fit" in schema.get("properties", {}):
        return json.dumps({
            "reasoning": "r", "fit": 70,
            "opportunity_sentence": "The announcement funds research projects [PAR-25-268].",
            "research_findings": [{"paper_id": "private:proposal",
                                   "finding": "proposed home insole sensing of gait"}],
            "link_sentence": "The proposal fits the announcement.",
            "cited_ids": ["PAR-25-268", "private:proposal"]})
    return ""


def persona_session(tmp_path, responder=fit_reply):
    _, service = make(tmp_path)
    with service.repo() as r:  # the public pipeline keeps the index; a session never writes it
        index_opportunities(r, service.models.get("index"), service.models.get("embedder"))
    service.models.provider = lambda spec: FakeProvider(responder=responder)
    sessions = PrivateSessions(service, SETTINGS)
    s = sessions.open()
    for kind, name in FILES.items():
        add_document(s, make_doc(kind, (PERSONA / name).read_text()))
    return service, sessions, s


def test_private_only_brief_returns_cited_routes(tmp_path):
    service, _, s = persona_session(tmp_path)
    b = s.service.create_private(None, as_of=date(2026, 10, 28))
    s.service.run(b.id)
    got = s.service.get(b.id)
    assert got, "the brief lives in the session"
    b, leads = got
    assert b.status == "done", b.error
    assert b.researcher_id == YOU
    assert [t["private"] for t in b.threads] == [True, True]  # proposal and manuscript
    assert abs(sum(t["weight"] for t in b.threads) - 1.0) < 1e-6
    assert leads and leads[0].explanation and "private:proposal" in leads[0].cited_ids
    # Nothing reached the shared store.
    with service.repo() as r:
        assert r.get(Brief, b.id) is None and not r.list(Lead)


def test_private_threads_take_their_share_beside_public_ones(tmp_path):
    _, _, s = persona_session(tmp_path)
    b = s.service.create_private("A5026494099", as_of=date(2026, 10, 28), explain=False)
    s.service.run(b.id)
    b, _ = s.service.get(b.id)
    assert b.status == "done", b.error
    private = [t["weight"] for t in b.threads if t["private"]]
    public = [t["weight"] for t in b.threads if not t["private"]]
    assert public and abs(sum(private) - 0.6) < 1e-3 and abs(sum(public) - 0.4) < 1e-3
    assert abs(private[0] / private[1] - 0.5 / 0.2) < 1e-2  # proposal : manuscript (Q21)


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
    import io
    import zipfile

    buf = io.BytesIO()
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body><w:p><w:r>'
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
