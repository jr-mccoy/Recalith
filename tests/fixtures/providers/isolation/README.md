# Provider isolation sentinel fixtures (Task 0)

`tools/probe_provider.py` materializes these files into a disposable fixture
tree for every probe run; nothing here is read by a production component.

| File | Role |
|---|---|
| `sentinels.json` | Sentinel tokens, hook events and scopes planted around the curator launch |
| `expected_inventory.json` | The expected effective inventory of a certified launch (empty) |
| `sentinel_hook.py` | Hook command that only appends its label to a marker file |
| `sentinel_mcp.py` | Stdio MCP server that records its start and advertises one inert sentinel tool |

The fixture tree contains a fake user home (instructions, skill, agent, native
memory, prior session, user hooks, user MCP server) and a fake project root
(project/local instructions, hooks and `.mcp.json`). The curator's working
directory is inside the fake project, so upward instruction discovery is
exercised. Detectors are validated by deliberately non-isolated control launches
in request-capture mode; a sentinel whose detector never fired is reported as
unvalidated instead of as a pass.

All tokens are inert strings. No fixture contains credentials.
