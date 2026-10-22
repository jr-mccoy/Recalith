"""``recalith integrate claude`` and ``integrate claude --remove`` (preview; SYSTEM_SPEC §2.2, §13.1; decision 0019).

Local by default and only: the owned entries go into the untracked
project-local ``.claude/settings.local.json`` and the location is explicitly
ignored (an owned ``/.claude/settings.local.json`` line in the project
``.gitignore``, verified with ``git check-ignore`` when git is available). A
settings file already tracked by git is refused: hooks committed to a shared
repository are the full-only ``--shared`` mode. ``--autostart`` (per-project
OS startup entries) and ``--shared`` pass the guard and answer
``capability_unavailable`` (decision 0018).

What is installed, through :mod:`recalith.integrations.install` with an
ownership record:

- one hook group per event of :data:`recalith.fast.claude.HOOK_EVENTS`, each
  running the pinned project launcher (``"$CLAUDE_PROJECT_DIR"/.recalith/bin/
  recalith-hook claude_code --event EVENT``);
- the administrative command deny rules (:func:`deny_rules`), in every
  launcher and module spelling this module knows, with their exact coverage
  and gaps reported; a prefix pattern never covers every wrapper or spelling.

Then the hook-context manifest (context_schema 4): the registered worker
start (autostart consent), the selected route's key names, the session-start
notice consent and **only the delivery paths a live certification of this
installation and this exact host version certified** (``.recalith/host.json``);
without one, delivery stays off and capture still runs. Private-path rules are
probed and reported (from the host record), never installed in preview.

The host is asked only for its version (``claude --version``, a fresh minimal
environment with a private temporary ``HOME``); no host session runs here.
Host sessions belong to the certification harness
(``tools/probe_delivery.py --engine-project``), which writes the host record
through :func:`write_host_record`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from recalith import __version__
from recalith.capture.hooks import write_hook_context
from recalith.contracts.common import InstallationContext, utc_now
from recalith.contracts.health import DELIVERY_PATHS, HostCertification
from recalith.errors import RecalithError
from recalith.fast import claude as fast_claude, claude_capture, entry, failpoints
from recalith.integrations import install

HOST_ID = "claude_code"
SETTINGS_LOCAL = Path(".claude") / "settings.local.json"
SHARED_SETTINGS = Path(".claude") / "settings.json"
IGNORE_LINE = "/.claude/settings.local.json"
HOST_FILE = Path(".recalith") / "host.json"
VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")
# Every administrative form of DATA_CONTRACTS §12, as the words that follow a spelling.
ADMIN_FORMS = (
    "init", "declare", "correct", "undo", "forget", "integrate", "backup", "restore", "export", "import", "upgrade",
    "workspace", "project", "worker", "jobs retry", "operator-token", "doctor --probe-host", "doctor --probe-provider",
)
COVERAGE_GAPS = {
    "global_options_before_subcommand": "a global option between the spelling and the form (e.g. --json, --project PATH, --operator-token-file PATH) defeats the prefix",
    "shell_wrapper": "sh -c, bash -c, bash SCRIPT, eval, xargs or a script file that runs the launcher is not matched",
    "other_interpreter_or_copy": "another interpreter path, a copied or symlinked launcher, a quoted absolute path or a renamed module invocation is not matched",
    "previews_overcovered": "undo/forget previews (read-only) are denied with their apply forms: a prefix cannot separate them",
}
# Observed outcomes of the host deny probe that certify the rules (the harness's report).
RULES_CERTIFIED = "denied_all_covered"
PRIVATE_STATES = ("probed_supported", "probed_limited", "probed_unsupported")
CERT_PATHS = {"session_start": "session_start", "prompt": "prompt", "pre_action": "pre_action", "compact": "compact_restore"}


# --------------------------------------------------------------------------
# The host and its rules


def host_version(executable: str | None) -> dict[str, Any]:
    """``{executable, version, capture}`` from ``EXE --version`` only (bounded; private temporary HOME)."""
    exe = executable or shutil.which("claude")
    if not exe:
        return {"executable": None, "version": None, "capture": "unknown"}
    home = tempfile.mkdtemp(prefix="recalith-host-version-")
    try:
        env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": home, "USERPROFILE": home}
        for key in ("SYSTEMROOT", "WINDIR", "PATHEXT", "TEMP", "TMP"):
            if key in os.environ:
                env[key] = os.environ[key]
        proc = subprocess.run([exe, "--version"], capture_output=True, env=env, stdin=subprocess.DEVNULL, timeout=30, check=False)
        match = VERSION_RE.search(proc.stdout.decode("utf-8", "replace")[:200]) if proc.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        match = None
    finally:
        shutil.rmtree(home, ignore_errors=True)
    version = match.group(1) if match else None
    capture = "unknown" if version is None else ("certified" if version in claude_capture.CERTIFIED_VERSIONS else "conservative")
    return {"executable": exe, "version": version, "capture": capture}


def spellings(root: Path) -> list[str]:
    """The launcher and module spellings of the ``recalith`` CLI that the deny rules name."""
    runtime = f".recalith/runtime/{__version__}/venv/bin/python"
    out = [
        ".recalith/bin/recalith", "./.recalith/bin/recalith", f"{root.as_posix()}/.recalith/bin/recalith", "recalith",
        "python -m recalith", "python3 -m recalith", "python -I -m recalith", "python3 -I -m recalith",
        "python -m recalith.cli.main", "python3 -m recalith.cli.main",
        f"{runtime} -I -m recalith", f"{root.as_posix()}/{runtime} -I -m recalith",
    ]
    if os.name == "nt":  # pragma: no cover - native Windows
        out += [".recalith/bin/recalith.cmd", ".recalith\\bin\\recalith.cmd"]
    return out


def deny_rules(root: Path) -> tuple[list[str], dict[str, Any]]:
    """The administrative command deny rules and their exact coverage report."""
    names = spellings(root)
    rules = [f"Bash({s} {form}:*)" for s in names for form in ADMIN_FORMS]
    coverage = {
        "syntax": "Bash(PREFIX:*) prefix rules in permissions.deny",
        "spellings": names, "forms": list(ADMIN_FORMS), "rule_count": len(rules),
        "complete": False, "gaps": dict(COVERAGE_GAPS),
        "backstop": "the CLI operator guard refuses every administrative form from a host-marked process (exit 6), with or without a rule",
        "certified_on_host": None,
    }
    return rules, coverage


def configured_permission_mode(root: Path) -> str:
    """The project's configured ``permissions.defaultMode`` (local over shared), default ``default``."""
    mode = "default"
    for rel in (SHARED_SETTINGS, SETTINGS_LOCAL):
        try:
            data, _raw = install.read_settings(Path(root) / rel)
        except RecalithError:
            continue
        value = (data.get("permissions") or {}).get("defaultMode") if isinstance(data.get("permissions"), dict) else None
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z]{1,32}", value):
            mode = value
    return mode


