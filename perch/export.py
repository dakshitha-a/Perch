"""Brief export as Markdown and as a print-ready HTML page (SPEC section 3).

Written by code from stored records; no model runs here. Model text that is already in
the brief (the profile summary, fit explanations) is copied with a "Model" label, as on
screen. The HTML page has no scripts beyond a print button; the browser's "Save as PDF"
makes the PDF, so Perch needs no PDF library (docs/DECISIONS.md, S12).

Both formats are built from one list of blocks, so they always say the same thing.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date

from perch import datefmt, egress
from perch.compare import COLUMNS, Row, award_size, lower_first
from perch.offices import RESEARCH_SECURITY, for_route
from perch.schemas import Brief, Lead, Opportunity, Organisation, Researcher, Scholarship, Work
from perch.score import band, match_text
from perch.sources import grants_gov, temple

# The Industry tab's note (web/app.js), word for word (R18).
# T18: a brief from documents alone has no industry search; the tab and the export say why.
INDUSTRY_NEEDS_PAPERS = ("Industry leads need public papers: Perch finds companies through the "
                         "works that cite yours, and this brief has none. Add your OpenAlex ID "
                         "to see them.")
INDUSTRY_NOTE = ("Inferred from public signals; not verified. A company that cites or works "
                 "near your research may have no interest in funding it. SBIR/STTR covers NIH "
                 "awards only.")


@dataclass
class Block:
    kind: str  # h1, h2, h3, p, note, model, list, table, link
    text: str = ""
    items: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    href: str | None = None


def _money(o: Opportunity) -> str:
    return award_size(o) or "Not in the record"  # the card's words (Q2)


# How a document is named in an export's model text, in place of its private id (Q10).
DOCUMENTS = {"proposal": "your draft proposal", "direction": "your research direction",
             "manuscript": "your unpublished work", "cv": "your CV",
             "interests": "your interests note", "achievement": "your achievements",
             "achievements": "your achievements"}
WORK_ID = re.compile(r"\b(W\d{5,})\b|\b(private:[a-z]+)(?:-[a-z0-9]+)?(?:#\d+)?")
GROUP = re.compile(r"\s?\[([^\[\]]+)\]")
MASK_LABEL = re.compile(r"(?:EMAIL|ORCID|PHONE|AWARD|URL|PERSON|INSTITUTION|PRIVATE-PHRASE|"
                        r"CV-VALUE)-\d+")  # the Masker's placeholders (perch.egress)
PRIVATE_KEY = re.compile(r"(?:private:)?([a-z]+)(-[a-z0-9]+)?(?:#\d+)?")
# "Cited work: W1 developed a tool [W1]": the bracket repeats the clause's subject (R9).
REPEAT = re.compile(r"\b(?P<id>W\d{5,}|private:(?P<k>[a-z]+(?:-[a-z0-9]+)?))\b(?P<mid>[^\[\];]*?)"
                    r"\s*\[(?:(?P=id)|(?P=k))\]")


# F2: a card's citation of its own record that stands in the sentence as a noun ("the aims
# of [26-523].") reads "this opportunity"; dropped, it left "the aims of.". web/format.js
# ownInPlace is the same rule for the cards.
OWN_PHRASE = "this opportunity"
DANGLE = re.compile(r"(?P<lead>\b(?:of|in|with|by|for|to|from|at|on|into|about|under|than|as|"
                    r"via|within|across|through|towards?|and|or)\s+)?(?:(?P<art>the|a|an)\s+)?"
                    r"\[(?P<ids>[^\[\]]+)\]", re.I)


def own_in_place(text: str, own: set[str]) -> str:
    """Where a citation of the card's own record (`own`) follows a preposition or an article,
    it becomes "this opportunity" (the article goes); other cited keys stay bracketed."""
    if not own or not text:
        return text

    def swap(m: re.Match) -> str:
        if not (m.group("lead") or m.group("art")):
            return m.group(0)
        keys = [k.strip() for k in re.split(r"[,;]", m.group("ids")) if k.strip()]

        def mine(k: str) -> bool:
            return k in own or k.removeprefix("grants_gov:") in own

        if not any(map(mine, keys)):
            return m.group(0)
        rest = [k for k in keys if not mine(k)]
        return f"{m.group('lead') or ''}{OWN_PHRASE}" + (f" [{', '.join(rest)}]" if rest else "")

    return DANGLE.sub(swap, text)


def _paper(w: Work | None, inline: bool, said: set[str] | None = None) -> str:
    if w is None:
        return "a paper on file"
    if said is not None:  # G21: after its first mention in a lead, a paper's short title
        if w.id in said:
            words = (w.title or "").split()
            return f"\u201c{' '.join(words[:5])}{'…' if len(words) > 5 else ''}\u201d"
        said.add(w.id)
    if inline:
        return f"\u201c{w.title}\u201d" + (f", {w.publication_year}" if w.publication_year else "")
    return f"\u201c{w.title}\u201d" + (f" ({w.publication_year})" if w.publication_year else "")


def _document(key: str) -> str | None:
    m = PRIVATE_KEY.fullmatch(key)
    if not m or m.group(1) not in DOCUMENTS:
        return "your document" if key.startswith("private:") else None
    if m.group(1) == "achievement" and m.group(2):
        return "one of your achievements"
    return DOCUMENTS[m.group(1)]


def _cite(key: str, works: dict[str, Work], names: dict[str, str],
          said: set[str] | None = None) -> str:
    """One cited id as the screen names it: a paper by title and year, a document by its
    kind, an option by its name, an opportunity by its number (R9)."""
    if re.fullmatch(r"W\d{5,}", key):
        return _paper(works.get(f"https://openalex.org/{key}"), inline=True, said=said)
    if key in names or key.rsplit(":", 1)[-1] in names:
        return names.get(key) or names[key.rsplit(":", 1)[-1]]
    if (doc := _document(key)) is not None:
        return doc
    return key.removeprefix("grants_gov:")


def name_papers(text: str | None, works: dict[str, Work], names: dict[str, str] | None = None,
                skip: set[str] = frozenset(), said: set[str] | None = None) -> str | None:
    """Model text with citations rendered as the screen renders them (Q10, R9): each
    OpenAlex work by its title and year, each private id by its kind of document (never by
    its title), a student option by its name, an opportunity by its number. A bracket
    group of keys reads as one parenthesis; a group that only repeats the clause's subject,
    or cites the lead's own record (`skip`), goes, as on the card. Masked labels such as
    [PRIVATE-PHRASE-1] stay."""
    if not text:
        return text
    names = names or {}
    text = own_in_place(text, set(skip))
    text = REPEAT.sub(lambda m: m.group(0)[:m.start("mid") - m.start()] + m.group("mid"), text)

    def group(m: re.Match) -> str:
        keys = [k.strip() for k in re.split(r"[,;]", m.group(1)) if k.strip()]
        if any(MASK_LABEL.fullmatch(k) for k in keys):
            return m.group(0)
        before = m.string[:m.start()].rstrip()
        subject = not before or before.endswith((".", "!", "?", ":"))
        # The lead's own record goes, except as a sentence's subject, where it is named
        keep = keys if subject else [k for k in keys if k not in skip
                                     and k.removeprefix("grants_gov:") not in skip]
        if not keep:
            return ""
        named = "; ".join(dict.fromkeys(_cite(k, works, names, said) for k in keep))
        if subject:  # the sentence's subject
            return m.group(0)[:len(m.group(0)) - len(m.group(0).lstrip())] + named
        return f" ({named})"

    text = GROUP.sub(group, text).lstrip()

    def named(m: re.Match) -> str:
        if m.group(1):
            return _paper(works.get(f"https://openalex.org/{m.group(1)}"), inline=False,
                          said=said)
        return _document(m.group(0)) or "your document"

    return WORK_ID.sub(named, text)


def labelled(label: str, text: str | None) -> Block:
    """A labelled model text, or one note when it is withheld (Q24): never
    "Inference: Withheld: ...". """
    if text == egress.WITHHELD:
        return Block("note", f"{label} withheld: {egress.WITHHELD.removeprefix('Withheld: ')}")
    return Block("model", f"{label}: {text}")


def _day(v: date | str | None) -> str:
    """A date as the screen writes it, "31 Oct 2026" (perch.datefmt.day, Q21)."""
    if v is None:
        return "Not in the record"
    return datefmt.day(date.fromisoformat(v) if isinstance(v, str) else v)


def _work(w: Work) -> str:
    year = f" ({w.publication_year})" if w.publication_year else ""
    venue = f". {w.venue}" if w.venue else ""
    return f"{w.title}{year}{venue}. {w.doi or w.source_url}"


def blocks(brief: Brief, researcher: Researcher | None, leads: list[Lead],
           opps: dict[str, Opportunity], orgs: dict[str, Organisation],
           works: dict[str, Work], compare_rows: list[Row],
           masker: egress.Masker | None = None, documents: bool = False) -> list[Block]:
    """Private-derived text is withheld unless a masker is given (perch.egress).
    `documents`: the session holds documents, so every model text counts as private."""
    name = researcher.display_name if researcher else brief.researcher_id
    if brief.researcher_id.startswith("private:"):  # F27: a brief from documents alone
        name = "your documents"
    as_of = brief.options.get("as_of") or date.today().isoformat()
    built = ("Built by Perch from your documents and public records" if documents
             else "Built from public records by Perch")  # Q24
    out = [Block("h1", f"Perch brief: {name}"),
           Block("p", f"Brief as of {_day(as_of)}. {built}. Every date and amount is copied "
                      "from the linked record. A brief is a starting point, not advice.")]
    docs_only = brief.researcher_id.startswith("private:")
    if researcher and not docs_only:  # G16: a documents brief has no public record to link
        out.append(Block("link", f"Researcher record ({researcher.source})",
                         href=researcher.id if researcher.id.startswith("https://")
                         else researcher.source_url))

    if not docs_only or brief.summary or brief.topics:
        out.append(Block("h2", "Research profile"))
    if brief.summary:
        out.append(Block("model", egress.release_model(name_papers(brief.summary, works), [],
                                                       masker, documents)))
    if brief.topics:
        if documents and masker is None:
            out.append(labelled("Topics", egress.WITHHELD))
        else:
            out.append(Block("list", items=[egress.release_model(t, [], masker, documents)
                                            for t in brief.topics]))
    if not docs_only:  # G16: no award search ran, and the screen hides the horizon
        out.append(Block("p", "Public award horizon (end date of the last public award): "
                         + (_day(brief.award_horizon) if brief.award_horizon
                            else "no public award found")))

    kept = [x for x in leads if x.status == "kept"]
    if compare_rows:
        out.append(Block("h2", f"Kept leads compared ({len(compare_rows)})"))
        cols = [c for c in COLUMNS if c[0] != "office"]
        table = [["Lead", *[lbl for _, lbl in cols], "Office"]]
        for r in compare_rows:
            # /compare gives the close date as ISO text, which the screen formats (R1).
            table.append([f"{'Industry' if r.route == 'B' else 'Grant'}: {r.title}",
                          *[datefmt.shown(r.cells[k].text) if k == "closes" else r.cells[k].text
                            for k, _ in cols], r.cells["office"].text])
        out.append(Block("table", rows=table))

    shown = [x for x in leads if x.status != "dismissed"]
    gone = [x for x in leads if x.status == "dismissed"]
    a = [x for x in shown if x.route == "A" and x.record_id in opps]
    b = [x for x in shown if x.route == "B"]
    out.append(Block("h2", f"Grants ({len(a)})"))
    if not a:
        out.append(Block("p", "No open opportunity passed the eligibility check."))
    if n := sum(x.route == "A" for x in gone):  # numbered 1 to n, with no gaps (Q11)
        out.append(Block("p", f"{n} dismissed {'lead is' if n == 1 else 'leads are'} left out."))
    for i, x in enumerate(a, 1):
        o = opps[x.record_id]
        mark = ", kept" if x.status == "kept" else ""  # G21
        out.append(Block("h3", f"{i}. {o.opportunity_number}: {o.title}{mark}"))
        # The card's rule (U3, T17, F3): the record's words for a placeholder date, and
        # "Expires <date>" for a parent announcement.
        closes = datefmt.closes(o, date.fromisoformat(as_of)) or "Not in the record"
        out.append(Block("list", items=[
            f"Agency: {o.agency_label()}", f"Closes: {closes}", f"Money: {_money(o)}",
            f"Activity code: {o.activity_code or 'Not in the record'}",
            f"Office: {for_route('A').name}"]))
        if x.explanation and not x.flagged:
            own = {o.id, o.opportunity_number}  # the card drops its own record's citation
            said: set[str] = set()  # G21: a paper's full title once per lead
            out.append(Block("model", egress.release_model(
                name_papers(x.explanation, works, skip=own, said=said), x.cited_ids, masker,
                documents)))
            if x.inference:
                out.append(labelled("Inference", egress.release_model(
                    name_papers(x.inference, works, skip=own, said=said), x.cited_ids,
                    masker, documents)))
        elif x.flagged:
            out.append(Block("note", "The explanation was withheld: it failed the checks twice."))
        cited = egress.public_only(works[f"https://openalex.org/{c}"] for c in x.cited_ids
                                   if f"https://openalex.org/{c}" in works)
        if cited:
            out.append(Block("list", items=[f"Cites: {_work(w)}" for w in cited]))
        out.append(Block("link", f"Record: Grants.gov {o.opportunity_number}", href=o.source_url))

    # A brief with no public papers has no industry search: no empty section (R18).
    skipped = any(s.name == "route_b" and s.status == "skipped" for s in brief.stages)
    if skipped and not b and not any(x.route == "B" for x in gone):  # T18: the tab's line
        out.append(Block("h2", "Industry leads"))
        out.append(Block("p", INDUSTRY_NEEDS_PAPERS))
    else:
        out.append(Block("h2", f"Industry leads ({len(b)})"))
        out.append(Block("note", INDUSTRY_NOTE))  # the Industry tab's words (R18)
        out.append(Block("note", RESEARCH_SECURITY))
    if not b and not skipped:
        out.append(Block("p", "No company had two kinds of public signal."))
    if n := sum(x.route == "B" for x in gone):
        out.append(Block("p", f"{n} dismissed {'lead is' if n == 1 else 'leads are'} left out."))
    for i, x in enumerate(b, 1):
        org = orgs.get(x.record_id)
        nm = org.name if org else x.record_id
        mark = ", kept" if x.status == "kept" else ""  # G21
        out.append(Block("h3", f"{i}. {nm}{mark}"))
        items = [f"Suggested relationship, by rule: {x.relationship}"] if x.relationship else []
        items.append(f"Office: {for_route('B').name}")
        out.append(Block("list", items=items))
        if x.explanation:
            out.append(Block("p", x.explanation))
        if org:
            src = {"openalex": "OpenAlex"}.get(org.source, org.source)  # T20
            out.append(Block("link", f"Record: {src} organization", href=org.id
                             if org.id.startswith("https://") else org.source_url))

    out.append(Block("h2", "About this export"))
    out.append(Block("p", f"{len(kept)} kept, {len(shown)} shown"
                     + (f", {len(gone)} dismissed" if gone else "") + ". Text marked Model was "
                     "written by a language model and checked against the records it cites."))
    out.append(Block("p", grants_gov.ATTRIBUTION))
    return _count_withheld(out, documents and masker is None)


def is_withheld(b: Block) -> bool:
    """A Withheld line: a withheld model text, or one labelled note (Q24)."""
    return (b.kind == "model" and b.text == egress.WITHHELD) or (
        b.kind == "note" and b.text.endswith(egress.WITHHELD.removeprefix("Withheld: "))
        and " withheld: " in b.text)


def _count_withheld(out: list[Block], banner: bool) -> list[Block]:
    """The banner under the opening states how many Withheld lines follow, counted from
    the lines themselves: the summary, the topics, each explanation and inference (R10)."""
    if banner and (n := sum(map(is_withheld, out))):
        out.insert(2, Block("note", egress.withheld_note(n)))
    return out


SAMPLE_BANNER = ("SAMPLE DATA: the Scholarships section lists invented records from a "
                 "SYNTHETIC test corpus. They are not real scholarships. Do not apply to them.")


def _amount(s: Scholarship) -> str:
    if s.amount_min is not None and s.amount_max is not None and s.amount_min != s.amount_max:
        return f"${s.amount_min:,.0f} to ${s.amount_max:,.0f}"
    if s.amount_max is not None:
        return f"${s.amount_max:,.0f}"
    return "Not in the record"


def _withheld(brief: Brief | None, leads: list[Lead]) -> int:
    """Model texts a documents session leaves out of the JSON export: the summary, the
    topics, and each explanation and inference (R10)."""
    return (bool(brief and brief.summary) + bool(brief and brief.topics)
            + sum(bool(x.explanation and not x.flagged) + bool(x.inference and x.explanation
                                                                and not x.flagged)
                  for x in leads if x.status != "dismissed" and x.route != "B"))


def _source_name(rec: object) -> str:
    """A record link's text, as the researcher export names it (R19): never the bare URL."""
    if isinstance(rec, Opportunity):
        return f"Grants.gov {rec.opportunity_number}"
    from urllib.parse import urlparse

    host = (urlparse(getattr(rec, "source_url", "") or "").hostname or "").removeprefix("www.")
    if getattr(rec, "source", None) == temple.SOURCE:
        name = "Temple Scholar Development and Fellowships Advising list"
        # T26: a listing on Temple's list whose link leaves Temple says where it goes
        return name if not host or host.endswith("temple.edu") else f"{name} (links to {host})"
    return host or "the listing"


