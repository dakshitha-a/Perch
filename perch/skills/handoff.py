"""Skill 3, hand-off drafter: an email the researcher can edit and send to one Temple
office about the leads they kept. Perch never sends it (standing rule 7).

The model writes one short paragraph only: what the research is about and which kept
leads the researcher wants help with, citing the records it was given. Code writes
everything else: the greeting, the list of leads with deadlines and amounts copied from
their records, the papers, and the sign-off. The paragraph passes validator layer 1 and
a phrase check (no "should apply", no "wants to fund"); a failure is regenerated once,
then the draft goes out with a code-written opening instead and is flagged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from perch import datefmt, egress
from perch.compare import award_size, lower_first
from perch.llm import Message
from perch.llm.audit import AuditedProvider
from perch.offices import RESEARCH_SECURITY, Office
from perch.schemas import Lead, Opportunity, Organisation, Record, Researcher, Work
from perch.skills import (
    GROUND_RULES,
    opportunity_view,
    parse_json,
    sentences,
    short_work_id,
    work_view,
)
from perch.validate import Check, check, generate_validated

SKILL = "handoff"
MAX_PAPERS = 6
SCHEMA = {
    "type": "object",
    "properties": {
        "paragraph": {"type": "string"},
        "cited_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    "required": ["paragraph", "cited_ids"],
    "additionalProperties": False,
}
SYSTEM = (
    "You draft the opening paragraph of an email from a researcher to a university office "
    "that helps researchers pursue funding. Write in the first person, as the researcher, "
    "2 to 4 sentences: what their published work is about, using the papers, and which of "
    "the listed leads they would like to discuss and why each relates to that work. Name "
    "each lead by its title or organisation. Do not repeat deadlines, amounts or counts; a "
    "list under your paragraph carries them. Industry leads are inferences from public "
    "signals: never say a company wants to fund, is interested in, or should partner with "
    "the researcher, and never say the researcher has worked or collaborated with it. Say "
    "only what its signals say, such as that its authors cite the papers or publish on the "
    "same topics. Do not put ids in the paragraph itself, since the reader does not know "
    "them; list every id you relied on in cited_ids, without brackets. " + GROUND_RULES
)
# Claims the app never makes (SPEC sections 1 and 12): advice to apply, predictions,
# or a company's intent.
BANNED = re.compile(
    r"\b(should|must) (apply|partner|submit)\b|\bwill (win|be funded|fund)\b|\bguarantee"
    r"|\b(wants?|eager|keen|interested) to (fund|partner|support|invest)\b"
    r"|\bis interested in (funding|my|our)\b"
    r"|\b(collaborations? with|collaborated with|worked with|have partnered)\b", re.I)


# Inline citations a model adds anyway, e.g. " [W123, PAR-26-121]", " [26-519]" or
# " [private:proposal]".
BRACKETED = re.compile(r"\s*\[([^\[\]]+)\]")


def plain_citations(text: str, records: dict[str, Record], listed: set[str]) -> str:
    """The email is plain prose (Q23): a bracketed citation key goes. A record the list
    below names is dropped; any other opportunity reads as its number in parentheses. A
    bracket that holds anything but citation keys stays as written."""
    def swap(m: re.Match) -> str:
        keys = [k.strip() for k in m.group(1).split(",")]
        if not all(k in records or egress.is_private_id(k) for k in keys):
            return m.group(0)
        out = [rec.opportunity_number for k in keys if k not in listed
               and isinstance(rec := records.get(k), Opportunity)]
        return f" ({', '.join(out)})" if out else ""
    return BRACKETED.sub(swap, text)


@dataclass
class Draft:
    office: Office
    subject: str
    body: str
    lead_ids: list[str]
    cited_ids: list[str] = field(default_factory=list)
    flagged: bool = False  # the model paragraph was withheld after two failures
    errors: list[str] = field(default_factory=list)
    model: str | None = None
    withheld: str | None = None  # why the model paragraph stayed in Perch (S8)
    opening_by: str = "code"  # F7: "model" when a model wrote the opening paragraph


def lead_key(lead: Lead) -> str:
    """Short id the model cites a lead by: the opportunity number, or B1..B5."""
    return lead.id.rsplit(":", 1)[-1]


def org_view(lead: Lead, org: Organisation | None) -> str:
    name = org.name if org else lead.record_id
    lines = [f"[{lead_key(lead)}] {name} (industry lead; inferred from public signals, not "
             "verified)"]
    if lead.relationship:
        lines.append(f"  Relationship suggested by rule: {lead.relationship}")
    if lead.explanation:
        lines.append(f"  Signals: {lead.explanation}")
    return "\n".join(lines)


def _money(o: Opportunity) -> str:
    """The card's award size (Q2): a floor-only record reads "from $X"."""
    size = award_size(o)
    return f"award size {lower_first(size)}" if size else \
        "award size not stated in the record"


