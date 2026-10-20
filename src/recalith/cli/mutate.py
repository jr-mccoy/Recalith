"""Administrative CLI forms behind the operator guard (DATA_CONTRACTS §12; SYSTEM_SPEC §13.1).

:func:`run` applies :mod:`recalith.cli.operator_guard` to the original caller
before anything else; a refusal exits 6 with a content-free audit (when an
installation exists) and no requested effect. Only afterwards is the operator
actor assigned and the form dispatched to the service. Forms whose owning task
is not complete in this build pass the same guard and then answer
``capability_unavailable`` (exit 4); they are still refused (exit 6) for a
marked or unauthorized caller.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from recalith import service
from recalith.cli import operator_guard
from recalith.cli.main import Form, Output, project_root
from recalith.contracts.common import ID_RE, Actor, Scope
from recalith.core import identity
from recalith.errors import RecalithError
from recalith.fast import process_env

MAX_SCOPE_BYTES = 64 * 1024
# Guarded forms whose implementation belongs to a later task (or to the full release).
LATER = {
    "integrate": "Task 13 (Claude Code integration)",
    "integrate_remove": "Task 13 (Claude Code integration)",
    "export": "Task 15 full (portable transfers; full release)",
    "import": "Task 15 full (portable transfers; full release)",
    "import_breadcrumbs": "Task 15 full (Breadcrumbs importer; full release)",
    "upgrade": "Task 17 full (local upgrades; full release)",
    "project_fork": "Task 2 full (project fork; full release)",
    "workspace_attach": "Task 2 full (workspace attachment; full release)",
    "forget_apply": "Task 16 (intentional forgetting)",
    "doctor_probe": "Tasks 13/17 (host and provider probes through doctor)",
}
EXIT_CODE_NAMES = {2: "invalid_schema", 3: "revision_conflict", 4: "capability_unavailable", 5: "storage_failure", 6: "policy_refused"}


def run(args: argparse.Namespace, form: Form, out: Output, environ: Mapping[str, str]) -> int:
    root = project_root(args)
    token_path = getattr(args, "operator_token_file", None)
    try:
        caller = operator_guard.check_caller(environ, token_path=token_path, interactive=operator_guard.interactive_terminal(0), terminal_only=form.terminal_only)
        if form.stage == "installed":
            verifiers, revoked = identity.operator_tokens(root)
            operator_guard.check_installed_token(caller, verifiers, revoked)
    except operator_guard.GuardRefusal as refusal:
        return refuse(out, form, refusal, root)
    actor = operator_guard.operator_actor(caller)  # assigned only now, after every check passed
    return dispatch(args, form, out, environ, root, actor, caller)


def refuse(out: Output, form: Form, refusal: operator_guard.GuardRefusal, root: Path) -> int:
    """Exit 6 before any effect; spool a content-free audit when an installation exists (never create one)."""
    audit = "no_installation"
    if identity.Layout(root).local_toml.exists():
        try:
            ctx = service.resolve(root, actor=service.AUDITOR)
            receipt = service.audit_refusal(ctx, command_kind=form.kind, marker_category=refusal.category)
            audit = "captured" if receipt.status == "accepted" else "unavailable"
        except Exception:  # noqa: BLE001 - audit failure still refuses
            audit = "unavailable"
    return out.failure("policy_refused", refusal.guidance, 6, refusal={"reason": refusal.reason, "category": refusal.category, "audit": audit})


def _scope(path: str) -> Scope:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        raise RecalithError("invalid_schema", "the --scope file cannot be read") from None
    if len(raw) > MAX_SCOPE_BYTES:
        raise RecalithError("invalid_schema", "the --scope file exceeds 64 KiB")
    try:
        return Scope.model_validate(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, ValueError, ValidationError):
        raise RecalithError("invalid_schema", "the --scope file is not a valid Scope object") from None


def dispatch(args: argparse.Namespace, form: Form, out: Output, environ: Mapping[str, str], root: Path, actor: Actor, caller: operator_guard.Caller) -> int:
    k = form.kind
    if k in LATER:
        raise service.unavailable(k.replace("_", " "), LATER[k])
    if k == "operator_token_create":
        try:
            token = operator_guard.create_token_file(args.output)
        except operator_guard.GuardRefusal as refusal:
            return out.failure("policy_refused", refusal.guidance, 6, refusal={"reason": refusal.reason, "category": refusal.category, "audit": "not_applicable"})
        registered = False
        if getattr(args, "project", None) is not None and identity.Layout(root).local_toml.exists():
            service.register_token(root, token.token_id, operator_guard.make_verifier(token))
            registered = True
        return out.success({"token_id": token.token_id, "output": str(Path(args.output)), "registered": registered})
    if k == "operator_token_revoke":
        match = ID_RE.match(args.token_id or "")
        if not match or match.group("prefix") != "tok":
            raise RecalithError("invalid_schema", "TOKEN_ID is a tok_ identifier")
        service.revoke_token(root, args.token_id)
        return out.success({"token_id": args.token_id, "revoked": True})
    if k == "init":
        if identity.Layout(root).local_toml.exists():
            raise RecalithError("policy_refused", "an installation already exists here; init never resets memory")
        if not root.is_dir():
            raise RecalithError("invalid_schema", "--project names an existing directory")
        verifiers = {caller.token.token_id: operator_guard.make_verifier(caller.token)} if caller.token is not None else None
        ctx = service.initialize(root, domain_profile=args.profile, release_profile=args.release_profile, operator_verifiers=verifiers)
        return out.success({"project_id": ctx.project_id, "installation_id": ctx.installation_id, "workspace_id": ctx.workspace_id, "root": str(ctx.root), "operator_token_registered": verifiers is not None})
    if k == "workspace_rebind":
        ctx = service.rebind(root, actor)
        return out.success({"installation_id": ctx.installation_id, "root": str(ctx.root)})
    if k == "workspace_discard_copy":
        service.discard_copy(root, actor)
        return out.success({"discarded": True})
    ctx = service.resolve(root, actor=actor)
    if k == "declare":
        return out.success(service.submit_declaration(ctx, args.kind, args.statement, _scope(args.scope)).report())
    if k == "correct":
        return out.success(service.submit_correction(ctx, args.id, expected_revision=args.expected_revision, statement=args.statement).report())
    if k == "undo_apply":
        return out.success(service.undo_apply(ctx, args.operation_id, preview_digest=args.preview_digest).model_dump(mode="json"))
    if k == "jobs_retry":
        return out.success(service.retry_job(ctx, args.job_id))
    if k == "backup":
        return out.success(service.submit_backup(ctx, Path(args.output)).report())
    if k == "restore":
        service.restore(ctx, Path(args.path), expected_digest=args.expected_digest)  # verifies, then answers Task 16
    if k.startswith("worker_"):
        if args.mode == "session":
            raise service.unavailable("session worker mode", "the full release (Task 4 full)")
        if k == "worker_start":
            return out.success(service.worker_start(ctx, inherited=environ))
        if k == "worker_stop":
            return out.success(service.worker_stop(ctx))
        return _worker_run(ctx, out, environ)
    raise RecalithError("invalid_schema", "unknown administrative form")


def _worker_run(ctx: Any, out: Output, environ: Mapping[str, str]) -> int:
    """``worker run --mode persistent``: the internal worker entry in the foreground with a fresh worker environment."""
    from recalith.controller import worker as worker_module

    argv, env = service.worker_command(ctx, inherited=environ)
    proc = subprocess.Popen(argv, env=env, cwd=process_env.run_dir(str(ctx.root)), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    try:
        code = proc.wait()
    except KeyboardInterrupt:
        worker_module.request_stop(ctx.root)
        try:
            code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = proc.wait()
    if code == 0:
        return out.success({"state": "exited", "exit_code": 0})
    return out.failure(EXIT_CODE_NAMES.get(code, "storage_failure"), "the worker exited with an error", code if code in EXIT_CODE_NAMES else 5)
