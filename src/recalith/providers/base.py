"""The provider contract: routes, certification status and isolated calls.

SYSTEM_SPEC §9.1, §6.3; DATA_CONTRACTS §7, §8, §11; decisions 0002, 0006, 0009.

**Explicit route.** A route is the installation's local ``.recalith/provider.json``
(``ProviderConfig``; private, never tracked). Nothing here looks for a CLI on
``PATH`` or picks another provider, model, account, billing route or weaker
launch when the configured one is unavailable: :func:`route_status` names
every reason it is unavailable and the worker keeps its model jobs waiting
(``provider_unavailable``) while capture and typed state continue.

**Certification is rechecked, never assumed.** A route is usable only when its
stored certification came from a complete live observation with the
operator's checked background-use eligibility *and* the executable digest,
the observed host version, the auth key names and expected auth source, and
the invocation (argument array, model, nonsecret switches, network keys) still
equal what was certified. A host or provider version change therefore makes
the route unavailable with ``host_version_changed`` until it is recertified
(review focus 5). A configured ``json_process`` route has no certification
procedure in this build and stays unavailable. Each call additionally
re-checks the host's own init diagnostic (:mod:`claude_cli`); a violation
disables the backend. Direct-API routes (``anthropic_messages``,
``openai_compatible``; decision 0023) pin the shipped adapter's digest instead
of an executable, observe no host version, and each reply is read strictly by
:mod:`api` (a different reported model, a tool call or a cap overrun
withdraws the route).

**Calls.** :class:`ProviderBackend` runs one call in a fresh private root with
the curator environment from the shared stdlib helper, bounded by
:func:`recalith.controller.launch.run_bounded` (argument array, stdin input,
timeout and process-tree termination, 256 KiB wire and 64 KiB stderr caps).
:func:`evaluate_outcome` checks the wire cap, unwraps the certified envelope,
counts the decoded body's original UTF-8 bytes against the purpose cap before
any parsing, then validates each operation strictly; usage and provenance are
appended by this code, never parsed from model text. :func:`complete` is the
DATA_CONTRACTS §11 single-call interface; the worker's model lane uses the
same backend and evaluation between its budget reservation and its charge.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from pydantic import ValidationError

from recalith.contracts.common import InstallationContext, canonical_json, digest_of, utc_now
from recalith.contracts.config import API_BACKENDS, MODEL_INPUT_CAP, PURPOSE_OUTPUT_ALLOWANCE, ProviderConfig, body_cap_for, estimate_tokens
from recalith.contracts.jobs import LocalUsage
from recalith.contracts.operations import ModelRequest, ModelResponse, ResponseProvenance, UsageReport
from recalith.controller import launch
from recalith.controller.budgets import OutputRejected, decode_purpose_body
from recalith.errors import RecalithError
from recalith.fast import failpoints
from recalith.prompts import CURATOR_SYSTEM_PROMPT
from recalith.providers import api, claude_cli, isolation, json_process
from recalith.providers.errors import IsolationViolation, ProviderCallFailed

PROVIDER_FILE = "provider.json"
CHECK_FILE = "provider-check.json"
PROVIDER_SCHEMA = 1
ADAPTER_VERSION = "1"
VERSION_TIMEOUT_SECONDS = 30
ADAPTERS = {"claude_cli": claude_cli, "json_process": json_process, "anthropic_messages": api, "openai_compatible": api}
# The output cap a request-capture isolation check asks for (no purpose allowance applies to it).
CHECK_OUTPUT_CAP = 64
MANAGED_SETTINGS_PATHS = (
    "/etc/claude-code/managed-settings.json",
    "/Library/Application Support/ClaudeCode/managed-settings.json",
    "C:\\ProgramData\\ClaudeCode\\managed-settings.json",
)


# --------------------------------------------------------------------------
# Launch outcomes and output evaluation


@dataclass
class LaunchOutcome:
    stdout: bytes
    overflowed: bool = False
    timed_out: bool = False
    returncode: int | None = 0
    duration_ms: int = 0
    stderr: bytes = b""
    tree_bound: str = "contained"
    tree_cleaned: bool | None = None
    observed_env_keys: list[str] | None = None


@dataclass
class Evaluation:
    code: str | None
    response: ModelResponse | None
    reported: UsageReport | None
    local: LocalUsage | None


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def evaluate_outcome(outcome: LaunchOutcome, backend: Any, *, purpose: str, body_cap: int, estimate: int, adapter_version: str = ADAPTER_VERSION, wire_cap: int | None = None) -> Evaluation:
    """Bound and decode one launch; the wire is checked before the envelope, the body before parsing."""
    result = _evaluate(outcome, backend, purpose=purpose, body_cap=body_cap, estimate=estimate, adapter_version=adapter_version, wire_cap=wire_cap)
    note = getattr(backend, "note_outcome", None)
    if callable(note):
        note(result.code)
    return result


def _reported(usage: Mapping[str, Any], *, estimate: int, output_estimate: int, duration_ms: int) -> UsageReport:
    return UsageReport(
        input_tokens=_count(usage.get("input_tokens")),
        output_tokens=_count(usage.get("output_tokens")),
        estimated_input_tokens=estimate,
        estimated_output_tokens=output_estimate,
        provider_request_id=usage.get("provider_request_id") if isinstance(usage.get("provider_request_id"), str) and len(usage["provider_request_id"]) <= 256 else None,
        duration_ms=max(0, int(duration_ms)),
    )


def _evaluate(outcome: LaunchOutcome, backend: Any, *, purpose: str, body_cap: int, estimate: int, adapter_version: str, wire_cap: int | None) -> Evaluation:
    from recalith.contracts.config import WIRE_STDOUT_CAP

    cap = WIRE_STDOUT_CAP if wire_cap is None else min(wire_cap, WIRE_STDOUT_CAP)
    if outcome.timed_out:
        return Evaluation("provider_timeout", None, None, None)
    if outcome.overflowed or len(outcome.stdout) > cap:
        return Evaluation("wire_stdout_oversized", None, None, None)
    if outcome.returncode != 0:
        return Evaluation("provider_failed", None, None, None)
    try:
        body, usage = backend.unwrap(outcome.stdout)
    except IsolationViolation as exc:
        return Evaluation(exc.code, None, None, None)
    except ProviderCallFailed as exc:  # an API reply that is a failure: charged, with any usage the provider reported
        reported = _reported(exc.usage, estimate=estimate, output_estimate=0, duration_ms=outcome.duration_ms) if exc.usage else None
        return Evaluation(exc.code, None, reported, None)
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        return Evaluation("envelope_invalid", None, None, None)
    local = LocalUsage(input_estimate=estimate, output_estimate=estimate_tokens(len(body)))
    reported = _reported(usage, estimate=estimate, output_estimate=local.output_estimate, duration_ms=outcome.duration_ms)
    try:
        operations, no_op_reason, malformed = decode_purpose_body(body, purpose=purpose, body_cap=body_cap)
    except OutputRejected as exc:
        return Evaluation(exc.code, None, reported, local)
    resolved = usage.get("resolved_model")
    provenance = ResponseProvenance(
        provider_id=str(backend.provider_id)[:64],
        configured_model=str(backend.configured_model)[:128],
        resolved_model=resolved[:128] if isinstance(resolved, str) and resolved else None,
        adapter_version=adapter_version,
    )
    response = ModelResponse(response_schema=1, operations=operations, no_op_reason=no_op_reason, usage=reported, provenance=provenance, malformed=malformed)
    return Evaluation(None, response, reported, local)


# --------------------------------------------------------------------------
# Route configuration and status


def provider_path(root: Path | str) -> Path:
    return Path(root) / ".recalith" / PROVIDER_FILE


def load_provider_config(root: Path | str) -> ProviderConfig | None:
    """The installation's explicit route, or None when none is configured; invalid → ``invalid_schema``."""
    path = provider_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("provider_schema") != PROVIDER_SCHEMA or set(data) != {"provider_schema", "provider"}:
            raise ValueError("unsupported provider file")
        return ProviderConfig.model_validate(data["provider"])
    except (OSError, ValueError, ValidationError) as exc:
        raise RecalithError("invalid_schema", f"the provider configuration is invalid ({type(exc).__name__})") from None


