"""Task 12a: public service and CLI contracts (A32, A60, A72, A73; Task 12a parts of A19, A33, A53).

Every CLI assertion runs the real command as a child process through an
installed spelling (module, ``recalith.cli.main`` module, project launcher).
Host-marked, worker- and curator-marked callers and terminals are controlled
test states (see ``cli_scenarios``); they prove the guard's decisions, never a
live operator workflow on a real IDE host. Events come from the real Claude
Code 2.1.301 payloads through the real adapter (``working_scenarios``); model
behavior is recorded proposals through the real persisted-proposal path.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import cli_scenarios as cs  # first: puts tests/ and tests/platform on sys.path
import admission_scenarios as adm  # noqa: E402
import consolidation_scenarios as cns  # noqa: E402
import operation_scenarios as osc  # noqa: E402
import retrieval_scenarios as rs  # noqa: E402
import worker_hosts as wh  # noqa: E402
import worker_scenarios as ws  # noqa: E402
import working_scenarios as wks  # noqa: E402
from recalith import service  # noqa: E402
from recalith.cli import operator_guard  # noqa: E402
from recalith.contracts.common import Actor, Scope  # noqa: E402
from recalith.controller import admission, jobs, requests, worker  # noqa: E402
from recalith.core import identity  # noqa: E402
from recalith.errors import RecalithError  # noqa: E402
from recalith.fast import process_env  # noqa: E402
from recalith.retrieval import compile as rcompile  # noqa: E402
from recalith.storage import db, records  # noqa: E402

STATEMENT = "Keep the fixture tests on pytest; do not migrate them."
POSIX = os.name != "nt"
needs_posix_tty = pytest.mark.skipif(not POSIX, reason="the pseudo-terminal variant is POSIX; Windows uses the console variant where a console can be attached")


@pytest.fixture
def root(tmp_path):
    return cs.init_project(tmp_path)


@pytest.fixture
def tok(tmp_path, root):
    """A registered, explicitly provisioned fixture token (evaluation/CI bootstrap input)."""
    t = cs.token(tmp_path / "operator.token")
    cs.register(root, t)
    return tmp_path / "operator.token"


def scope_file(tmp_path: Path, scope: dict | None = None) -> Path:
    path = tmp_path / "scope.json"
    path.write_text(json.dumps(scope or {}), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# A72: machine output and exit codes


def test_json_stdout_is_one_object(root, tmp_path, tok):
    """Every outcome class prints exactly one JSON object on stdout, and diagnostics only on stderr."""
    cases = [
        (["status", "--json"], 8),
        (["--json", "claims"], 0),
        (["--json", "tasks", "--status", "active"], 0),
        (["--json", "jobs", "list"], 0),
        (["--json", "show", "claim_00000000-0000-4000-8000-000000000000"], 2),
        (["--json", "claims", "--status", "nonsense"], 2),
        (["--json", "declare", "decision", "--statement", STATEMENT], 2),  # syntax: missing --scope
        (["--json", "forget", "--selector", str(tmp_path / "sel.json"), "--preview"], 2),  # Task 16: a missing selector file is invalid input
        (["--json", "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path))], 6),  # no terminal, no token
    ]
    for args, expected in cases:
        result = cs.cli(root, *args)
        assert result.code == expected, (args, result.stdout, result.stderr)
        obj = result.obj
        assert obj["ok"] is (expected in (0, 8)) and obj["command"]
        if expected not in (0, 8):
            assert obj["exit_code"] == expected and obj["error"] and result.stderr.startswith("recalith: ")
    marked = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)), env=cs.marked_env("CLAUDECODE"))
    assert marked.code == 6 and marked.obj["error"] == "policy_refused"
    missing = cs.cli(tmp_path / "nowhere", "--json", "status")
    assert missing.code == 4 and missing.obj["error"] == "capability_unavailable"


def test_observe_not_captured_returns_7(root, tmp_path):
    """A72: a valid observation whose durability was not acknowledged is exit 7; accepted IDs are explicit."""
    observation = json.dumps({"source_event_key": "obs-1", "text": "I decide: the fixture tests always use pytest."}).encode()
    cs.block_spool(root)
    refused = cs.cli(root, "--json", "observe", "--stdin", stdin=observation)
    assert refused.code == 7 and refused.obj["error"] == "not_captured"
    assert refused.obj["receipt"]["status"] == "not_captured" and refused.obj["receipt"]["event_ids"] == []
    cs.unblock_spool(root)
    accepted = cs.cli(root, "--json", "observe", "--stdin", stdin=observation)
    assert accepted.code == 0, accepted.stderr
    receipt = accepted.obj["result"]
    assert receipt["status"] == "accepted" and len(receipt["event_ids"]) == 1
    invalid = cs.cli(root, "--json", "observe", "--stdin", stdin=b'{"text": "no key"}')
    assert invalid.code == 2 and invalid.obj["error"] == "invalid_schema"
    # A32: an agent assertion is untrusted external data, never a user-authority root.
    from recalith.capture import pipeline
    from recalith.core import lineage

    pipeline.ingest_ready(cs.context(root))
    with db.open_store(cs.context(root), readonly=True) as store, store.read() as view:
        env = db_event(view, receipt["event_ids"][0])
        assert (env.kind, env.channel, env.authority) == ("generic_observation", "external", "untrusted")
        assert lineage.classify(env).descriptor is None
        link = {"ref": {"kind": "event", "id": env.event_id, "revision": 1}, "relation": "supports", "root_event_ids": [env.event_id], "locator": None, "mapping": None}
        from recalith.contracts.common import EvidenceLink

        assert admission.declaration_refusal(view, EvidenceLink.model_validate(link)) == "declaration_requires_user_evidence"


def db_event(view, event_id):
    from recalith.contracts.events import EventEnvelope

    envelope, payload = view.execute("SELECT envelope, payload FROM events WHERE event_id = ?", (event_id,)).fetchone()
    data = json.loads(envelope)
    data["payload"] = json.loads(payload)
    return EventEnvelope.model_validate(data)


def test_degraded_capability_returns_8(root, tmp_path, tok):
    """A72: partial capability is exit 8 with registered reasons; nothing claims readiness or autonomy."""
    status = cs.cli(root, "--json", "status")
    assert status.code == 8
    obj = status.obj
    assert obj["status"] == "capability_degraded" and "provider_not_configured" in obj["degraded"] and "host_not_integrated" in obj["degraded"]
    report = obj["result"]
    assert report["autonomous_ready"] is False and report["readiness"] == "degraded"
    health = report["health"]
    assert health["autonomous_ready"] is False and health["capabilities"]["inference"]["state"] == "unavailable"
    assert "provider_not_configured" in health["capabilities"]["inference"]["reason_codes"]
    doctor = cs.cli(root, "--json", "doctor")
    assert doctor.code == 8 and doctor.obj["result"]["checks"]["revision_chain"] == "unavailable_in_preview"
    # A degraded context packet is exit 8 too (no snapshot of a missing store view); its packet is still one object.
    packet = cs.cli(root, "--json", "context", "--purpose", "manual", "--session", "sess_00000000-0000-4000-8000-000000000001", "--stdin", stdin=b'{"text": "pytest"}')
    assert packet.code in (0, 8)
    assert (packet.code == 8) == bool(packet.obj["result"]["degraded_reasons"])
    # Unavailable (not merely degraded) capabilities are 4, after the guard for administrative forms.
    assert cs.cli(root, "--json", "doctor", "--full-integrity").code == 4
    assert cs.cli(root, "--json", "--operator-token-file", str(tok), "worker", "start", "--mode", "session").code == 4


# ---------------------------------------------------------------------------
# A73: the administrative guard


def _forms(tmp_path: Path) -> dict[str, list[str]]:
    selector = tmp_path / "selector.json"
    selector.write_text('{"record_refs": []}', encoding="utf-8")
    some = tmp_path / "some.file"
    some.write_bytes(b"x")
    scope = scope_file(tmp_path)
    claim = "claim_00000000-0000-4000-8000-000000000001"
    zero = "0" * 64
    return {
        "init": ["init", "--profile", "coding", "--release-profile", "claude_preview"],
        "init_full": ["init", "--profile", "general", "--release-profile", "full"],
        "declare": ["declare", "decision", "--statement", STATEMENT, "--scope", str(scope)],
        "declare_preference": ["declare", "preference", "--statement", STATEMENT, "--scope", str(scope)],
        "correct": ["correct", claim, "--expected-revision", "1", "--statement", STATEMENT],
        "undo_apply": ["undo", "op_00000000-0000-4000-8000-000000000001", "--apply", "--preview-digest", zero],
        "forget_apply": ["forget", "--selector", str(selector), "--apply", "--preview-digest", zero],
        "import": ["import", str(some), "--expected-digest", zero],
        "import_breadcrumbs": ["import", "breadcrumbs", "--source", str(some)],
        "restore": ["restore", str(some), "--expected-digest", zero],
        "upgrade": ["upgrade", "--wheel", str(some), "--expected-digest", zero],
        "upgrade_full": ["upgrade", "--wheel", str(some), "--expected-digest", zero, "--release-profile", "full"],
        "integrate": ["integrate", "claude", "--autostart"],
        "integrate_shared": ["integrate", "claude", "--shared"],
        "integrate_remove": ["integrate", "claude", "--remove"],
        "workspace_attach": ["workspace", "attach", str(tmp_path)],
        "workspace_rebind": ["workspace", "rebind"],
        "workspace_discard_copy": ["workspace", "discard-copy"],
        "project_fork": ["project", "fork"],
        "worker_start": ["worker", "start", "--mode", "persistent"],
        "worker_session": ["worker", "start", "--mode", "session"],
        "worker_stop": ["worker", "stop"],
        "worker_run": ["worker", "run", "--mode", "persistent"],
        "jobs_retry": ["jobs", "retry", "job_00000000-0000-4000-8000-000000000001"],
        "backup": ["backup", "--output", str(tmp_path / "backup.out")],
        "export": ["export", "--selection", str(some), "--output", str(tmp_path / "export.out")],
        "operator_token_create": ["operator-token", "create", "--output", str(tmp_path / "minted.token")],
        "operator_token_revoke": ["operator-token", "revoke", "tok_00000000-0000-4000-8000-000000000001"],
        "doctor_probe_host": ["doctor", "--probe-host", "claude_code"],
        "doctor_probe_provider": ["doctor", "--probe-provider", "claude_cli"],
    }


GUARDED = sorted([
    "init", "init_full", "declare", "declare_preference", "correct", "undo_apply", "forget_apply", "import", "import_breadcrumbs", "restore", "upgrade", "upgrade_full",
    "integrate", "integrate_shared", "integrate_remove", "workspace_attach", "workspace_rebind", "workspace_discard_copy", "project_fork",
    "worker_start", "worker_session", "worker_stop", "worker_run", "jobs_retry", "backup", "export", "operator_token_create", "operator_token_revoke",
    "doctor_probe_host", "doctor_probe_provider",
])
COMBOS = [(True, True), (False, False), (True, False), (False, True)]  # (terminal, token)


def test_guarded_forms_cover_the_contract(tmp_path):
    """Every agent-refusable form of DATA_CONTRACTS §12 is in the refusal matrix (and nothing else)."""
    assert sorted(_forms(tmp_path)) == GUARDED


@pytest.fixture(scope="module")
def launcher_project(tmp_path_factory):
    """One provisioned project per module: the launcher spelling needs a pinned runtime."""
    parent = tmp_path_factory.mktemp("launcher")
    r = cs.init_project(parent, "proj")
    cs.provision_runtime(r)
    return r


@pytest.mark.parametrize("marker", sorted(cs.MARKERS))
@pytest.mark.parametrize("form", GUARDED)
def test_agent_channel_cannot_declare_or_forget(form, marker, launcher_project, tmp_path):
    """A73/A32: every guarded form is refused (6) for a host/worker/curator-marked caller, with or without terminal and token.

    Each case runs the strongest combination (terminal *and* a valid
    registered token) and one more terminal/token combination, through a
    rotating installed spelling (launcher, module, ``recalith.cli.main``).
    No requested effect, no store creation; a content-free audit is spooled.
    """
    r = launcher_project
    t = cs.token(tmp_path / f"{form}.token")
    cs.register(r, t)
    forms = _forms(tmp_path)
    index = GUARDED.index(form) + sorted(cs.MARKERS).index(marker)
    combos = [COMBOS[0], COMBOS[1 + index % 3]]
    for n, (terminal, with_token) in enumerate(combos):
        if terminal and not POSIX and (n > 0 or index % 4):
            terminal = False  # a new Windows console per run is slow: a quarter of the cases use it; the rest keep the token
        spelling = cs.SPELLINGS[(index + n) % 3]
        before_tree, before_rows = cs.tree(r), cs.store_rows(r)
        before_audits = len(cs.audit_events(r))
        token_args = ["--operator-token-file", str(tmp_path / f"{form}.token")] if with_token else []
        result = cs.cli(r, "--json", *token_args, *forms[form], spelling=spelling, env=cs.marked_env(marker, r), tty=terminal)
        assert result.code == 6, (form, marker, spelling, terminal, with_token, result.stdout, result.stderr)
        obj = result.obj
        assert obj["error"] == "policy_refused" and obj["refusal"]["category"] == cs.MARKERS[marker]
        assert obj["refusal"]["audit"] == "captured"
        if cs.MARKERS[marker] == "host_marker":
            assert "ordinary OS terminal" in obj["message"] and "never cleared" in obj["message"]
        assert marker not in result.stdout + result.stderr and STATEMENT not in result.stdout + result.stderr
        assert cs.tree(r) == before_tree and cs.store_rows(r) == before_rows  # no requested effect
        assert not (tmp_path / "minted.token").exists() and not (tmp_path / "backup.out").exists()
        assert len(cs.audit_events(r)) == before_audits + 1
    assert not process_env.worker_running(str(r))


def test_refusal_audit_is_content_free(root, tmp_path, tok):
    """A healthy refusal audit records command kind, caller category and reason only: no statement, token or argv."""
    secret = json.loads(tok.read_text(encoding="utf-8"))["secret"]
    scope = scope_file(tmp_path)
    result = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope), env=cs.marked_env("CLAUDECODE"))
    assert result.code == 6 and result.obj["refusal"]["audit"] == "captured"
    (event,) = cs.audit_events(root)
    assert event["payload"] == {"command_kind": "declare", "marker_category": "host_marker", "reason_code": "policy_refused"}
    assert (event["channel"], event["authority"], event["root_event_ids"]) == ("memory", "derived", [])
    text = cs.audit_segments_text(root)
    for forbidden in (STATEMENT, "pytest", secret, str(tok), tok.name, str(scope), "--statement", "CLAUDECODE"):
        assert forbidden not in text
    # Ingested, it is telemetry: no root, no task, no support.
    p = ws.worker.Worker(cs.context(root, ws.ACTOR))
    try:
        for _ in range(10):
            if not p.poll_once():
                break
    finally:
        p.close()
    with db.open_store(cs.context(root), readonly=True) as store, store.read() as view:
        assert view.execute("SELECT COUNT(*) FROM root_members").fetchone()[0] == 0
        assert view.execute("SELECT kind, channel, authority FROM events").fetchall() == [("agent_attempted_operator_command", "memory", "derived")]


def test_unmarked_noninteractive_refusal(root, tmp_path):
    """No marker, no terminal, no token: refused with the terminal/token route, audited, nothing changed."""
    before = cs.store_rows(root)
    result = cs.cli(root, "--json", "declare", "preference", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)))
    assert result.code == 6
    refusal = result.obj["refusal"]
    assert refusal == {"reason": "terminal_or_token_required", "category": "unmarked_noninteractive", "audit": "captured"}
    assert "interactive terminal" in result.obj["message"]
    assert cs.store_rows(root) == before


@needs_posix_tty
def test_human_terminal_and_token_workflow(root, tmp_path):
    """The positive route: an unmarked terminal mints a registered token, declares, and a token drives automation."""
    minted = tmp_path / "human.token"
    created = cs.cli(root, "--json", "operator-token", "create", "--output", str(minted), tty=True)
    assert created.code == 0, created.stdout + created.stderr
    info = created.obj["result"]
    assert info["registered"] is True and "secret" not in json.dumps(info)
    assert stat.S_IMODE(minted.stat().st_mode) == 0o600
    secret = json.loads(minted.read_text(encoding="utf-8"))["secret"]
    assert secret not in (root / ".recalith/local.toml").read_text(encoding="utf-8")  # only a one-way verifier
    declared = cs.cli(root, "--json", "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)), tty=True)
    assert declared.code == 0, declared.stdout + declared.stderr
    report = declared.obj["result"]
    assert [(d["outcome"], d["reason_code"]) for d in report["result"]["decisions"]] == [("candidate_only", "candidate_pending_review")]
    assert len(report["review_job_ids"]) == 1
    # Noninteractive automation with the registered token (no terminal).
    retried = cs.cli(root, "--json", "--operator-token-file", str(minted), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)))
    assert retried.code == 0 and retried.obj["result"]["duplicate"] is True  # the same submission: no second effect
    # Revocation needs the terminal; afterwards the token is refused (6), with or without a terminal.
    revoked = cs.cli(root, "--json", "operator-token", "revoke", info["token_id"], tty=True)
    assert revoked.code == 0
    for terminal in (False, True):
        refused = cs.cli(root, "--json", "--operator-token-file", str(minted), "declare", "decision", "--statement", "Another decision.", "--scope", str(scope_file(tmp_path)), tty=terminal)
        assert refused.code == 6 and refused.obj["refusal"]["reason"] == "token_revoked"


@needs_posix_tty
def test_terminal_without_controlling_terminal_is_noninteractive(root, tmp_path):
    """A terminal descriptor on stdin is not enough: a process with no controlling terminal is refused."""
    result = cs.cli(root, "--json", "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)), tty="no_ctty")
    assert result.code == 6 and result.obj["refusal"]["category"] == "unmarked_noninteractive"
    assert cs.store_rows(root)["counts"]["claim_heads"] == 0


@needs_posix_tty
def test_terminal_init_without_token(tmp_path):
    """An unmarked interactive terminal may initialize without a token; no verifier is installed then."""
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    result = cs.cli(fresh, "--json", "init", "--profile", "general", "--release-profile", "claude_preview", tty=True)
    assert result.code == 0, result.stdout + result.stderr
    assert result.obj["result"]["operator_token_registered"] is False
    assert identity.operator_tokens(fresh) == ({}, {})
    assert identity.load_project_config(identity.Layout(fresh)).domain_profile == "general"


def test_worker_run_in_the_foreground(root, tmp_path, tok):
    """``worker run --mode persistent`` runs the internal entry in the foreground with a fresh worker environment."""
    proc = subprocess.Popen(cs.argv_for("module", root, ["--json", "--operator-token-file", str(tok), "worker", "run", "--mode", "persistent"]), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=cs.base_env())
    try:
        status = wh.wait_running(root)
        assert status and status["spawn"]["spawned_by"] == "cli" and status["environment"]["role_marker"] == cs.context(root).installation_id
        worker.request_stop(root)
        out, _err = proc.communicate(timeout=60)
        assert proc.returncode == 0 and json.loads(out)["result"] == {"state": "exited", "exit_code": 0}
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        wh.stop_worker(root)


def test_audit_failure_still_refuses(root, tmp_path, tok):
    """Storage failure while auditing: the command is still refused, and the audit is reported unavailable."""
    cs.block_spool(root)
    before = cs.store_rows(root)
    result = cs.cli(root, "--json", "--operator-token-file", str(tok), "correct", "claim_00000000-0000-4000-8000-000000000001", "--expected-revision", "1", "--statement", STATEMENT, env=cs.marked_env("CLAUDE_CODE_CHILD_SESSION"))
    assert result.code == 6 and result.obj["refusal"]["audit"] == "unavailable"
    assert cs.store_rows(root) == before
    # An unreadable store (the audit cannot even resolve the installation): still refused, never an error exit.
    store = root / ".recalith" / db.STATE_DB
    store.rename(store.with_name("moved-away.sqlite"))
    store.write_bytes(b"not a database")
    broken = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)), env=cs.marked_env("CLAUDECODE"))
    assert broken.code == 6 and broken.obj["refusal"]["audit"] == "unavailable"


@pytest.mark.skipif(not hasattr(os, "geteuid") or not hasattr(signal, "SIGXFSZ"), reason="POSIX RLIMIT_FSIZE (a real disk-full write failure)")
def test_disk_full_audit_still_refuses(root, tmp_path, tok):
    import resource

    def full() -> None:
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))

    result = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)), env=cs.marked_env("CLAUDECODE"), preexec=full)
    assert result.code == 6 and result.obj["refusal"]["audit"] == "unavailable"
    assert cs.audit_events(root) == []


def test_preinit_refusal_creates_no_store(tmp_path):
    """Before init a refusal returns bounded metadata and creates nothing; no store is created just to log it."""
    empty = tmp_path / "fresh"
    empty.mkdir()
    for env, terminal in ((cs.marked_env("CLAUDECODE"), True), (cs.base_env(), False)):
        result = cs.cli(empty, "--json", "init", "--profile", "coding", "--release-profile", "claude_preview", env=env, tty=terminal and POSIX)
        assert result.code == 6 and result.obj["refusal"]["audit"] == "no_installation"
        assert list(empty.iterdir()) == []
    minted = cs.cli(empty, "--json", "operator-token", "create", "--output", str(tmp_path / "t.token"), env=cs.marked_env(process_env.CURATOR_MARKER), tty=POSIX)
    assert minted.code == 6 and not (tmp_path / "t.token").exists() and list(empty.iterdir()) == []


@needs_posix_tty
def test_preinit_token_bootstraps_without_tty(tmp_path):
    """A73: a terminal mints a standalone token before init (no installation lookup); noninteractive init uses it once."""
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / ".recalith").mkdir()
    (fresh / ".recalith" / "local.toml.partial").write_text("not an installation", encoding="utf-8")
    minted = cs.cli(None, "--json", "operator-token", "create", "--output", str(tmp_path / "boot.token"), tty=True, cwd=tmp_path)
    assert minted.code == 0 and minted.obj["result"]["registered"] is False
    assert sorted(p.name for p in (fresh / ".recalith").iterdir()) == ["local.toml.partial"]  # no lookup, nothing created
    _bootstrap_with(tmp_path, fresh, tmp_path / "boot.token")


def test_fixture_token_initializes_noninteractively(tmp_path):
    """Evaluation/CI initialization: an explicitly provisioned fixture token, every platform, every spelling but the launcher."""
    fresh = tmp_path / "ci"
    fresh.mkdir()
    cs.token(tmp_path / "ci.token")
    _bootstrap_with(tmp_path, fresh, tmp_path / "ci.token")


def _bootstrap_with(tmp_path: Path, fresh: Path, token_path: Path) -> None:
    no_token = cs.cli(fresh, "--json", "init", "--profile", "coding", "--release-profile", "claude_preview")
    assert no_token.code == 6 and not (fresh / ".recalith" / "state").exists()
    init = cs.cli(fresh, "--json", "--operator-token-file", str(token_path), "init", "--profile", "coding", "--release-profile", "claude_preview")
    assert init.code == 0, init.stdout + init.stderr
    assert init.obj["result"]["operator_token_registered"] is True
    local = (fresh / ".recalith/local.toml").read_text(encoding="utf-8")
    secret = json.loads(token_path.read_text(encoding="utf-8"))["secret"]
    assert "operator_verifiers" in local and secret not in local
    before = cs.store_rows(fresh)
    again = cs.cli(fresh, "--json", "--operator-token-file", str(token_path), "init", "--profile", "coding", "--release-profile", "claude_preview")
    assert again.code == 6 and cs.store_rows(fresh) == before  # never overwrites an existing installation
    declared = cs.cli(fresh, "--json", "--operator-token-file", str(token_path), "declare", "preference", "--statement", "Prefer short test names.", "--scope", str(scope_file(tmp_path)), spelling="cli_module")
    assert declared.code == 0, declared.stdout + declared.stderr
    full = cs.cli(tmp_path, "--json", "--operator-token-file", str(token_path), "init", "--profile", "coding", "--release-profile", "full")
    assert full.code == 4  # the full profile is unavailable in this build, after the guard


def test_noninteractive_cannot_mint_token(root, tmp_path, tok):
    """Token create/revoke need the unmarked terminal; a token never substitutes, and nothing is written."""
    for args in (["operator-token", "create", "--output", str(tmp_path / "new.token")], ["operator-token", "revoke", "tok_00000000-0000-4000-8000-000000000009"]):
        for with_token in (False, True):
            token_args = ["--operator-token-file", str(tok)] if with_token else []
            result = cs.cli(root, "--json", *token_args, *args)
            assert result.code == 6 and result.obj["refusal"]["reason"] == "terminal_required", result.stdout
    assert not (tmp_path / "new.token").exists()
    assert identity.operator_tokens(root)[1] == {}


def test_missing_or_revoked_token_returns_6(root, tmp_path, tok):
    """Missing, malformed, mismatched, linked, oversized, too-open or revoked token files are 6, never 2, never a fallback."""
    scope = str(scope_file(tmp_path))
    args = ["declare", "decision", "--statement", STATEMENT, "--scope", scope]

    def attempt(path: Path, *, terminal: bool = False) -> str:
        result = cs.cli(root, "--json", "--operator-token-file", str(path), *args, tty=terminal)
        assert result.code == 6, (path.name, result.stdout, result.stderr)
        return result.obj["refusal"]["reason"]

    assert attempt(tmp_path / "missing.token") == "token_unreadable"
    malformed = tmp_path / "malformed.token"
    malformed.write_text("{not json", encoding="utf-8")
    os.chmod(malformed, 0o600)
    assert attempt(malformed) == "token_malformed"
    unknown = tmp_path / "unknown.token"
    cs.token(unknown)  # well-formed, never registered here
    assert attempt(unknown) == "token_not_recognized"
    data = json.loads(tok.read_text(encoding="utf-8"))
    forged = tmp_path / "forged.token"
    forged.write_text(json.dumps(dict(data, secret="A" * 43)), encoding="utf-8")
    os.chmod(forged, 0o600)
    assert attempt(forged) == "token_not_recognized"
    big = tmp_path / "big.token"
    big.write_text(json.dumps(dict(data, padding="x" * 5000)), encoding="utf-8")
    os.chmod(big, 0o600)
    assert attempt(big) == "token_oversized"
    if POSIX:
        link = tmp_path / "link.token"
        link.symlink_to(tok)
        assert attempt(link) == "token_not_regular_file"
        os.chmod(tok, 0o640)
        assert attempt(tok) == "token_permissions_too_open"
        os.chmod(tok, 0o600)
        assert attempt(forged, terminal=True) == "token_not_recognized"  # a bad token never falls back to the terminal
    identity.update_operator_tokens(root, revoke=data["token_id"])  # fixture setup; the CLI revoke is the terminal workflow
    assert attempt(tok) == "token_revoked"
    syntax = cs.cli(root, "--json", *args, "--operator-token-file")
    assert syntax.code == 2  # invalid option syntax stays 2
    assert cs.store_rows(root)["counts"]["events"] == 0


@pytest.mark.skipif(not POSIX or not hasattr(os, "geteuid") or os.geteuid() != 0, reason="ownership as root: a token owned by another user is refused even though root can read it")
def test_root_refuses_token_owned_by_another_user(root, tmp_path, tok):
    os.chown(tok, 65534, 65534)
    result = cs.cli(root, "--json", "--operator-token-file", str(tok), "jobs", "retry", "job_00000000-0000-4000-8000-000000000001")
    assert result.code == 6 and result.obj["refusal"]["reason"] == "token_owner_mismatch"


def test_marked_ide_tty_plus_token_still_refused(root, tmp_path, tok):
    """An IDE terminal inheriting the host marker: terminal + valid token is still 6, with the external-terminal route."""
    env = cs.marked_env("CLAUDECODE", TERM_PROGRAM="vscode")
    result = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)), env=env, tty=True)
    assert result.code == 6
    obj = result.obj
    assert obj["refusal"] == {"reason": "host_marker_present", "category": "host_marker", "audit": "captured"}
    assert "ordinary OS terminal launched outside the host agent" in obj["message"] and ".recalith/bin/recalith" in obj["message"]
    assert "CLAUDECODE" not in result.stdout + result.stderr
    assert cs.store_rows(root)["counts"]["claim_heads"] == 0


def test_registered_hook_starts_worker_without_operator_cli(tmp_path):
    """A73 permitted-start control: the marked host's hook starts the worker through the registered path; the CLI form is refused."""
    replay = wks.cf.Replay(tmp_path / "hooked")
    wh.enable_autostart(replay)
    r = replay.root
    marked = wh.marked_env()
    refused = cs.cli(r, "--json", "worker", "start", env=marked, tty=POSIX)
    assert refused.code == 6 and not process_env.worker_running(str(r))
    audit_hook = tmp_path / "spawns.json"
    code = (
        "import json, subprocess, sys\n"
        "seen = []\n"
        "def hook(event, args):\n"
        "    if event == 'subprocess.Popen':\n"
        "        seen.append(args[1] if isinstance(args[1], str) else [str(a) for a in args[1]])\n"
        "sys.addaudithook(hook)\n"
        "from recalith.fast import entry\n"
        f"sys.argv = ['entry', '--project', {str(r)!r}, 'claude_code', '--event', 'SessionStart']\n"
        "try:\n"
        "    entry.main()\n"
        "finally:\n"
        f"    open({str(audit_hook)!r}, 'w', encoding='utf-8').write(json.dumps(seen))\n"
    )
    data = replay.prepare(wh.start_record())
    try:
        for _ in range(5):
            proc = subprocess.run([sys.executable, "-I", "-c", code], input=data, capture_output=True, env=marked, timeout=60, check=False)
            assert proc.returncode == 0, proc.stderr
            spawned = json.loads(audit_hook.read_text(encoding="utf-8"))
            if spawned:
                break
        assert spawned, "the hook never started the worker"
        (cmd,) = spawned
        # The audit event carries the argument list on POSIX and the command-line string on Windows.
        line = subprocess.list2cmdline(cmd) if isinstance(cmd, list) else cmd
        if isinstance(cmd, list):
            assert cmd[1:4] == ["-I", "-m", "recalith.controller.worker"]  # the internal entry, never the operator CLI
        assert " -I -m recalith.controller.worker --project " in line
        assert " -m recalith " not in f"{line} " and "recalith.cli" not in line and "bin/recalith" not in line.replace("\\", "/") and "recalith.cmd" not in line
        status = wh.wait_running(r)
        assert status and status["spawn"]["spawned_by"] == "hook"
        assert status["environment"]["host_markers_present"] == [] and status["environment"]["role_marker"] == cs.context(r).installation_id
    finally:
        wh.stop_worker(r)


