# Decision 0002: Curator launch requirements from the Task 0 probe

Status: accepted (empirical, Task 0) · Date: 2026-10-15 · Host observed: Claude Code CLI 2.1.301 on Linux

## Context

Task 0 ran `tools/probe_provider.py` in request-capture mode against the installed Claude CLI: the CLI was pointed at a loopback recording endpoint with a placeholder key, so the probe saw the exact request the CLI would send. Hostile sentinel customizations (user/project/local instructions, skill, agent, native memory, prior session, hooks in all three scopes, user and project MCP servers) were planted around the launch, and non-isolated control launches proved every blocking detector fires. Evidence: `docs/host-compatibility.json` → `sections.provider_isolation.claude_cli`.

With the candidate argument array (`-p --bare --tools "" --strict-mcp-config --setting-sources "" --disable-slash-commands --no-session-persistence`), the isolated request carried no tools and no sentinel, no sentinel hook or MCP server ran, and no transcript was written, from both a clean and a host-marked parent. Four facts change how the production curator (Task 7) must launch. None weakens SYSTEM_SPEC §9.1; they make its "isolated working directory" and "purpose-specific home" requirements concrete.

## Decisions

1. **No `--json-schema` in the curator invocation.** On 2.1.301, `--json-schema` adds a model-visible `StructuredOutput` tool, so the effective tool inventory is no longer empty. The curator asks for JSON in its prompt and the engine validates the decoded body locally against the strict contracts, as SYSTEM_SPEC §10 already requires. The probe fails any invocation that exposes a tool, including this one.
2. **The curator runs in a fresh private root outside every user project.** Its `HOME` and working directory live in a per-call private directory that is deleted after the call. With hostile home configuration, the isolated `--bare --setting-sources ""` launch still rewrote `.claude/settings.local.json` at the git root containing its cwd (a legacy `enabledMcpjsonServers` migration from the home config). Inside a user checkout that would be a background write to a project file, which SYSTEM_SPEC §13 forbids. A fresh, private, per-call root makes such host housekeeping harmless and prevents state carrying between calls. The probe models exactly this layout and records writes inside the private root as observations.
3. **`--bare` fixes the auth route to an API key or `apiKeyHelper`.** OAuth/keychain subscription credentials are not read in bare mode. Selecting a subscription route requires a different candidate argument array and its own complete certification; the probe never substitutes one route for another.
4. **Built-in host components remain and are reported, not hidden.** Under `--bare`, the init diagnostic still lists built-in agents and two built-in plugins (`cc-plugin-agents-md@builtin`, `cc-plugin-plugin-authoring@builtin`), and the debug log shows their native hook modules loading. With no tools the model cannot invoke them, and no planted `AGENTS.md` content appeared in any request (isolated or control). Because the control never showed `AGENTS.md` content, that detector is informational rather than validated; its presence in an isolated run still fails the probe. A non-builtin plugin fails the probe.

Observed resolution rules used by the fixture: project `settings.json` resolves at the cwd, `settings.local.json` at the git root, and `CLAUDE.md` upward from the cwd. These are version facts for 2.1.301, re-probed whenever the host version changes.

## Consequences

* Task 7's `providers/claude_cli.py` must reuse the certified argument array and the private-root layout, and must re-run this probe (plus live mode) before any autonomous extraction.
* Certification is still **not** established: live mode needs an explicitly configured route and the operator's background-use attestation. Request-capture results are host observations, not account certification.
