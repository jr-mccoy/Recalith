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

For a direct-API backend (decision 0023; ``--backend anthropic_messages`` or
``openai_compatible``) it runs the production request capture instead
(``providers.isolation.api_isolation_check``: the shipped transport against a
loopback capture endpoint, the exact request verified) from the same two
parents, and reports the route status without any executable or host version.

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
    parser.add_argument("--backend", choices=pp.BACKENDS, default=None, help="the backend you intend to check; must equal the configuration's backend")
    ns = parser.parse_args(argv)
    try:
        cfg = pp.load_config(ns.config, backend=ns.backend)
    except pp.ConfigError as exc:
        return pc.die_usage(str(exc))
    if cfg["backend"] in pp.API_BACKENDS:
        return api_runtime(cfg, ns.output)
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


def api_runtime(cfg: dict, output: Path) -> int:
    """The production request capture of a direct-API route from a clean and a host-marked parent (decision 0023)."""
    import probe_api

    from recalith import __version__
    from recalith.providers import api, base, isolation

    config = probe_api.provider_config(cfg, installation_id=PLACEHOLDER_INSTALLATION)
    parents = {
        "clean": {k: v for k, v in os.environ.items() if k not in pc.DEFAULT_HOST_MARKERS and not k.startswith("RECALITH_")},
        "host_marked": {**os.environ, **DECOYS, "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", pc.WORKER_MARKER: "inst_99999999-9999-4999-8999-999999999999"},
    }
    checks = {name: isolation.isolation_check(config, inherited=env) for name, env in parents.items()}
    status = base.route_status(config, installation_id=PLACEHOLDER_INSTALLATION, inherited=os.environ)
    passed = all(c["verdict"] == "pass" for c in checks.values())
    sanitizer = pc.Sanitizer({str(Path.home()): "<home>", str(ROOT): "<repo>"}, secrets=[os.environ.get(k, "") for k in config.auth_env_keys])
    report = {
        "tool": "tools/check_provider_runtime.py",
        "tested_at": pc.utc_now(),
        "platform": pc.platform_facts(),
        "engine_build": __version__,
        "backend": config.backend,
        "adapter": "recalith.providers.api",
        "adapter_version": base.ADAPTER_VERSION,
        "adapter_sha256": api.adapter_digest(),
        "transport": "python -I src/recalith/providers/http_transport.py (stdlib only), launched by controller.launch.run_bounded",
        "configured_model": config.configured_model,
        "expected_resolved_model": config.expected_resolved_model,
        "endpoint": {k: v for k, v in config.endpoint.model_dump(mode="json").items() if k != "url"} | {"path": isolation.endpoint_path(config.endpoint.url)},
        "expected_header_names": api.expected_header_names(config),
        "expected_body_keys": sorted(api.expected_body_keys(config)),
        "nonsecret_env_names": sorted(config.nonsecret_env),
        "environment_builder": "recalith.fast.process_env.spawn_environment (purpose curator); no second filter",
        "isolation_checks": {name: {k: c.get(k) for k in ("verdict", "failures", "endpoint", "environment", "request_capture", "process")} for name, c in checks.items()},
        "route_status": status.report(),
        "certifies": False,
        "verdict": "certified" if status.certified and passed else ("isolation_failed" if not passed else "unavailable"),
        "limitations": [
            "Request capture uses a loopback endpoint and a placeholder key: it observes the exact client-side request, never an account route, and cannot certify.",
            "Environment key names are observed through /proc on Linux; other platforms report the constructed map only.",
        ],
    }
    pc.merge_report_section(output, SECTION, cfg["provider_id"], sanitizer.value(report))
    print(json.dumps({"verdict": report["verdict"], "isolation": {k: c["verdict"] for k, c in checks.items()}, "route_reasons": status.reasons}))
    return pc.EXIT_CERTIFIED if report["verdict"] == "certified" else pc.EXIT_UNAVAILABLE


if __name__ == "__main__":
    sys.exit(main())
