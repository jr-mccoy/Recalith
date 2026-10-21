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
import re
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
        cmd = args[1] if event == "subprocess.Popen" else None
        if event == "sqlite3.connect":
            seen.append([event, str(args[0])])
        else:
            seen.append([event, (cmd if isinstance(cmd, str) else [str(a) for a in cmd]) if cmd is not None else None])
sys.addaudithook(audit)
import importlib
mode = sys.argv[1]
if mode == "package":
    importlib.import_module(sys.argv[2])
elif mode == "compile":
    import time
    from recalith.fast import entry
    from recalith.fast import context as fc
    packets = []
    for case in json.loads(sys.stdin.read()):
        ctx = entry.load_context(case["root"], "claude_code")
        packets.append(fc.hook_compile_context(ctx, case["query"], deadline=time.monotonic() + 2))
    print(json.dumps({"packets": packets}))
elif mode == "deliver":
    from recalith.fast import entry, failpoints
    outputs = []
    for case in json.loads(sys.stdin.read()):
        if case.get("failpoint"):
            failpoints.arm(case["failpoint"], failpoints.DISK_FULL)
        out = io.BytesIO()
        rc = entry.main(case["argv"], stdin=io.BytesIO(case["stdin"].encode("utf-8")), env=dict(os.environ, **case.get("env", {})), stdout=out)
        failpoints.disarm_all()
        assert rc == 0, case
        outputs.append(out.getvalue().decode("utf-8"))
    print(json.dumps({"outputs": outputs}))
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
    effects = [e for e, _ in report["audit"] if not (e == "subprocess.Popen" and "subprocess" in allowed) and not (e.startswith("sqlite3.connect") and "sqlite3" in allowed)]
    assert effects == [], f"forbidden runtime effects on the hook path: {report['audit']}"
    # Interpreter/site start-up (e.g. a uv ``_virtualenv`` .pth hook) is outside the
    # entry's control, but must not pull in heavy packages either.
    assert not [m for m in report["baseline"] if m.split(".")[0] in ("pydantic", "packaging", "sqlite3")]


@pytest.mark.parametrize("module", ["recalith", "recalith.fast", "recalith.fast.context", "recalith.fast.delivery", "recalith.fast.cache", "recalith.fast.fence", "recalith.fast.wire", "recalith.fast.wire_generated", "recalith.fast.spool", "recalith.fast.failpoints", "recalith.fast.redact", "recalith.fast.parsers", "recalith.fast.normalize", "recalith.fast.session", "recalith.fast.claude_capture", "recalith.fast.claude", "recalith.fast.process_env", "recalith.fast.entry"])
def test_each_fast_module_and_package_initializer_is_stdlib_only(module):
    report = _run_probe(["package", module])
    # The read-only snapshot modules (and the delivery branch on them) may import sqlite3; nothing else may.
    _assert_clean(report, allowed=("sqlite3", "_sqlite3") if module in ("recalith.fast.delivery", "recalith.fast.cache", "recalith.fast.fence") else ())
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
        if isinstance(argv, str):  # Windows audits the CreateProcess command line, one string
            assert subprocess.list2cmdline(["-I", "-m", "recalith.controller.worker", "--project", str(replay.root)]) in argv, argv
            assert " -m recalith " not in argv and " worker start" not in argv
        else:
            assert argv[1:5] == ["-I", "-m", "recalith.controller.worker", "--project"] and argv[5] == str(replay.root)
            assert "recalith" not in argv[1:4] and "worker" not in argv[4:]  # not `python -m recalith worker start`
        assert wh.wait_running(replay.root), "the started worker never came up"
    finally:
        wh.stop_worker(replay.root)


