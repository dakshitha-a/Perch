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
from perch.compare import COLUMNS, Row, award_size
from perch.offices import for_route
from perch.schemas import Brief, Lead, Opportunity, Organisation, Researcher, Scholarship, Work
from perch.sources import grants_gov


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
             "interests": "your interests note", "achievement": "your achievements"}
WORK_ID = re.compile(r"\b(W\d{5,})\b|\b(private:[a-z]+)(?:-[a-z0-9]+)?(?:#\d+)?")


def name_papers(text: str | None, works: dict[str, Work]) -> str | None:
    """Model text with each OpenAlex work id named as the screen names it, by title and
    year, and each private id named by its kind of document, never by its title (Q10)."""
    if not text:
        return text

    def named(m: re.Match) -> str:
        if m.group(1):
            w = works.get(f"https://openalex.org/{m.group(1)}")
            if w is None:
                return m.group(0)
            year = f" ({w.publication_year})" if w.publication_year else ""
            return f"\u201c{w.title}\u201d{year}"
        kind = m.group(2).split(":", 1)[1]
        return DOCUMENTS.get(kind, "your document")

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
    as_of = brief.options.get("as_of") or date.today().isoformat()
    built = ("Built by Perch from your documents and public records" if documents
             else "Built from public records by Perch")  # Q24
    out = [Block("h1", f"Perch brief: {name}"),
           Block("p", f"Brief as of {_day(as_of)}. {built}. Every date and amount is copied "
                      "from the linked record. A brief is a starting point, not advice.")]
    if documents and masker is None and (n := _withheld(brief, leads)):
        out.append(Block("note", egress.withheld_note(n)))
    if researcher:
        out.append(Block("link", f"Researcher record ({researcher.source})",
                         href=researcher.id if researcher.id.startswith("https://")
                         else researcher.source_url))

    out.append(Block("h2", "Research profile"))
    if brief.summary:
        out.append(Block("model", egress.release_model(brief.summary, [], masker, documents)))
    if brief.topics:
        if documents and masker is None:
            out.append(labelled("Topics", egress.WITHHELD))
        else:
            out.append(Block("list", items=[egress.release_model(t, [], masker, documents)
                                            for t in brief.topics]))
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
        mark = " (kept)" if x.status == "kept" else ""
        out.append(Block("h3", f"{i}. {o.opportunity_number}: {o.title}{mark}"))
        far = datefmt.placeholder_close(o, date.fromisoformat(as_of))  # the card's rule (U3)
        closes = ("Not in the record" if not o.close_date
                  else o.close_date_note or "" if far else _day(o.close_date))
        out.append(Block("list", items=[
            f"Agency: {o.agency_label()}", f"Closes: {closes}", f"Money: {_money(o)}",
            f"Activity code: {o.activity_code or 'Not in the record'}",
            f"Office: {for_route('A').name}"]))
        if x.explanation and not x.flagged:
            out.append(Block("model", egress.release_model(
                name_papers(x.explanation, works), x.cited_ids, masker, documents)))
            if x.inference:
                out.append(labelled("Inference", egress.release_model(
                    name_papers(x.inference, works), x.cited_ids, masker, documents)))
        elif x.flagged:
            out.append(Block("note", "The explanation was withheld: it failed the checks twice."))
        cited = egress.public_only(works[f"https://openalex.org/{c}"] for c in x.cited_ids
                                   if f"https://openalex.org/{c}" in works)
        if cited:
            out.append(Block("list", items=[f"Cites: {_work(w)}" for w in cited]))
        out.append(Block("link", f"Record: Grants.gov {o.opportunity_number}", href=o.source_url))

    out.append(Block("h2", f"Industry leads ({len(b)})"))
    out.append(Block("note", "Inferred from public signals; not verified. NIH SBIR/STTR only."))
    if not b:
        out.append(Block("p", "No company had two kinds of public signal."))
    if n := sum(x.route == "B" for x in gone):
        out.append(Block("p", f"{n} dismissed {'lead is' if n == 1 else 'leads are'} left out."))
    for i, x in enumerate(b, 1):
        org = orgs.get(x.record_id)
        nm = org.name if org else x.record_id
        mark = " (kept)" if x.status == "kept" else ""
        out.append(Block("h3", f"{i}. {nm}{mark}"))
        items = [f"Suggested relationship, by rule: {x.relationship}"] if x.relationship else []
        items.append(f"Office: {for_route('B').name}")
        out.append(Block("list", items=items))
        if x.explanation:
            out.append(Block("p", x.explanation))
        if org:
            out.append(Block("link", f"Record: {org.source} organisation", href=org.id
                             if org.id.startswith("https://") else org.source_url))

    out.append(Block("h2", "About this export"))
    out.append(Block("p", f"{len(kept)} kept, {len(shown)} shown"
                     + (f", {len(gone)} dismissed" if gone else "") + ". Text marked Model was "
                     "written by a language model and checked against the records it cites."))
    out.append(Block("p", grants_gov.ATTRIBUTION))
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
    """Model texts a documents session leaves out: the summary and each explanation."""
    return (bool(brief and brief.summary)
            + sum(bool(x.explanation and not x.flagged) for x in leads
                  if x.status != "dismissed" and x.route != "B"))


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
    if documents and masker is None and (n := _withheld(None, shown)):
        out.append(Block("note", egress.withheld_note(n)))
    if any(x.sample for x in shown):
        out.append(Block("note", SAMPLE_BANNER))
    for route, title, office in (("F", "Fellowships (public)", for_route("F")),
                                 ("S", "Scholarships and awards (sample)", for_route("S"))):
        xs = sorted((x for x in shown if x.route == route), key=lambda x: x.rank or 0)
        out.append(Block("h2", f"{title} ({len(xs)})"))
        if route == "S":
            out.append(Block("note", SAMPLE_BANNER))
        if n := sum(x.route == route for x in gone):  # numbered 1 to n, as Q11 (R8)
            out.append(Block("p", f"{n} dismissed {'option is' if n == 1 else 'options are'} "
                                  "left out."))
        for i, x in enumerate(xs, 1):
            rec = records.get(x.record_id)
            name = getattr(rec, "name", None) or getattr(rec, "title", x.record_id)
            mark = " (kept)" if x.status == "kept" else ""
            badge = " [SAMPLE]" if x.sample else ""
            out.append(Block("h3", f"{i}. {name}{badge}{mark}"))
            # The verdict, its rule lines and the gaps are written by code from the rules
            # and the record: they are never withheld; only model text is (Q12).
            items = [f"Verdict: {x.verdict}", *x.verdict_lines]
            if isinstance(rec, Scholarship):
                items.append(f"Sponsor: {rec.sponsor or 'Not in the record'}")
                items.append(f"Deadline: {_day(rec.deadline)}")
                items.append(f"Amount: {_amount(rec)}")
            elif isinstance(rec, Opportunity):
                items.append(f"Closes: {_day(rec.close_date)}")
            items += [f"Still needed: {g}" for g in x.gaps]
            items.append(f"Office: {office.name}")
            out.append(Block("list", items=[i for i in items if i]))
            if x.explanation and not x.flagged:
                out.append(Block("model", egress.release_model(x.explanation, x.cited_ids,
                                                               masker, documents)))
            url = getattr(rec, "source_url", None)
            if url and not x.sample:
                out.append(Block("link", f"Record: {url}", href=url))
            elif x.sample:
                out.append(Block("p", f"Record: {x.record_id} (SYNTHETIC sample, no web page)"))
    out.append(Block("h2", "About this export"))
    out.append(Block("p", f"{len(kept)} kept, {len(shown)} shown"
                     + (f", {len(gone)} dismissed" if gone else "") + ". Text marked Model was "
                     "written by a language model and checked against the records it cites."))
    out.append(Block("p", grants_gov.ATTRIBUTION))
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