# ---------------------------------------------------------------------------
# A60 / A19: guarded declare and correct reuse the review, hold and recheck paths


def test_operator_declaration_is_not_agent_authority(tmp_path, root, tok):
    """Only the guarded operator transport assigns operator authority; an agent assertion stays untrusted data."""
    scope = Scope()
    for actor in (Actor(kind="host_agent", id="claude", channel="cli"), Actor(kind="host_agent", id="claude", channel="mcp"), Actor(kind="adapter", id="hook", channel="hook"), Actor(kind="operator", id="x", channel="mcp")):
        with pytest.raises(RecalithError) as refused:
            service.declare(cs.context(root, actor), "decision", STATEMENT, scope)
        assert refused.value.code == "policy_refused"
        with pytest.raises(RecalithError):
            service.correct(cs.context(root, actor), "claim_00000000-0000-4000-8000-000000000001", expected_revision=1, statement=STATEMENT)
        # The service's own check, independent of the domain's actor policy: no operator event, no worker control.
        for call in (lambda c: service.operator_event(c, "operator_declaration", {"statement": STATEMENT}, key="k"), lambda c: service.worker_stop(c), lambda c: service.retry_job(c, "job_00000000-0000-4000-8000-000000000001")):
            with pytest.raises(RecalithError) as refused:
                call(cs.context(root, actor))
            assert refused.value.code == "policy_refused"
    agent = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)), env=cs.marked_env("CLAUDECODE"))
    assert agent.code == 6
    assert cs.store_rows(root)["counts"]["claim_heads"] == 0
    operator = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)))
    assert operator.code == 0
    report = operator.obj["result"]
    with db.open_store(cs.context(root), readonly=True) as store, store.read() as view:
        env = db_event(view, report["event_id"])
        assert (env.kind, env.channel, env.authority, env.payload["statement"]) == ("operator_declaration", "user", "explicit_user", STATEMENT)
        claim_id = report["result"]["changed_refs"][0]["id"]
        head = records.body(view, "claim", claim_id, 1)
        assert (head["status"], head["basis"], head["strength"], head["kind"]) == ("candidate", "user_declared", "weak", "decision")
        assert view.execute("SELECT origin FROM review_requests WHERE review_job_id = ?", (report["review_job_ids"][0],)).fetchone() == ("typed_declaration",)
        actor = json.loads(view.execute("SELECT actor FROM operations WHERE kind = 'propose_claim'").fetchone()[0])
        assert actor == {"kind": "operator", "id": json.loads(tok.read_text(encoding="utf-8"))["token_id"], "channel": "cli"}


