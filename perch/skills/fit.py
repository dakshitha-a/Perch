"""Skill 2, fit explainer: one lead at a time, reasoning first, constrained JSON last.

Output: a fit score 0 to 100 and a 2 to 3 sentence explanation citing the opportunity
and 1 to 3 of the researcher's papers. The profile is the system prompt, identical for
every lead of a brief, so providers with prompt caching reuse it. Leads run in parallel.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from perch.llm import Message
from perch.llm.audit import AuditedProvider
from perch.profile import Profile
from perch.schemas import Opportunity, Record, Work
from perch.skills import (
    GROUND_RULES,
    opportunity_view,
    parse_json,
    sentences,
    short_work_id,
    work_view,
)
from perch.validate import Check, Validated, check, generate_validated

SKILL = "fit_explainer"
SCHEMA = {
    "type": "object",
    "properties": {  # order matters: reasoning is generated before the answer
        "reasoning": {"type": "string"},
        "fit": {"type": "integer", "minimum": 0, "maximum": 100},
        "explanation": {"type": "string"},
        "cited_ids": {"type": "array", "minItems": 2, "maxItems": 4,
                      "items": {"type": "string"}},
    },
    "required": ["reasoning", "fit", "explanation", "cited_ids"],
    "additionalProperties": False,
}
INSTRUCTIONS = (
    "You explain how well one funding opportunity fits a researcher's published work. "
    "First write brief private reasoning comparing the opportunity's aims with the papers. "
    "Then give fit from 0 (no overlap) to 100 (the opportunity reads as if written for this "
    "work), and an explanation of 2 or 3 sentences for the researcher that names the "
    "opportunity's aim and the specific papers that match it. cited_ids must hold the "
    "opportunity id and 1 to 3 paper ids. " + GROUND_RULES
)


@dataclass
class Fit:
    fit: int
    explanation: str
    cited_ids: list[str]
    reasoning: str


def profile_prompt(profile: Profile, works: dict[str, Work], per_thread: int = 5) -> tuple[str,
                                                                                         dict]:
    lines, records = [], {}
    for t in profile.threads:
        lines.append(f"\nResearch thread {t.index + 1} ({t.weight:.0%} of recent work): "
                     f"{t.label}")
        for wid in t.work_ids[:per_thread]:
            if wid in works:
                w = works[wid]
                records[short_work_id(w)] = w
                lines.append(work_view(w, abstract_chars=400))
    return INSTRUCTIONS + "\n\nThe researcher's papers:" + "\n".join(lines), records


def explain_one(o: Opportunity, system: str, paper_records: dict[str, Record],
                provider: AuditedProvider) -> Validated[Fit]:
    records = {**paper_records, o.opportunity_number: o}
    prompt = "Opportunity:\n" + opportunity_view(o)

    def generate(feedback: list[str]) -> Fit:
        msg = prompt + ("\n\nYour previous answer was rejected: " + "; ".join(feedback)
                        + ". Fix these problems." if feedback else "")
        r = provider.chat([Message("user", msg)], system=system, schema=SCHEMA, max_tokens=900,
                          cache_system=True)
        d = parse_json(r.text)
        return Fit(int(d["fit"]), d["explanation"], list(d["cited_ids"]), d.get("reasoning", ""))

    attempts = [0]

    def validate(f: Fit) -> Check:
        attempts[0] += 1
        c = check(f.explanation, f.cited_ids, records)
        errors = list(c.errors)
        if o.opportunity_number not in f.cited_ids:
            errors.append(f"cited_ids must include the opportunity id {o.opportunity_number}")
        papers = [i for i in f.cited_ids if i in paper_records]
        if not 1 <= len(papers) <= 3:
            errors.append(f"cite 1 to 3 paper ids, got {len(papers)}")
        n = sentences(f.explanation)
        if not 2 <= n <= 3:
            errors.append(f"explanation must be 2 or 3 sentences, got {n}")
        provider.log.validation(provider.last_call_id, SKILL, not errors, errors, attempts[0])
        return Check(not errors, errors)

    return generate_validated(generate, validate)


def explain_leads(opps: list[Opportunity], profile: Profile, works: dict[str, Work],
                  provider: AuditedProvider, workers: int = 4) -> list[Validated[Fit]]:
    system, paper_records = profile_prompt(profile, works)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda o: explain_one(o, system, paper_records, provider), opps))
