"""Skill 2, fit explainer: one lead at a time, reasoning first, constrained JSON last.

Output: a fit score 0 to 100 and a three-part explanation citing the opportunity and
1 to 3 of the researcher's papers: an opportunity sentence (checked by validator layer 2
against the opportunity record), a research sentence (checked against the cited papers)
and a link sentence (a judgment, shown as an inference; layer 1 still checks it). The
split exists because a grounding model scores fit judgments ("aligns with") as
unsupported by design. The profile is the system prompt, identical for every lead of a
brief, so providers with prompt caching reuse it. Leads run in parallel.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from perch.grounding import THRESHOLD, Grounder
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
        "opportunity_sentence": {"type": "string"},
        "research_sentence": {"type": "string"},
        "link_sentence": {"type": "string"},
        "cited_ids": {"type": "array", "minItems": 2, "maxItems": 4,
                      "items": {"type": "string"}},
    },
    "required": ["reasoning", "fit", "opportunity_sentence", "research_sentence",
                 "link_sentence", "cited_ids"],
    "additionalProperties": False,
}
INSTRUCTIONS = (
    "You explain how well one funding opportunity fits a researcher's published work. "
    "First write brief private reasoning comparing the opportunity's aims with the papers. "
    "Then give fit from 0 (no overlap) to 100 (the opportunity reads as if written for this "
    "work), and three sentences for the researcher. opportunity_sentence: one factual sentence "
    "on what the opportunity funds, using only the opportunity record. research_sentence: one "
    "factual sentence on what the cited papers did, using only those papers, naming them by "
    "id. link_sentence: one short sentence on why the two fit or do not. cited_ids must hold "
    "the opportunity id and 1 to 3 paper ids. " + GROUND_RULES
)


@dataclass
class Fit:
    fit: int
    opportunity_sentence: str
    research_sentence: str
    link_sentence: str
    cited_ids: list[str]
    reasoning: str
    unsupported: list[str] = field(default_factory=list)  # layer 2 flags (factual sentences)
    support: dict[str, float] = field(default_factory=dict)

    @property
    def explanation(self) -> str:
        return " ".join(x for x in (self.opportunity_sentence, self.research_sentence,
                                    self.link_sentence) if x)


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
                provider: AuditedProvider, grounder: Grounder | None = None
                ) -> Validated[Fit]:
    records = {**paper_records, o.opportunity_number: o}
    prompt = "Opportunity:\n" + opportunity_view(o)

    def generate(feedback: list[str]) -> Fit:
        msg = prompt + ("\n\nYour previous answer was rejected: " + "; ".join(feedback)
                        + ". Fix these problems." if feedback else "")
        r = provider.chat([Message("user", msg)], system=system, schema=SCHEMA, max_tokens=900,
                          cache_system=True)
        d = parse_json(r.text)
        try:
            return Fit(int(d["fit"]), d["opportunity_sentence"].strip(),
                       d["research_sentence"].strip(), d.get("link_sentence", "").strip(),
                       list(d["cited_ids"]), d.get("reasoning", ""))
        except (KeyError, TypeError, AttributeError) as e:
            raise ValueError(f"missing field: {e}") from e

    attempts = [0]

    def unparseable(errors: list[str]) -> None:
        attempts[0] += 1
        provider.log.validation(provider.last_call_id, SKILL, False, errors, attempts[0])

    def validate(f: Fit) -> Check:
        attempts[0] += 1
        c = check(f.explanation, f.cited_ids, records)
        errors = list(c.errors)
        if o.opportunity_number not in f.cited_ids:
            errors.append(f"cited_ids must include the opportunity id {o.opportunity_number}")
        papers = [i for i in f.cited_ids if i in paper_records]
        if not 1 <= len(papers) <= 3:
            errors.append(f"cite 1 to 3 paper ids, got {len(papers)}")
        for name in ("opportunity_sentence", "research_sentence"):
            n = sentences(getattr(f, name))
            if n != 1:
                errors.append(f"{name} must be one sentence, got {n}")
        provider.log.validation(provider.last_call_id, SKILL, not errors, errors, attempts[0])
        return Check(not errors, errors)

    v = generate_validated(generate, validate, unparseable)
    if v.value and grounder:
        ground(v.value, o, paper_records, grounder, provider)
    return v


def ground(f: Fit, o: Opportunity, paper_records: dict[str, Record], grounder: Grounder,
           provider: AuditedProvider) -> None:
    """Layer 2: each factual sentence against the records it may draw on."""
    papers = "\n".join(work_view(paper_records[i], abstract_chars=1500)
                       for i in f.cited_ids if i in paper_records)
    checks = {"opportunity_sentence": opportunity_view(o, description_chars=4000),
              "research_sentence": papers}
    for name, doc in checks.items():
        sent = getattr(f, name)
        p = grounder.support(doc, [sent])[0]
        f.support[name] = round(p, 3)
        if p <= THRESHOLD:
            f.unsupported.append(sent)
    passed = not f.unsupported
    provider.log.validation(provider.last_call_id, SKILL, passed,
                            [f"unsupported: {s}" for s in f.unsupported], 1, layer=2)


def explain_leads(opps: list[Opportunity], profile: Profile, works: dict[str, Work],
                  provider: AuditedProvider, grounder: Grounder | None = None,
                  workers: int = 4) -> list[Validated[Fit]]:
    system, paper_records = profile_prompt(profile, works)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(
            lambda o: explain_one(o, system, paper_records, provider, grounder), opps))