def test_declared_preference_stays_candidate_until_supported_review(tmp_path):
    """A60: no bypass. Budget-paused review keeps the candidate; a recorded supported review activates it."""
    p = adm.project(tmp_path)
    t = cs.token(tmp_path / "op.token")
    cs.register(p.root, t)
    result = cs.cli(p.root, "--json", "--operator-token-file", str(tmp_path / "op.token"), "declare", "preference", "--statement", "Prefer pytest fixtures over setUp methods.", "--scope", str(scope_file(tmp_path)))
    assert result.code == 0, result.stdout + result.stderr
    claim_id = result.obj["result"]["result"]["changed_refs"][0]["id"]
    (job,) = adm.review_jobs(p, claim_id)
    assert job.review_priority == "correction_or_declaration" and job.priority == jobs.BAND_DECLARATION_REVIEW and job.state == "pending"
    # Exhausted budget: the review waits; the candidate is never admitted around it.
    from test_claim_admission import exhaust_budget

    clock = ws.FakeClock(adm.at(5))
    exhaust_budget(p, clock.now())
    backend = ws.FakeBackend(lambda purpose, i: worker.LaunchOutcome(stdout=ws.envelope(osc.body([], "nothing"))))
    w = worker.Worker(p.ctx, clock=clock, model=ws.runtime(backend, requests.runtime_preparer(p.ctx)))
    try:
        assert w.lane.step() is False and backend.calls == []
    finally:
        w.close()
    waiting = adm.review_jobs(p, claim_id)[0]
    assert waiting.state == "waiting_budget" and waiting.last_error_code.startswith("budget_exhausted:protected+ordinary.")
    assert adm.head(p, claim_id)["status"] == "candidate"
    # The same Task 9 review path, recorded verdict: only a supported review activates it.
    reset_budget(p)
    request, applied = adm.run_review(p, waiting.job_id, adm.supported_all)
    assert [d.outcome for d in applied.decisions] == ["apply"]
    head = adm.head(p, claim_id)
    assert (head["status"], head["basis"], head["strength"], head["review_assessment"]["verdict"]) == ("active", "user_declared", "supported", "supported")
    assert all("reason" not in json.dumps(c.model_dump(mode="json")) or True for c in request.claims)