# --------------------------------------------------------------------------
# Certified delivery paths (from the host record)


def certified_paths(ctx: InstallationContext, version: str | None) -> tuple[list[str], list[str]]:
    """The delivery paths a live record certifies for this installation and exact version, with the reasons for the rest."""
    from recalith.operations.health import load_host_certification

    state, record = load_host_certification(ctx.root, ctx.installation_id)
    reasons: list[str] = []
    if version is None:
        reasons.append("host_version_unknown")
    elif version not in claude_capture.CERTIFIED_VERSIONS:
        reasons.append("host_version_uncertified")
    if state == "absent":
        reasons.append("delivery_not_certified")
    elif state == "invalid":
        reasons.append("host_certification_invalid")
    else:
        assert record is not None
        if record.mode != "live":
            reasons.append("delivery_request_capture_only")
        if record.host_version != version:
            reasons.append("host_version_changed")
    if reasons:
        return [], reasons
    assert record is not None
    paths = [p for p in DELIVERY_PATHS if record.delivery[p] == "certified"]
    return paths, ([] if {"session_start", "prompt"} <= set(paths) else ["required_delivery_path_not_certified"])


def _route_keys(root: Path) -> list[str]:
    from recalith.providers import base

    try:
        config = base.load_provider_config(root)
    except RecalithError:
        return []
    # The route's auth key names and its network (proxy/TLS) key names: the worker must carry both to its curator.
    return list(dict.fromkeys([*config.auth_env_keys, *config.network_env_keys])) if config is not None else []