def student_blocks(brief: Brief, leads: list[Lead], records: dict[str, object],
                   masker: egress.Masker | None = None, documents: bool = True) -> list[Block]:
    """A student brief (S18). Verdicts and gaps are code-written; the sample section
    carries the banner. Text drawn from the student's documents is withheld unless
    masked, as for every private export."""
    as_of = brief.options.get("as_of") or date.today().isoformat()
    shown = [x for x in leads if x.status != "dismissed"]
    gone = [x for x in leads if x.status == "dismissed"]
    kept = [x for x in leads if x.status == "kept"]
    out = [Block("h1", "Perch student brief (private)"),
           Block("p", f"Brief as of {_day(as_of)}. Eligibility is checked by rule from your CV; "
                      "\"may be eligible\" means Perch could not check everything. A brief is "
                      "a starting point, not advice.")]
    if any(x.sample for x in shown):
        out.append(Block("note", SAMPLE_BANNER))
    names = {}  # a cited option reads as its name, as on the card (R9)
    for rid, rec in records.items():
        nm = getattr(rec, "name", None) or getattr(rec, "title", None)
        if nm:
            names[rid] = names[rid.rsplit(":", 1)[-1]] = (
                f"{nm} (sample)" if rid.startswith("sample:") else nm)
    # F17, F27: each route as the screen shows it: the options you may apply for, the
    # lines most cards share said once, then the ones not eligible by rule.
    for route, title, office in (("F", "Fellowships, public", for_route("F")),
                                 ("S", "Scholarships and awards, sample", for_route("S"))):
        xs = sorted((x for x in shown if x.route == route), key=lambda x: x.rank or 0)
        ok = [x for x in xs if x.verdict != "not eligible"]
        no = [x for x in xs if x.verdict == "not eligible"]
        out.append(Block("h2", f"{title} ({len(ok)})"))
        if route == "S":
            out.append(Block("note", SAMPLE_BANNER))
        if n := sum(x.route == route for x in gone):  # numbered 1 to n, as Q11 (R8)
            out.append(Block("p", f"{n} dismissed {'option is' if n == 1 else 'options are'} "
                                  "left out."))
        common = _common_lines(ok, records)
        if common:
            out.append(Block("p", "Unless an option says otherwise:"))
            out.append(Block("list", items=[NO_FACTS_LINE if c == NO_FACTS else
                                            egress.release_cv_line(c, masker) for c in common]))
        for i, x in enumerate(ok, 1):
            out += _student_option(i, x, records.get(x.record_id), office, names, common,
                                   masker, documents)
        if no:  # G14: one line each, so a student can print what matters
            out.append(Block("h2", f"{title}: not eligible by rule ({len(no)})"))
            out.append(Block("p", "One line each: the option, the rule it does not meet, and "
                                  "its Match."))
            out.append(Block("list", items=[_not_eligible_line(x, records.get(x.record_id),
                                                               masker) for x in no]))
    out.append(Block("h2", "About this export"))
    out.append(Block("p", f"{len(kept)} kept, {len(shown)} shown"
                     + (f", {len(gone)} dismissed" if gone else "") + ". Text marked Model was "
                     "written by a language model and checked against the records it cites."))
    out.append(Block("p", grants_gov.ATTRIBUTION))
    return _count_withheld(out, documents and masker is None)


