"""Scout's tools for a student brief (S24; Q27 revised 2026-10-30).

A separate allowlist from the researcher's nine (perch.scout.tools), so researcher Scout
and the MCP server are unchanged. Every tool reads the session's student brief: its
leads, already checked against the CV by rule (perch.student), and their records. No tool
returns CV text; read_cv returns the fields the rules read. Notes are written by code,
as on the Compare tab. Sample records keep their `sample: true` flag and their
`sample:` ids, so an answer cannot pass one off as real.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from perch.compare import lower_first
from perch.datefmt import day, expires_only, no_deadline, placeholder_close
from perch.llm import Tool
from perch.schemas import Lead, Opportunity, Record, Scholarship
from perch.scout.tools import ScoutContext, ToolError, _obj, get_record, short_id

STUDENT_ALLOWLIST = ("search_options", "check_option", "explain_verdict", "read_cv",
                     "compare_options", "draft_note", "get_record")
ROUTES = {"F": "Fellowships (public)", "S": "Scholarships and awards (sample)"}
OFFICES = {"F": ("Scholar Development and Fellowships Advising",
                 "https://undergraduate.temple.edu/fellowships"),
           "S": ("Student Financial Services", "https://sfs.temple.edu/")}
NOT_STATED = "not stated in the record"


def _brief(ctx: ScoutContext) -> tuple[object, list[Lead]]:
    got = ctx.service.get(ctx.brief_id) if ctx.brief_id else None
    if not got or not got[0].options.get("student"):
        raise ToolError("no student brief in this session")
    return got[0], [x for x in got[1] if x.route in ROUTES]


def _record(ctx: ScoutContext, lead: Lead) -> Record | None:
    return record_of(ctx.service, lead)


def record_of(service: object, lead: Lead) -> Record | None:
    with service.repo() as r:
        return r.get(Scholarship, lead.record_id) or r.get(Opportunity, lead.record_id)


def facts_of(rec: Record | None) -> dict:
    """Deadline and amount, copied from the record or marked as not stated."""
    if isinstance(rec, Scholarship):
        amt = (f"${rec.amount_min:,.0f} to ${rec.amount_max:,.0f}"  # as the cards (T27)
               if rec.amount_min is not None and rec.amount_max is not None
               and rec.amount_min != rec.amount_max
               else f"${rec.amount_max:,.0f}" if rec.amount_max is not None
               else NOT_STATED)
        return {"title": rec.name, "sponsor": rec.sponsor,
                "deadline": day(rec.deadline) if rec.deadline else NOT_STATED,  # Q22
                "amount": amt}
    if isinstance(rec, Opportunity):
        out = {"title": rec.title, "sponsor": rec.agency,
               "amount": f"${rec.award_ceiling:,.0f}" if rec.award_ceiling else NOT_STATED}
        if rec.close_date and expires_only(rec):  # F3, T17: an expiry is not a deadline
            return {**out, "announcement_expires": day(rec.close_date)}
        if rec.close_date and placeholder_close(rec):  # the record's own words
            return {**out, "deadline": rec.close_date_note}
        return {**out, "deadline": day(rec.close_date) if rec.close_date else NOT_STATED}
    return {"title": None, "deadline": NOT_STATED, "amount": NOT_STATED}


def _row(ctx: ScoutContext, lead: Lead) -> dict:
    rec = _record(ctx, lead)
    facts = facts_of(rec)
    # G7: the id sits beside its own title, so a line cites its own row
    out = {"id": ctx.see(rec) if rec else lead.record_id, "title": facts.pop("title"),
           "route": ROUTES[lead.route], **facts, "verdict": lead.verdict,
           "kept": lead.status == "kept"}
    if lead.verdict != "eligible" and lead.verdict_lines:  # F6: the rule's reason, by code
        out["why"] = lead.verdict_lines[:2]
        ctx.facts[out["id"]] = [*lead.verdict_lines, *lead.gaps]
    if lead.sample:
        out["sample"] = True
        out["note"] = "SAMPLE record from a test corpus; not a real scholarship"
    return out


def _find(ctx: ScoutContext, option_id: str) -> Lead:
    _, leads = _brief(ctx)
    key = option_id.strip().strip("[]")
    for x in leads:
        if key in (x.id, x.record_id, x.record_id.rsplit("/", 1)[-1],
                   x.record_id.rsplit(":", 1)[-1]):
            return x
    raise ToolError(f"{option_id} is not an option in this brief: use an id from "
                    "search_options")


def search_options(ctx: ScoutContext, route: str = "all", verdict: str | None = None,
                   deadline_after: str | None = None, deadline_before: str | None = None,
                   min_amount: float | None = None, words: str | None = None,
                   sort: str = "match") -> dict:
    _, leads = _brief(ctx)
    used = search_words(words)
    after = date.fromisoformat(deadline_after) if deadline_after else None
    before = date.fromisoformat(deadline_before) if deadline_before else None
    rows, due_of, amount_of, undated = [], {}, {}, 0
    for x in sorted(leads, key=lambda x: (x.route, x.rank or 0)):
        if route != "all" and x.route != route:
            continue
        if verdict and x.verdict != verdict:
            continue
        if not verdict and x.verdict == "not eligible":
            continue
        rec = _record(ctx, x)
        due = (None if isinstance(rec, Opportunity) and no_deadline(rec)  # T17
               else getattr(rec, "deadline", None) or getattr(rec, "close_date", None))
        if (after or before) and due is None:
            undated += x.route == "F"
            continue
        if (after and due <= after) or (before and due >= before):
            continue
        top = getattr(rec, "amount_max", None) or getattr(rec, "award_ceiling", None)
        if min_amount is not None and (top is None or top < min_amount):
            continue
        where = None
        if used:  # T10: the card's own fit sentence counts, as the student reads it
            text = " ".join(str(v) for v in (facts_of(rec).get("title"),
                                             getattr(rec, "purpose", ""),
                                             getattr(rec, "description", ""))).lower()
            fit = (getattr(x, "inference", None) or "").lower()
            if any(w in text for w in used):  # any of the words (R7)
                where = "the listing"
            elif any(w in fit for w in used):
                where = "its fit sentence on the card"
            else:
                continue
        extra_row = {"words_found_in": where} if where else {}
        if where and where.startswith("its fit"):  # the sentence itself, without its ids
            extra_row["fit_sentence"] = " ".join(re.sub(r"\s*\[[^\[\]]*\]", "",
                                                        x.inference).split())
        rows.append({**_row(ctx, x), **extra_row})
        due_of[rows[-1]["id"]] = due
        amount_of[rows[-1]["id"]] = top
    if sort == "deadline":  # the soonest first, undated last, as Q14 for researchers (R13)
        rows.sort(key=lambda r: (due_of[r["id"]] is None, due_of[r["id"]] or date.max))
    elif sort == "amount":  # F15: "pays the most": the largest stated amount first
        rows.sort(key=lambda r: -(amount_of[r["id"]] or -1))
    rows = rows[:15]
    extra = {}
    if undated and not any(not r.get("sample") for r in rows):
        # G20: "No public fellowships have deadlines before March" hid that none states one
        extra["fellowships_note"] = ("None of the public fellowships that pass the other "
                                     "filters states a deadline: say that in your first "
                                     "sentence, then give each sample with its deadline.")
    if sort == "amount":  # G12: what pays the most, the samples too
        extra["amount_note"] = ("Sorted by amount, the largest first. Name the public "
                                "fellowships first, saying plainly if none states an amount, "
                                "then the samples with their amounts under their own heading.")
    if used and route in ("all", "F") and not any(not r.get("sample") for r in rows):
        # T10: no fellowship holds the words; the brief's Match order already reads the
        # student's interests, so its top fellowships are offered instead of "none fit".
        top = [x for x in sorted(leads, key=lambda x: x.rank or 0)
               if x.route == "F" and x.verdict != "not eligible"][:3]
        if top:
            extra = {"fellowships_by_match": [_row(ctx, x) for x in top],
                     "fellowships_note": "No fellowship's title, purpose or fit sentence holds "
                     "these words. fellowships_by_match are the brief's top fellowships by "
                     "Match, which is read from the student's interests: offer them."}
    return {**apart(rows, "options"), "count": len(rows), **extra,
            **({"words_used": used} if used else {}),
            "note": "Options in this student brief, checked against the CV by rule, each "
            "group in the brief's own order by Match, the strongest first. Cite each row's "
            "own id. "
            + ("Every option listed matches: its listing or its fit sentence on the card "
               "holds one of words_used (words_found_in says which). " if used else "")
            + APART_NOTE}


# Words too common to narrow a search (R7): "my stream monitoring work" searches stream
# and monitoring.
COMMON = set("""a an and any are as at be by for from i in into is it me my of on or our
that the their this to with work works study studies""".split())


def search_words(words: str | None) -> list[str]:
    """The words of a search, split on commas and spaces, any of which may match (R7)."""
    out = [w for w in re.split(r"[,\s]+", (words or "").lower()) if w]
    return list(dict.fromkeys(w for w in out if w not in COMMON and len(w) > 1))


APART_NOTE = ("Records marked sample are invented test data. When both groups are present, "
              "list the sample scholarships under their own heading, such as 'Sample "
              "scholarships (invented)', never in the same list or sentence as the public "
              "fellowships.")


def apart(rows: list[dict], key: str) -> dict:
    """Standing rule 11 (U10, Q1): public options and SYNTHETIC samples come back as two
    groups whenever both are present, never as one list."""
    public = [r for r in rows if not r.get("sample")]
    samples = [r for r in rows if r.get("sample")]
    if public and samples:
        return {"fellowships": public, "sample_scholarships": samples}
    return {key: rows}


def is_sample_id(i: str, seen: dict[str, Record]) -> bool:
    r = seen.get(i)
    return i.startswith("sample:") or bool(r is not None and r.source == "synthetic")


LIST_LINE = re.compile(r"^\s*(?:[*-]|\d{1,2}[.)])\s")


def mixed_lists(text: str, seen: dict[str, Record]) -> list[str]:
    """Q1, standing rule 11 enforced by code: a list (consecutive list lines) or a sentence
    that cites a sample record together with a public one. The model's answer is
    rewritten once, then withheld (rule 5)."""
    from perch.scout.loop import SENTENCE_RE, cited

    units: list[str] = []
    block: list[str] = []
    for line in text.splitlines():
        if LIST_LINE.match(line):
            block.append(line)
            continue
        if block:
            units.append("\n".join(block))
            block = []
        units += [x for x in SENTENCE_RE.split(line) if x.strip()]
    if block:
        units.append("\n".join(block))
    for u in units:
        ids = cited(u)
        if any(is_sample_id(i, seen) for i in ids) and not all(is_sample_id(i, seen)
                                                                for i in ids):
            return ["a list or sentence names a sample scholarship together with a public "
                    "fellowship: put the sample scholarships under their own heading, such "
                    "as 'Sample scholarships (invented):', in their own list"]
    # R13: the answer's lead sentence cites public records only; a sample comes after its
    # own heading, never as the answer.
    heading = False
    for u in units:
        if SAMPLE_HEADING.search(u):
            heading = True
        ids = cited(u)
        if not ids:
            continue
        if not heading and any(is_sample_id(i, seen) for i in ids):
            return ["the answer opens with a sample scholarship: lead with the public "
                    "fellowships, or say that none of them answers the question, then give "
                    "any samples under the heading 'Sample scholarships (invented):'"]
        break
    return []


SAMPLE_HEADING = re.compile(r"^\W*sample scholarships", re.I | re.M)


def _facts(ctx: ScoutContext, row: dict, x: Lead) -> dict:
    """The option's rule lines and gaps, written by code, may back an answer's numbers."""
    ctx.facts[row["id"]] = [*x.verdict_lines, *x.gaps]
    return row


def check_option(ctx: ScoutContext, option_id: str) -> dict:
    x = _find(ctx, option_id)
    return {**_facts(ctx, _row(ctx, x), x), "rule_lines": x.verdict_lines, "still_needed": x.gaps,
            "note": "Checked by rule code against the fields read from the CV; no model "
            "made this check."}


def explain_verdict(ctx: ScoutContext, option_id: str) -> dict:
    x = _find(ctx, option_id)
    rec = _record(ctx, x)
    asks = {}
    if isinstance(rec, Scholarship):
        e = rec.eligibility
        asks = {k: v for k, v in {
            "level": ", ".join(rec.level_of_study or []) or None,
            "minimum_gpa": e.gpa_min if e else None,
            "majors": ", ".join(e.major or []) if e and e.major else None,
            "enrolment": e.enrolment_status if e else None,
            "also_asks_you_decide": e.targeted_criterion if e else None,
            "listing_notes": e.notes if e else None}.items() if v not in (None, "")}
    elif isinstance(rec, Opportunity) and rec.eligibility_notes:
        asks = {"eligibility_notes": rec.eligibility_notes[:800]}
    return {**_facts(ctx, _row(ctx, x), x), "why": x.verdict_lines, "still_needed": x.gaps,
            "what_the_record_asks": asks,
            "note": "The verdict comes from rule code; the asks are copied from the record."}


def read_cv(ctx: ScoutContext) -> dict:
    from perch.student import parse_student_cv

    doc = getattr(getattr(ctx.service, "session", None), "docs", {}).get("cv")
    if doc is None:
        raise ToolError("no CV in this session")
    return {"fields": dict(parse_student_cv(doc.abstract or "").summary()),
            "note": "Fields the rules read from the CV. The CV text itself is not shown."}


def compare_options(ctx: ScoutContext, ids: list[str] | None = None) -> dict:
    _, leads = _brief(ctx)
    chosen = [_find(ctx, i) for i in ids] if ids else [x for x in leads if x.status == "kept"]
    if not chosen:
        raise ToolError("nothing kept: pass option ids from search_options")
    rows = [{**_facts(ctx, _row(ctx, x), x), "still_needed": x.gaps} for x in chosen]
    return {**apart(rows, "rows"), "count": len(rows),
            "note": "These are the options compared, not the brief's best ones: for top or "
            "best, use search_options, which lists the brief's own order by Match. Each cell "
            "is copied from its record or checked against the CV by rule. " + APART_NOTE}


def draft_note(ctx: ScoutContext, route: str | None = None,
               ids: list[str] | None = None) -> dict:
    _, leads = _brief(ctx)
    chosen = [_find(ctx, i) for i in ids] if ids else [x for x in leads if x.status == "kept"]
    if route:
        chosen = [x for x in chosen if x.route == route]
    routes = {x.route for x in chosen}
    if not chosen:
        raise ToolError("nothing to write about: keep options or pass their ids")
    if len(routes) > 1:
        raise ToolError("fellowships go to Scholar Development and Fellowships Advising and "
                        "scholarships to Student Financial Services: call once per route")
    out = write_note(routes.pop(), [(x, _row(ctx, x)) for x in chosen])
    out.pop("sample")
    return {**out, "opening_withheld": False,
            "note": "Written by code from the kept options; no model. Perch never sends it."}


def mine(gap: str) -> str:
    """T13: the note is written as the student, so a gap's CV fact reads in the first
    person: "3 letters of recommendation (my CV lists 2 referees)"."""
    return re.sub(r"; your CV (.+)$", r" (my CV \1)", gap)


def _due(f: dict) -> str:
    """The note's deadline clause (F3, R17): "deadline 20 Dec 2026", "announcement expires
    7 May 2028", or the record's own words in lower case."""
    if f.get("announcement_expires"):
        return f"announcement expires {f['announcement_expires']}"
    d = f.get("deadline") or NOT_STATED
    return f"deadline {d}" if d == NOT_STATED or d[:1].isdigit() else lower_first(d)


