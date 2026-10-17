"""Task 8: tri-state applicability (SYSTEM_SPEC §7.4, §8.1, §13; DATA_CONTRACTS §1.1, §9).

Acceptance: A18, A23, A62, A70 (and the runtime-provenance side of A52/A54).
Actions come from real Claude 2.1.301 payloads through the real adapter where
the action shape matters (A70); runtime versions come from the real
provenance resolver over a real store (declared, observed, stale and
conflicting values).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

HERE = Path(__file__).resolve().parent
for extra in (HERE.parent / "integration", HERE.parent / "platform"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import capture_scenarios as cs  # noqa: E402
import lineage_scenarios as ls  # noqa: E402
from recalith.capture import pipeline, provenance  # noqa: E402
from recalith.capture.normalize import RawEvent, normalize_event  # noqa: E402
from recalith.contracts.common import Actor, Condition, DependencyRef, Scope  # noqa: E402
from recalith.contracts.context import ContextItem, ContextQuery  # noqa: E402
from recalith.contracts.events import ActionDescriptor  # noqa: E402
from recalith.core import conditions as cond  # noqa: E402
from recalith.core import identity  # noqa: E402
from recalith.storage import db  # noqa: E402

WS = "ws_33333333-3333-4333-8333-333333333333"
OTHER_WS = "ws_44444444-4444-4444-8444-444444444444"
SESSION = "sess_44444444-4444-4444-8444-444444444444"
TASK = "task_55555555-5555-4555-8555-555555555555"
CONTROLLER = Actor(kind="controller", id="worker", channel="worker")
FP1, FP2 = "1" * 64, "2" * 64


def action(paths=(), *, kind="test", tool="Bash", parse="exact", argv=("pytest", "-q")) -> ActionDescriptor:
    if parse == "unknown":
        return ActionDescriptor(tool=tool, parse_status="unknown", paths=list(paths))
    return ActionDescriptor(cwd_path=".", tool=tool, action_kind=kind, executable=argv[0] if argv else None, argv=list(argv) if argv else None, paths=list(paths), parse_status=parse)


def query(*, act=None, environment=None, workspace=WS, task=None, branch=None, text="") -> ContextQuery:
    return ContextQuery(session_id=SESSION, task_id=task, workspace_id=workspace, purpose="pre_action", text=text, action=act, environment=environment or {}, branch_ref=branch)


def c(kind, value, key="", **kw) -> Condition:
    return Condition(kind=kind, key=key, value=value, **kw)


# ---------------------------------------------------------------------------
# Plan-named tests


def test_unknown_condition_cannot_caution():
    """A23: an unknown condition evaluates unknown, is at most labeled context, and a caution item refuses it."""
    unknown_condition = c("environment_equals", "true", key="ci")
    q = query(act=action(["src/app.py"]))  # the query carries no ci value
    assert cond.evaluate_conditions([unknown_condition], q) == "unknown"
    # AND with a satisfied condition stays unknown; only a false condition decides.
    assert cond.evaluate_conditions([c("path", "src/"), unknown_condition], q) == "unknown"
    assert cond.evaluate_conditions([c("path", "docs/"), unknown_condition], q) == "false"
    assert cond.advice_for("unknown", "current", caution_candidate=True) == "context"
    assert cond.advice_for("true", "needs_revalidation", caution_candidate=True) == "context"
    assert cond.advice_for("true", "current", caution_candidate=True) == "caution"
    assert cond.advice_for("false", "current", caution_candidate=True) is None
    with pytest.raises(ValidationError):
        ContextItem(ref={"kind": "claim", "id": "claim_66666666-6666-4666-8666-666666666666", "revision": 1}, text="t", advice="caution", basis="observed", applicability="unknown", freshness="current", why=["path_match"])
    # A failure lesson without complete dependency fingerprints cannot earn a caution either.
    assert cond.dependency_applicability([], {}) == "unknown"
    assert cond.dependency_applicability([DependencyRef(kind="file", key="src/app.py", fingerprint=None)], {"file:src/app.py": FP1}) == "unknown"


def test_scope_precedes_similarity():
    """A23 / SYSTEM_SPEC §8.1: scope eligibility is decided before any similarity; text overlap cannot override it."""
    text = "pytest fails on src/app.py with ImportError"
    q = query(act=action(["src/app.py"]), text=text, task=TASK, environment={"os": "linux"})
    candidates = [
        (Scope(workspace_ids=[OTHER_WS]), []),  # identical wording, another workspace
        (Scope(paths=["docs/"]), []),  # identical wording, other paths
        (Scope(environment={"os": "windows"}), []),  # identical wording, another platform
        (Scope(task_ids=["task_66666666-6666-4666-8666-666666666666"]), []),  # another task
        (Scope(paths=["src/"]), [c("path", "src/app.py")]),  # low overlap, in scope
        (Scope(), [c("environment_equals", "true", key="ci")]),  # in scope, unknown condition
    ]
    assert cond.in_scope(candidates, q) == [4, 5]
    assert [cond.applicability(s, cs_, q) for s, cs_ in candidates] == ["false", "false", "false", "false", "true", "unknown"]
    # Branch annotations are recall metadata, never eligibility.
    assert cond.scope_applicability(Scope(branch_refs=["feature/x"]), query(branch="main")) == "true"


# ---------------------------------------------------------------------------
# Tri-state combination and exclusions


def test_conditions_combine_with_and_including_exclusions():
    q = query(act=action(["src/app.py"]), environment={"os": "linux", "python_version": "3.12.4"})
    assert cond.evaluate_conditions([], q) == "true"
    assert cond.evaluate_conditions([c("path", "src/"), c("environment_equals", "linux", key="os")], q) == "true"
    assert cond.evaluate_conditions([c("path", "src/"), c("environment_equals", "windows", key="os")], q) == "false"
    # Exclusions negate a known result and leave unknown unknown.
    assert cond.evaluate_conditions([c("path", "src/vendor/", exclude=True)], q) == "true"
    assert cond.evaluate_conditions([c("path", "src/", exclude=True)], q) == "false"
    assert cond.evaluate_conditions([c("environment_equals", "true", key="ci", exclude=True)], q) == "unknown"
    assert cond.evaluate_conditions([c("version_range", "3.12", key="python_version", upper="3.12.99"), c("path", "src/app.py", exclude=True)], q) == "false"
    assert cond.all_of(["true", "unknown", "false"]) == "false" and cond.any_of(["false", "unknown"]) == "unknown"


def test_paths_are_exact_or_directory_prefixes_without_globs():
    q = query(act=action(["src/app.py", "tests/test_app.py"]))
    assert cond.evaluate_condition(c("path", "src/app.py"), q) == "true"
    assert cond.evaluate_condition(c("path", "src/"), q) == "true"
    assert cond.evaluate_condition(c("path", "src"), q) == "false"  # not a prefix without the trailing '/'
    for pattern in ("src/*.py", "src/app.p?", "src/[ab].py", "src/{a,b}.py"):  # no model-authored globs (DATA_CONTRACTS §1.1)
        with pytest.raises(ValidationError):
            c("path", pattern)
    assert cond.evaluate_condition(c("path", "s"), q) == "false"
    # Names that differ only by case or Unicode normalization may be one file on Windows/macOS: unknown, never lowercased.
    assert cond.evaluate_condition(c("path", "SRC/APP.py"), q) == "unknown"
    assert cond.evaluate_condition(c("path", "Src/"), q) == "unknown"
    nfd = query(act=action(["docs/re\u0301sume\u0301.md"]))
    assert cond.evaluate_condition(c("path", "docs/r\u00e9sum\u00e9.md"), nfd) == "unknown"
    # No action, no paths or an unparsed action: unknown.
    assert cond.evaluate_condition(c("path", "src/"), query()) == "unknown"
    assert cond.evaluate_condition(c("path", "src/"), query(act=action([]))) == "unknown"
    assert cond.evaluate_condition(c("path", "src/"), query(act=action(["src/app.py"], parse="unknown"))) == "unknown"
    # Portable condition paths only: absolute, drive-letter, backslash and parent paths are refused at the contract.
    for bad in ("/etc/passwd", "C:/repo/src/", "src\\app.py", "../outside/"):
        with pytest.raises(ValidationError):
            c("path", bad)


def test_environment_equals_only_over_registered_keys():
    q = query(environment={"os": "linux", "arch": "x86_64", "ci": "unknown"})
    assert cond.evaluate_condition(c("environment_equals", "linux", key="os"), q) == "true"
    assert cond.evaluate_condition(c("environment_equals", "aarch64", key="arch"), q) == "false"
    assert cond.evaluate_condition(c("environment_equals", "true", key="ci"), q) == "unknown"  # ci unknown is unknown
    assert cond.evaluate_condition(c("environment_equals", "3.12.4", key="python_version"), q) == "unknown"  # missing
    for key, value in (("HOME", "/root"), ("AWS_REGION", "us-east-1"), ("os", "solaris")):
        with pytest.raises(ValidationError):
            c("environment_equals", value, key=key)
    with pytest.raises(ValidationError):
        query(environment={"PATH": "/usr/bin"})


def test_version_ranges_use_pep440_never_lexicographic():
    def v(current, lower, upper=None, key="python_version"):
        return cond.evaluate_condition(c("version_range", lower, key=key, upper=upper), query(environment={key: current}))

    assert v("3.10.2", "3.9", "3.11") == "true"  # lexicographically "3.10" < "3.9"
    assert v("3.9.18", "3.10") == "false"
    assert v("3.13.0", "3.12") == "true"  # no upper bound
    assert v("3.12.0", "3.12.0", "3.12.0") == "true" and v("3.12.1", "3.12.0", "3.12.0") == "false"
    assert v("3.13.0rc1", "3.13") == "false" and v("3.13.0", "3.13.0rc1", "3.13.0") == "true"  # pre-releases order by PEP 440
    assert v("v20.11.1", "v18", "v20.99", key="node_version") == "true"
    assert v("v22.1.0", "v18", "v20.99", key="node_version") == "false"
    # Outside the PEP 440 grammar: unknown, unless the condition specifies exact comparison.
    assert v("3.12-custom-build", "3.12", "3.13") == "unknown"
    assert v("3.12-custom-build", "3.12-custom-build", "3.12-custom-build") == "true"
    assert v("3.12-other-build", "3.12-custom-build", "3.12-custom-build") == "false"
    assert v("3.12.4", "3.13", "3.12") == "unknown"  # an inverted range states nothing
    assert cond.evaluate_condition(c("version_range", "3.12", key="python_version"), query()) == "unknown"
    with pytest.raises(ValidationError):
        c("version_range", "1.0", key="os")


def test_branch_ref_is_an_explicit_predicate_not_an_annotation():
    """A62: explicit branch constraints apply; branch annotations never restrict, and fingerprints decide caution."""
    on_feature = query(branch="feature/login")
    assert cond.evaluate_condition(c("branch_ref", "feature/login"), on_feature) == "true"
    assert cond.evaluate_condition(c("branch_ref", "main"), on_feature) == "false"
    assert cond.evaluate_condition(c("branch_ref", "main"), query()) == "unknown"
    lesson_scope = Scope(branch_refs=["feature/login"])  # where the lesson was learned
    after_merge = query(branch="main")
    assert cond.scope_applicability(lesson_scope, after_merge) == "true"
    deps = [DependencyRef(kind="file", key="src/auth.py", fingerprint=FP1), DependencyRef(kind="config", key="pyproject:tool.pytest", fingerprint=FP2)]
    unchanged = {"file:src/auth.py": FP1, "config:pyproject:tool.pytest": FP2}
    # Merged with unchanged dependencies: still applicable on main.
    assert cond.dependency_applicability(deps, unchanged) == "true"
    # The same branch later changes a dependency: caution suppressed regardless of branch name.
    assert cond.dependency_applicability(deps, {**unchanged, "file:src/auth.py": "f" * 64}) == "false"
    # Missing or unreadable current values: unknown.
    assert cond.dependency_applicability(deps, {"file:src/auth.py": FP1}) == "unknown"
    assert cond.dependency_applicability(deps, {**unchanged, "file:src/auth.py": None}) == "unknown"


def test_same_proposition_in_different_scopes_is_not_a_global_contradiction():
    """A18: claims for different branches or dependency versions each apply only in their own scope."""
    py312 = [c("version_range", "3.12", key="python_version", upper="3.12.99")]
    py313 = [c("version_range", "3.13", key="python_version", upper="3.13.99")]
    on_312, on_313 = query(environment={"python_version": "3.12.4"}), query(environment={"python_version": "3.13.1"})
    assert (cond.evaluate_conditions(py312, on_312), cond.evaluate_conditions(py313, on_312)) == ("true", "false")
    assert (cond.evaluate_conditions(py312, on_313), cond.evaluate_conditions(py313, on_313)) == ("false", "true")
    feature, main = [c("branch_ref", "feature/x")], [c("branch_ref", "main")]
    assert cond.evaluate_conditions(feature, query(branch="main")) == "false" and cond.evaluate_conditions(main, query(branch="main")) == "true"


# ---------------------------------------------------------------------------
# Real actions (A70)


def test_real_actions_use_host_arrays_and_ambiguity_stays_unknown(tmp_path):
    """A70: real 2.1.301 actions: exact argv are used as captured; a shell pipeline has no guessed kind or path."""
    p = ls.project(tmp_path)
    by_call = {e["payload"]["tool_call_id"]: ActionDescriptor.model_validate(e["payload"]["action"]) for e in p.events("tool_started")}
    pytest_run, pipeline_run, read = by_call["toolu_probe_0003"], by_call["toolu_probe_0013"], by_call["toolu_probe_0007"]
    assert pytest_run.argv == ["pytest", "-q", "test_mid.py"] and pipeline_run.parse_status == "unknown" and pipeline_run.argv is None
    test_kind = c("action_kind", "test")
    assert cond.evaluate_condition(test_kind, query(act=pytest_run)) == "true"
    assert cond.evaluate_condition(test_kind, query(act=pipeline_run)) == "unknown"  # never guessed from the command text
    assert cond.evaluate_condition(c("action_kind", "read"), query(act=read)) == "true"
    assert cond.evaluate_condition(c("path", "notes.txt"), query(act=read)) == "true"
    assert cond.evaluate_condition(c("path", "notes.txt"), query(act=pipeline_run)) == "unknown"
    assert cond.evaluate_condition(c("tool", "Bash"), query(act=pipeline_run)) == "true"  # the host-reported tool identity is known
    assert cond.evaluate_condition(c("tool", "Read"), query(act=pipeline_run)) == "false"


# ---------------------------------------------------------------------------
# Runtime provenance (SYSTEM_SPEC §13)


def _version_event(ctx, key, *, output, exe="python", at="2026-10-16T10:00:00.000000Z"):
    argv = [exe, "--version"]
    raw = RawEvent(
        adapter_id=cs.ADAPTER, adapter_version="1", source_event_key=key, session_id=cs.SESSION, host_session_id=cs.HOST_SESSION, kind="tool_finished", occurred_at=at,
        payload={"tool_call_id": key, "tool_name": "Bash", "arguments": {"command": " ".join(argv)}, "result_received": True, "outcome": "success", "exit_code": 0, "result_text": output, "action": cs.action(argv), "observation": None},
    )
    envelopes = normalize_event(ctx, raw)[0]
    assert pipeline.capture(ctx, envelopes).status == "accepted"
    pipeline.ingest_ready(ctx)


def _query_environment(ctx) -> dict[str, str]:
    with db.open_store(ctx, readonly=True) as store:
        return provenance.environment_values(store, ctx)


def test_missing_stale_or_conflicting_runtime_provenance_is_unknown(tmp_path):
    root = cs.init_project(tmp_path, "proj")
    ctx = identity.resolve_installation(root, actor=CONTROLLER)
    in_312 = c("version_range", "3.12", key="python_version", upper="3.12.99")

    def evaluate() -> str:
        environment = _query_environment(ctx)
        return cond.evaluate_condition(in_312, query(environment=environment, workspace=ctx.workspace_id))

    assert evaluate() == "unknown"  # missing: Recalith's own interpreter is never the project's Python
    with db.open_store(ctx) as store:
        provenance.register_executable(store, ctx, identity="python", fingerprint=FP1)
    _version_event(ctx, "v1", output="Python 3.12.4")
    assert evaluate() == "true"  # a certified observation bound to the registered executable
    with db.open_store(ctx) as store:
        provenance.register_executable(store, ctx, identity="python", fingerprint=FP2)
    assert evaluate() == "unknown"  # stale after the executable changed
    _version_event(ctx, "v2", output="Python 3.11.9", at="2099-01-01T00:00:00.000000Z")
    assert evaluate() == "false"  # a fresh observation restores a current value
    with db.open_store(ctx) as store:
        provenance.record_declared_runtime(store, ctx, key="python_version", value="3.12.4", config_revision=1)
    assert evaluate() == "unknown"  # declared and observed disagree without a resolved target
