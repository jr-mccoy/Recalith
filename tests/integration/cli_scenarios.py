"""Test-only helpers for Task 12a: the real CLI as a subprocess, simulated callers and the crash scenario.

Every CLI call here is a real child process of an installed spelling:
``python -I -m recalith`` (the module), ``python -I -m recalith.cli.main`` and
the project launcher ``.recalith/bin/recalith`` (``recalith.cmd`` on Windows)
on a provisioned runtime. **Simulated callers are controlled test states**:
a host-marked environment (``CLAUDECODE``/``CLAUDE_CODE_CHILD_SESSION`` as
Claude Code 2.1.301 sets them), a worker or curator role marker, and an
interactive controlling terminal given through a real pseudo-terminal (POSIX)
or a real new console (Windows). They are never a production bypass and never
evidence that a live operator workflow on a real IDE host succeeded.
"""

from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import operation_scenarios as osc  # first: puts tests/ and tests/platform on sys.path
import claude_fixtures as cf  # noqa: E402
from recalith.cli import operator_guard  # noqa: E402
from recalith.contracts.common import Actor  # noqa: E402
from recalith.contracts.config import ProjectConfig  # noqa: E402
from recalith.core import identity  # noqa: E402
from recalith.fast import process_env, spool  # noqa: E402
from recalith.storage import db  # noqa: E402

PROJECT_ID = "proj_12121212-1212-4212-8212-121212121212"
OPERATOR = Actor(kind="operator", id="terminal", channel="cli")
SPELLINGS = ("module", "cli_module", "launcher")
MARKERS = {
    "CLAUDECODE": "host_marker",
    "CLAUDE_CODE_CHILD_SESSION": "host_marker",
    process_env.WORKER_MARKER: "worker_marker",
    process_env.CURATOR_MARKER: "curator_marker",
}
POSIX_TTY = os.name != "nt"


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str

    @property
    def obj(self) -> dict[str, Any]:
        lines = [ln for ln in self.stdout.splitlines() if ln.strip()]
        assert len(lines) == 1, f"stdout is not exactly one JSON line: {self.stdout!r} / {self.stderr!r}"
        value = json.loads(lines[0])
        assert isinstance(value, dict)
        return value


def init_project(parent: Path, name: str = "cli") -> Path:
    root = parent / name
    root.mkdir(parents=True)
    identity.initialize_installation(root, ProjectConfig.defaults_for(PROJECT_ID))
    return root


def context(root: Path, actor: Actor = OPERATOR):
    return identity.resolve_installation(root, actor=actor)


def meta(root: Path) -> db.Meta:
    with db.open_store(context(root), readonly=True) as store:
        return store.meta()


def base_env(**extra: str) -> dict[str, str]:
    """An unmarked caller environment (no RECALITH_*/CLAUDE* keys, no PYTHONPATH)."""
    return cf.child_env(**extra)


def marked_env(marker: str, root: Path | None = None, **extra: str) -> dict[str, str]:
    value = "1"
    if marker in (process_env.WORKER_MARKER, process_env.CURATOR_MARKER) and root is not None and (root / ".recalith/local.toml").exists():
        value = context(root).installation_id
    return base_env(**{marker: value}, **extra)


# --------------------------------------------------------------------------
# Spellings


def provision_runtime(root: Path) -> None:
    """A pinned runtime for the launcher: a venv whose site path holds the source tree and this interpreter's dependencies."""
    venv = identity.Layout(root).runtime_python(identity.__version__).parents[1]
    if venv.exists():
        return
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=180)
    target = next(venv.rglob("site-packages"))
    paths = [cf.SRC, *site.getsitepackages()]
    (target / "recalith_runtime.pth").write_text("\n".join(paths) + "\n", encoding="utf-8")


def argv_for(spelling: str, root: Path | None, args: Sequence[str]) -> list[str]:
    project = ["--project", str(root)] if root is not None else []
    if spelling == "module":
        return [sys.executable, "-I", "-m", "recalith", *project, *args]
    if spelling == "cli_module":
        return [sys.executable, "-I", "-m", "recalith.cli.main", *project, *args]
    assert root is not None, "the launcher supplies --project itself"
    if os.name == "nt":
        return ["cmd", "/c", str(root / ".recalith" / "bin" / "recalith.cmd"), *args]
    return ["sh", str(root / ".recalith" / "bin" / "recalith"), *args]