def reset_budget(p) -> None:
    with db.open_store(p.ctx) as store, store.transaction() as txn:
        txn.execute("DELETE FROM provider_usage")
        for (body,) in txn.execute("SELECT body FROM jobs WHERE state = 'waiting_budget'").fetchall():
            job = jobs._job(body)
            jobs._save(txn, job.model_copy(update={"state": "pending", "last_error_code": None}))


def test_correction_invalidates_atomically_and_queues_review(tmp_path):
    """A19 through the guarded transport: one transaction, the next packet excludes old guidance, review queued, no model call."""
    p = cns.project(tmp_path)
    decision = cns.declaration(p, "Always run the fixture tests with pytest -q.", "The fixture tests run with pytest -q.", subject="test runner")
    t = cs.token(tmp_path / "op.token")
    cs.register(p.root, t)
    query = rs.query(p, "prompt", text="How are the fixture tests run with pytest?")
    assert decision in rs.ids(rs.service(p, query))
    start = cs.meta(p.root)
    usage = osc.count(p.root, "SELECT COUNT(*) FROM provider_usage")
    head_rev = adm.head(p, decision)["revision"]
    stale = cs.cli(p.root, "--json", "--operator-token-file", str(tmp_path / "op.token"), "correct", decision, "--expected-revision", str(head_rev + 1), "--statement", "Run the fixture tests with pytest -x.")
    assert stale.code == 3 and stale.obj["error"] == "revision_conflict" and cs.meta(p.root) == start
    result = cs.cli(p.root, "--json", "--operator-token-file", str(tmp_path / "op.token"), "correct", decision, "--expected-revision", str(head_rev), "--statement", "Run the fixture tests with pytest -x.")
    assert result.code == 0, result.stdout + result.stderr
    after = cs.meta(p.root)
    assert after.store_revision == start.store_revision + 1 and after.guidance_epoch == start.guidance_epoch + 1  # one transaction
    report = result.obj["result"]
    assert adm.head(p, decision)["status"] == "invalidated"
    replacement = [r["id"] for r in report["result"]["changed_refs"] if r["id"] != decision][0]
    new = adm.head(p, replacement)
    assert (new["status"], new["basis"], new["kind"], new["strength"]) == ("candidate", "user_declared", "decision", "weak")
    assert osc.count(p.root, "SELECT COUNT(*) FROM provider_usage") == usage  # no model call
    (job_id,) = report["review_job_ids"]
    with p.view() as v:
        assert v.execute("SELECT origin FROM review_requests WHERE review_job_id = ?", (job_id,)).fetchone() == ("operator_correction",)
    assert decision not in rs.ids(rs.service(p, query))  # the next packet excludes the old guidance
    # The replacement is admitted only by its own supported review (Task 9 path), and then serves.
    adm.admit(p, replacement)
    assert adm.head(p, replacement)["status"] == "active"