def lead_lines(items: list[tuple[Lead, Record | None]]) -> list[str]:
    """The code-written list: every date and amount copied from the lead's record."""
    out = []
    for i, (lead, rec) in enumerate(items, 1):
        if isinstance(rec, Opportunity):
            # One clause for every deadline (F3): "closes 6 Nov 2026" as the cards say
            # (U14), a placeholder date as the record's words (U3), mid-sentence (R17), or
            # a parent announcement's expiry, which is no deadline (T17).
            closes = ("close date not stated in the record" if not rec.close_date
                      else lower_first(datefmt.deadline(rec)))
            code = (f" ({rec.activity_code})" if rec.activity_code
                    and rec.activity_code not in rec.title else "")
            out.append(f"{i}. {rec.opportunity_number}: {rec.title}{code}. {rec.agency_label()}; "
                       f"{closes}; {_money(rec)}.\n   Record: {rec.source_url}")
        elif isinstance(rec, Organisation):
            rel = f" Suggested relationship, by rule: {lead.relationship}." \
                if lead.relationship else ""
            link = rec.id if rec.id.startswith("https://openalex.org/") else rec.source_url
            out.append(f"{i}. {rec.name}: industry lead, inferred from public signals and not "
                       f"verified. {signals_mine(lead, rec.name)}{rel}\n   Record: {link}")
        else:
            out.append(f"{i}. {lead.record_id}")
    return out


def signals_mine(lead: Lead, name: str) -> str:
    """The lead's signal sentences in the researcher's own voice, "cite 2 of my papers":
    the email goes to the office from the researcher (R12)."""
    from perch.route_b import sentence

    if not lead.signals:
        return lead.explanation or ""
    return " ".join(sentence(s, name, len(lead.cited_ids), person="first") for s in lead.signals)


def paper_lines(papers: list[Work]) -> list[str]:
    out = []
    for w in papers:
        year = f" ({w.publication_year})" if w.publication_year else ""
        link = w.doi or w.source_url
        out.append(f"- {w.title}{year}. {link}")
    return out


def subject_for(items: list[tuple[Lead, Record | None]]) -> str:
    n_a = sum(1 for x, _ in items if x.route == "A")
    n_b = len(items) - n_a
    parts = []
    if n_a:
        parts.append(f"{n_a} funding {'opportunity' if n_a == 1 else 'opportunities'}")
    if n_b:
        parts.append(f"{n_b} industry {'lead' if n_b == 1 else 'leads'}")
    return "Request to discuss " + " and ".join(parts)


def assemble(office: Office, researcher: Researcher, opening: str,
             items: list[tuple[Lead, Record | None]], papers: list[Work],
             documents: bool = False) -> str:
    # F8: "kept" only when every lead listed is kept on the brief.
    kept = all(x.status == "kept" for x, _ in items)
    blocks = [f"Dear {office.name} team,", opening,
              "These are the leads I kept in Perch:" if kept
              else "These are the leads I would like to discuss:", "\n".join(lead_lines(items))]
    if papers:
        blocks += ["The papers they draw on:", "\n".join(paper_lines(papers))]
    # F19: a session's documents are named, as the export's header names them.
    note = (f"Perch drafted this from {'your documents and ' if documents else ''}public "
            "records. Each date and amount above is copied from the linked record.")
    if any(x.route == "B" for x, _ in items):
        note += (" Industry leads are inferences from public signals, not verified interest. "
                 + RESEARCH_SECURITY)
    # A researcher with no public profile signs the email themselves (Q26).
    name = "" if researcher.id.startswith("private:") else researcher.display_name
    blocks += [note, f"Best regards,\n{name}"]
    return "\n\n".join(blocks)


FALLBACK = "I would like to talk with your team about the funding leads listed below."
# F7: a session's documents named in the first person, in a code-written opening.
MY_DOCUMENTS = {"proposal": "my draft proposal", "direction": "my research direction",
                "manuscript": "my unpublished work", "cv": "my CV",
                "interests": "my interests note", "achievement": "my achievements",
                "achievements": "my achievements"}
DOCS_OPENING_NOTE = ("Written by Perch’s code from the lead’s title and the names of your "
                     "documents. No model read your documents for this draft.")


