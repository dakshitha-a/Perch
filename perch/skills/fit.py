"""Skill 2, fit explainer: one lead at a time, reasoning first, constrained JSON last.

Output: a three-part explanation (no score since S49 S15) citing the opportunity and
1 to 3 of the researcher's papers: an opportunity sentence (checked by validator layer 2
against the opportunity record), a research sentence (checked against the cited papers)
and a link sentence (a judgment, shown as an inference; layer 1 still checks it). The
split exists because a grounding model scores fit judgments ("aligns with") as
unsupported by design. The profile is the system prompt, identical for every lead of a
brief, so providers with prompt caching reuse it. Leads run in parallel.
"""

from __future__ import annotations

import re
from collections.abc import Callable
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
PROMPT_VERSION = "fit-4"  # bump with INSTRUCTIONS or SCHEMA; keys cached text (tests/test_cache.py)
SCHEMA = {
    "type": "object",
    "properties": {  # order matters: reasoning is generated before the answer
        "reasoning": {"type": "string"},
        "opportunity_sentence": {"type": "string"},
        "research_findings": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
            "type": "object",
            "properties": {"paper_id": {"type": "string"}, "finding": {"type": "string"}},
            "required": ["paper_id", "finding"], "additionalProperties": False}},
        "link_sentence": {"type": "string"},
        "cited_ids": {"type": "array", "minItems": 2, "maxItems": 4,
                      "items": {"type": "string"}},
    },
    "required": ["reasoning", "opportunity_sentence", "research_findings",
                 "link_sentence", "cited_ids"],
    "additionalProperties": False,
}
INSTRUCTIONS = (
    "You explain how well one funding opportunity fits a researcher's published work. "
    "First, in the reasoning field, note in at most three short phrases which of the "
    "opportunity's aims the papers touch. Then write three sentences for the researcher. "
    "opportunity_sentence: one factual sentence "
    "on what the opportunity funds, using only the opportunity record; when the record says "
    "little, say what it names and never what it leaves out. research_findings: 1 "
    "to 3 items, each one paper id and a short clause starting with a past-tense verb that "
    "states what that one paper did, using only that paper (e.g. \"surveyed living kidney "
    "donors about genetic testing\"). link_sentence: one short sentence on why the work and "
    "the opportunity fit or do not. cited_ids must hold the opportunity id and the paper ids "
    "used. " + GROUND_RULES
)


TRAILING_CITE = re.compile(r"\s*\[[^\[\]]*\]\s*\.?\s*$")
SPLIT_BRACKETS = re.compile(r"(\[[^\[\]]*\])")


def name_ids(text: str, labels: dict[str, str]) -> str:
    """S50 (3a): a user document's id written bare in model text ("user:achievement-a
    presented ...") reads as its title; ids inside citation brackets stay."""
    if not labels or not text:
        return text
    keys = sorted({k for i in labels for k in (i, i.removeprefix("user:"))}, key=len,
                  reverse=True)
    rx = re.compile(r"(?<![\w:-])(?:" + "|".join(re.escape(k) for k in keys) + r")(?![\w-])")

    def label(m: re.Match) -> str:
        key = m.group(0)
        name = labels.get(key) or labels[f"user:{key}"]
        before = m.string[:m.start()].rstrip()
        if not before or before.endswith((".", "!", "?", ":")) or name[1:2].isupper():
            return name  # a sentence's start, or an acronym such as CV
        return name[:1].lower() + name[1:]

    return "".join(p if SPLIT_BRACKETS.fullmatch(p) else rx.sub(label, p)
                   for p in SPLIT_BRACKETS.split(text))


# S50 (3b): the live capture cited the same three papers on almost every card. Code now
# picks, per lead, the papers whose words best match the opportunity record (tf-idf cosine
# over the profile's papers, ties in profile order), and the findings may use only those.
# S51 H10: a student card names its single closest record; with two, every card cited the
# same pair (achievement A and the interests note).
CHOSEN_PAPERS = {"researcher": 3, "student": 1}


def choose_papers(o: Opportunity, paper_records: dict[str, Record], k: int) -> list[str]:
    import math
    from collections import Counter

    from perch.profile import words

    ids = [i for i, r in paper_records.items() if isinstance(r, Work)]
    if len(ids) <= k:
        return ids
    bags = {i: Counter(words(f"{paper_records[i].title or ''} "
                             f"{paper_records[i].abstract or ''}")) for i in ids}
    df = Counter(t for b in bags.values() for t in b)
    idf = {t: math.log(1 + len(ids) / n) for t, n in df.items()}
    q = Counter(words(f"{o.title} {o.description or ''}"))

    def cos(b: Counter) -> float:
        dot = sum(q[t] * b[t] * idf[t] ** 2 for t in b if t in q)
        nb = math.sqrt(sum((b[t] * idf[t]) ** 2 for t in b)) or 1.0
        return dot / nb

    order = sorted(range(len(ids)), key=lambda j: (-cos(bags[ids[j]]), j))
    return [ids[j] for j in order[:k]]


