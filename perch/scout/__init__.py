"""Scout, the agent layer: its own loop over the allowlisted tools (SPEC section 8).

`make_scout` builds one for a researcher, optionally around an existing brief, with
the model for the "scout" role and an audited provider for the fit explanations.
"""

from __future__ import annotations

from datetime import date

from perch.llm import spec_for_role
from perch.llm.audit import AuditedProvider, AuditLog
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
    explainer = AuditedProvider(service.models.provider(llm or service.models.fit_spec
                                                        or spec_for_role("fit_explainer")),
                                audit, "fit_explainer")
    ctx = ScoutContext(service, as_of or date.today(), explainer=explainer)
    # A private brief with no public profile has no OpenAlex id; tools that need one say so.
    ctx.researcher_id = (author_id if author_id.startswith("private:")
                         else ctx.full_author_id(author_id))
    note, table, rules = "", None, None
    if brief_id and (got := service.get(brief_id)):
        b, leads = got
        ctx.as_of = date.fromisoformat(b.options["as_of"])
        ctx.brief_id = b.id
        if b.options.get("student"):  # a student brief gets the student tools (S24)
            from perch.scout.student_tools import STUDENT_RULES, STUDENT_TOOLS, student_brief_note

            if private is None:
                raise PermissionError("student Scout runs only in a private session")
            table, rules = STUDENT_TOOLS, STUDENT_RULES
            note = student_brief_note(ctx, leads)
        else:
            note = brief_note(ctx, b, leads)
    return Scout(provider, ctx, policy=policy, log=None if private else log,
                 private=private, brief_note=note, budget=budget, table=table, rules=rules)


def brief_note(ctx: ScoutContext, b: Brief, leads: list[Lead]) -> str:
    """The brief's ranked leads, so "the third one" means something to the model."""
    lines = []
    with ctx.service.repo() as r:
        for lead in sorted(leads, key=lambda x: x.rank or 0):
            if (o := r.get(Opportunity, lead.record_id)) is not None:
                lines.append(f"{lead.rank}. [{ctx.see(o)}] {o.title}")
    return ("\n\nThe user is looking at brief " + b.id + ". Its ranked leads (Route A):\n"
            + "\n".join(lines)) if lines else ""
