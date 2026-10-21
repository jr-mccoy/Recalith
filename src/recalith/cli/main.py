"""``recalith`` command-line transport: parsing, the guard, dispatch and output (DATA_CONTRACTS §12).

Exactly the command forms of DATA_CONTRACTS §12. With ``--json`` stdout is
exactly one JSON object; human diagnostics go to stderr and never carry
source bodies, statements, token contents or arguments. Both are written as
UTF-8 whatever the console's text encoding (a Windows pipe defaults to the
code page). Exit codes: 0
success, 2 invalid input, 3 revision conflict, 4 unavailable capability
(including ``installation_relocated``), 5 storage failure, 6 policy refusal,
7 ``not_captured``, 8 ``capability_degraded``.

Order for an administrative form (SYSTEM_SPEC §13.1): syntax is parsed
first (a syntax error is 2); then :mod:`recalith.cli.operator_guard` inspects
the original caller (markers, then token shape, then terminal or token, then
the installation's verifier) **before any actor is assigned**; a refusal
spools a content-free audit when an installation exists and exits 6 before
any requested effect or child environment. Only then is the operator actor
assigned and the form dispatched to :mod:`recalith.cli.mutate`. Read-only
forms (:mod:`recalith.cli.inspect`) carry no authority (a ``host_agent``
reader). No command accepts an actor argument, and nothing here holds
business policy: the service and domain decide.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from recalith.errors import RecalithError

EXIT_OK = 0
EXIT_DEGRADED = 8


class ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise ArgError(message)


@dataclass(frozen=True)
class Form:
    """One command form: its content-free kind, and whether/how the operator guard applies."""

    kind: str
    admin: bool = False
    stage: str = "installed"  # pre_init (token create, init) | installed
    terminal_only: bool = False


# --------------------------------------------------------------------------
# Parsing


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", default=argparse.SUPPRESS, metavar="PATH")
    common.add_argument("--operator-token-file", dest="operator_token_file", default=argparse.SUPPRESS, metavar="PATH")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = _Parser(prog="recalith", parents=[common], description="Recalith project memory")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def add(name: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common])

    p = add("init")
    p.add_argument("--profile", choices=("coding", "general"), required=True)
    p.add_argument("--release-profile", dest="release_profile", choices=("claude_preview", "full"), required=True)
    add("status")
    p = add("doctor")
    p.add_argument("--full-integrity", dest="full_integrity", action="store_true")
    p.add_argument("--probe-host", dest="probe_host", metavar="HOST")
    p.add_argument("--probe-provider", dest="probe_provider", metavar="PROVIDER")
    p = add("worker")
    p.add_argument("action", choices=("start", "stop", "run"))
    p.add_argument("--mode", choices=("persistent", "session"), default="persistent")
    p = add("integrate")
    p.add_argument("host")
    p.add_argument("--autostart", action="store_true")
    p.add_argument("--shared", action="store_true")
    p.add_argument("--remove", action="store_true")
    p = add("declare")
    p.add_argument("kind", choices=("decision", "preference"))
    p.add_argument("--statement", required=True)
    p.add_argument("--scope", required=True, metavar="FILE")
    p = add("observe")
    p.add_argument("--stdin", action="store_true", required=True)
    p = add("context")
    p.add_argument("--purpose", required=True, choices=("session_start", "prompt", "pre_action", "compact_restore", "manual"))
    p.add_argument("--session", required=True)
    p.add_argument("--task")
    p.add_argument("--stdin", action="store_true", required=True)
    p = add("search")
    p.add_argument("query")
    p.add_argument("--history", action="store_true")
    p.add_argument("--limit", type=int)
    p = add("show")
    p.add_argument("id")
    p.add_argument("--revision", type=int)
    for group in ("tasks", "episodes", "claims"):
        p = add(group)
        p.add_argument("--status")
        p.add_argument("--limit", type=int)
        p.add_argument("--after")
    p = add("correct")
    p.add_argument("id")
    p.add_argument("--expected-revision", dest="expected_revision", type=int, required=True)
    p.add_argument("--statement", required=True)
    p = add("undo")
    p.add_argument("operation_id")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--preview-digest", dest="preview_digest")
    p = add("forget")
    p.add_argument("--selector", required=True, metavar="FILE")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    p.add_argument("--preview-digest", dest="preview_digest")
    p = add("jobs")
    p.add_argument("action", choices=("list", "retry"))
    p.add_argument("job_id", nargs="?")
    p.add_argument("--limit", type=int)
    p = add("backup")
    p.add_argument("--output", required=True)
    p = add("restore")
    p.add_argument("path")
    p.add_argument("--expected-digest", dest="expected_digest", required=True)
    p = add("export")
    p.add_argument("--selection", required=True)
    p.add_argument("--output", required=True)
    p = add("import")
    p.add_argument("path")
    p.add_argument("--expected-digest", dest="expected_digest")
    p.add_argument("--source")
    p = add("upgrade")
    p.add_argument("--wheel", required=True)
    p.add_argument("--expected-digest", dest="expected_digest", required=True)
    p.add_argument("--release-profile", dest="release_profile", choices=("claude_preview", "full"))
    p = add("workspace")
    p.add_argument("action", choices=("attach", "rebind", "discard-copy"))
    p.add_argument("path", nargs="?")
    p = add("project")
    p.add_argument("action", choices=("fork",))
    p = add("operator-token")
    p.add_argument("action", choices=("create", "revoke"))
    p.add_argument("token_id", nargs="?")
    p.add_argument("--output")
    return parser


def parse(argv: Sequence[str]) -> argparse.Namespace:
    args = build_parser().parse_args(list(argv))
    _check_shapes(args)
    return args


def _check_shapes(args: argparse.Namespace) -> None:
    """Syntax rules argparse cannot express (still exit 2, before the guard)."""
    c = args.command
    if c in ("undo", "forget") and args.apply and not args.preview_digest:
        raise ArgError(f"{c} --apply requires --preview-digest")
    if c in ("undo", "forget") and args.preview and args.preview_digest:
        raise ArgError(f"{c} --preview takes no --preview-digest")
    if c == "jobs" and (args.action == "retry") != (args.job_id is not None):
        raise ArgError("jobs retry takes exactly one JOB_ID; jobs list takes none")
    if c == "operator-token":
        if args.action == "create" and (args.output is None or args.token_id is not None):
            raise ArgError("operator-token create --output PATH")
        if args.action == "revoke" and (args.token_id is None or args.output is not None):
            raise ArgError("operator-token revoke TOKEN_ID")
    if c == "workspace" and (args.action == "attach") != (args.path is not None):
        raise ArgError("workspace attach PATH; rebind and discard-copy take no path")
    if c == "import":
        breadcrumbs = args.path == "breadcrumbs" and args.source is not None
        if not breadcrumbs and (args.expected_digest is None or args.source is not None):
            raise ArgError("import PATH --expected-digest DIGEST, or import breadcrumbs --source PATH")
    if c == "integrate" and args.remove and (args.autostart or args.shared):
        raise ArgError("integrate HOST --remove takes no other option")


def form_of(args: argparse.Namespace) -> Form:
    c = args.command
    admin = {
        "init": Form("init", True, "pre_init"),
        "declare": Form("declare", True),
        "correct": Form("correct", True),
        "integrate": Form("integrate_remove" if getattr(args, "remove", False) else "integrate", True),
        "backup": Form("backup", True),
        "restore": Form("restore", True),
        "export": Form("export", True),
        "upgrade": Form("upgrade", True),
        "project": Form("project_fork", True),
    }
    if c in admin:
        return admin[c]
    if c == "worker":
        return Form(f"worker_{args.action}", True)
    if c == "undo":
        return Form("undo_apply", True) if args.apply else Form("undo_preview")
    if c == "forget":
        return Form("forget_apply", True) if args.apply else Form("forget_preview")
    if c == "jobs":
        return Form("jobs_retry", True) if args.action == "retry" else Form("jobs_list")
    if c == "import":
        return Form("import_breadcrumbs" if args.source is not None else "import", True)
    if c == "workspace":
        return Form("workspace_" + args.action.replace("-", "_"), True)
    if c == "operator-token":
        return Form("operator_token_" + args.action, True, "pre_init" if args.action == "create" else "installed", terminal_only=True)
    if c == "doctor" and (args.probe_host or args.probe_provider):
        return Form("doctor_probe", True)
    return Form(c)


# --------------------------------------------------------------------------
# Output


def _emit(stream: Any, text: str) -> None:
    """Write ``text`` as UTF-8, whatever the stream's text encoding (a Windows pipe defaults to the console code page)."""
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text)
        stream.flush()
        return
    stream.flush()
    buffer.write(text.encode("utf-8"))
    buffer.flush()