# --------------------------------------------------------------------------
# Running the CLI


def run(argv: Sequence[str], *, env: dict[str, str] | None = None, stdin: bytes = b"", tty: bool | str = False, timeout: float = 120, preexec=None, cwd: Path | None = None) -> Result:
    """One CLI child; ``tty`` gives it a real controlling terminal on standard input.

    ``tty="no_ctty"`` (POSIX) puts a terminal on standard input of a new
    session that has *no* controlling terminal: what a detached or
    agent-launched process with an inherited terminal descriptor looks like.
    """
    env = base_env() if env is None else env
    if tty == "no_ctty":
        return _run_tty(list(argv), env=env, timeout=timeout, cwd=cwd, controlling=False)
    if tty:
        return _run_tty(list(argv), env=env, timeout=timeout, cwd=cwd)
    proc = subprocess.run(list(argv), input=stdin, capture_output=True, env=env, timeout=timeout, check=False, preexec_fn=preexec, cwd=cwd)
    return Result(proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace"))


def _run_tty(argv: list[str], *, env: dict[str, str], timeout: float, cwd: Path | None, controlling: bool = True) -> Result:
    if os.name == "nt":  # pragma: no cover - native Windows
        return _run_console(argv, env=env, timeout=timeout, cwd=cwd)
    import fcntl
    import pty
    import termios

    master, slave = pty.openpty()

    def take_terminal() -> None:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)  # the pty on stdin becomes this new session's controlling terminal

    try:
        proc = subprocess.Popen(argv, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True, preexec_fn=take_terminal if controlling else None, cwd=cwd)
    finally:
        os.close(slave)
    try:
        out, err = proc.communicate(timeout=timeout)
    finally:
        os.close(master)
    return Result(proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


CONSOLE_WRAPPER = r"""
import json, subprocess, sys
spec = json.loads(sys.argv[1])
try:
    conin = open("CONIN$", "rb")
except OSError as exc:
    open(spec["result"], "w", encoding="utf-8").write(json.dumps({"console": False, "error": str(exc)}))
    sys.exit(0)
with open(spec["out"], "wb") as out, open(spec["err"], "wb") as err:
    code = subprocess.call(spec["argv"], stdin=conin, stdout=out, stderr=err, env=spec["env"], cwd=spec["cwd"])
open(spec["result"], "w", encoding="utf-8").write(json.dumps({"console": True, "code": code}))
"""


def _run_console(argv: list[str], *, env: dict[str, str], timeout: float, cwd: Path | None) -> Result:  # pragma: no cover - native Windows
    """A real new console: the CLI's standard input is that console's input handle."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        spec = {"argv": argv, "env": env, "cwd": str(cwd) if cwd else None, "out": os.path.join(tmp, "out"), "err": os.path.join(tmp, "err"), "result": os.path.join(tmp, "result.json")}
        proc = subprocess.Popen([sys.executable, "-I", "-c", CONSOLE_WRAPPER, json.dumps(spec)], creationflags=subprocess.CREATE_NEW_CONSOLE, env=env)
        proc.wait(timeout=timeout)
        result = json.loads(Path(spec["result"]).read_text(encoding="utf-8"))
        if not result["console"]:
            import pytest

            pytest.skip(f"no console could be attached on this runner: {result['error']}")
        return Result(result["code"], Path(spec["out"]).read_text(encoding="utf-8", errors="replace"), Path(spec["err"]).read_text(encoding="utf-8", errors="replace"))


def cli(root: Path | None, *args: str, spelling: str = "module", **kw: Any) -> Result:
    return run(argv_for(spelling, root, args), **kw)


# --------------------------------------------------------------------------
# Tokens, effects and audits


def token(path: Path) -> operator_guard.OperatorTokenFile:
    """An explicitly provisioned fixture token (the evaluation/CI bootstrap input; never committed)."""
    return operator_guard.create_token_file(path)


def register(root: Path, tok: operator_guard.OperatorTokenFile) -> None:
    identity.update_operator_tokens(root, register={tok.token_id: operator_guard.make_verifier(tok)})


def tree(root: Path) -> dict[str, str]:
    """Digest of every file except the spool (where the audit lands) and SQLite sidecars."""
    import hashlib

    out = {}
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir() or rel.startswith((".recalith/spool/", ".recalith/runtime/")) or rel.endswith(("-wal", "-shm")):
            continue
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def store_rows(root: Path) -> dict[str, Any]:
    """Authoritative store content that a refused command must not touch."""
    with db.open_store(context(root), readonly=True) as store, store.read() as view:
        tables = [r[0] for r in view.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
        counts = {t: view.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}  # noqa: S608 - names from sqlite_master
    m = meta(root)
    return {"counts": counts, "store_revision": m.store_revision, "guidance_epoch": m.guidance_epoch}


def audit_events(root: Path) -> list[dict[str, Any]]:
    out = []
    for path in spool.ready_segments(spool.SpoolDirs(root)):
        segment = json.loads(path.read_text(encoding="utf-8"))
        out += [e for e in segment["envelopes"] if e["kind"] == "agent_attempted_operator_command"]
    return out


def audit_segments_text(root: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in spool.ready_segments(spool.SpoolDirs(root)))


def block_spool(root: Path) -> None:
    """Make durable spool publication fail (a regular file where the ready directory must be)."""
    ready = spool.SpoolDirs(root).ready
    shutil.rmtree(ready, ignore_errors=True)
    ready.write_bytes(b"blocked")


def unblock_spool(root: Path) -> None:
    ready = spool.SpoolDirs(root).ready
    if ready.is_file():
        ready.unlink()
    ready.mkdir(exist_ok=True)


def wait_for(predicate, timeout: float, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


def seconds_since(start: float) -> float:
    return time.monotonic() - start


__all__ = ["osc"]


# --------------------------------------------------------------------------
# The kill/restart scenario (driven by worker_scenarios.py)
#
# An operator session of guarded service writes, retried as a whole after a
# kill (an operator re-running the same commands): a token-provisioned first
# init of a fresh checkout, a typed declaration, a correction of an admitted
# declaration, and a retry of a failed job. Each write is one transaction (the
# init's completing ``local.toml`` write is its own boundary); a retried
# command must have exactly one effect.

SCENARIO = "service.json"
DECLARED = "Keep the fixture tests on pytest; never migrate them."
TARGET_TEXT = "Always run the fixture tests with pytest -q."
TARGET = "The fixture tests run with pytest -q."
CORRECTION = "Run the fixture tests with pytest -x so the first failure stops the run."


def crash_project(tmp: Path, name: str) -> Path:
    import admission_scenarios as adm
    import consolidation_scenarios as cns
    from recalith.controller import jobs
    from recalith.contracts.common import utc_now

    p = adm.project(tmp, name)
    target = cns.declaration(p, TARGET_TEXT, TARGET, subject="test runner")
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="maintenance", input_refs=[], now=utc_now())
        job = jobs.get_job(txn, job_id)
        jobs._save(txn, job.model_copy(update={"state": "failed", "last_error_code": "fixture_failure"}))
    token_path = tmp / name / "operator.token"
    tok = token(token_path)
    register(p.root, tok)
    fresh = tmp / name / "fresh"
    fresh.mkdir()
    with db.open_store(p.ctx, readonly=True) as store, store.read() as view:
        from recalith.storage import records

        revision = records.head(view, "claim", target)[0]
    spec = {"target": target, "target_revision": revision, "job": job_id, "token": str(token_path), "fresh": str(fresh)}
    (p.root / SCENARIO).write_text(json.dumps(spec), encoding="utf-8")
    return p.root


def scenario(root: Path) -> dict[str, Any] | None:
    path = root / SCENARIO
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def run_script(root: Path, spec: dict[str, Any]) -> None:
    """The operator's commands through the service (the guard is exercised by the CLI tests)."""
    from recalith import service
    from recalith.contracts.common import Scope
    from recalith.controller import jobs

    fresh = Path(spec["fresh"])
    if not (fresh / ".recalith" / "local.toml").exists():  # the CLI refuses init once local.toml exists
        tok = operator_guard.load_token_file(spec["token"])
        service.initialize(fresh, domain_profile="coding", release_profile="claude_preview", operator_verifiers={tok.token_id: operator_guard.make_verifier(tok)})
    ctx = context(root)
    service.submit_declaration(ctx, "decision", DECLARED, Scope())
    service.submit_correction(ctx, spec["target"], expected_revision=spec["target_revision"], statement=CORRECTION)
    with db.open_store(ctx, readonly=True) as store, store.read() as view:
        state = jobs.get_job(view, spec["job"]).state
    if state == "failed":  # an operator retries only a job that still shows failed
        service.retry_job(ctx, spec["job"])


def _owed(root: Path, spec: dict[str, Any]) -> list[str]:
    """Commands whose effect is not yet recorded, judged from the effects themselves (never a progress flag)."""
    import sqlite3

    from recalith.contracts.common import derived_id, digest_of

    owed = []
    fresh = Path(spec["fresh"])
    try:
        verifiers, _revoked = identity.operator_tokens(fresh)
        tok = operator_guard.load_token_file(spec["token"])
        if not operator_guard.verifier_matches(verifiers.get(tok.token_id, ""), tok):
            owed.append("init")
    except Exception:  # noqa: BLE001 - no complete installation yet
        owed.append("init")
    path = root / ".recalith" / db.STATE_DB
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        installation = conn.execute("SELECT installation_id FROM installation_meta").fetchone()[0]
        declared_key = "operator_declaration:" + digest_of(["decision", DECLARED, {"workspace_ids": [], "task_ids": [], "branch_refs": [], "paths": [], "environment": {}}])
        declared = derived_id("evt", [installation, "recalith_cli", declared_key])
        if not _cited(conn, declared) or not conn.execute("SELECT COUNT(*) FROM review_requests WHERE origin = 'typed_declaration'").fetchone()[0]:
            owed.append("declare")
        status = conn.execute("SELECT status FROM claim_heads WHERE claim_id = ?", (spec["target"],)).fetchone()[0]
        reviews = conn.execute("SELECT COUNT(*) FROM review_requests WHERE origin = 'operator_correction'").fetchone()[0]
        if status != "invalidated" or reviews == 0:
            owed.append("correct")
        job = json.loads(conn.execute("SELECT body FROM jobs WHERE job_id = ?", (spec["job"],)).fetchone()[0])
        if job["state"] == "failed":
            owed.append("retry")
    except sqlite3.Error:
        owed.append("store")
    finally:
        conn.close()
    return owed


def _cited(conn, event_id: str) -> bool:
    """A claim revision citing the declaration event as support (the declaration's effect)."""
    for (body,) in conn.execute("SELECT body FROM claim_revisions WHERE body IS NOT NULL").fetchall():
        if event_id in body:
            return True
    return False


def outstanding(root: Path) -> str:
    spec = scenario(root)
    assert spec is not None
    return "1" if _owed(root, spec) else "0"


def service_state(root: Path) -> dict[str, Any]:
    """The authoritative effects of the operator session, with random IDs and salts normalized."""
    spec = scenario(root)
    assert spec is not None
    fresh = Path(spec["fresh"])
    tok = operator_guard.load_token_file(spec["token"])
    try:
        verifiers, revoked = identity.operator_tokens(fresh)
        init = {"installed": True, "verifies": operator_guard.verifier_matches(verifiers.get(tok.token_id, ""), tok), "verifiers": len(verifiers), "revoked": len(revoked), "store": (fresh / ".recalith" / db.STATE_DB).exists()}
    except Exception as exc:  # noqa: BLE001
        init = {"installed": False, "error": type(exc).__name__}
    with db.open_store(context(root), readonly=True) as store, store.read() as view:
        claims = sorted(
            (body["proposition"], status, body["basis"], body["kind"], body["strength"], rev)
            for claim_id, rev, status in view.execute("SELECT claim_id, revision, status FROM claim_heads").fetchall()
            for body in [json.loads(view.execute("SELECT body FROM claim_revisions WHERE claim_id = ? AND revision = ?", (claim_id, rev)).fetchone()[0])]
        )
        events = sorted(r for r in view.execute("SELECT event_id, kind FROM events WHERE adapter_id = 'recalith_cli'").fetchall())
        reviews = sorted(r for r in view.execute("SELECT origin, partition_index FROM review_requests").fetchall())
        jobs_ = sorted(r for r in view.execute("SELECT kind, state FROM jobs").fetchall())
        operations = sorted(r for r in view.execute("SELECT kind, COUNT(*) FROM operations GROUP BY kind").fetchall())
        m = store.meta()
    return {"init": init, "claims": claims, "events": events, "reviews": reviews, "jobs": jobs_, "operations": operations, "revision": m.store_revision, "epoch": m.guidance_epoch}