def test_correction_makes_held_supersession_stale(tmp_path):
    """Task 10 holds: a worker supersession held for an unreviewed replacement goes stale when the operator corrects the target."""
    p = cns.project(tmp_path)
    fail = cns.failure(p)
    old = cns.fact(p, "test_mid fails on an assertion.", subject="mid", predicate="cause")
    old_ref = osc.head_ref(p.root, "claim", old).model_dump(mode="json")
    body = adm.claim("test_mid fails because its fixture omits the value.", subject="mid")
    body["proposition_key"]["predicate"] = "cause"
    retire = osc.op("retire", "change_claim_status", {"claim_ref": old_ref, "status": "superseded", "replacement_local_ref": "new"}, depends_on=["new"], target=old_ref, evidence=[adm.link(fail)])
    held = adm.extract(p, [osc.op("new", "propose_claim", body, evidence=[adm.link(fail)]), retire])
    assert [(d.outcome, d.reason_code) for d in held.decisions] == [("candidate_only", "candidate_pending_review"), ("review_required", "replacement_pending_review")]
    new = adm.created_claim(held)
    with p.view() as v:
        assert v.execute("SELECT state FROM pending_supersessions WHERE replacement_id = ?", (new,)).fetchone()[0] == "pending"  # held
    cs.token(tmp_path / "op.token")
    cs.register(p.root, operator_guard.load_token_file(tmp_path / "op.token"))
    result = cs.cli(p.root, "--json", "--operator-token-file", str(tmp_path / "op.token"), "correct", old, "--expected-revision", str(old_ref["revision"]), "--statement", "test_mid fails because the fixture value is missing.")
    assert result.code == 0, result.stdout + result.stderr
    with p.view() as v:
        assert v.execute("SELECT state FROM pending_supersessions WHERE replacement_id = ?", (new,)).fetchone()[0] == "stale"
    replacement = [r["id"] for r in result.obj["result"]["result"]["changed_refs"] if r["id"] != old][0]
    assert (adm.head(p, replacement)["basis"], adm.head(p, replacement)["kind"]) == ("inferred", "fact")  # a fact is never relabeled observed
    adm.admit(p, new)  # its own review still runs; the corrected target is not resurrected or superseded
    assert (adm.head(p, old)["status"], adm.head(p, new)["status"]) == ("invalidated", "active")


