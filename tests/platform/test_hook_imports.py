"""The hook fast path imports only the standard library and ``recalith.fast`` (A58).

Each check runs in a fresh interpreter (``-I``), takes the module inventory
after interpreter/site start-up as a baseline, then imports and *runs* the
real entry point on actual Claude 2.1.301 payloads and on its failure paths.
An audit hook records any SQLite connection, socket, subprocess, exec or
spawn: the hook never writes SQLite, calls a model, touches the network or
probes a runtime (SYSTEM_SPEC §5.1.1).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import claude_fixtures as cf

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_MODULES = ("pydantic", "pydantic_core", "packaging", "sqlite3", "_sqlite3", "socket", "ssl", "http", "urllib.request", "subprocess", "tomllib", "dataclasses", "typing", "recalith.contracts", "recalith.capture", "recalith.storage", "recalith.core", "recalith.errors")
AUDIT_EVENTS = ("sqlite3.connect", "socket.connect", "socket.getaddrinfo", "socket.bind", "subprocess.Popen", "os.exec", "os.posix_spawn", "os.spawn", "os.system", "os.startfile", "ctypes.dlopen")

PROBE = r"""
import io, json, os, sys
baseline = set(sys.modules)
seen = []
def audit(event, args):
    if event.startswith(tuple(json.loads(os.environ["RECALITH_TEST_AUDIT"]))):
        seen.append([event, [str(a) for a in args[1]] if event == "subprocess.Popen" else None])
sys.addaudithook(audit)
import importlib
mode = sys.argv[1]
if mode == "package":
    importlib.import_module(sys.argv[2])
else:
    from recalith.fast import entry, failpoints
    for case in json.loads(sys.stdin.read()):
        if case.get("failpoint"):
            failpoints.arm(case["failpoint"], failpoints.DISK_FULL)
        env = dict(os.environ, **case.get("env", {}))
        rc = entry.main(case["argv"], stdin=io.BytesIO(case["stdin"].encode("utf-8")), env=env)
        failpoints.disarm_all()
        assert rc == 0, case
new = sorted(set(sys.modules) - baseline)
print(json.dumps({"new": new, "baseline": sorted(baseline), "audit": seen, "stdlib": sorted(sys.stdlib_module_names)}))
"""


def _run_probe(args: list[str], stdin: str = "") -> dict:
    env = cf.child_env(RECALITH_TEST_AUDIT=json.dumps(AUDIT_EVENTS))
    proc = subprocess.run([sys.executable, "-I", "-c", PROBE, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _assert_clean(report: dict, *, allowed: tuple = ()) -> None:
    stdlib = set(report["stdlib"])
    offenders = [m for m in report["new"] if m.split(".")[0] not in stdlib and m != "recalith" and not m.startswith("recalith.fast")]
    assert offenders == [], f"non-stdlib modules imported by the hook path: {offenders}"
    forbidden = [m for m in report["new"] if any(m == f or m.startswith(f + ".") for f in FORBIDDEN_MODULES if f not in allowed)]
    assert forbidden == [], f"forbidden modules on the hook path: {forbidden}"
    effects = [e for e, _ in report["audit"] if e != "subprocess.Popen" or "subprocess" not in allowed]
    assert effects == [], f"forbidden runtime effects on the hook path: {report['audit']}"
    # Interpreter/site start-up (e.g. a uv ``_virtualenv`` .pth hook) is outside the
    # entry's control, but must not pull in heavy packages either.
    assert not [m for m in report["baseline"] if m.split(".")[0] in ("pydantic", "packaging", "sqlite3")]


@pytest.mark.parametrize("module", ["recalith", "recalith.fast", "recalith.fast.wire", "recalith.fast.wire_generated", "recalith.fast.spool", "recalith.fast.failpoints", "recalith.fast.redact", "recalith.fast.parsers", "recalith.fast.normalize", "recalith.fast.session", "recalith.fast.claude_capture", "recalith.fast.process_env", "recalith.fast.entry"])
def test_each_fast_module_and_package_initializer_is_stdlib_only(module):
    report = _run_probe(["package", module])
    _assert_clean(report)
    if module in ("recalith", "recalith.fast"):
        assert [m for m in report["new"] if m.startswith("recalith")] == (["recalith"] if module == "recalith" else ["recalith", "recalith.fast"])


def test_fast_entry_imports_only_stdlib_and_fast(tmp_path):
    """Real payloads, every capture branch and the failure paths, in one fresh process."""
    replay = cf.Replay(tmp_path)
    cases = []
    for scenario in ("lifecycle", "subagent", "denied"):
        for record in cf.records(scenario):
            cases.append({"argv": ["--project", str(replay.root), "claude_code", "--event", record["event"]], "stdin": replay.prepare(record).decode("utf-8")})
    sample = replay.prepare(cf.records("lifecycle")[1]).decode("utf-8")
    outside = json.dumps(dict(json.loads(sample), cwd=str(tmp_path)))
    bare = tmp_path / "not-a-project"
    bare.mkdir()
    cases += [
        {"argv": ["--project", str(replay.root), "claude_code"], "stdin": "{not json"},  # malformed host input
        {"argv": ["--project", str(replay.root), "claude_code"], "stdin": outside},  # cwd outside the workspace
        {"argv": ["--project", str(bare), "claude_code"], "stdin": sample},  # no hook context manifest
        {"argv": ["--project", str(replay.root), "unknown_host"], "stdin": sample},  # unregistered adapter
        {"argv": ["--project", str(replay.root), "claude_code"], "stdin": sample, "env": {"RECALITH_CURATOR_INSTALLATION": replay.ctx.installation_id}},
        {"argv": ["--project", str(replay.root), "claude_code"], "stdin": sample, "failpoint": "spool.fsync"},  # injected disk full
        {"argv": [], "stdin": sample},  # no arguments at all
    ]
    report = _run_probe(["entry"], json.dumps(cases))
    _assert_clean(report)
    assert "recalith.fast.entry" in report["new"] and "recalith.fast.claude_capture" in report["new"]


def test_hook_wire_tables_match_strict_contracts():
    """The generated validator tables have no drift and every strict rule has a stdlib twin."""
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "generate_hook_wire.py"), "--check"], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr


def test_hook_worker_start_is_the_only_process_effect(tmp_path):
    """With autostart enabled, the hook's one process effect is the registered worker start (A58, A73).

    No SQLite, socket, exec or spawn other than one ``subprocess.Popen`` of
    ``python -I -m recalith.controller.worker`` for this installation, never
    the public ``recalith worker`` CLI; ``subprocess`` is imported only on
    that path. Later hooks find the worker running and launch nothing.
    """
    import worker_hosts as wh

    replay = cf.Replay(tmp_path)
    wh.enable_autostart(replay)
    try:
        cases = []
        for record in cf.records("lifecycle")[:4]:
            cases.append({"argv": ["--project", str(replay.root), "claude_code", "--event", record["event"]], "stdin": replay.prepare(record).decode("utf-8"), "env": {"CLAUDECODE": "1"}})
        report = _run_probe(["entry"], json.dumps(cases))
        _assert_clean(report, allowed=("subprocess",))
        launches = [args for event, args in report["audit"] if event == "subprocess.Popen"]
        assert len(launches) == 1, report["audit"]
        argv = launches[0]
        assert argv[1:5] == ["-I", "-m", "recalith.controller.worker", "--project"] and argv[5] == str(replay.root)
        assert "recalith" not in argv[1:4] and "worker" not in argv[4:]  # not `python -m recalith worker start`
        assert wh.wait_running(replay.root), "the started worker never came up"
    finally:
        wh.stop_worker(replay.root)