def write_note(route: str, rows: list[tuple[Lead, dict]]) -> dict:
    """The note to the Temple office for one route, written by code from the options and
    their record facts (title, deadline). One source for Scout's draft_note and the
    Compare tab's note (review W9)."""
    kind = "fellowships" if route == "F" else "scholarships"
    sample = any(x.sample for x, _ in rows)
    lines = [f"- {f['title']}{' (SAMPLE record, not real)' if x.sample else ''}: "
             f"{x.verdict}, {_due(f)}"
             + (f". Still needed: {'; '.join(lower_first(mine(g)) for g in x.gaps)}"
                if x.gaps else "")
             for x, f in rows]
    demo = (["SAMPLE DATA, A DEMONSTRATION: DO NOT SEND. The scholarships marked SAMPLE are "
             "invented.", ""] if sample else [])
    body = "\n".join([*demo, "Hello,", "", f"I am a student looking at the {kind} below and would "
                      "like advice on applying.", "", *lines, "",
                      *(["Note: records marked SAMPLE come from a test corpus in Perch and "
                         "are not real scholarships.", ""] if sample else []), "Thank you."])
    name, url = OFFICES[route]
    return {"office": name, "office_page": url, "to": "",
            "subject": f"Advice on {kind}: {len(rows)} on my list", "body": body,
            "sample": sample}