def test_service_results_match_direct_domain(tmp_path):
    """The CLI renders exactly the service results, and the service returns exactly the domain's."""
    p = cns.project(tmp_path)
    lesson = cns.lesson(p)
    rs.publish(p)
    t = cs.token(tmp_path / "op.token")
    cs.register(p.root, t)
    reader = cs.context(p.root, service.READER)
    shown = cs.cli(p.root, "--json", "show", lesson)
    with p.view() as v:
        revision, status = records.head(v, "claim", lesson)
        direct = records.body(v, "claim", lesson, revision)
    assert shown.code == 0 and shown.obj["result"]["body"] == direct and shown.obj["result"]["head_status"] == status
    claims = cs.cli(p.root, "--json", "claims", "--status", "active")
    assert [c["id"] for c in claims.obj["result"]["items"]] == [c["id"] for c in service.list_records(reader, "claims", status="active")["items"]]
    session = p.session_of()
    query = {"text": "rerun test_mid", "action": rs.mid_action(p).model_dump(mode="json")}
    packet = cs.cli(p.root, "--json", "context", "--purpose", "pre_action", "--session", session, "--stdin", stdin=json.dumps(query).encode())
    assert packet.code in (0, 8)
    direct_packet = rcompile.compile_context(reader, service.manual_query(reader, query["text"], purpose="pre_action", session_id=session, action=query["action"]))
    cli_packet = packet.obj["result"]
    assert [i["ref"] for i in cli_packet["items"]] == [i.ref.model_dump(mode="json") for i in direct_packet.items]
    assert [i["advice"] for i in cli_packet["items"]] == [i.advice for i in direct_packet.items]
    assert lesson in rs.ids(direct_packet)
    manual = cs.cli(p.root, "--json", "context", "--purpose", "manual", "--session", session, "--stdin", stdin=b'{"text": "test_mid fixture"}')
    assert manual.obj["result"]["estimated_tokens"] <= 2000  # manual purpose budget (decision 0013)
    found = cs.cli(p.root, "--json", "search", "test_mid fixture")
    assert found.code == 0 and lesson in [i["ref"]["id"] for i in found.obj["result"]["items"]]
    # A declaration through the CLI and the same typed operations applied directly agree in kind and outcome.
    cli_decl = cs.cli(p.root, "--json", "--operator-token-file", str(tmp_path / "op.token"), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path)))
    other = cs.init_project(tmp_path, "direct")
    direct_result = service.declare(cs.context(other, cs.OPERATOR), "decision", STATEMENT, Scope())
    assert [(d.outcome, d.reason_code) for d in direct_result.decisions] == [(d["outcome"], d["reason_code"]) for d in cli_decl.obj["result"]["result"]["decisions"]]