def bare_findings_out(text: str) -> str:
    """G21: masked, a finding can be only "one of your achievements [PRIVATE-PHRASE-1]",
    the same on every option. Such findings go, and the "Cited work:" tail with them when
    none is left."""
    head, sep, tail = text.partition(" Cited work: ")
    if not sep:
        return text
    names = {"one of your achievements", *(d.lower() for d in DOCUMENTS.values())}
    keep = [f for f in tail.rstrip(".").split("; ") if re.sub(r"\W+", " ", re.sub(
        r"\[(?:" + MASK_LABEL.pattern + r")\]", " ", f)).strip().lower() not in names]
    return head + (sep + "; ".join(keep) + "." if keep else "")


def _not_eligible_line(x: Lead, rec: object, masker: egress.Masker | None) -> str:
    name = getattr(rec, "name", None) or getattr(rec, "title", None) or x.record_id
    head = (f"{name}{' [SAMPLE]' if x.sample else ''}{', kept' if x.status == 'kept' else ''}")
    rule = " ".join(egress.release_cv_line(v, masker) for v in x.verdict_lines)
    m = match_text(x.match_score)
    return f"{head}: {rule}" + (f" {m}." if m else "")


NO_FACTS = "no-facts"
NO_FACTS_LINE = "The listing states no deadline or amount."