# --------------------------------------------------------------------------
# Git


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    git = shutil.which("git")
    if not git or not (root / ".git").exists():
        return None
    env = {"PATH": os.environ.get("PATH", os.defpath), "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root), "GIT_TERMINAL_PROMPT": "0"}
    for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if key in os.environ:
            env[key] = os.environ[key]
    try:
        return subprocess.run([git, "-C", str(root), *args], capture_output=True, env=env, stdin=subprocess.DEVNULL, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _tracked(root: Path, rel: Path) -> bool | None:
    proc = _git(root, "ls-files", "--error-unmatch", "--", rel.as_posix())
    return None if proc is None else proc.returncode == 0


def _ignored(root: Path, rel: Path) -> str:
    proc = _git(root, "check-ignore", "-q", "--", rel.as_posix())
    if proc is None:
        return "unverified"
    return "verified" if proc.returncode == 0 else "not_ignored"


# --------------------------------------------------------------------------
# Integrate and remove


def desired(root: Path) -> install.Desired:
    hooks = []
    for event, matcher in fast_claude.HOOK_EVENTS:
        group: dict[str, Any] = {"hooks": [{"type": "command", "command": fast_claude.hook_command(event), "timeout": fast_claude.HOOK_TIMEOUT_SECONDS}]}
        if matcher is not None:
            group = {"matcher": matcher, **group}
        hooks.append((event, group))
    rules, _coverage = deny_rules(root)
    return install.Desired(hooks=hooks, deny=rules, ignore_line=IGNORE_LINE, marker=fast_claude.LAUNCHER)


def integrate(ctx: InstallationContext, *, executable: str | None = None, now: str | None = None) -> dict[str, Any]:
    """Install (or update) the local Claude Code integration; see the module docstring."""
    now = now or utc_now()
    root = Path(ctx.root)
    if _tracked(root, SETTINGS_LOCAL):
        raise RecalithError("policy_refused", ".claude/settings.local.json is tracked by git; the local integration needs an untracked location (shared, tracked settings are the full-release --shared mode)")
    host = host_version(executable)
    paths, reasons = certified_paths(ctx, host["version"])
    want = desired(root)
    _rules, coverage = deny_rules(root)
    host_state, record = _host_record(ctx)
    if record is not None and record.command_rules == "installed" and record.host_version == host["version"]:
        coverage["certified_on_host"] = {"host_version": record.host_version, "mode": record.mode, "certified_at": record.certified_at}
    extra = {"host": {"executable_name": None if host["executable"] is None else Path(host["executable"]).name, "version": host["version"]}, "engine_version": __version__, "deny_rule_count": len(want.deny)}
    outcome, final = install.install(root, HOST_ID, SETTINGS_LOCAL, want, extra=extra, now=now)
    write_hook_context(ctx, adapter_id=HOST_ID, host_version=host["version"], worker_autostart=True, worker_route_keys=_route_keys(root), delivery_paths=paths, session_notice=True)
    failpoints.hit(install.AFTER_MANIFEST)
    install.finish(root, HOST_ID, final)
    private = record.private_paths if record is not None and record.host_version == host["version"] else "not_run"
    return {
        "host_id": HOST_ID, "scope": "local", "settings_path": SETTINGS_LOCAL.as_posix(), "settings": outcome.settings,
        "formatting_preserved": outcome.formatting_preserved, "ignored": _ignored(root, SETTINGS_LOCAL),
        "owned": {"hooks": len(final["owned"]["hooks"]), "deny_rules": len(final["owned"]["deny"]), "deny_rules_preexisting": len(final.get("deny_preexisting") or []), "gitignore_line": bool((final["owned"]["gitignore"] or {}).get("owned"))},
        "host": host, "delivery_paths": paths, "delivery_reasons": reasons,
        "worker": {"autostart": "registered_hook_start", "route_keys": _route_keys(root)},
        "os_startup_entries": {"state": "unavailable", "reason": "deferred_full_release"},
        "command_deny_rules": coverage,
        "private_paths": {"state": private, "installed_rules": "unavailable_in_preview", "os_level_isolation": False},
        "host_record": host_state, "notices": {"session_start": True},
        "certification": "tools/probe_delivery.py --config LOCAL_CONFIG --engine-project PATH --output REPORT (decision 0019)",
    }


def remove(ctx: InstallationContext) -> dict[str, Any]:
    """Remove the unchanged owned entries and the hook manifest; report modified entries for reconciliation."""
    root = Path(ctx.root)

    def drop_manifest() -> None:
        path = root / entry.HOOK_CONTEXT_FILE
        if path.exists():
            path.unlink()
        failpoints.hit(install.REMOVE_AFTER_MANIFEST)

    record_before = install.Ownership(root, HOST_ID).load()
    outcome, record = install.remove(root, HOST_ID, marker=fast_claude.LAUNCHER, after_settings=drop_manifest)
    if record_before is None:
        drop_manifest()
    return {
        "host_id": HOST_ID, "integration": "absent" if record_before is None else ("reconcile" if record is not None else "removed"),
        "removed": outcome.removed, "modified": outcome.modified, "missing": outcome.missing, "unrelated_preserved": outcome.unrelated_preserved,
    }


# --------------------------------------------------------------------------
# The host record (``.recalith/host.json``)


def _host_record(ctx: InstallationContext) -> tuple[str, HostCertification | None]:
    from recalith.operations.health import load_host_certification

    return load_host_certification(ctx.root, ctx.installation_id)


def rules_installed(root: Path) -> bool:
    """The owned deny rules are recorded as installed and are all present, unchanged, in the settings file."""
    try:
        record = install.Ownership(Path(root), HOST_ID).load()
        if record is None or record.get("state") != "installed" or not record["owned"]["deny"]:
            return False
        data, _raw = install.read_settings(Path(root) / record["settings_path"])
    except RecalithError:
        return False
    present = set((data.get("permissions") or {}).get("deny") or [])
    return set(record["owned"]["deny"]) <= present


def write_host_record(ctx: InstallationContext, report: Mapping[str, Any], *, now: str | None = None) -> HostCertification:
    """The installation's ``HostCertification`` from a certification report; ``live`` only for a complete live observation.

    ``report``: ``{mode, host_version, paths: {session_start|prompt|pre_action|compact: {state}}, command_rules: {state},
    private_paths: {state}, report_digest}``. A live run whose four paths were not all observed (any ``not_run``), or
    any request-capture run, is recorded ``request_capture`` with every delivery path ``unavailable``. The command
    rules are ``installed`` only when the host probe saw every covered spelling denied *and* this installation's
    owned rules are present. The report must be for the host version this installation integrated.
    """
    from recalith.operations.autostart import read_manifest

    state, manifest = read_manifest(ctx.root)
    integrated = ((manifest or {}).get("adapters") or {}).get(HOST_ID, {}).get("host_version") if state == "ok" else None
    if integrated is None or report.get("host_version") != integrated:
        raise RecalithError("invalid_schema", "the certification report is not for the host version this installation integrated")
    paths = report.get("paths") or {}
    states = {name: (paths.get(name) or {}).get("state", "not_run") for name in CERT_PATHS}
    live = report.get("mode") == "live" and all(s in ("healthy", "degraded", "unavailable") for s in states.values())
    if live:
        delivery = {CERT_PATHS[n]: {"healthy": "certified", "degraded": "failed"}.get(s, "unavailable") for n, s in states.items()}
    else:
        delivery = {p: "unavailable" for p in DELIVERY_PATHS}
    rules = "installed" if (report.get("command_rules") or {}).get("state") == RULES_CERTIFIED and rules_installed(Path(ctx.root)) else "unavailable"
    private = (report.get("private_paths") or {}).get("state")
    record = HostCertification.model_validate({
        "certification_schema": 1, "installation_id": ctx.installation_id, "host_id": HOST_ID, "host_version": integrated,
        "mode": "live" if live else "request_capture", "certified_at": now or utc_now(), "report_digest": report["report_digest"],
        "delivery": delivery, "command_rules": rules, "private_paths": private if private in PRIVATE_STATES else "not_run",
    })
    install.atomic_write(Path(ctx.root) / HOST_FILE, (record.model_dump_json() + "\n").encode("utf-8"))
    return record


__all__ = ["integrate", "remove", "write_host_record", "deny_rules", "spellings", "certified_paths", "configured_permission_mode", "host_version", "rules_installed", "ADMIN_FORMS", "HOST_ID"]


# --------------------------------------------------------------------------
# What health reads (read-only)

PATH_EVENTS = {"session_start": "SessionStart", "prompt": "UserPromptSubmit", "pre_action": "PreToolUse", "compact_restore": "SessionStart"}


def installed_state(root: Path) -> dict[str, Any] | None:
    """Read-only: the ownership record's state and, per owned hook event and for the deny rules, whether they are intact.

    ``None`` when no ``integrate`` ran here (a manifest written by tooling or
    tests). Never writes or repairs anything.
    """
    try:
        record = install.Ownership(Path(root), HOST_ID).load()
    except RecalithError:
        return {"state": "invalid", "hooks": {}, "deny_rules": "unknown"}
    if record is None:
        return None
    try:
        data, _raw = install.read_settings(Path(root) / record["settings_path"])
    except RecalithError:
        return {"state": record.get("state"), "hooks": {}, "deny_rules": "unknown", "settings": "unreadable"}
    hooks: dict[str, str] = {}
    for item in record["owned"].get("hooks") or []:
        state = install._hook_state(data, item["event"], item["group"], fast_claude.LAUNCHER)
        hooks[item["event"]] = "intact" if state == "present" else state
    present = set((data.get("permissions") or {}).get("deny") or [])
    owned = set(record["owned"].get("deny") or [])
    rules = "not_installed" if not owned else ("intact" if owned <= present else "modified")
    return {"state": record.get("state"), "hooks": hooks, "deny_rules": rules, "deny_rule_count": len(owned)}