@dataclass
class Fit:
    # The model's own 0-100 number. Not asked for since S49 S15: it was never shown, and a
    # generated number may not be (rule 3). Kept as a field so stored rows still load.
    fit: int | None
    opportunity_sentence: str
    findings: list[tuple[str, str]]  # (paper id, clause)
    link_sentence: str
    cited_ids: list[str]
    reasoning: str
    unsupported: list[str] = field(default_factory=list)  # layer 2 flags (factual sentences)
    support: dict[str, float] = field(default_factory=dict)
    # S50 (3a): a user document's title by its id ("Your achievement A"), so the visible text
    # names it and the id stays only inside a citation mark. Empty for papers.
    labels: dict[str, str] = field(default_factory=dict)

    def part(self, pid: str, clause: str) -> str:
        """One finding as shown: "W1 studied ..." for a paper (web/format.js parses that
        shape), "Your achievement A presented ... [user:achievement-a]" for a document."""
        if pid in self.labels:
            c = TRAILING_CITE.sub("", clause.strip()).rstrip(".")
            return f"{self.labels[pid]} {c} [{pid}]"
        return f"{pid} {clause.strip().rstrip('.')}"

    @property
    def research_sentence(self) -> str:
        """Rendered by code from the per-paper findings, so each part stays checkable."""
        parts = [self.part(pid, clause) for pid, clause in self.findings]
        return ("Cited work: " + "; ".join(parts) + ".") if parts else ""

    @property
    def explanation(self) -> str:
        return " ".join(x for x in (self.opportunity_sentence, self.research_sentence,
                                    self.link_sentence) if x)


# Student mode (S22, audit M5): the same task, addressed to a student, so the link
# sentence does not call them "the researcher". The record shapes are unchanged.
STUDENT_INSTRUCTIONS = (
    INSTRUCTIONS.replace("a researcher's published work", "a student's achievements and interests")
    .replace("for the researcher", "for the student")
    .replace("the papers touch", "the student's records touch")
    + " The person is a student: call them \"you\" or \"the student\", never \"the researcher\"."
)


def profile_prompt(profile: Profile, works: dict[str, Work], per_thread: int = 5,
                   audience: str = "researcher") -> tuple[str, dict]:
    lines, records = [], {}
    for t in profile.threads:
        lines.append(f"\nResearch thread {t.index + 1} ({t.weight:.0%} of recent work): "
                     f"{t.label}")
        for wid in t.work_ids[:per_thread]:
            if wid in works:
                w = works[wid]
                records[short_work_id(w)] = w
                lines.append(work_view(w, abstract_chars=400))
    if audience == "student":
        return STUDENT_INSTRUCTIONS + "\n\nThe student's records:" + "\n".join(lines), records
    return INSTRUCTIONS + "\n\nThe researcher's papers:" + "\n".join(lines), records


def explain_one(o: Opportunity, system: str, paper_records: dict[str, Record],
                provider: AuditedProvider, grounder: Grounder | None = None,
                audience: str = "researcher") -> Validated[Fit]:
    records = {**paper_records, o.opportunity_number: o}
    chosen = choose_papers(o, paper_records, CHOSEN_PAPERS.get(audience, 3))
    labels = ({i: r.title for i, r in paper_records.items()
               if i.startswith("user:") and isinstance(r, Work) and r.title}
              if audience == "student" else {})
    noun = "records" if audience == "student" else "papers"
    prompt = ("Opportunity:\n" + opportunity_view(o)
              + f"\n\nThe {noun} closest to this opportunity, chosen by code, closest first: "
              + ", ".join(f"[{i}]" for i in chosen)
              + f". research_findings and cited_ids use only these {noun}.")

    def generate(feedback: list[str]) -> Fit:
        msg = prompt + ("\n\nYour previous answer was rejected: " + "; ".join(feedback)
                        + ". Fix these problems." if feedback else "")
        r = provider.chat([Message("user", msg)], system=system, schema=SCHEMA, max_tokens=3000,
                          cache_system=True)
        d = parse_json(r.text)
        def known(i: str) -> str:
            # Models often drop the "user:" prefix of a user document's id.
            i = i.strip("[] ")
            return f"user:{i}" if i not in records and f"user:{i}" in records else i

        try:
            findings = [(known(x["paper_id"]), name_ids(x["finding"].strip(), labels))
                        for x in d["research_findings"]]
            return Fit(None, name_ids(d["opportunity_sentence"].strip(), labels), findings,
                       name_ids(d.get("link_sentence", "").strip(), labels),
                       [known(i) for i in d["cited_ids"]], d.get("reasoning", ""),
                       labels=labels)
        except (KeyError, TypeError, AttributeError) as e:
            raise ValueError(f"missing field: {e}") from e

    attempts = [0]

    def unparseable(errors: list[str]) -> None:
        attempts[0] += 1
        provider.log.validation(provider.last_call_id, SKILL, False, errors, attempts[0])

    def validate(f: Fit) -> Check:
        attempts[0] += 1
        c = check(f.explanation, f.cited_ids, records)  # numbers, dates, ids across all parts
        errors = list(c.errors)
        if o.opportunity_number not in f.cited_ids:
            errors.append(f"cited_ids must include the opportunity id {o.opportunity_number}")
        papers = [i for i in f.cited_ids if i in paper_records]
        if not 1 <= len(papers) <= 3:
            errors.append(f"cite 1 to 3 paper ids, got {len(papers)}")
        for pid, _ in f.findings:
            if pid not in paper_records:
                errors.append(f"finding names {pid!r}, which is not one of the given papers")
            elif pid not in f.cited_ids:
                errors.append(f"finding names {pid!r} but cited_ids does not list it")
        if off := [i for i in papers if i not in chosen]:  # S50 (3b): code chose the papers
            errors.append(f"cite only the {noun} chosen for this opportunity "
                          f"({', '.join(chosen)}), not {', '.join(off)}")
        if sentences(f.opportunity_sentence) != 1:
            errors.append("opportunity_sentence must be one sentence")
        provider.log.validation(provider.last_call_id, SKILL, not errors, errors, attempts[0])
        return Check(not errors, errors)

    v = generate_validated(generate, validate, unparseable)
    if v.value and grounder:
        ground(v.value, o, paper_records, grounder, provider)
    return v