def _facts_stated(rec: object) -> bool:
    if isinstance(rec, Scholarship):
        return bool(rec.deadline) or _amount(rec) != "Not in the record"
    return bool(getattr(rec, "close_date", None))


def _common_lines(xs: list[Lead], records: dict[str, object]) -> list[str]:
    """The screen's rule (web/student.js, U20): a line at least three cards and more than
    half of them repeat word for word is said once above the list."""
    if len(xs) < 3:
        return []
    counts: dict[str, int] = {}
    for x in xs:
        lines = {NO_FACTS} if not _facts_stated(records.get(x.record_id)) else set()
        if len(x.verdict_lines) == 1:
            lines.add(x.verdict_lines[0])
        for c in lines:
            counts[c] = counts.get(c, 0) + 1
    return [c for c, n in counts.items() if n >= 3 and n > len(xs) / 2]


def you(text: str) -> str:
    """web/student.js you(): the card says "you" where the model said "the student"."""
    text = re.sub(r"\b([Tt])he student's\b", lambda m: "Your" if m.group(1) == "T" else "your",
                  text)
    return re.sub(r"\b([Tt])he student\b", lambda m: "You" if m.group(1) == "T" else "you", text)


def _student_option(i: int, x: Lead, rec: object, office: object, names: dict[str, str],
                    common: list[str], masker: egress.Masker | None,
                    documents: bool) -> list[Block]:
    name = getattr(rec, "name", None) or getattr(rec, "title", x.record_id)
    mark = ", kept" if x.status == "kept" else ""  # G21: "(Parent F31), kept"
    badge = " [SAMPLE]" if x.sample else ""
    out = [Block("h3", f"{i}. {name}{badge}{mark}")]
    # The verdict, its rule lines and the gaps are written by code from the rules and the
    # record: they stay; only model text is withheld (Q12). A value a rule read from the CV
    # is dropped, or masked on opt-in (Q42).
    lines = [] if len(x.verdict_lines) == 1 and x.verdict_lines[0] in common \
        else x.verdict_lines
    items = [f"Verdict: {x.verdict}", *(egress.release_cv_line(v, masker) for v in lines)]
    if isinstance(rec, Scholarship) and rec.sponsor:
        items.append(f"Sponsor: {rec.sponsor}")
    if not _facts_stated(rec):
        if NO_FACTS not in common:
            items.append(NO_FACTS_LINE)
    elif isinstance(rec, Scholarship):
        items.append(f"Deadline: {_day(rec.deadline) if rec.deadline else 'Not in the record'}")
        items.append(f"Amount: {_amount(rec)}")
    elif isinstance(rec, Opportunity):  # F3: one rule for every deadline, as the card
        label = "Announcement" if datefmt.expires_only(rec) else "Deadline"  # G17, F20
        items.append(f"{label}: {datefmt.closes(rec) or 'Not in the record'}")
    if x.gaps:  # G21: one line, as the card writes it ("a transcript; an essay")
        items.append("Still needed: " + "; ".join(
            lower_first(egress.release_cv_line(g, masker)) for g in x.gaps))
    items.append(f"Office: {office.name}")  # type: ignore[attr-defined]
    out.append(Block("list", items=[i for i in items if i]))
    own = {x.record_id, x.record_id.rsplit(":", 1)[-1]}  # F4: no own-record parenthesis
    if x.flagged:  # G15: as the card and the researcher export say
        out.append(Block("note", "The explanation was withheld: it failed the checks twice."))
    if x.explanation and not x.flagged:
        out.append(Block("model", bare_findings_out(egress.release_model(
            name_papers(x.explanation, {}, names, skip=own), x.cited_ids, masker, documents))))
        if x.inference:  # F4: the fit sentence under the card's label, worded as the card
            label = "How it relates" if band(x.match_score) == "weak" else "Why it may fit"
            out.append(labelled(label, egress.release_model(
                name_papers(you(x.inference), {}, names, skip=own), x.cited_ids, masker,
                documents)))
    url = getattr(rec, "source_url", None)
    if url and not x.sample:
        out.append(Block("link", f"Record: {_source_name(rec)}", href=url))
    elif x.sample:
        out.append(Block("p", f"Record: {x.record_id} (SYNTHETIC sample, no web page)"))
    return out


