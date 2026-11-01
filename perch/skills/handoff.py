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
from perch.compare import award_size
from perch.llm import Message
from perch.llm.audit import AuditedProvider
from perch.offices import Office
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


# Inline citations a model adds anyway, e.g. " [W123, PAR-26-121]".
BRACKETED = re.compile(r"\s*\[(?:[A-Z]+[\w-]*\d[\w-]*)(?:\s*,\s*[A-Z]+[\w-]*\d[\w-]*)*\]")


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
    return f"award size {size[0].lower()}{size[1:]}" if size else \
        "award size not stated in the record"


def lead_lines(items: list[tuple[Lead, Record | None]]) -> list[str]:
    """The code-written list: every date and amount copied from the lead's record."""
    out = []
    for i, (lead, rec) in enumerate(items, 1):
        if isinstance(rec, Opportunity):
            closes = ("close date not stated in the record" if not rec.close_date
                      # the card's rule: a placeholder date reads as the record's words (U3)
                      else rec.close_date_note or "" if datefmt.placeholder_close(rec)
                      else f"closes {datefmt.day(rec.close_date)}")  # as the cards say (U14)
            code = (f" ({rec.activity_code})" if rec.activity_code
                    and rec.activity_code not in rec.title else "")
            out.append(f"{i}. {rec.opportunity_number}: {rec.title}{code}. {rec.agency_label()}; "
                       f"{closes}; {_money(rec)}.\n   Record: {rec.source_url}")
        elif isinstance(rec, Organisation):
            rel = f" Suggested relationship, by rule: {lead.relationship}." \
                if lead.relationship else ""
            link = rec.id if rec.id.startswith("https://openalex.org/") else rec.source_url
            out.append(f"{i}. {rec.name}: industry lead, inferred from public signals and not "
                       f"verified. {lead.explanation or ''}{rel}\n   Record: {link}")
        else:
            out.append(f"{i}. {lead.record_id}")
    return out


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
             items: list[tuple[Lead, Record | None]], papers: list[Work]) -> str:
    blocks = [f"Dear {office.name} team,", opening,
              "These are the leads I kept in Perch:", "\n".join(lead_lines(items))]
    if papers:
        blocks += ["The papers they draw on:", "\n".join(paper_lines(papers))]
    note = ("Perch drafted this from public records. Each date and amount above is copied "
            "from the linked record.")
    if any(x.route == "B" for x, _ in items):
        note += " Industry leads are inferences from public signals, not verified interest."
    blocks += [note,
               f"Best regards,\n{researcher.display_name}"]
    return "\n\n".join(blocks)


FALLBACK = "I would like to talk with your team about the funding leads listed below."


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
    if provider is not None and private and masker is None:
        return Draft(office, subject, assemble(office, researcher, FALLBACK, items, papers),
                     lead_ids, withheld=egress.HANDOFF_WITHHELD)
    if provider is None:
        return Draft(office, subject, assemble(office, researcher, FALLBACK, items, papers),
                     lead_ids)
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
        if m := BANNED.search(text):
            errors.append(f"the paragraph says {m.group(0)!r}; describe fit only")
        n = sentences(text)
        if not 2 <= n <= 4:
            errors.append(f"write 2 to 4 sentences, got {n}")
        provider.log.validation(provider.last_call_id, SKILL, not errors, errors, attempts[0])
        return Check(not errors, errors)

    v = generate_validated(generate, validate, unparseable)
    if v.value is None:
        return Draft(office, subject, assemble(office, researcher, FALLBACK, items, papers),
                     lead_ids, flagged=True, errors=v.errors, model=provider.model)
    text, cited = v.value
    text = BRACKETED.sub("", text)  # ids are for the validator, not the reader
    if egress.uses_private(cited) and masker is None:
        return Draft(office, subject, assemble(office, researcher, FALLBACK, items, papers),
                     lead_ids, cited_ids=cited, model=provider.model, flagged=True,
                     errors=[egress.WITHHELD])
    text = (egress.release_model(text, cited, masker, bool(private)) if private
            else egress.release(text, cited, masker)) or FALLBACK
    return Draft(office, subject, assemble(office, researcher, text, items, papers), lead_ids,
                 cited_ids=cited, model=provider.model)