def strip_ids(text: str) -> str:
    return re.sub(r"\s*\[[^\]]*\]", "", text).strip()


def ground(f: Fit, o: Opportunity, paper_records: dict[str, Record], grounder: Grounder,
           provider: AuditedProvider) -> None:
    """Layer 2: the opportunity sentence against the opportunity record, and each finding
    against its one paper. Citation brackets are removed before scoring."""
    p = grounder.support(opportunity_view(o, description_chars=4000),
                         [strip_ids(f.opportunity_sentence)])[0]
    f.support["opportunity_sentence"] = round(p, 3)
    if p <= THRESHOLD:
        f.unsupported.append(f.opportunity_sentence)
    for pid, clause in f.findings:
        w = paper_records.get(pid)
        if not isinstance(w, Work):
            continue
        claim = "The paper " + strip_ids(clause).rstrip(".") + "."
        p = grounder.support(work_view(w, abstract_chars=2000), [claim])[0]
        f.support[pid] = round(p, 3)
        if p <= THRESHOLD:
            f.unsupported.append(f.part(pid, clause))
    passed = not f.unsupported
    provider.log.validation(provider.last_call_id, SKILL, passed,
                            [f"unsupported: {s}" for s in f.unsupported], 1, layer=2)


def explain_leads(opps: list[Opportunity], profile: Profile, works: dict[str, Work],
                  provider: AuditedProvider, grounder: Grounder | None = None,
                  workers: int = 4,
                  on_result: Callable[[int, Validated[Fit]], None] | None = None,
                  audience: str = "researcher",
                  cancelled: Callable[[], bool] | None = None) -> list[Validated[Fit]]:
    """Explain every lead; `on_result(index, result)` is called as each one finishes.
    `cancelled` is checked before each lead, so a cancelled or timed-out job stops paying
    between leads (S49 B6). By default it is the running job's own signal, read from the
    brief store of the calling thread (pool threads do not inherit it)."""
    if cancelled is None:
        from perch.user.briefs import current_store

        store = current_store.get()
        cancelled = store.cancelled if store is not None else (lambda: False)
    system, paper_records = profile_prompt(profile, works, audience=audience)
    results: list[Validated[Fit] | None] = [None] * len(opps)

    def one(i: int) -> None:
        if cancelled():
            return
        results[i] = explain_one(opps[i], system, paper_records, provider, grounder, audience)
        if on_result:
            on_result(i, results[i])

    if not opps:
        return []
    # With prompt caching, the first call writes the shared profile prefix; later calls
    # read it at a tenth of the price, but only once the write exists. So the first lead
    # runs alone, the rest in parallel (live: 3 parallel calls all wrote the cache).
    start = 0
    if "prompt_cache" in provider.capabilities:
        one(0)
        start = 1
    # S50 re-check C1: each pool thread runs in a copy of the job's context, so a wait for the
    # model slot inside an explanation (the citation checker takes the slot) is tracked as a
    # wait, not counted against the brief's timeout.
    import contextvars

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(contextvars.copy_context().run, one, i)
                   for i in range(start, len(opps))]
        for f in futures:
            f.result()
    return [r for r in results if r is not None]