def _md_text(s: str) -> str:
    """Record or model text as Markdown that renders as the same text (review S15): one
    line, so it cannot leave its quote or list item, and no link, image or HTML of its
    own. Brackets, angle brackets and backslashes are escaped; so is a leading # or >."""
    s = " ".join((s or "").split())
    s = s.replace("\\", "\\\\")
    for ch in "[]<>`":
        s = s.replace(ch, "\\" + ch)
    return "\\" + s if s[:1] in ("#", ">") else s


def _md_escape(s: str) -> str:
    return _md_text(s).replace("|", "\\|")


def to_markdown(bs: list[Block]) -> str:
    lines: list[str] = []
    for b in bs:
        t = _md_text(b.text)
        if b.kind in ("h1", "h2", "h3"):
            lines += ["#" * int(b.kind[1]) + " " + t, ""]
        elif b.kind == "p":
            lines += [t, ""]
        elif b.kind == "note":
            lines += [f"> {t}", ""]
        elif b.kind == "model":
            lines += [f"> **Model:** {t}", ""]
        elif b.kind == "list":
            lines += [f"- {_md_text(i)}" for i in b.items] + [""]
        elif b.kind == "link":
            href = b.href or ""
            ok = href.startswith(("https://", "http://")) and not any(c in href for c in " <>()")
            lines += [f"[{t}]({href})" if ok else t, ""]
        elif b.kind == "table":
            head, *body = b.rows
            lines.append("| " + " | ".join(_md_escape(c) for c in head) + " |")
            lines.append("|" + "---|" * len(head))
            lines += ["| " + " | ".join(_md_escape(c) for c in r) + " |" for r in body]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


