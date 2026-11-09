# Security policy

Recalith is an experimental preview (engine `0.1.0.dev15`, not released). It runs on your machine, inside one project, and sends scrubbed excerpts of that project's activity to the model provider you configure. What it protects, what it does not, and how to report a problem are below.

## Reporting a vulnerability

Report privately through GitHub's security advisories for this repository ("Report a vulnerability" under the Security tab). Do not open a public issue for a vulnerability. Include the engine version (`recalith status --json` prints it), the platform, and the smallest reproduction you have; never include a credential, a transcript or a store file. You will get an acknowledgement within seven days and a decision (fix, won't fix, or more information needed) within thirty.

There is no bug bounty.

## Scope

In scope:

- the engine (`src/recalith/`): the hook fast path, the worker, the store, the curator request path, the CLI and its operator guard, retention, forgetting, backups and restore;
- the installed Claude Code integration (hooks, deny rules, the hook manifest);
- the release bootstrap (`bootstrap.py`) and the release layout (digests, hash-locked wheelhouses);
- the probes and the live-gate harness, where they handle credentials or write tracked evidence.

Examples of what counts: a credential that survives scrubbing and reaches the spool, the store, a delivered packet or a provider request; a working agent that can run an administrative command, read private state or modify memory; a curator reply that changes memory without passing deterministic admission; a backup or restore that loses or resurrects forgotten text; a hook that blocks or alters the host's tool call; a dependency installed without its locked hash.

## Out of scope

SYSTEM_SPEC §13 states the boundary: Recalith's markers, terminal checks, operator tokens, command deny rules and the revision chain are **friction and detection against ordinary confused-agent mistakes, not an operating-system security boundary.** A hostile process running as the same user can remove markers, read token files and edit the store directly. Reports of that kind describe the design, not a vulnerability.

Also out of scope: what the model provider does with the requests it receives (its retention and terms are its own; OPERATIONS §7 says exactly what is sent), vulnerabilities in Claude Code or in the provider's service, and findings that need physical access or root.

## What a fix looks like

A fix ships as a new engine version with a decision record under `docs/decisions/` naming the finding (content-free where the report asked for it) and a test that fails on the previous version. The CHANGELOG names the version. There is no separate security-advisory feed yet; watch releases.