def test_hook_context_compiler_is_stdlib_and_read_only(tmp_path):
    """The hook compiler (views, fallback, fence) imports only stdlib and ``recalith.fast`` and opens SQLite read-only (A58).

    Real payloads, a published projection (warm views), then a stale one
    (fallback rows) and a missing store (degraded). The only SQLite effect is
    ``sqlite3.connect`` on a ``mode=ro`` URI (never ``immutable=1``); no
    socket, subprocess or exec; no Pydantic, ``packaging``, service, storage or
    retrieval module.
    """
    sys.path.insert(0, str(ROOT / "tests" / "integration"))
    import consolidation_scenarios as cs
    import retrieval_scenarios as rs

    p = rs.project(tmp_path)
    cs.lesson(p)
    rs.publish(p)
    act = rs.mid_action(p)
    warm = rs.query(p, act=act).model_dump(mode="json")
    prompt = rs.query(p, "prompt", text="fixture test_mid", act=act).model_dump(mode="json")
    cases = [{"root": str(p.root), "query": warm}, {"root": str(p.root), "query": prompt}]
    report = _run_probe(["compile"], json.dumps(cases))
    cs.fact(p, "A later fact makes the views stale.", subject="later")
    stale = _run_probe(["compile"], json.dumps(cases))
    (p.root / ".recalith" / "state" / "memory.sqlite").rename(p.root / "moved.sqlite")
    gone = _run_probe(["compile"], json.dumps(cases[:1]))
    for rep in (report, stale, gone):
        _assert_clean(rep, allowed=("sqlite3", "_sqlite3"))
        connects = [args for event, args in rep["audit"] if event == "sqlite3.connect"]
        assert all("mode=ro" in a and "immutable" not in a for a in connects), connects
        assert not [m for m in rep["new"] if m.startswith(("recalith.retrieval", "recalith.storage", "recalith.contracts", "recalith.controller"))]
    assert {e for e, _ in report["audit"]} == {"sqlite3.connect", "sqlite3.connect/handle"}  # snapshots and the fresh fence only


def test_hook_delivery_branch_is_stdlib_and_read_only(tmp_path):
    """The delivery branch (Task 12b) on real payloads: stdlib and ``recalith.fast`` only, SQLite read-only, no other effect (A58).

    A controlled test manifest enables every delivery path; the replayed
    session emits a session-start lookup, a prompt, a pre-action caution, the
    overlay update, a compaction restoration and the session end, plus a
    disk-full receipt spool. The only SQLite effect is ``sqlite3.connect`` on
    ``mode=ro`` URIs; no socket, subprocess (autostart off) or exec; no
    Pydantic, ``packaging``, service, CLI, storage, retrieval or contracts
    module. Receipts go to the spool, never to SQLite.
    """
    sys.path.insert(0, str(ROOT / "tests" / "integration"))
    import delivery_scenarios as ds

    p, ids = ds.project(tmp_path)
    host = ds.fresh_session(70)
    pre, post = ds.call_records(ds.MID, "imp", session=host)
    records = [ds.in_session(ds.record("SessionStart"), host), ds.wks.variant(ds.record("UserPromptSubmit"), session=host, prompt="Fix test_mid's fixture."), pre, post,
               ds.in_session(ds.record("PreCompact"), host), ds.in_session(ds.record("SessionStart", n=1), host), ds.in_session(ds.record("SessionEnd"), host)]
    cases = [{"argv": ["--project", str(p.root), "claude_code", "--event", r["event"]], "stdin": p.replay.prepare(r).decode("utf-8")} for r in records]
    pre2, _ = ds.call_records(ds.MID, "imp2", session=ds.fresh_session(71))
    cases.append({"argv": ["--project", str(p.root), "claude_code", "--event", pre2["event"]], "stdin": p.replay.prepare(pre2).decode("utf-8"), "failpoint": "spool.fsync"})
    env = cf.child_env(RECALITH_TEST_AUDIT=json.dumps(AUDIT_EVENTS))
    proc = subprocess.run([sys.executable, "-I", "-c", PROBE, "deliver"], input=json.dumps(cases), capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-3000:]
    lines = proc.stdout.strip().splitlines()
    outputs, report = json.loads(lines[-2])["outputs"], json.loads(lines[-1])
    _assert_clean(report, allowed=("sqlite3", "_sqlite3"))
    connects = [args for event, args in report["audit"] if event == "sqlite3.connect"]
    assert connects and all("mode=ro" in a and "immutable" not in a for a in connects), connects
    assert not [m for m in report["new"] if m.startswith(("recalith.retrieval", "recalith.storage", "recalith.contracts", "recalith.controller", "recalith.service", "recalith.cli", "recalith.capture"))]
    assert "recalith.fast.delivery" in report["new"]
    emitted = [o for o in outputs if o]
    assert len(emitted) >= 3 and ids["lesson"] in "".join(emitted)  # prompt/pre-action/restoration reached stdout
    for out in emitted:
        assert set(json.loads(out)) == {"hookSpecificOutput"}


