"""The three bounded model skills (standing rule 5). S5 builds skills 1 and 2.

Every skill: compact record views with short ids go in, JSON constrained by a schema
comes out, validator layer 1 checks it, a failure is regenerated once with the errors,
then flagged. Every call goes through the audit log.
"""

from __future__ import annotations

import json
import re

from perch.schemas import Opportunity, Work


def parse_json(text: str) -> dict:
    """The JSON object in a reply (tolerates a fenced block). Raises ValueError."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in the reply")
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    if not isinstance(out, dict):
        raise ValueError("reply JSON is not an object")
    return out


def sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def short_work_id(w: Work) -> str:
    return w.id.rstrip("/").rsplit("/", 1)[-1]


def work_view(w: Work, abstract_chars: int = 600) -> str:
    year = w.publication_year or "n.d."
    venue = f"; {w.venue}" if w.venue else ""
    abstract = f"\n  Abstract: {w.abstract[:abstract_chars]}" if w.abstract else ""
    return f"[{short_work_id(w)}] ({year}{venue}) {w.title}{abstract}"


def opportunity_view(o: Opportunity, description_chars: int = 1500) -> str:
    lines = [f"[{o.opportunity_number}] {o.title}", f"  Agency: {o.agency}"]
    if o.activity_code:
        lines.append(f"  Activity code: {o.activity_code}")
    if o.open_date:
        lines.append(f"  Opens: {o.open_date.isoformat()}")
    if o.close_date:
        lines.append(f"  Closes: {o.close_date.isoformat()}")
    if o.award_ceiling is not None:
        lines.append(f"  Award ceiling: ${o.award_ceiling:,.0f}")
    if o.description:
        lines.append(f"  Description: {o.description[:description_chars]}")
    return "\n".join(lines)


GROUND_RULES = (
    "Rules: use only the records given. Cite records by the id in square brackets. "
    "Do not state any number, dollar amount or date unless it appears in a record you cite; "
    "if in doubt, leave numbers out. Do not say a researcher should apply, will win, or is "
    "eligible; describe fit only. Plain, specific sentences."
)
