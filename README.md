# Recalith

Recalith is an autonomous memory for one software project, used with [Claude Code](https://docs.anthropic.com/en/docs/claude-code). It runs alongside the project, inside it:
- it watches what the coding agent does and what you tell it;
- it keeps the current task state and episodes of past work;
- it keeps long-term knowledge backed by evidence: facts, decisions, preferences, and approaches that failed.

Each new session gets the relevant parts back as advisory context. Nobody has to remember to "update the memory".

Each project has its own complete installation under `.recalith/`, with its own engine version, configuration, worker, database, evidence and budgets. There is no shared daemon, global registry, or automatic learning across projects.

## Status: experimental preview, not released

- **Engine:** `0.1.0.dev17`, release profile `claude_preview`. It fixes the first five phases of a [pre-publication audit](docs/audits/2026-11-06-memory-system-audit.md) (credentials escaping the scrubber, lost large messages, a worker that could spin, starve work or die silently, retrieval that lost applicable guidance in a large store, an install path nobody could follow from the documents, and a repository that did not yet read as a public project); the live gate below ran on `0.1.0.dev10` and is re-run on the fixed engine before any release.
- **Tests:** the deterministic suites run in CI on Linux (Python 3.12–3.14), macOS and Windows (Python 3.13). One macOS timing test fails intermittently (see BUILD_PROGRESS).
- **The live preview gate passed** on native Windows on 2026-11-04 (its tenth run). That is 12 scripted scenarios, each run with Recalith and with a clean no-memory baseline, plus three eight-hour workload days. With reviewer labels:
  - 21 of 22 saved facts were supported by their evidence;
  - 7 of 7 reusable lessons were learned, and 2 of 2 lessons from failed approaches;
  - there was no wrong advice given with confidence;
  - forgetting, restore and project isolation were all demonstrated.
- **What that does not show:** that Recalith makes the agent better than having no memory. With one trial per scenario the paired outcomes are inconclusive, and memory costs extra tokens. The full comparison (48 scenarios, three trials, held-out scenarios) belongs to the full release. The [evaluation records](docs/evaluations/) hold every run, failures included.
- **Platforms** ([decision 0041](docs/decisions/0041-preview-platforms-windows-and-linux.md)):

  | Platform | Status |
  |---|---|
  | Native Windows | certified live |
  | Linux | live certification pending |
  | macOS | not certified; help wanted, below |
- **Not yet published** to a package index. Release signing is still open.

Current progress, blockers and next steps are in [docs/BUILD_PROGRESS.md](docs/BUILD_PROGRESS.md). Before trying it, read [what Recalith stores and sends](docs/OPERATIONS.md#7-what-recalith-stores-and-sends) (scrubbed prompts, commands and result excerpts go to the model provider you configure), [how to uninstall](docs/OPERATIONS.md#8-uninstalling) and [what a preview store's memory can expect to survive](docs/OPERATIONS.md#9-compatibility-of-preview-stores). Changes by version are in [CHANGELOG.md](CHANGELOG.md); reporting a vulnerability is in [SECURITY.md](SECURITY.md).

## Trying it

This is for people comfortable with an experimental tool. You need:
- Python 3.12, 3.13 or 3.14 (the plain interpreter; nothing else is installed globally);
- Claude Code;
- one explicitly configured route for the background curator: an Anthropic API key, an OpenAI-compatible provider, or a local server.

Background curation is billed by your provider. Recalith enforces its own daily call and token budgets. Captured prompts, tool output and file excerpts are scrubbed and then sent to that provider; see [docs/OPERATIONS.md](docs/OPERATIONS.md).

A release is a directory holding the wheel, `bootstrap.py`, `requirements.lock`, `SHA256SUMS` and one `wheelhouse-<platform>-<python>/` per platform and Python version (until one is published, build it from a checkout: `uv run python tools/build_release.py --out dist-release`, plus `uv run --with pip python tools/build_wheelhouse.py --out dist-release` on each platform). From that directory, in an ordinary terminal (not one inside Claude Code), with `RELEASE` its path and `PROJECT` your project's:

```bash
# Linux (the wheelhouse tag must match the python3 that runs the bootstrap)
TAG=$(python3 -c 'import sys; print("cp%d%d" % sys.version_info[:2])')
DIGEST=$(grep ' recalith-0.1.0.dev17-py3-none-any.whl$' "$RELEASE/SHA256SUMS" | cut -d' ' -f1)
python3 "$RELEASE/bootstrap.py" init --project "$PROJECT" --profile coding --release-profile claude_preview \
    --wheel "$RELEASE/recalith-0.1.0.dev17-py3-none-any.whl" --expected-digest "$DIGEST" \
    --wheelhouse "$RELEASE/wheelhouse-linux-x86_64-$TAG"
cd "$PROJECT" && .recalith/bin/recalith status        # exit 8: installed, not yet certified
```

```powershell
# Windows (PowerShell; Python 3.13 shown)
$Digest = (Select-String -Path "$Release\SHA256SUMS" -Pattern ' recalith-0.1.0.dev17-py3-none-any.whl$').Line.Split(' ')[0]
py -3.13 "$Release\bootstrap.py" init --project $Project --profile coding --release-profile claude_preview `
    --wheel "$Release\recalith-0.1.0.dev17-py3-none-any.whl" --expected-digest $Digest `
    --wheelhouse "$Release\wheelhouse-win-amd64-cp313"
cd $Project; .recalith\bin\recalith.cmd status      # exit 8: installed, not yet certified
```

`status` then names the next command. The rest (certifying your curator route and Claude Code's delivery paths, `integrate claude`) is one ordered page per platform in [docs/OPERATIONS.md §4](docs/OPERATIONS.md#4-one-time-setup-operator-from-an-ordinary-terminal). Administrative commands must run from an ordinary terminal, not from inside an agent session. That is deliberate.

## Help wanted

- **macOS live certification.** The maintainer has no Mac. On a Mac with Claude Code and your own curator credentials:
  1. Run the deterministic suite with `uv sync --locked`, then `uv run pytest`.
  2. Run the one-time setup above in a fresh project, through `tools/probe_provider.py`, `tools/check_provider_runtime.py` and `tools/probe_delivery.py --engine-project`.
  3. Open a pull request with the sanitized `docs/host-compatibility.json` the probes write, plus the exact commands and exit codes.

  Never commit keys, tokens or private paths. The probes sanitize their own output, but check it.
- **Linux live certification:** the same steps on a native Linux machine.
- **Bug reports and fixes.** Read [AGENTS.md](AGENTS.md) first: it lists the constraints every change must keep, such as hooks never writing SQLite and no model call inside a write transaction.

## Documentation

| Document | What it holds |
|---|---|
| [docs/SYSTEM_SPEC.md](docs/SYSTEM_SPEC.md) | Product behavior, policy and defaults |
| [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) | Records, interfaces, CLI and wire contracts |
| [docs/ACCEPTANCE_TESTS.md](docs/ACCEPTANCE_TESTS.md) | Acceptance cases and release gates |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Work packages and their order |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Setting up and operating an installation |
| [docs/decisions/](docs/decisions/) | Recorded design and policy decisions |
| [docs/BUILD_PROGRESS.md](docs/BUILD_PROGRESS.md) | Build history, current state and next actions |
| [AGENTS.md](AGENTS.md), [CODING_AGENT_HANDOFF.md](CODING_AGENT_HANDOFF.md) | Instructions for coding agents working on this repository |
| [docs/STARTER_PACKET.md](docs/STARTER_PACKET.md) | The original specification packet's README (historical) |

## License

Recalith is free software under the [GNU General Public License, version 3](LICENSE) (GPL-3.0-only, [decision 0042](docs/decisions/0042-gpl-3-license.md)). Contributions are accepted under the same license.