_ID = {"type": "string", "description": "An option id from search_options"}
_IDS = {"type": "array", "items": {"type": "string"},
        "description": "Option ids; leave out to use the kept options"}
_DATE = {"type": "string", "description": "YYYY-MM-DD"}

STUDENT_TOOLS: dict[str, tuple[Tool, Callable[..., dict]]] = {
    "search_options": (Tool(
        "search_options", "The options in this student brief (fellowships and sample "
        "scholarships), with filters. Not-eligible options are left out unless verdict asks "
        "for them.", _obj({
            "route": {"type": "string", "enum": ["F", "S", "all"],
                      "description": "F fellowships, S sample scholarships, or all"},
            "verdict": {"type": "string",
                        "enum": ["eligible", "may be eligible", "not eligible"]},
            "deadline_after": _DATE, "deadline_before": _DATE,
            "min_amount": {"type": "number", "description": "US dollars"},
            "sort": {"type": "string", "enum": ["match", "deadline", "amount"],
                     "description": "match (the brief's order, the default), deadline (the "
                     "soonest first) or amount (the largest first, for what pays the most)"},
            "words": {"type": "string", "description": "Words to look for in the title or "
                      "purpose, separated by commas or spaces; an option matches if it holds "
                      "any of them"}}, [])), search_options),
    "check_option": (Tool("check_option", "The rule check of one option against the CV: "
                          "verdict, the rule lines and what is still needed.",
                          _obj({"option_id": _ID}, ["option_id"])), check_option),
    "explain_verdict": (Tool("explain_verdict", "Why one option got its verdict, with what "
                             "its record asks for, quoted.",
                             _obj({"option_id": _ID}, ["option_id"])), explain_verdict),
    "read_cv": (Tool("read_cv", "The fields the rules read from the CV (level, year, major, "
                     "GPA, enrollment, graduation, referees).", _obj({}, [])), read_cv),
    "compare_options": (Tool("compare_options", "Kept or chosen options side by side. For "
                             "kept options, the shortlist or a comparison; not for the top "
                             "or best options, which are the brief's order by Match.",
                             _obj({"ids": _IDS}, [])), compare_options),
    "draft_note": (Tool("draft_note", "A note to the right Temple office about kept or "
                        "chosen options, written by code, for the student to copy. Never "
                        "sent.", _obj({"route": {"type": "string", "enum": ["F", "S"]},
                                       "ids": _IDS}, [])), draft_note),
    "get_record": (Tool("get_record", "One record by id, with its fields as stored.",
                        _obj({"id": {"type": "string"}}, ["id"])), get_record),
}
assert tuple(STUDENT_TOOLS) == STUDENT_ALLOWLIST

