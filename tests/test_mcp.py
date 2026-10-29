"""MCP server (S14): an MCP client lists Perch's tools and gets a cited brief.

In process, through the SDK's own Client, with fake models and fixture-backed sources.
"""

import json

import anyio
from mcp.client.client import Client

from perch.llm.fake import FakeProvider
from perch.mcp_server import MAX_CALLS, Budget, call, create_server, make_context
from perch.retrieve import index_opportunities
from perch.scout.tools import ALLOWLIST

from .test_api import make


def fit_reply(messages, system, schema):
    if schema and "fit" in schema.get("properties", {}):
        paper = next(w for w in system.split("[")[1:] if w.startswith("W")).split("]")[0]
        return json.dumps({
            "reasoning": "r", "fit": 66,
            "opportunity_sentence": "The announcement funds research projects [PAR-25-268].",
            "research_findings": [{"paper_id": paper, "finding": "studied molecular "
                                                                 "simulation software"}],
            "link_sentence": "The work fits.", "cited_ids": ["PAR-25-268", paper]})
    return ""


def served(tmp_path):
    _, service = make(tmp_path)
    with service.repo() as r:
        index_opportunities(r, service.models.get("index"), service.models.get("embedder"))
    service.models.provider = lambda spec: FakeProvider(responder=fit_reply)
    return create_server(make_context(service)), service


def test_an_mcp_client_gets_a_cited_brief(tmp_path):
    server, _ = served(tmp_path)

    async def run():
        async with Client(server) as c:
            tools = await c.list_tools()
            assert tuple(t.name for t in tools.tools) == ALLOWLIST
            r = await c.call_tool("search_opportunities",
                                  {"route": "A", "author_id": "A5026494099"})
            assert not r.is_error, r.content[0].text
            got = r.structured_content
            lead = got["leads"][0]
            e = await c.call_tool("explain_fit", {"opportunity_id": lead["id"]})
            assert not e.is_error, e.content[0].text
            return got, e.structured_content

    got, fit = anyio.run(run)
    text = json.dumps(got)
    assert "PAR-25-268" in text and "source_url" in text and "fetched_at" in text
    assert fit["cited_ids"][0] == "grants_gov:PAR-25-268" and len(fit["cited_ids"]) == 2
    assert set(fit["provenance"]) >= set(fit["cited_ids"][1:])  # the paper it cites
    assert "Cited work:" in json.dumps(fit)


def test_bad_calls_are_refused_and_budgets_hold(tmp_path):
    _, service = served(tmp_path)
    ctx, b = make_context(service), Budget()
    assert call(ctx, b, "send_email", {})[1]
    res, err = call(ctx, b, "search_opportunities", {"route": "C"})
    assert err and "must be one of" in res["error"]
    res, err = call(ctx, b, "build_profile", {"author_id": 5})
    assert err and "must be string" in res["error"]
    b.calls = MAX_CALLS
    res, err = call(ctx, b, "get_record", {"id": "x"})
    assert err and "limit" in res["error"]
