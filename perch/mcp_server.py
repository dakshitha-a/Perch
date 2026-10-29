"""Perch as an MCP server (S14): Scout's nine tools for any MCP client, local ones included.

The tools are `perch.scout.tools.TOOLS`, unchanged: the same schemas, the same argument
check (`check_arguments`) before every call, and the same tool code, so every result
names records by id, with a "provenance" map (source, source_url, fetched_at) for the
records it brought in. The two tools that call a model, `explain_fit`
and `draft_handoff`, run Perch's own validator inside the tool, as they do for Scout.
What the client's own model writes from these results is outside Perch's control; the
records it was given are in each result for it to cite.

Budgets per connection: at most MAX_CALLS tool calls, of which MAX_MODEL_CALLS may
call a model. Transport: stdio only, so the server runs on the machine of the process
that starts it.

`--private` runs every tool on a private session (perch.private): nothing is written
to the store, caches or logs, and the server refuses to start unless every model is
self-hosted on an allowed endpoint (perch.privacy). Private documents cannot be added
through MCP yet; that stays in the web app.

  uv run perch mcp [--author A5026494099] [--private]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

import mcp_types as types
from mcp.server import Server

from perch.llm import spec_for_role
from perch.llm.audit import AuditedProvider, AuditLog
from perch.schemas import Record
from perch.scout.tools import ALLOWLIST, TOOLS, ScoutContext, ToolError, check_arguments

MAX_CALLS = 60
MAX_MODEL_CALLS = 20
MODEL_TOOLS = {"explain_fit", "draft_handoff"}
INSTRUCTIONS = (
    "Perch finds routes to fund a researcher's work from public records. Start with "
    "build_profile or search_opportunities for an OpenAlex author id (e.g. A5026494099); "
    "the id is remembered for later calls. Every result carries the records it is based "
    "on, with source, source_url and fetched_at. Cite record ids for every date, amount "
    "and eligibility statement, and copy them from the records; never state one that no "
    "record holds. Industry leads are inferences from public signals, not verified "
    "interest. Perch never sends anything: a hand-off is a draft for the user.")


@dataclass
class Budget:
    calls: int = 0
    model_calls: int = 0
    log: list[dict] = field(default_factory=list)  # in memory only: (tool, status)

    def refuse(self, tool: str) -> str | None:
        if self.calls >= MAX_CALLS:
            return f"the limit of {MAX_CALLS} tool calls for this connection is reached"
        if tool in MODEL_TOOLS and self.model_calls >= MAX_MODEL_CALLS:
            return f"the limit of {MAX_MODEL_CALLS} model-backed calls is reached"
        return None


def make_context(service: object, author_id: str | None = None, as_of: date | None = None,
                 audit: AuditLog | None = None) -> ScoutContext:
    explainer = AuditedProvider(service.models.provider(service.models.fit_spec
                                                        or spec_for_role("fit_explainer")),
                                audit if audit is not None else service.audit, "fit_explainer")
    ctx = ScoutContext(service, as_of or date.today(), explainer=explainer)
    if author_id:
        ctx.researcher_id = ctx.full_author_id(author_id)
    return ctx


def call(ctx: ScoutContext, budget: Budget, name: str, args: dict | None) -> tuple[dict, bool]:
    """(result, is_error) for one tool call, checked exactly as Scout checks it."""
    args = args or {}
    entry = TOOLS.get(name)
    if entry is None:
        return {"error": f"{name!r} is not a Perch tool. Tools: {', '.join(ALLOWLIST)}."}, True
    if why := budget.refuse(name):
        return {"error": why}, True
    if errs := check_arguments(entry[0], args):
        return {"error": "bad arguments: " + "; ".join(errs)}, True
    budget.calls += 1
    budget.model_calls += name in MODEL_TOOLS
    try:
        if aid := args.get("author_id"):  # remembered, as Scout's session researcher
            ctx.researcher_id = ctx.full_author_id(aid)
        before = set(ctx.seen)
        result = entry[1](ctx, **{k: v for k, v in args.items() if v is not None})
        budget.log.append({"tool": name, "status": "done"})
        new = [i for i in ctx.seen if i not in before]
        if new:  # provenance of every record this result names, for the client to cite
            result = {**result, "provenance": {i: provenance(ctx.seen[i]) for i in new}}
        return result, False
    except ToolError as e:
        budget.log.append({"tool": name, "status": "error"})
        return {"error": str(e)}, True
    except Exception as e:  # noqa: BLE001 - reported by type only; messages can quote input
        budget.log.append({"tool": name, "status": "error"})
        return {"error": f"the tool failed ({type(e).__name__})"}, True


def provenance(r: Record) -> dict:
    return {"kind": r.kind, "source": r.source, "source_url": r.source_url,
            "fetched_at": r.fetched_at.isoformat()}


def mcp_tools() -> list[types.Tool]:
    return [types.Tool(name=t.name, description=t.description, input_schema=t.parameters)
            for t, _ in TOOLS.values()]


def create_server(ctx: ScoutContext, budget: Budget | None = None,
                  private: bool = False) -> Server:
    budget = budget or Budget()

    async def list_tools(_ctx: object, _params: object) -> types.ListToolsResult:
        return types.ListToolsResult(tools=mcp_tools())

    async def call_tool(_ctx: object, params: types.CallToolRequestParams
                        ) -> types.CallToolResult:
        import anyio

        result, err = await anyio.to_thread.run_sync(call, ctx, budget, params.name,
                                                     params.arguments)
        text = json.dumps(result, default=str)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    structured_content=json.loads(text), is_error=err)

    note = (" This server runs in private mode: nothing is saved or logged, and only "
            "self-hosted models are used." if private else "")
    return Server("perch", version="0.1.0", instructions=INSTRUCTIONS + note,
                  on_list_tools=list_tools, on_call_tool=call_tool)


def serve_stdio(server: Server) -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)
