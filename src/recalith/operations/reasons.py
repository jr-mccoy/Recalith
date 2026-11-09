"""What each health reason code means and what the operator does about it (OPERATIONS §2 as code; decision 0046).

``recalith status`` and ``doctor`` print these in their human form: one line per
degraded code of a required capability, with the action it implies, and the
one next command. Codes come from :mod:`recalith.operations.health`, the
provider route (:mod:`recalith.providers.base`) and the worker. The JSON form
is unchanged; this module never decides health, only describes it. A code
without an entry is still printed, with a pointer to the operations guide.
"""

from __future__ import annotations

from typing import Any, Mapping

GUIDE = "docs/OPERATIONS.md"
PROBE_PROVIDER = "tools/probe_provider.py --config probe-private/local-config.json --backend BACKEND --route-out ."
PROBE_DELIVERY = "tools/probe_delivery.py --config probe-private/local-config.json --engine-project . --output REPORT"
INTEGRATE = "recalith integrate claude"
START_WORKER = "start a Claude Code session in the project (the first hook starts the worker), or `recalith worker start`"
RECERTIFY = f"re-run the route certification: {PROBE_PROVIDER}"

# code -> (what it means, what to do). Prefixes end in ``:`` and match ``code:detail``.
MEANINGS: dict[str, tuple[str, str]] = {
    # inference: the curator's route
    "provider_not_configured": ("no curator route is configured, so nothing new is learned", f"certify a route from an ordinary terminal: {PROBE_PROVIDER} (OPERATIONS §4)"),
    "provider_config_invalid": ("the recorded route (.recalith/provider.json) does not parse", RECERTIFY),
    "foreign_provider_config": ("the recorded route belongs to another installation", RECERTIFY),
    "request_capture_only": ("the route was only exercised in request-capture mode, never live", f"run the live probe: {PROBE_PROVIDER}"),
    "route_uncertified": ("the route was recorded but its certification did not pass", RECERTIFY),
    "certification_failed:": ("a certification check failed", RECERTIFY),
    "selected_auth_missing": ("the key the route names is not set in the environment being judged", "export the key's variable in the shell that launches Claude Code (the worker inherits it); for this terminal, export it here too"),
    "executable_missing": ("the route's executable is not on PATH", RECERTIFY),
    "executable_changed": ("the route's executable changed since certification", RECERTIFY),
    "host_version_changed": ("the host (Claude Code) version changed since certification", f"recertify: {PROBE_PROVIDER}, then {INTEGRATE}, then {PROBE_DELIVERY}"),
    "adapter_changed": ("this engine's adapter differs from the one certified", RECERTIFY),
    "auth_route_changed": ("the route's key names or key source changed since certification", RECERTIFY),
    "invocation_changed": ("the route's invocation changed since certification", RECERTIFY),
    "invocation_not_isolated:": ("the route's arguments would let the curator reach tools or settings", "fix the invocation in the probe config and recertify"),
    "backend_certification_unavailable": ("this backend cannot be certified in preview", "use claude_cli, anthropic_messages or openai_compatible"),
    "isolation_recheck_pending": ("the worker is rechecking the route's isolation", "wait a moment and run status again"),
    "provider_auth_rejected": ("the provider rejected the key; the route is withdrawn", "fix the key, then recertify"),
    "provider_request_rejected": ("the provider refused the request (credit, terms)", "check the provider account, then recertify"),
    "provider_rate_limited": ("the provider is rate-limiting calls; they retry on the backoff", "nothing, unless it persists"),
    "provider_overloaded": ("the provider is overloaded; calls retry on the backoff", "nothing, unless it persists"),
    "provider_server_error": ("the provider answered with a server error; calls retry", "nothing, unless it persists"),
    "provider_timeout": ("the last call timed out; calls retry on the backoff", "nothing, unless it persists"),
    "provider_failed": ("the last call failed without a named cause; calls retry", "see the worker's status record if it persists"),
    "endpoint_unreachable": ("the endpoint could not be reached", "check the network or proxy settings named in the route"),
    "tls_verification_failed": ("TLS verification of the endpoint failed", "name the CA bundle in network_env_keys; verification is never turned off"),
    "model_mismatch": ("the provider served another model than the configured one; the route is withdrawn", "set expected_resolved_model or fix the model, then recertify"),
    "output_cap_exceeded": ("a reply exceeded the hard output cap; the route is withdrawn", RECERTIFY),
    "provider_not_found": ("the endpoint or model was not found; the route is withdrawn", "fix the URL or model, then recertify"),
    "provider_redirect_refused": ("the endpoint redirected; redirects are never followed", "use the final URL, then recertify"),
    "isolation_tools_exposed": ("the curator could reach tools; the route is withdrawn", "fix the invocation, then recertify"),
    "ordinary_budget_exhausted": ("today's ordinary model budget is spent (UTC day)", "nothing; it resets at the next UTC day"),
    "budget_exhausted:": ("a budget pool is spent for the UTC day", "nothing; it resets at the next UTC day"),
    "provider_unavailable": ("the route is unavailable", RECERTIFY),
    # admission
    "review_provider_unavailable": ("reviews wait because the curator route is unavailable", "see the inference reasons above"),
    "protected_budget_exhausted": ("the protected review budget is spent for the UTC day", "nothing; it resets at the next UTC day"),
    # delivery and the host
    "host_not_integrated": ("Claude Code is not integrated with this project (no hooks installed)", f"from an ordinary terminal: {INTEGRATE}"),
    "delivery_not_certified": ("memory delivery into Claude Code is not certified for this installation", f"after the route: {PROBE_DELIVERY}"),
    "delivery_request_capture_only": ("delivery was only exercised in request-capture mode", f"run the live delivery probe: {PROBE_DELIVERY}"),
    "delivery_path_not_installed": ("a certified delivery path is not in the hook manifest", f"run {INTEGRATE} again"),
    "delivery_path_failed": ("a delivery path failed its live certification", f"re-run {PROBE_DELIVERY}"),
    "delivery_path_unavailable": ("a delivery path is not certified", f"run {PROBE_DELIVERY}"),
    "host_version_uncertified": ("the installed Claude Code version is not capture-certified", "use a certified version, or capture and review fixtures for this one (decision 0019)"),
    "host_version_unknown": ("the Claude Code version could not be read", "make sure `claude` is on PATH, then run integrate again"),
    "host_certification_invalid": ("the host record (.recalith/host.json) does not parse", f"re-run {PROBE_DELIVERY}"),
    "host_hooks_modified": ("an installed hook entry was edited", f"run {INTEGRATE} (or --remove, then integrate)"),
    "hook_context_invalid": ("the hook manifest does not parse", f"run {INTEGRATE} again"),
    "hook_context_relocated": ("the hook manifest was written for another root", "run `recalith workspace rebind` if the project moved, then integrate again"),
    "required_delivery_path_not_certified": ("session-start or prompt delivery is not certified", f"run {PROBE_DELIVERY}"),
    "uncertified_host_version": ("the host version is uncertified: capture is conservative, delivery is off", "use a certified Claude Code version"),
    # operator guard
    "command_deny_rules_not_installed": ("Claude Code's deny rules for administrative commands are not installed", f"run {INTEGRATE}, then the delivery probe certifies them"),
    "command_deny_rules_modified": ("an installed deny rule was edited", f"run {INTEGRATE} again"),
    "command_deny_rules_uncertified": ("the deny rules are installed but no host probe observed them", f"run {PROBE_DELIVERY}"),
    "private_path_probe_not_run": ("the private-path probe has not run for this host version", f"run {PROBE_DELIVERY}"),
    # recovery, worker, store
    "worker_autostart_not_registered": ("no hook start is registered, so no worker starts with a session", f"run {INTEGRATE}"),
    "worker_crashed": ("the worker stopped on an unexpected error", f"{START_WORKER}; the status record names the error type"),
    "worker_error": ("the worker survived a failing step and recorded it", "see the worker's status record (.recalith/run/worker.json)"),
    "worker_heartbeat_stale": ("the worker's heartbeat is old", "stop and restart the worker: `recalith worker stop`, then a session or `recalith worker start`"),
    "worker_status_unavailable": ("a worker holds the lock but its status record is missing or foreign", "restart the worker"),
    "worker_independence_degraded": ("the worker runs inside the host's job object (Windows) and may die with it", "nothing in preview (decision 0027 item 8)"),
    "worker_lock_unsupported": ("this platform has no lock primitive the worker needs", "unsupported platform"),
    "engine_pin_mismatch": ("the tracked engine pin names another version than this engine", "run the bootstrap for the pinned version, or upgrade"),
    "engine_pin_unreadable": ("engine.lock does not parse", "restore it from version control"),
    "store_integrity_check_failed": ("the store failed SQLite's quick check", "restore from a verified backup: `recalith restore PATH --expected-digest D`"),
    "backup_recovery_pending": ("an interrupted backup waits for the worker", START_WORKER),
    "restore_recovery_pending": ("an interrupted restore waits for the worker", START_WORKER),
    "upgrade_recovery_pending": ("an interrupted profile transition waits for the worker", START_WORKER),
    "backup_unavailable_after_forget": ("the backup after a forget failed, so old backups still hold the forgotten text", "fix the backup location, then the worker retries"),
    "ledger_copy_stale": ("the tombstone ledger copy is behind the store", START_WORKER),
    "ingestion_delayed": ("captured events wait in the spool", START_WORKER),
    "scratch_cleanup_pending": ("session scratch files await cleanup", START_WORKER),
    "privacy_maintenance_pending": ("a forget or restore has unfinished phases", START_WORKER),
    "maintenance_in_progress": ("privacy maintenance is running; delivery and model calls wait", "wait for it to finish"),
    "maintenance_marker_stale": ("a maintenance marker is old; a worker may have died mid-maintenance", START_WORKER),
    "revision_chain_findings": ("the revision chain shows out-of-band edits", "run `recalith doctor --full-integrity` and investigate"),
    "revision_chain_not_verified": ("the revision chain has not been verified", "run `recalith doctor`"),
    "revision_chain_full_check_required": ("the chain needs a full check", "run `recalith doctor --full-integrity`"),
    "revision_chain_checkpoint_untrusted": ("the verifier's checkpoint is not trusted", "run `recalith doctor --full-integrity`"),
    "revision_chain_missing_baseline": ("the chain has no baseline", "full release only"),
    "schema_migration_required": ("the store predates this engine's schema and no migration exists in preview", "use the engine the project pins (engine.lock), or a fresh installation"),
    "store_schema_newer": ("the store was written by a newer engine than this one", "use that engine (the project's engine.lock names it)"),
    "store_unreadable": ("the store cannot be opened or its metadata read", "restore from a verified backup: `recalith restore PATH --expected-digest D`"),
    "not_autonomous_ready": ("at least one required capability is not healthy", "see the lines above"),
}


def explain(code: str, coverage: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """``(meaning, action)`` for ``code``; a prefixed code (``budget_exhausted:pool.dimension``) uses its prefix's entry."""
    entry = MEANINGS.get(code)
    if entry is None:
        head = code.split(":", 1)[0] + ":"
        entry = MEANINGS.get(head)
    if entry is None:
        return ("no description registered for this code", f"see {GUIDE} §2")
    meaning, action = entry
    if code == "selected_auth_missing" and coverage:
        source = coverage.get("source")
        if source == "worker":
            meaning = "the running worker's environment lacks the key the route names (the worker inherits the environment of the shell that launched Claude Code)"
            action = "quit Claude Code, export the key's variable in that shell, start Claude Code there again"
        elif source == "configuration":
            meaning = "this terminal's environment lacks the key the route names (no running worker reported its own view)"
            action = "export the key's variable in this shell for the probes, and in the shell that launches Claude Code for the worker"
    return meaning, action


__all__ = ["MEANINGS", "explain", "GUIDE"]
