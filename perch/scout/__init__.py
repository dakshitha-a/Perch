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
from perch.scout.loop import Mode, Policy, Scout, ScoutBudget, Session
from perch.scout.tools import ScoutContext

__all__ = ["Scout", "ScoutBudget", "ScoutContext", "Session", "make_scout"]


def make_scout(service: object, author_id: str, *, as_of: date | None = None,
               brief_id: str | None = None, llm: str | None = None, mode: Mode = "ask",
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
    ctx.researcher_id = ctx.full_author_id(author_id)
    note = ""
    if brief_id and (got := service.get(brief_id)):
        b, leads = got
        ctx.as_of = date.fromisoformat(b.options["as_of"])
        note = brief_note(ctx, b, leads)
    return Scout(provider, ctx, mode=mode, policy=policy, log=None if private else log,
                 private=private, brief_note=note, budget=budget)


def brief_note(ctx: ScoutContext, b: Brief, leads: list[Lead]) -> str:
    """The brief's ranked leads, so "the third one" means something to the model."""
    lines = []
    with ctx.service.repo() as r:
        for lead in sorted(leads, key=lambda x: x.rank or 0):
            if (o := r.get(Opportunity, lead.record_id)) is not None:
                lines.append(f"{lead.rank}. [{ctx.see(o)}] {o.title}")
    return ("\n\nThe user is looking at brief " + b.id + ". Its ranked leads (Route A):\n"
            + "\n".join(lines)) if lines else ""