def save_provider_config(root: Path | str, config: ProviderConfig) -> Path:
    """Write the local route file privately (it holds key *names*, never values)."""
    path = provider_path(root)
    tmp = path.with_name(f".{PROVIDER_FILE}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"provider_schema": PROVIDER_SCHEMA, "provider": config.model_dump(mode="json")}, indent=1, sort_keys=True))
    os.replace(tmp, path)
    return path


def invocation_digest(config: ProviderConfig) -> str:
    """What a certification pins about the launch besides executable, version and auth.

    For an API route (decision 0023): the configured and expected models, the
    whole endpoint (URL, dialect, auth header, cap field, JSON mode, API
    version), the auth key names, nonsecret switches and network key names.
    """
    if config.backend in API_BACKENDS:
        assert config.endpoint is not None
        return digest_of([
            config.backend, config.provider_id, config.configured_model, config.expected_resolved_model, config.endpoint.model_dump(mode="json"),
            sorted(config.auth_env_keys), [list(kv) for kv in sorted(config.nonsecret_env.items())], sorted(config.network_env_keys),
        ])
    return digest_of([config.backend, config.provider_id, config.configured_model, list(config.invocation_args), [list(kv) for kv in sorted(config.nonsecret_env.items())], sorted(config.network_env_keys)])


def executable_digest(path: str) -> str | None:
    try:
        h = hashlib.sha256()
        with open(os.path.realpath(path), "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def observe_version(config: ProviderConfig, executable: str, inherited: Mapping[str, str]) -> str | None:
    """``--version`` of the configured executable, run in a private root with a route-free curator environment."""
    with isolation.PrivateRoot() as root:
        env, _report = isolation.curator_environment(config, root, inherited, mode="request_capture")
        result = launch.run_bounded([executable, "--version"], env=env, cwd=root.work, stdin_data=b"", timeout_s=VERSION_TIMEOUT_SECONDS, stdout_cap=4096)
    if result.returncode != 0:
        return None
    return claude_cli.parse_version(result.stdout.decode("utf-8", "replace"))


@dataclass
class RouteStatus:
    state: str  # certified | unavailable
    reasons: list[str] = field(default_factory=list)
    provider_id: str | None = None
    backend: str | None = None
    configured_model: str | None = None
    executable: str | None = None
    observed_version: str | None = None
    certified_version: str | None = None
    auth_route: str | None = None
    auth_key_names: list[str] = field(default_factory=list)
    checked_at: str = field(default_factory=utc_now)

    @property
    def certified(self) -> bool:
        return self.state == "certified"

    def report(self) -> dict[str, Any]:
        return {
            "state": self.state, "reasons": list(self.reasons), "provider_id": self.provider_id, "backend": self.backend, "configured_model": self.configured_model,
            "observed_version": self.observed_version, "certified_version": self.certified_version, "auth_route": self.auth_route,
            "auth_key_names": list(self.auth_key_names), "checked_at": self.checked_at,
            "recertification_required": any(r in RECERTIFY for r in self.reasons),
        }


RECERTIFY = frozenset({"executable_changed", "adapter_changed", "host_version_changed", "auth_route_changed", "invocation_changed"})


def route_status(config: ProviderConfig | None, *, installation_id: str, inherited: Mapping[str, str], observe: bool = True) -> RouteStatus:
    """Every reason the configured route cannot be used now; no fallback is ever chosen."""
    if config is None:
        return RouteStatus("unavailable", ["provider_not_configured"])
    cert = config.certification
    status = RouteStatus(
        "unavailable", [], provider_id=config.provider_id, backend=config.backend, configured_model=config.configured_model,
        certified_version=cert.host_version, auth_route=config.auth_route, auth_key_names=list(config.auth_env_keys),
    )
    reasons = status.reasons
    if config.installation_id != installation_id:
        reasons.append("foreign_provider_config")
    if config.backend == "json_process":
        reasons.append("backend_certification_unavailable")
    elif config.backend == "claude_cli":
        reasons.extend(f"invocation_not_isolated:{p}"[:64] for p in claude_cli.argument_problems(config.invocation_args))
    if not cert.certified:
        reasons.append("request_capture_only" if cert.mode == "request_capture" else "route_uncertified")
        reasons.extend(f"certification_failed:{c}"[:64] for c in cert.failed_checks)
    if config.backend in API_BACKENDS:
        # The shipped adapter is the launched program: its digest is pinned, no host version exists to observe.
        if cert.executable_sha256 is not None and cert.executable_sha256 != api.adapter_digest():
            reasons.append("adapter_changed")
        _auth_and_invocation(config, cert, reasons, inherited)
        status.reasons = list(dict.fromkeys(reasons))
        status.state = "unavailable" if status.reasons else "certified"
        return status
    executable = isolation.resolve_executable(config.executable or "", inherited)
    status.executable = executable
    if executable is None:
        reasons.append("executable_missing")
    else:
        if cert.executable_sha256 is not None and executable_digest(executable) != cert.executable_sha256:
            reasons.append("executable_changed")
        if observe and config.backend == "claude_cli":
            status.observed_version = observe_version(config, executable, inherited)
            if status.observed_version is None:
                reasons.append("host_version_unobserved")
            elif cert.host_version is not None and status.observed_version != cert.host_version:
                reasons.append("host_version_changed")
    _auth_and_invocation(config, cert, reasons, inherited)
    status.reasons = list(dict.fromkeys(reasons))
    status.state = "unavailable" if status.reasons else "certified"
    return status


def _auth_and_invocation(config: ProviderConfig, cert: Any, reasons: list[str], inherited: Mapping[str, str]) -> None:
    if cert.certified:
        if sorted(config.auth_env_keys) != sorted(cert.auth_env_keys) or config.expected_api_key_source != cert.expected_api_key_source:
            reasons.append("auth_route_changed")
        if cert.invocation_digest != invocation_digest(config):
            reasons.append("invocation_changed")
    missing = [k for k in config.auth_env_keys if not inherited.get(k)]
    if missing:
        reasons.append("selected_auth_missing")


# --------------------------------------------------------------------------
# Backends


class ProviderBackend:
    """One configured route as the worker's :class:`~recalith.controller.worker.Backend`.

    ``mode="request_capture"`` (tests and isolation checks) launches without
    route keys and expects nothing of the auth source; it never certifies.
    """

    def __init__(self, config: ProviderConfig, *, inherited: Mapping[str, str] | None = None, mode: str = "live", capture: Mapping[str, str] | None = None, executable: str | None = None, run_dir: Path | None = None, endpoint_url: str | None = None) -> None:
        if mode not in ("live", "request_capture"):
            raise ValueError("mode is live or request_capture")
        if endpoint_url is not None and mode != "request_capture":
            raise ValueError("only a request-capture check points an API route at another endpoint")
        self.config = config
        self.adapter = ADAPTERS[config.backend]
        self.provider_id = config.provider_id
        self.configured_model = config.configured_model
        self.mode = mode
        self.capture = dict(capture or {})
        self.inherited = inherited
        self.is_api = config.backend in API_BACKENDS
        self.endpoint_url = endpoint_url
        cert = config.certification
        live = mode == "live"
        if self.is_api:
            assert config.endpoint is not None
            self.executable = executable or sys.executable  # the worker's own interpreter runs the shipped transport
            self.expect: Any = api.Expect(dialect=config.endpoint.dialect, model=api.expected_model(config))
        else:
            self.executable = executable or isolation.resolve_executable(config.executable or "", self._env()) or config.executable or ""
            self.expect = claude_cli.Expectations(host_version=cert.host_version if live else None, api_key_source=cert.expected_api_key_source if live else None)
        self.last_failure: dict[str, Any] | None = None
        self.last_curator_marker: str | None = None
        self.last_spec: dict[str, Any] | None = None
        self.unavailable_reason: str | None = None
        self.last_environment_report: dict[str, Any] | None = None
        self.last_result: launch.BoundedResult | None = None
        self.run_dir = run_dir
        self._lock = threading.Lock()

    def _env(self) -> Mapping[str, str]:
        return os.environ if self.inherited is None else self.inherited

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None

    def disable(self, reason: str) -> None:
        with self._lock:
            if self.unavailable_reason is None:
                self.unavailable_reason = reason[:64]

    def note_outcome(self, code: str | None) -> None:
        """Remember the last call's failure (content-free) for status; a success clears it."""
        self.last_failure = None if code is None else {"code": code[:64], "at": utc_now()}

    def argv(self) -> list[str]:
        if self.is_api:
            return api.argv(self.executable)
        return self.adapter.argv(self.executable, self.config.invocation_args, model=self.config.configured_model, system_prompt=CURATOR_SYSTEM_PROMPT)

    def stdin_for(self, request: bytes, *, timeout_s: float, purpose: str, output_cap: int | None = None) -> bytes:
        """What the child reads: the request itself, or for an API route the transport specification around the exact body."""
        if not self.is_api:
            return request
        cap = output_cap if output_cap is not None else PURPOSE_OUTPUT_ALLOWANCE.get(purpose, CHECK_OUTPUT_CAP)
        body = api.build_body(self.config, request, output_cap=cap)
        spec = api.transport_spec(self.config, body, output_cap=cap, timeout_s=timeout_s, url=self.endpoint_url)
        self.last_spec = {k: v for k, v in spec.items() if k != "body"}
        return json.dumps(spec, ensure_ascii=False).encode("utf-8")

    def _spawned(self, pid: int, pgid: int | None, root: Path) -> Path | None:
        """Record a launched child before anything waits on it (a test may observe the pid here)."""
        if self.run_dir is None:
            return None
        return record_spawn(self.run_dir, pid=pid, pgid=pgid, root=root)

    def launch(self, request: bytes, *, timeout_s: float, purpose: str, output_cap: int | None = None) -> LaunchOutcome:
        if self.unavailable_reason is not None:
            raise RecalithError("capability_unavailable", f"the provider route is unavailable: {self.unavailable_reason}")
        with isolation.PrivateRoot() as root:
            env, report = isolation.curator_environment(self.config, root, self._env(), mode=self.mode, capture=self.capture)
            self.last_environment_report = report
            self.last_curator_marker = env.get(isolation.process_env.CURATOR_MARKER)
            if self.mode == "live" and report["missing_route_keys"]:
                self.disable("selected_auth_missing")
                raise RecalithError("capability_unavailable", "the selected auth keys are not present")
            spawned: list[Path] = []

            def on_spawn(pid: int, pgid: int | None) -> None:
                path = self._spawned(pid, pgid, root.base)
                if path is not None:
                    spawned.append(path)
                failpoints.hit(failpoints.PROVIDER_AFTER_SPAWN)

            timeout = min(timeout_s, self.config.timeout_seconds)
            stdin = self.stdin_for(request, timeout_s=timeout, purpose=purpose, output_cap=output_cap)
            try:
                result = launch.run_bounded(
                    self.argv(), env=env, cwd=root.work, stdin_data=stdin, timeout_s=timeout,
                    stdout_cap=self.config.max_wire_stdout_bytes, stderr_cap=self.config.max_stderr_bytes, observe_env=True, on_spawn=on_spawn,
                )
            finally:
                for path in spawned:
                    _unlink(path)
        self.last_result = result
        return LaunchOutcome(
            stdout=result.stdout, overflowed=result.stdout_overflow, timed_out=result.timed_out, returncode=result.returncode, duration_ms=result.duration_ms,
            stderr=result.stderr, tree_bound=result.tree_bound, tree_cleaned=result.tree_cleaned, observed_env_keys=result.observed_env_keys,
        )

    def unwrap(self, stdout: bytes) -> tuple[bytes, dict[str, Any]]:
        try:
            return self.adapter.unwrap(stdout, expect=self.expect)
        except IsolationViolation as exc:
            self.disable(exc.code)  # the effective launch (or the provider's reply) no longer matches its certification
            raise


# --------------------------------------------------------------------------
# Spawn records: a curator tree must not outlive a crashed worker


SPAWN_DIR = "curators"


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _start_ticks(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        return int(stat[stat.rfind(")") + 2 :].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def record_spawn(run_dir: Path, *, pid: int, pgid: int | None, root: Path) -> Path:
    """Record a launched curator tree before anything can wait on it (private, content-free)."""
    directory = Path(run_dir) / SPAWN_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{pid}.json"
    record = {"pid": pid, "pgid": pgid, "start_ticks": _start_ticks(pid), "root": str(root), "recorded_at": utc_now()}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(record))
    return path


def reap_orphans(run_dir: Path, *, max_age_seconds: float) -> list[dict[str, Any]]:
    """At worker start (holding the installation lock): end curator trees a dead worker left behind.

    No live worker of this installation can own a recorded tree, so a
    recorded process group that is still alive is killed and its private root
    removed. Windows trees already died with their kill-on-close Job Object.
    A POSIX group is killed only when its leader's recorded start time still
    matches (Linux) or the record is younger than ``max_age_seconds``, so a
    reused group ID is not touched.
    """
    import datetime as _dt
    import shutil
    import signal
    import tempfile

    from recalith.contracts.common import parse_utc

    directory = Path(run_dir) / SPAWN_DIR
    reaped: list[dict[str, Any]] = []
    if not directory.is_dir():
        return reaped
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _unlink(path)
            continue
        pgid = record.get("pgid")
        killed = False
        if os.name != "nt" and isinstance(pgid, int) and pgid > 1 and launch.group_alive(pgid):
            age = (_dt.datetime.now(_dt.timezone.utc) - parse_utc(record.get("recorded_at") or utc_now())).total_seconds()
            ticks = _start_ticks(int(record.get("pid") or 0))
            same_leader = ticks is not None and ticks == record.get("start_ticks")
            if same_leader or age <= max_age_seconds:
                for sig in (signal.SIGKILL,):
                    try:
                        os.killpg(pgid, sig)
                        killed = True
                    except (ProcessLookupError, PermissionError):
                        pass
        root = Path(str(record.get("root") or ""))
        temp = Path(tempfile.gettempdir()).resolve()
        if root.name.startswith("recalith-curator-") and root.parent == temp:
            shutil.rmtree(root, ignore_errors=True)
        _unlink(path)
        reaped.append({"pid": record.get("pid"), "killed": killed})
    return reaped


def complete(request: ModelRequest, config: ProviderConfig, *, inherited: Mapping[str, str] | None = None, backend: Any = None) -> ModelResponse:
    """One isolated provider call (DATA_CONTRACTS §11); raises ``ProviderCallFailed`` with a reason code.

    Without an explicit ``backend`` the configured route must be certified
    now (:func:`route_status`); there is no fallback. Budget reservation and
    charging belong to the worker's model lane, which uses the same backend
    and :func:`evaluate_outcome`.
    """
    env = os.environ if inherited is None else inherited
    if backend is None:
        status = route_status(config, installation_id=config.installation_id, inherited=env)
        if not status.certified:
            raise RecalithError("capability_unavailable", "provider route unavailable: " + ",".join(status.reasons))
        backend = ProviderBackend(config, inherited=env)
    raw = canonical_json(request.model_dump(mode="json"))
    if len(raw) > min(request.limits.max_input_bytes, MODEL_INPUT_CAP):
        raise ProviderCallFailed("model_input_oversized")
    outcome = backend.launch(raw, timeout_s=request.limits.timeout_seconds, purpose=request.purpose)
    result = evaluate_outcome(outcome, backend, purpose=request.purpose, body_cap=min(request.limits.max_body_bytes, body_cap_for(request.purpose)), estimate=estimate_tokens(len(raw)), wire_cap=request.limits.max_wire_stdout_bytes)
    if result.code is not None or result.response is None:
        raise ProviderCallFailed(result.code or "response_invalid")
    return result.response


# --------------------------------------------------------------------------
# Worker wiring


class ProviderSupervisor:
    """The worker's view of its configured route: status, the per-start isolation recheck, and the backend.

    A certified route yields a backend that stays gated until the
    request-capture isolation recheck from the worker's own environment has
    passed; a failed recheck disables it. Without a certified route there is no
    backend and model jobs wait visibly (``provider_unavailable``); a configured
    but uncertified route is still rechecked so its effective isolation is
    reported (never certified) in ``run/provider-check.json``.
    """

    def __init__(self, ctx: InstallationContext, *, inherited: Mapping[str, str] | None = None, recheck: bool = True) -> None:
        self.ctx = ctx
        self.inherited = os.environ if inherited is None else inherited
        self.run_dir = Path(ctx.root) / ".recalith" / "run"
        self.recheck_enabled = recheck
        self.ready = threading.Event()
        self.done = False
        self.check: dict[str, Any] | None = None
        self.backend: ProviderBackend | None = None
        try:
            self.config = load_provider_config(ctx.root)
            self.status = route_status(self.config, installation_id=ctx.installation_id, inherited=self.inherited)
        except RecalithError as exc:
            self.config = None
            self.status = RouteStatus("unavailable", ["provider_config_invalid" if exc.code == "invalid_schema" else exc.code])
        if self.status.certified and self.config is not None:
            self.backend = ProviderBackend(self.config, inherited=self.inherited, run_dir=self.run_dir)
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.config is None or not self.recheck_enabled:
            self.done = True
            self.write()
            self.ready.set()
            return
        self._thread = threading.Thread(target=self._recheck, name="recalith-provider-recheck", daemon=True)
        self._thread.start()

    def _recheck(self) -> None:
        try:
            assert self.config is not None
            self.check = isolation.isolation_check(self.config, inherited=self.inherited)
        except Exception as exc:  # noqa: BLE001 - an unexpected failure withdraws the route, never the worker
            self.check = {"verdict": "fail", "failures": [f"recheck_error:{type(exc).__name__}"[:64]]}
        if self.backend is not None and self.check.get("verdict") != "pass":
            self.backend.disable("isolation_recheck_failed")
        self.done = True
        self.write()  # the record exists before anyone waiting on ``ready`` reads it
        self.ready.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def available(self) -> bool:
        return self.backend is not None and self.done and self.backend.available

    def report(self) -> dict[str, Any]:
        reasons = list(self.status.reasons)
        if self.backend is not None and self.backend.unavailable_reason:
            reasons.append(self.backend.unavailable_reason)
        state = "certified" if self.available else ("checking" if self.backend is not None and not self.done else "unavailable")
        return {
            **self.status.report(),
            "state": state,
            "reasons": reasons,
            "isolation_recheck": None if self.check is None else {k: self.check.get(k) for k in ("verdict", "failures", "mode", "certifies", "host_version")},
            "last_call_failure": None if self.backend is None else self.backend.last_failure,
            "managed_settings_paths_present": sorted(p for p in MANAGED_SETTINGS_PATHS if os.path.exists(p)),
        }

    def write(self) -> None:
        record = {"check_schema": 1, "installation_id": self.ctx.installation_id, "route": self.report(), "isolation_check": self.check}
        path = self.run_dir / CHECK_FILE
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{CHECK_FILE}.{os.getpid()}.tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True))
            os.replace(tmp, path)
        except OSError:
            pass


def read_check(root: Path | str) -> dict[str, Any] | None:
    try:
        return json.loads((Path(root) / ".recalith" / "run" / CHECK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


__all__ = [
    "LaunchOutcome", "OutputRejected", "Evaluation", "evaluate_outcome", "decode_purpose_body", "load_provider_config", "save_provider_config",
    "invocation_digest", "executable_digest", "route_status", "RouteStatus", "ProviderBackend", "complete", "ProviderSupervisor", "read_check",
    "IsolationViolation", "ProviderCallFailed", "record_spawn", "reap_orphans",
]