STUDENT_RULES = """You are Scout, the agent inside Perch. This session is a student's: \
fellowships from public listings and scholarships from an invented SAMPLE corpus, each \
checked against the student's CV by rule code.

Rules:
- Answer a question about the options, the shortlist or the CV only from a tool result \
in this conversation: call a tool first. The list below is a snapshot; what is kept may \
have changed. For the shortlist or kept options, call compare_options once: it returns \
every kept option with what is still needed. Do not check options one by one.
- "Top", "best" or "strongest" options mean the brief's own order by Match, the \
strongest first, never the kept options: search_options lists them in that order, and so \
does the list below. Only a question about the kept options, the shortlist or a comparison \
uses compare_options.
- Use only the tools you are given. You cannot browse the web, send email, apply for \
anything, change a record, or read the CV text. If no tool can do what is asked, say so \
plainly in one sentence and do not call a tool.
- Every fact in your answer comes from a tool result. Cite the record id in square \
brackets right after the fact, like [sample:sch-0001] or [temple_sdfa:nsf-reu].
- A record marked sample is invented test data. Say "sample" whenever you name one. \
Never suggest applying to a sample record. When an answer covers fellowships and sample \
scholarships, give the fellowships first, then a line "Sample scholarships (invented):" \
with the samples in their own list. Never name a sample in the same list or sentence as \
a fellowship.
- Copy dates and dollar amounts exactly as the record gives them and cite that record. \
Never compute, round, estimate or count. If a record has no value, say it is not stated.
- "The soonest deadline" means search_options with sort deadline and deadline_after the \
as-of date. Your first sentence names public fellowships only: if none states a deadline, \
say so, then give any samples under their own heading.
- A question that filters by verdict, deadline, amount or words always runs \
search_options with those filters; "pays the most" sorts by amount. Not-eligible options \
are in the brief too, left out of the list below: search_options with verdict "not \
eligible" lists them, each with its reason in why. Never say there are none without searching.
- Today is the as-of date. A month named with no year means its next one after today.
- Verdicts come from rule code. Never judge the student's chances or give odds.
- Answer in two to five short, plain sentences."""


def student_brief_note(ctx: ScoutContext, leads: list[Lead]) -> str:
    lines = []
    for x in sorted(leads, key=lambda x: (x.route, x.rank or 0)):
        if x.route not in ROUTES or x.verdict == "not eligible":
            continue
        rec = _record(ctx, x)
        if rec is not None:
            title = facts_of(rec)["title"]
            marks = (", SAMPLE" if x.sample else "") + (", kept" if x.status == "kept" else "")
            lines.append(f"- [{ctx.see(rec)}] {title} ({x.verdict}{marks})")
    out = sum(1 for x in leads if x.route in ROUTES and x.verdict == "not eligible")
    hidden = (f"\nThe brief also holds {out} not-eligible option{'' if out == 1 else 's'}, "
              "not listed here: search_options with verdict \"not eligible\" lists them, each "
              "with its reason." if out else "")
    return ("\n\nThe student's options in this brief, each group in the brief's own order "
            "by Match, the strongest first:\n" + "\n".join(lines) + hidden) if lines else ""


__all__ = ["STUDENT_ALLOWLIST", "STUDENT_RULES", "STUDENT_TOOLS", "mixed_lists", "short_id",
           "student_brief_note"]