CSS = """
:root { color-scheme: light; }
body { font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: #1F2B2D;
  background: #fff; max-width: 820px; margin: 24px auto; padding: 0 16px; }
h1 { font: 600 28px/1.2 Georgia, serif; }
h2 { margin-top: 28px; border-bottom: 1px solid #D8DED7; }
h3 { margin-bottom: 4px; } a { color: #2E6A54; word-break: break-all; }
blockquote { margin: 8px 0; padding: 8px 12px; background: #F3F5F1;
  border-left: 3px solid #A9B6AC; }
blockquote.model { background: #ECEBF5; border-color: #5B5A86; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid #D8DED7; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #E9EDE7; } .tw { overflow-x: auto; }
table { min-width: 560px; }
.print { margin: 8px 0 16px; padding: 10px 16px; font-size: 15px; }
@media print { .print { display: none; } .tw { overflow: visible; } table { min-width: 0; }
  body { margin: 0; max-width: none; }
  h2, h3 { break-after: avoid; } table, blockquote { break-inside: avoid; } }
"""


# The print button's one script. No inline handler: the app's Content-Security-Policy
# allows this script and the CSS above by their hashes only (review S11), and a blob:
# page opened from the app inherits that policy.
PRINT_JS = 'document.querySelector(".print").addEventListener("click", () => window.print());'