class Output:
    def __init__(self, *, as_json: bool, command: str, stdout: Any = None, stderr: Any = None) -> None:
        self.as_json = as_json
        self.command = command
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr

    def _write(self, obj: Mapping[str, Any]) -> None:
        text = json.dumps(obj, ensure_ascii=False, sort_keys=True) if self.as_json else json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)
        _emit(self.stdout, text + "\n")

    def success(self, result: Any, *, degraded: Sequence[str] = ()) -> int:
        body: dict[str, Any] = {"ok": True, "command": self.command, "result": result}
        if degraded:
            body["status"] = "capability_degraded"
            body["degraded"] = list(degraded)
        self._write(body)
        return EXIT_DEGRADED if degraded else EXIT_OK

    def failure(self, code: str, message: str, exit_code: int, **extra: Any) -> int:
        body = {"ok": False, "command": self.command, "error": code, "message": message, "exit_code": exit_code, **extra}
        if self.as_json:
            self._write(body)
        else:
            self.stdout.flush()
        _emit(self.stderr, f"recalith: {code}: {message}\n")
        return exit_code

    def error(self, exc: RecalithError, **extra: Any) -> int:
        return self.failure(exc.code, exc.message, exc.exit_code, **extra)


# --------------------------------------------------------------------------
# Entry


def project_root(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "project", None) or os.getcwd())


def main(argv: Sequence[str] | None = None) -> int:
    from recalith.cli import inspect, mutate

    environ = dict(os.environ)  # the original caller's environment, never modified
    raw = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in raw
    try:
        args = parse(raw)
    except ArgError as exc:
        return Output(as_json=as_json, command="invalid").failure("invalid_schema", str(exc), 2)
    form = form_of(args)
    out = Output(as_json=bool(getattr(args, "json", False)) or as_json, command=form.kind)
    try:
        if form.admin:
            return mutate.run(args, form, out, environ)
        return inspect.run(args, form, out, environ)
    except RecalithError as exc:
        return out.error(exc)
    except KeyboardInterrupt:
        return out.failure("capability_unavailable", "interrupted", 4)
    except Exception as exc:  # noqa: BLE001 - one object, no source bodies, no traceback content
        return out.failure("storage_failure", f"unexpected {type(exc).__name__}", 5)


if __name__ == "__main__":
    sys.exit(main())
