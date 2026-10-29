"""Live MCP check (S14): spawn `perch mcp` over stdio, as an MCP client would, and ask it
for a cited brief: search_opportunities for a researcher, then explain_fit on the top lead.

  uv run python scripts/mcp_check.py [--author A5026494099] [--private]

The server inherits the environment, so PERCH_MODEL_SERVER, OLLAMA_BASE_URL and the
private-mode settings apply to it. Prints a JSON summary.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

import anyio
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters


async def main(author: str, private: bool) -> dict:
    uv = shutil.which("uv") or "uv"
    args = ["run", "perch", "mcp", "--author", author] + (["--private"] if private else [])
    params = StdioServerParameters(command=uv, args=args, env=dict(os.environ))
    out: dict = {"author": author, "private": private}
    t0 = time.time()
    async with Client(params) as c:
        out["tools"] = [t.name for t in (await c.list_tools()).tools]
        r = await c.call_tool("search_opportunities", {"route": "A", "top": 5})
        s = r.structured_content or {}
        out["search_error"] = r.is_error and r.content[0].text
        out["leads"] = [(x["id"], x["title"][:70], x.get("close_date"))
                        for x in s.get("leads", [])]
        out["search_provenance"] = len(s.get("provenance", {}))
        if s.get("leads"):
            e = await c.call_tool("explain_fit", {"opportunity_id": s["leads"][0]["id"]})
            f = e.structured_content or {}
            out["explain_error"] = e.is_error and e.content[0].text
            out["explanation"] = (" ".join(f.get(k) or "" for k in (
                "opportunity_sentence", "research_sentence")).strip()
                or f.get("detail") or f.get("error"))
            out["fit"] = f.get("fit")
            out["unsupported"] = f.get("unsupported_statements")
            out["cited_ids"] = f.get("cited_ids")
            out["cited_with_provenance"] = sorted(set(f.get("cited_ids") or [])
                                                  & set(f.get("provenance") or {}))
    out["seconds"] = round(time.time() - t0, 1)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--author", default="A5026494099")
    ap.add_argument("--private", action="store_true")
    a = ap.parse_args()
    print(json.dumps(anyio.run(main, a.author, a.private), indent=2, default=str))
    sys.exit(0)
