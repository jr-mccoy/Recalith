#!/usr/bin/env python3
"""Task 7: record the production curator launch's effective isolation and route status.

Usage::

    python tools/check_provider_runtime.py --config LOCAL_CONFIG --output docs/host-compatibility.json

Where ``tools/probe_provider.py`` (Task 0) certifies a route, this tool runs the
*production* adapter (``recalith.providers``): the ProviderConfig built from the
same local configuration, the shared ``spawn_environment`` curator role, a
fresh private root, the certified argument array and the per-call host
diagnostic. It launches the configured executable in request-capture mode
(loopback endpoint, placeholder key; no account) with the Task 0 sentinel
fixtures planted, from a clean and a deliberately host-marked parent with
decoy credentials, and reports the route status the worker would compute
(``route_status``). It writes ``sections.provider_runtime.<provider_id>`` and
never touches another section.

Request capture never certifies: exit 0 only when the route status is
``certified`` *and* both isolation checks pass; exit 4 otherwise (the report
names every reason). Values of environment variables never enter the report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import probe_common as pc  # noqa: E402
import probe_provider as pp  # noqa: E402

SECTION = "provider_runtime"
DECOYS = {"ANTHROPIC_AUTH_TOKEN": "recalith-probe-decoy", "AWS_PROFILE": "recalith-probe-decoy", "OPENAI_API_KEY": "recalith-probe-decoy", "CLAUDE_CODE_USE_BEDROCK": "1"}
PLACEHOLDER_INSTALLATION = "inst_00000000-0000-4000-8000-000000000000"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    ns = parser.parse_args(argv)
    try:
        cfg = pp.load_config(ns.config)
    except pp.ConfigError as exc:
        return pc.die_usage(str(exc))
    from recalith import __version__
    from recalith.contracts.config import ProviderConfig
    from recalith.providers import base, claude_cli, isolation

    auth = cfg["auth_route"]
    config = ProviderConfig(
        provider_id=cfg["provider_id"], installation_id=PLACEHOLDER_INSTALLATION, backend="claude_cli", executable=cfg["executable"],
        configured_model=cfg["model"] or pp.UNSELECTED_MODEL, auth_route=auth["kind"] if auth["kind"] != "not_configured" else "env_api_key",
        auth_env_keys=auth["env_keys"] or ["ANTHROPIC_API_KEY"], expected_api_key_source=auth["expected_api_key_source"],
        network_env_keys=cfg["network_env_keys"], nonsecret_env=cfg["nonsecret_env"], invocation_args=cfg["invocation_args"], certification={"certified": False},
    )
    parents = {
        "clean": {k: v for k, v in os.environ.items() if k not in pc.DEFAULT_HOST_MARKERS and not k.startswith("RECALITH_")},
        "host_marked": {**os.environ, **DECOYS, "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", pc.WORKER_MARKER: "inst_99999999-9999-4999-8999-999999999999"},
    }
    checks = {name: isolation.isolation_check(config, inherited=env) for name, env in parents.items()}
    status = base.route_status(config, installation_id=PLACEHOLDER_INSTALLATION, inherited=os.environ)
    executable = isolation.resolve_executable(config.executable, os.environ)
    passed = all(c["verdict"] == "pass" for c in checks.values())
    sanitizer = pc.Sanitizer({str(Path.home()): "<home>", str(ROOT): "<repo>"})
    report = {
        "tool": "tools/check_provider_runtime.py",
        "tested_at": pc.utc_now(),
        "platform": pc.platform_facts(),
        "engine_build": __version__,
        "adapter": "recalith.providers.claude_cli",
        "adapter_version": base.ADAPTER_VERSION,
        "executable": executable,
        "executable_sha256": base.executable_digest(executable) if executable else None,
        "host_version": status.observed_version,
        "tested_flags": list(config.invocation_args),
        "argument_problems": claude_cli.argument_problems(config.invocation_args),
        "configured_model": config.configured_model,
        "nonsecret_env_names": sorted(config.nonsecret_env),
        "curator_root": "fresh private directory in the system temp dir per call (home/, work/, tmp/), removed afterwards; refused inside a git checkout",
        "environment_builder": "recalith.fast.process_env.spawn_environment (purpose curator); no second filter",
        "effective_configuration": {
            "user_level": "sentinel CLAUDE.md, skill, agent, settings.json hooks and MCP server planted in the private HOME",
            "project_level": "sentinel CLAUDE.md, CLAUDE.local.md, AGENTS.md, settings(.local).json hooks and .mcp.json planted in the private cwd",
            "native_memory": "sentinel MEMORY.md and a prior session transcript planted under the private HOME's projects/",
            "managed_settings_paths_present": sorted(p for p in base.MANAGED_SETTINGS_PATHS if os.path.exists(p)),
        },
        "isolation_checks": {name: {k: c.get(k) for k in ("verdict", "failures", "host_version", "init", "environment", "hooks_fired", "mcp_servers_started", "session_transcripts_written", "request_capture", "process")} for name, c in checks.items()},
        "route_status": status.report(),
        "certifies": False,
        "verdict": "certified" if status.certified and passed else ("isolation_failed" if not passed else "unavailable"),
        "limitations": [
            "Request capture uses a loopback endpoint and a placeholder key: it observes the client-side launch, never an account route, and cannot certify.",
            "Environment key names are observed through /proc on Linux; other platforms report the constructed map only.",
        ],
    }
    pc.merge_report_section(ns.output, SECTION, cfg["provider_id"], sanitizer.value(report))
    print(json.dumps({"verdict": report["verdict"], "isolation": {k: c["verdict"] for k, c in checks.items()}, "route_reasons": status.reasons}))
    return pc.EXIT_CERTIFIED if report["verdict"] == "certified" else pc.EXIT_UNAVAILABLE


if __name__ == "__main__":
    sys.exit(main())
