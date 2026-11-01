"""Scout, the agent layer: its own loop over the allowlisted tools (SPEC section 8).

`make_scout` builds one for a researcher, optionally around an existing brief, with
the model for the "scout" role and an audited provider for the fit explanations.
"""

from __future__ import annotations

from datetime import date

from perch.llm import spec_for_role
from perch.llm.audit import AuditedProvider, AuditLog, CountedProvider
from perch.privacy import PrivateSettings
from perch.schemas import Brief, Lead, Opportunity
from perch.scout.log import ScoutLog
from perch.scout.loop import Policy, Scout, ScoutBudget, Session
from perch.scout.tools import ScoutContext

__all__ = ["Scout", "ScoutBudget", "ScoutContext", "Session", "make_scout"]


def make_scout(service: object, author_id: str, *, as_of: date | None = None,
               brief_id: str | None = None, llm: str | None = None,
               policy: Policy | None = None, log: ScoutLog | None = None,
               private: PrivateSettings | None = None,
               budget: ScoutBudget | None = None) -> Scout:
    """`service` is a perch.service.BriefService. Private sessions log nothing anywhere."""
    audit = AuditLog(None) if private else service.audit
    provider = AuditedProvider(service.models.provider(llm or spec_for_role("scout")), audit,
                               "scout")
    # The two model-backed tools count toward the session budget (S28), so each session
    # gets its own counted providers for them.
    explainer = CountedProvider(service.models.provider(llm or service.models.fit_spec
                                                        or spec_for_role("fit_explainer")),
                                audit, "fit_explainer")
    handoff = CountedProvider(service.models.provider(service.models.handoff_spec
                                                      or spec_for_role("handoff")),
                              audit, "handoff")
    ctx = ScoutContext(service, as_of or date.today(), explainer=explainer, handoff=handoff)
    # A private brief with no public profile has no OpenAlex id; tools that need one say so.
    ctx.researcher_id = (author_id if author_id.startswith("private:")
                         else ctx.full_author_id(author_id))
    note, table, rules, who, check = "", None, None, None, None
    if brief_id and (got := service.get(brief_id)):
        b, leads = got
        ctx.as_of = date.fromisoformat(b.options["as_of"])
        ctx.brief_id = b.id
        if b.options.get("student"):  # a student brief gets the student tools (S24)
            from perch.scout.student_tools import (
                STUDENT_RULES,
                STUDENT_TOOLS,
                mixed_lists,
                student_brief_note,
            )

            if private is None:
                raise PermissionError("student Scout runs only in a private session")
            table, rules, who = STUDENT_TOOLS, STUDENT_RULES, "a student (private session)"
            check = mixed_lists

            def note() -> str:  # read again at each question: kept marks change (Q4)
                return student_brief_note(ctx, (service.get(b.id) or (None, []))[1])
        else:
            def note() -> str:
                return brief_note(ctx, b, (service.get(b.id) or (None, []))[1])
    return Scout(provider, ctx, policy=policy, log=None if private else log,
                 private=private, brief_note=note, budget=budget, table=table, rules=rules,
                 who=who, answer_check=check)


def brief_note(ctx: ScoutContext, b: Brief, leads: list[Lead]) -> str:
    """The brief's ranked leads, so "the third one" means something to the model, with
    the ones kept now marked (Q4)."""
    lines, kept = [], []
    with ctx.service.repo() as r:
        for lead in sorted((x for x in leads if x.route == "A" and x.status != "dismissed"),
                           key=lambda x: x.rank or 0):
            if (o := r.get(Opportunity, lead.record_id)) is not None:
                mark = " (kept)" if lead.status == "kept" else ""
                lines.append(f"{len(lines) + 1}. [{ctx.see(o)}] {o.title}{mark}")
        kept = [x for x in leads if x.status == "kept"]
    if not lines:
        return ""
    k = (f"The user has kept {len(kept)} lead{'' if len(kept) == 1 else 's'} on the brief. "
         "For questions about the kept leads, the shortlist or a comparison, call compare or "
         "draft_handoff with no ids; pass ids only when the user names other leads."
         if kept else "The user has kept no lead on the brief yet. If asked about kept "
         "leads, say so and offer to compare the top three.")
    # R2: "top" and "best" mean this order, never the kept list.
    top = ("\"Top\", \"best\" or \"strongest\" leads mean this order: the first ones in this "
           "list, whatever is kept. Answer such a question from this list and cite each lead; "
           "do not call compare for it. Do not state Match scores or positions as numbers.")
    return ("\n\nThe user is looking at brief " + b.id + ". Its grant leads (Route A), in the "
            "brief's own order by Match, the strongest first (dismissed leads left out):\n"
            + "\n".join(lines) + "\n" + top + "\n" + k)
