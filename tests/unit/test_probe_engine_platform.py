"""The engine-mode host probe on native Windows (tools/probe_engine.py; decision 0027).

The probe ran only on Linux before: it linked the shared runtime with a
symlink (a privilege Windows grants only in Developer Mode or to
administrators), drove the deny probe through the POSIX launcher (which exits 4
under Git Bash before the operator guard) and named fixture directories so
long that the host's transcript path passed the 260-character limit of a
Windows without long-path support. These tests pin the platform switches; the
real-host run is ``tests/platform/test_claude_smoke.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import probe_engine as pe  # noqa: E402
from recalith.integrations import claude as integration  # noqa: E402

SPELLINGS = [".recalith/bin/recalith", "python -m recalith"]


def test_posix_deny_commands_are_unchanged():
    commands = pe.deny_commands(SPELLINGS, windows=False)
    covered = [c for c in commands if c["covered"]]
    assert [c["command"] for c in covered[:2]] == [f"{s} {pe.ADMIN_SAMPLE_ARGS['declare']}" for s in SPELLINGS]
    forms = covered[2:]
    assert [c["form"] for c in forms] == [f for f in integration.ADMIN_FORMS if f != "declare"]
    assert all(c["command"] == f".recalith/bin/recalith {pe.ADMIN_SAMPLE_ARGS[c['form']]}" for c in forms)
    assert [(c["gap"], c["command"]) for c in commands if not c["covered"]] == list(pe.GAP_COMMANDS)


def test_windows_deny_commands_reach_the_guard_through_the_cmd_launcher():
    commands = pe.deny_commands(SPELLINGS, windows=True)
    forms = [c for c in commands if c["covered"]][2:]
    assert forms and all(c["command"].startswith(".recalith/bin/recalith.cmd ") for c in forms)
    gaps = [c for c in commands if not c["covered"]]
    assert [(c["gap"], c["command"]) for c in gaps] == list(pe.WINDOWS_GAP_COMMANDS)
    assert all(".recalith/bin/recalith.cmd" in c["command"] for c in gaps)
    assert not any(c["command"].startswith("bash .recalith/bin/recalith") for c in gaps)  # bash cannot run a .cmd as a script


def test_windows_fixture_names_are_short_and_stable(monkeypatch):
    monkeypatch.setattr(pe, "WINDOWS", True)
    monkeypatch.setattr(pe, "_SHORT_NAMES", {})
    a, b = pe.short_name("trial-live-session_start-positive-1"), pe.short_name("trial-live-session_start-positive-2")
    assert a != b and len(a) <= 4 and pe.short_name("trial-live-session_start-positive-1") == a
    monkeypatch.setattr(pe, "WINDOWS", False)
    assert pe.short_name("trial-live-session_start-positive-1") == "trial-live-session_start-positive-1"


def test_windows_private_attempts_use_a_real_python():
    pairs = dict(pe.WINDOWS_PRIVATE_ATTEMPTS)
    assert pairs["Bash python"][1]["command"].startswith("python -c ")
    assert dict(pe.PRIVATE_ATTEMPTS)["Bash python"][1]["command"].startswith("python3 -c ")  # POSIX unchanged
    assert [label for label, _ in pe.WINDOWS_PRIVATE_ATTEMPTS] == [label for label, _ in pe.PRIVATE_ATTEMPTS]


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows; POSIX uses a symlink")
def test_runtime_link_is_a_junction_that_unlinks_without_touching_its_target(tmp_path):
    target = tmp_path / "shared-runtime"
    (target / "0.1.0.dev0").mkdir(parents=True)
    (target / "0.1.0.dev0" / "marker").write_text("kept\n", encoding="utf-8")
    link = tmp_path / "fixture" / "runtime"
    link.parent.mkdir()
    pe.link_dir(link, target)
    assert (link / "0.1.0.dev0" / "marker").read_text(encoding="utf-8") == "kept\n"
    pe.unlink_dir(link)
    assert not link.exists() and (target / "0.1.0.dev0" / "marker").exists()


def test_canary_question_names_one_unambiguous_value():
    """Session start and compaction restoration carry the nonce in an open intent question (decision 0013). The first
    live run seeded "the canary value is X" against "no canary value is recorded": the model, told to report a supplied
    value and not to guess, answered NONE in 5 of 6 positives. The conflict is now the option; both sides name the value."""
    (a_stmt, a_claim), (b_stmt, b_claim) = pe.canary_declarations("c0ffee00c0ffee00")
    assert "c0ffee00c0ffee00" in a_claim and "c0ffee00c0ffee00" in b_claim and a_claim != b_claim and a_stmt != b_stmt
    (_, na), (_, nb) = pe.canary_declarations(None)
    assert na != nb and "withheld" in na and "withheld" in nb
    assert [s for s, _ in pe.canary_declarations(None)] == [a_stmt, b_stmt]  # negatives keep the positives' shape