def test_read_only_forms_need_no_guard(root, tmp_path):
    """Inspection, previews and observe stay available to a marked caller; they carry no authority."""
    env = cs.marked_env("CLAUDECODE")
    for args in (["claims"], ["tasks"], ["episodes"], ["jobs", "list"], ["search", "pytest"], ["status"], ["doctor"]):
        result = cs.cli(root, "--json", *args, env=env)
        assert result.code in (0, 8), (args, result.stdout, result.stderr)
    assert cs.audit_events(root) == []


def test_undo_preview_and_guarded_apply(root, tmp_path, tok):
    """``undo --preview`` is read-only for anyone; ``undo --apply`` is guarded and applies exactly the previewed compensation."""
    report = service.submit_declaration(cs.context(root), "decision", STATEMENT, Scope())
    claim_id = report.result.changed_refs[0].id
    with db.open_store(cs.context(root), readonly=True) as store, store.read() as view:
        op_id = view.execute("SELECT operation_id FROM operations WHERE kind = 'propose_claim'").fetchone()[0]
    preview = cs.cli(root, "--json", "undo", op_id, "--preview", env=cs.marked_env("CLAUDECODE"))
    assert preview.code == 0 and preview.obj["result"]["state"] == "clean"
    digest = preview.obj["result"]["preview_digest"]
    refused = cs.cli(root, "--json", "--operator-token-file", str(tok), "undo", op_id, "--apply", "--preview-digest", digest, env=cs.marked_env("CLAUDECODE"))
    assert refused.code == 6
    with db.open_store(cs.context(root), readonly=True) as store, store.read() as view:
        assert records.head(view, "claim", claim_id)[1] == "candidate"
    wrong = cs.cli(root, "--json", "--operator-token-file", str(tok), "undo", op_id, "--apply", "--preview-digest", "0" * 64)
    assert wrong.code in (2, 3)
    applied = cs.cli(root, "--json", "--operator-token-file", str(tok), "undo", op_id, "--apply", "--preview-digest", digest)
    assert applied.code == 0, applied.stdout + applied.stderr
    with db.open_store(cs.context(root), readonly=True) as store, store.read() as view:
        assert records.head(view, "claim", claim_id)[1] == "archived"


