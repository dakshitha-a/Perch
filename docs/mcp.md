# MCP server

[Back to the README](../README.md)


`perch mcp` serves Scout's nine tools to any MCP client over stdio (`perch/mcp_server.py`, MCP Python SDK 2.3.0). Each result names its records with their source, link and fetch time. `explain_fit` and `draft_handoff` run Perch's citation checks before they return. A connection may make 60 tool calls, and 20 of them may call a model. `--author A5026494099` sets the default researcher. `--private` runs with no writes or logs. With `--private`, the server will not start unless every model is self-hosted. Private documents cannot be added through MCP yet.

Add it to Claude Code (checked against `claude mcp add --help`, Claude Code 2.1.312):

```
claude mcp add perch -- uv --directory /path/to/perch run perch mcp
```

Or try it once without changing any settings. This is the command S14 tested:

```
claude -p --strict-mcp-config --mcp-config perch-mcp.json \
  --allowedTools mcp__perch__search_opportunities mcp__perch__explain_fit -- \
  "Find the top 3 open federal funding opportunities for OpenAlex author A5026494099, then explain the fit of the first, citing record ids."
```

Here `perch-mcp.json` is `{"mcpServers": {"perch": {"command": "uv", "args": ["--directory", "/path/to/perch", "run", "perch", "mcp"]}}}`. Any other MCP client that can start a stdio server uses the same command, including an agent driving a local Ollama model. That local-agent setup has not been tested (UNVERIFIED). `scripts/mcp_check.py` runs the same check with the SDK's own client.