def test_session_start_notice_is_stdlib_bounded_and_once(tmp_path):
    """The session-start notice (SYSTEM_SPEC §14; Task 13) reads small local files only: no SQLite, no Pydantic, no health layer.

    A controlled manifest with the notice consent (``integrate`` sets it) and
    delivery off; no provider route: the first session start prints one
    ``systemMessage`` envelope, the second (same limitations) prints nothing.
    """
    from recalith.capture.hooks import write_hook_context

    replay = cf.Replay(tmp_path)
    write_hook_context(replay.ctx, adapter_id="claude_code", host_version=cf.VERSION, session_notice=True)
    start = cf.records("lifecycle")[0]
    case = {"argv": ["--project", str(replay.root), "claude_code", "--event", start["event"]], "stdin": replay.prepare(start).decode("utf-8")}
    env = cf.child_env(RECALITH_TEST_AUDIT=json.dumps(AUDIT_EVENTS))
    proc = subprocess.run([sys.executable, "-I", "-c", PROBE, "deliver"], input=json.dumps([case, case]), capture_output=True, text=True, encoding="utf-8", env=env, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-3000:]
    lines = proc.stdout.strip().splitlines()
    outputs, report = json.loads(lines[-2])["outputs"], json.loads(lines[-1])
    _assert_clean(report)
    assert not {"recalith.fast.delivery", "recalith.fast.cache", "sqlite3", "recalith.operations"} & set(report["new"])
    first = json.loads(outputs[0])
    assert set(first) == {"systemMessage"} and len(first["systemMessage"].encode("utf-8")) <= 512 and "inference" in first["systemMessage"]
    assert outputs[1] == ""


def test_capture_only_hooks_never_import_the_delivery_branch(tmp_path):
    """With delivery off (the default manifest) the hook imports neither SQLite nor the delivery branch."""
    replay = cf.Replay(tmp_path)
    cases = [{"argv": ["--project", str(replay.root), "claude_code", "--event", r["event"]], "stdin": replay.prepare(r).decode("utf-8")} for r in cf.records("lifecycle")[:9]]
    report = _run_probe(["entry"], json.dumps(cases))
    _assert_clean(report)
    assert not {"recalith.fast.delivery", "recalith.fast.cache", "sqlite3"} & set(report["new"])


LAYER_PROBE = r"""
import importlib, json, sys
importlib.import_module(sys.argv[1])
print(json.dumps(sorted(m for m in sys.modules if m.startswith("recalith"))))
"""


@pytest.mark.parametrize("module", ["recalith.service", "recalith.controller.worker", "recalith.retrieval.compile", "recalith.capture.pipeline", "recalith.controller.apply"])
def test_service_and_domain_import_no_cli_or_host_entry(module):
    """Task 12a layering: the domain and the service import no CLI module; the service imports no host entry point."""
    out = subprocess.run([sys.executable, "-I", "-c", LAYER_PROBE, module], capture_output=True, text=True, encoding="utf-8", timeout=120, check=True)
    loaded = set(json.loads(out.stdout))
    assert not {m for m in loaded if m == "recalith.cli" or m.startswith("recalith.cli.") or m == "recalith.__main__"}, module
    if module == "recalith.service":
        assert not loaded & {"recalith.fast.entry", "recalith.fast.claude_capture", "recalith.fast.context"}


def test_no_domain_module_names_the_cli():
    """Static check: only the CLI package and ``recalith.__main__`` import ``recalith.cli``."""
    offenders = []
    for path in (ROOT / "src" / "recalith").rglob("*.py"):
        rel = path.relative_to(ROOT / "src" / "recalith").as_posix()
        if rel.startswith("cli/") or rel == "__main__.py":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(from\s+recalith\.cli\b|import\s+recalith\.cli\b|from\s+recalith\s+import\s+.*\bcli\b)", text, re.MULTILINE):
            offenders.append(rel)
    assert offenders == []