def _and(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def documents_opening(items: list[tuple[Lead, Record | None]], private: list[Work],
                      papers: list[Work]) -> str:
    """F7: the opening for a session that holds documents and no masking, by code with no
    model call: the leads by title and the documents by kind. Nothing about their content."""
    names = [rec.title if isinstance(rec, Opportunity) else rec.name
             for _, rec in items if isinstance(rec, Opportunity | Organisation)]
    kinds = list(dict.fromkeys(
        MY_DOCUMENTS.get(d.id.removeprefix("private:").split("-")[0].split("#")[0], "my documents")
        for d in private))
    sources = (["my published papers"] if papers else []) + kinds
    what = (_and(names) if 0 < len(names) <= 2
            else f"the {len(items)} leads listed below" if items else "the leads listed below")
    head = f"I would like to talk with your team about {what}."
    return head + (f" Perch matched {'it' if len(items) == 1 else 'them'} to my work from "
                   f"{_and(sources)}." if sources else "")


# F7: a citation that names no record, or a placeholder for one, is not a citation.
EMPTY_CITE = re.compile(r"\[\s*\]|\bno (?:papers?|records?|documents?) (?:were |was )?"
                        r"(?:provided|given|available)\b", re.I)


def draft_handoff(office: Office, researcher: Researcher,
                  items: list[tuple[Lead, Record | None]], papers: list[Work],
                  provider: AuditedProvider | None, masker: egress.Masker | None = None,
                  private: list[Work] | None = None) -> Draft:
    """items: the kept leads for this office with their opportunity or organisation.
    `private`: a private session's documents, which the model may cite. They sit in the
    prompt, so with documents the paragraph is private-derived whatever it cites: it is
    withheld, and no model runs, unless masked (perch.egress, S8)."""
    papers = egress.public_only(papers)[:MAX_PAPERS]
    lead_ids = [x.id for x, _ in items]
    subject = subject_for(items)
    docs = bool(private)
    if provider is not None and private and masker is None:
        return Draft(office, subject, assemble(office, researcher, documents_opening(
            items, private, papers), items, papers, docs), lead_ids,
            withheld=egress.HANDOFF_WITHHELD)
    if provider is None:
        return Draft(office, subject, assemble(office, researcher, FALLBACK, items, papers,
                                               docs), lead_ids)
    records: dict[str, Record] = {short_work_id(w): w for w in papers}
    views = []
    for lead, rec in items:
        if isinstance(rec, Opportunity):
            records[rec.opportunity_number] = rec
            views.append(opportunity_view(rec, description_chars=800))
        else:
            records[lead_key(lead)] = lead  # the lead holds its code-written signal sentences
            views.append(org_view(lead, rec if isinstance(rec, Organisation) else None))
    prompt = (f"Researcher: {researcher.display_name}\nOffice: {office.name}\n\nLeads:\n"
              + "\n".join(views) + "\n\nPapers:\n" + "\n".join(work_view(w) for w in papers))
    for d in private or []:
        records[d.id] = d
        prompt += "\n\nPrivate document:\n" + work_view(d, abstract_chars=1500)

    def generate(feedback: list[str]) -> tuple[str, list[str]]:
        msg = prompt + ("\n\nYour previous answer was rejected: " + "; ".join(feedback)
                        + ". Fix these problems." if feedback else "")
        r = provider.chat([Message("user", msg)], system=SYSTEM, schema=SCHEMA, max_tokens=700)
        d = parse_json(r.text)
        return str(d["paragraph"]).strip(), [str(c).strip("[] ") for c in d["cited_ids"]]

    attempts = [0]

    def unparseable(errors: list[str]) -> None:
        attempts[0] += 1
        provider.log.validation(provider.last_call_id, SKILL, False, errors, attempts[0])

    def validate(v: tuple[str, list[str]]) -> Check:
        attempts[0] += 1
        text, cited = v
        errors = list(check(text, cited, records).errors)
        if m := EMPTY_CITE.search(text):  # F7: "[]", "[No papers provided]"
            errors.append(f"the paragraph says {m.group(0)!r}: cite only records you were given")
        for g in BRACKETED.findall(text):
            keys = [k.strip() for k in g.split(",")]
            if not all(k in records or egress.is_private_id(k) for k in keys):
                errors.append(f"the bracket [{g}] names no record you were given")
        if m := BANNED.search(text):
            errors.append(f"the paragraph says {m.group(0)!r}; describe fit only")
        n = sentences(text)
        if not 2 <= n <= 4:
            errors.append(f"write 2 to 4 sentences, got {n}")
        provider.log.validation(provider.last_call_id, SKILL, not errors, errors, attempts[0])
        return Check(not errors, errors)

    v = generate_validated(generate, validate, unparseable)
    if v.value is None:
        return Draft(office, subject, assemble(office, researcher, FALLBACK, items, papers,
                                               docs), lead_ids, flagged=True, errors=v.errors,
                     model=provider.model)
    text, cited = v.value
    text = plain_citations(text, records, set(records))  # every record given is listed below
    if egress.uses_private(cited) and masker is None:
        return Draft(office, subject, assemble(office, researcher, FALLBACK, items, papers,
                                               docs), lead_ids, cited_ids=cited,
                     model=provider.model, flagged=True, errors=[egress.WITHHELD])
    released = (egress.release_model(text, cited, masker, bool(private)) if private
                else egress.release(text, cited, masker))
    return Draft(office, subject, assemble(office, researcher, released or FALLBACK, items,
                                           papers, docs), lead_ids, cited_ids=cited,
                 model=provider.model, opening_by="model" if released else "code")
