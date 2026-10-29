"""Skill 1, profile summariser: 3 to 6 topic labels and a two-sentence summary, tied
to work ids. Validated by layer 1; regenerated once, then flagged."""

from __future__ import annotations

from dataclasses import dataclass

from perch.llm import Message
from perch.llm.audit import AuditedProvider
from perch.profile import Profile
from perch.schemas import Work
from perch.skills import GROUND_RULES, parse_json, sentences, short_work_id, work_view
from perch.validate import Check, Validated, check, generate_validated

SKILL = "profile_summary"
SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {"type": "array", "minItems": 3, "maxItems": 6, "items": {
            "type": "object",
            "properties": {"label": {"type": "string"},
                           "work_ids": {"type": "array", "minItems": 1, "maxItems": 5,
                                        "items": {"type": "string"}}},
            "required": ["label", "work_ids"], "additionalProperties": False}},
        "summary": {"type": "string"},
        "cited_ids": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    "required": ["topics", "summary", "cited_ids"],
    "additionalProperties": False,
}
SYSTEM = (
    "You summarise a researcher's public papers for a funding brief. Return 3 to 6 short "
    "topic labels (2 to 5 words each), each with the ids of the papers it comes from, and a "
    "summary of exactly two sentences describing the body of work. List every paper id you "
    "relied on in cited_ids. " + GROUND_RULES
)


@dataclass
class Summary:
    topics: list[tuple[str, list[str]]]
    summary: str
    cited_ids: list[str]


def papers_for(profile: Profile, works: dict[str, Work], per_thread: int = 6) -> list[Work]:
    out: list[Work] = []
    for t in profile.threads:
        out += [works[i] for i in t.work_ids[:per_thread] if i in works]
    return out


def summarise_profile(profile: Profile, works: dict[str, Work], provider: AuditedProvider
                      ) -> Validated[Summary]:
    papers = papers_for(profile, works)
    records = {short_work_id(w): w for w in papers}
    prompt = "Papers:\n" + "\n".join(work_view(w) for w in papers)

    def generate(feedback: list[str]) -> Summary:
        msg = prompt + ("\n\nYour previous answer was rejected: " + "; ".join(feedback)
                        + ". Fix these problems." if feedback else "")
        r = provider.chat([Message("user", msg)], system=SYSTEM, schema=SCHEMA, max_tokens=800)
        d = parse_json(r.text)
        return Summary([(t["label"], list(t["work_ids"])) for t in d["topics"]],
                       d["summary"], list(d["cited_ids"]))

    attempts = [0]

    def unparseable(errors: list[str]) -> None:
        attempts[0] += 1
        provider.log.validation(provider.last_call_id, SKILL, False, errors, attempts[0])

    def validate(s: Summary) -> Check:
        attempts[0] += 1
        ids = sorted({*s.cited_ids, *(i for _, ws in s.topics for i in ws)})
        c = check(s.summary + " " + " ".join(lbl for lbl, _ in s.topics), ids, records)
        errors = list(c.errors)
        n = sentences(s.summary)
        if n != 2:
            errors.append(f"summary must be exactly two sentences, got {n}")
        provider.log.validation(provider.last_call_id, SKILL, not errors, errors, attempts[0])
        return Check(not errors, errors)

    return generate_validated(generate, validate, unparseable)