def csp_hash(text: str) -> str:
    import base64
    import hashlib

    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def to_html(bs: list[Block], title: str) -> str:
    e = html.escape
    parts = [f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
             f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
             f"<title>{e(title)}</title><style>{CSS}</style></head><body>",
             "<main><button class=\"print\" type=\"button\">Print or save as PDF</button>"]
    for b in bs:
        if b.kind in ("h1", "h2", "h3"):
            parts.append(f"<{b.kind}>{e(b.text)}</{b.kind}>")
        elif b.kind == "p":
            parts.append(f"<p>{e(b.text)}</p>")
        elif b.kind == "note":
            parts.append(f"<blockquote>{e(b.text)}</blockquote>")
        elif b.kind == "model":
            parts.append(f"<blockquote class=\"model\"><b>Model:</b> {e(b.text)}</blockquote>")
        elif b.kind == "list":
            parts.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in b.items) + "</ul>")
        elif b.kind == "link":
            href = b.href or ""
            parts.append(f"<p><a href=\"{e(href)}\">{e(b.text)}</a></p>"
                         if href.startswith(("https://", "http://")) else f"<p>{e(b.text)}</p>")
        elif b.kind == "table":
            head, *body = b.rows
            parts.append("<div class=\"tw\"><table><thead><tr>"
                         + "".join(f"<th>{e(c)}</th>" for c in head)
                         + "</tr></thead><tbody>"
                         + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in r) + "</tr>"
                                   for r in body) + "</tbody></table></div>")
    parts.append(f"</main><script>{PRINT_JS}</script></body></html>")
    return "\n".join(parts)