def test_jobs_retry_and_unavailable_forms(root, tmp_path, tok):
    with db.open_store(cs.context(root)) as store, store.transaction() as txn:
        job_id, _ = jobs.enqueue(txn, kind="maintenance", input_refs=[], now=ws.START)
        job = jobs.get_job(txn, job_id)
        jobs._save(txn, job.model_copy(update={"state": "failed", "last_error_code": "fixture_failure"}))
    retried = cs.cli(root, "--json", "--operator-token-file", str(tok), "jobs", "retry", job_id)
    assert retried.code == 0 and retried.obj["result"]["state"] == "pending"
    again = cs.cli(root, "--json", "--operator-token-file", str(tok), "jobs", "retry", job_id)
    assert again.code == 6  # only a failed job is retried
    forms = _forms(tmp_path)
    for name in ("export", "import", "import_breadcrumbs", "upgrade", "integrate", "integrate_shared", "workspace_attach", "project_fork", "doctor_probe_host"):  # integrate --autostart/--shared are full-only (decision 0019)
        result = cs.cli(root, "--json", "--operator-token-file", str(tok), *forms[name])
        assert result.code == 4 and result.obj["error"] == "capability_unavailable", (name, result.stdout)
        assert "Task" in result.obj["message"] or "full release" in result.obj["message"]
    # Task 15 core: backup works behind the guard; restore verifies first (something that is no backup is rejected, exit 2).
    made = cs.cli(root, "--json", "--operator-token-file", str(tok), *forms["backup"])
    assert made.code == 0 and made.obj["result"]["manifest"]["artifact_type"] == "backup", made.stdout
    rejected = cs.cli(root, "--json", "--operator-token-file", str(tok), *forms["restore"])
    assert rejected.code == 2 and "backup verification failed" in rejected.obj["message"], rejected.stdout
    # Task 16: forget runs behind the guard; a selector that names nothing is invalid input (test_forgetting owns the behavior).
    empty = cs.cli(root, "--json", "--operator-token-file", str(tok), *forms["forget_apply"])
    assert empty.code == 2 and empty.obj["error"] == "invalid_schema", empty.stdout


def test_worker_start_and_stop_through_the_guarded_cli(root, tmp_path, tok):
    try:
        started = cs.cli(root, "--json", "--operator-token-file", str(tok), "worker", "start")
        assert started.code == 0 and started.obj["result"]["state"] in ("worker_started", "worker_independence_degraded")
        status = wh.wait_running(root)
        assert status and status["spawn"]["spawned_by"] == "cli" and status["environment"]["host_markers_present"] == []
        stopped = cs.cli(root, "--json", "--operator-token-file", str(tok), "worker", "stop")
        assert stopped.code == 0 and stopped.obj["result"]["state"] == "stopped"
    finally:
        wh.stop_worker(root)


def test_workspace_rebind_through_the_guarded_cli(tmp_path, tok, root):
    moved = tmp_path / "moved"
    root.rename(moved)
    assert cs.cli(moved, "--json", "status").code == 4  # installation_relocated
    rebound = cs.cli(moved, "--json", "--operator-token-file", str(tok), "workspace", "rebind")
    assert rebound.code == 0, rebound.stdout + rebound.stderr
    assert cs.cli(moved, "--json", "status").code == 8


def test_statement_with_credential_is_not_recorded(root, tmp_path, tok):
    """A60/A32: an exact statement is recorded as given or not at all (no silent scrubbing into another statement)."""
    secret_text = "Use the key " + "sk-ant-" + "api03-" + "A" * 40 + " for the fixture tests."
    result = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", secret_text, "--scope", str(scope_file(tmp_path)))
    assert result.code == 2 and cs.store_rows(root)["counts"]["events"] == 0
    assert "sk-ant" not in result.stdout + result.stderr


def test_scope_paths_cannot_escape_the_workspace(root, tmp_path, tok):
    """A33 (Task 12a part): a declaration scope names only portable workspace-relative paths; escapes are invalid input."""
    for bad in (["../outside.txt"], ["/etc/passwd"], ["C:\\\\Windows\\\\system.ini"]):
        result = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path, {"paths": bad})))
        assert result.code == 2, (bad, result.stdout)
    good = cs.cli(root, "--json", "--operator-token-file", str(tok), "declare", "decision", "--statement", STATEMENT, "--scope", str(scope_file(tmp_path, {"paths": ["src/ünïcødé dir/"]})))
    assert good.code == 0, good.stdout + good.stderr
    with db.open_store(cs.context(root), readonly=True) as store, store.read() as view:
        (body,) = [json.loads(r[0]) for r in view.execute("SELECT body FROM claim_revisions").fetchall()]
    assert body["scope"]["paths"] == ["src/ünïcødé dir/"]


@pytest.mark.parametrize("encoding", ["cp1252", "ascii", "utf-8"])
def test_machine_output_is_utf8_whatever_the_console_encoding(encoding):
    """JSON stdout and diagnostics are UTF-8 even where the stream's text encoding is a Windows code page (CI run 85).

    Windows pipes default to the console code page: a project path with ``é``
    was written as ``0xE9`` and a character outside the code page raised
    ``UnicodeEncodeError``. Real ``TextIOWrapper`` streams with that encoding stand in for the console.
    """
    import io

    from recalith.cli.main import Output

    out_buf, err_buf = io.BytesIO(), io.BytesIO()
    out, err = io.TextIOWrapper(out_buf, encoding=encoding), io.TextIOWrapper(err_buf, encoding=encoding)
    o = Output(as_json=True, command="integrate", stdout=out, stderr=err)
    assert o.success({"spelling": "C:/Users/proj with space é/.recalith/bin/recalith", "arrow": "180\u219230"}) == 0
    assert o.failure("invalid_schema", "the path proj é \u2192 is invalid", 2) == 2
    out.flush()
    err.flush()
    lines = out_buf.getvalue().decode("utf-8").splitlines()
    assert json.loads(lines[0])["result"]["spelling"].endswith("proj with space é/.recalith/bin/recalith")
    assert json.loads(lines[1])["message"] == "the path proj é \u2192 is invalid"
    assert "proj é \u2192" in err_buf.getvalue().decode("utf-8")
