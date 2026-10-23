"""Fixture-capture and probe-report sanitization (tools/capture_claude_fixtures.py, tools/probe_common.py; decision 0027).

The first native-Windows capture (Claude Code 2.1.309) leaked the login name and
the repository path: the host's ``/compact`` output echoes each hook command as a
JSON-encoded string, so a Windows path arrives JSON-escaped (``C:\\\\Users\\\\…``),
which the literal placeholders did not match. The host's temporary directory
(``%SystemRoot%\\temp\\claude``) had no placeholder on Windows. These tests pin
every spelling, on any OS, and keep POSIX sanitization literal.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))

import capture_claude_fixtures as cap  # noqa: E402

WS = r"C:\Users\someone\AppData\Local\Temp\recalith-claude-fixture-ab12\workspace"
REPO_WIN = r"C:\Code\Repo"
PY = r"C:\Code\Repo\.venv\Scripts\python.exe"


def _placeholders() -> cap.Placeholders:
    return cap.Placeholders({WS: "<workspace>", REPO_WIN: "<repo>", PY: "<python>", r"C:\Users\someone": "<user-home>", r"C:\Windows\temp\claude": "<host-tmp>"})


def test_windows_path_forms():
    forms = cap.path_forms(REPO_WIN)
    assert forms == [r"C:\Code\Repo", "C:/Code/Repo", r"C:\\Code\\Repo", r"C:\\\\Code\\\\Repo", "/c/Code/Repo"]
    assert cap.path_forms("/tmp/x/workspace") == ["/tmp/x/workspace"]


def test_every_windows_spelling_is_replaced():
    ph = _placeholders()
    command = json.dumps([PY, "-I", REPO_WIN + r"\tools\fixtures\hook_recorder.py", "--log", r"C:\Users\someone\AppData\Local\Temp\x\hooks.jsonl"])
    echoed = f"<local-command-stdout>Compacted PreCompact {command} completed successfully"  # the host's JSON-in-text echo
    cases = {
        WS + r"\notes.txt": r"<workspace>\notes.txt",
        "C:/Users/someone/AppData/Local/Temp/recalith-claude-fixture-ab12/workspace": "<workspace>",  # $CLAUDE_PROJECT_DIR in Git Bash
        "/c/Users/someone/AppData/Local/Temp/recalith-claude-fixture-ab12/workspace/new.txt": "<workspace>/new.txt",  # MSYS
        r"c:\users\SOMEONE\appdata\local\temp\recalith-claude-fixture-ab12\workspace": "<workspace>",  # case-insensitive filesystem
        r"C:\Windows\temp\claude\slug\task.output": r"<host-tmp>\slug\task.output",
    }
    for raw, want in cases.items():
        assert ph.text(raw) == want, raw
    out = ph.text(echoed)
    assert "someone" not in out and "Code" not in out
    assert out.startswith('<local-command-stdout>Compacted PreCompact ["<python>", "-I", "<repo>\\\\tools')
    twice = json.dumps(json.dumps({"cwd": WS}))  # a JSON string inside a JSON string
    assert "someone" not in ph.text(twice)


def test_posix_sanitization_stays_literal():
    ph = cap.Placeholders({"/tmp/fx/workspace": "<workspace>", "/home/someone": "<user-home>"})
    assert ph.text("/tmp/fx/workspace/notes.txt") == "<workspace>/notes.txt"
    assert ph.text("/TMP/FX/WORKSPACE") == "/TMP/FX/WORKSPACE"  # case-sensitive: no folding on POSIX paths
    assert ph.text("/home/someone/.claude") == "<user-home>/.claude"


def test_host_tmp_dir_follows_the_child_environment():
    assert cap.host_tmp_dir({"SystemRoot": r"C:\Windows"}, windows=True) == r"C:\Windows\temp\claude"
    assert cap.host_tmp_dir({"TEMP": "D:\\t\\", "SystemRoot": r"C:\Windows"}, windows=True) == r"D:\t\claude"
    assert cap.host_tmp_dir({"TMP": r"E:\tmp", "SystemRoot": r"C:\Windows"}, windows=True) == r"E:\tmp\claude"


def test_unsanitized_detects_residue_key_and_login_name():
    ph = _placeholders()
    clean = ph.text(json.dumps({"cwd": WS, "transcript_path": r"C:\Users\someone\.claude\projects\x.jsonl"}))
    assert not cap.unsanitized(clean, ph, user="someone")
    escaped = json.dumps({"stdout": json.dumps([WS])})
    assert cap.unsanitized(escaped, ph, user="someone")  # residue: a spelling the placeholders replace
    assert cap.unsanitized('{"k": "' + cap.PLACEHOLDER_KEY + '"}', ph, user="someone")
    assert cap.unsanitized(r'{"p": "D:\\Other\\someone\\file"}', ph, user="someone")  # an unlisted path naming the login
    assert not cap.unsanitized('{"text": "someone said hello"}', ph, user="someone")  # a word, not a path component


def test_report_sanitizer_covers_windows_spellings():
    """Probe reports (docs/host-compatibility.json) list the deny probe's absolute spellings in forward-slash, native
    and MSYS forms; on Windows each must lose the login name, while POSIX replacement stays literal."""
    import probe_common as pc

    base = r"C:\Users\someone\AppData\Local\Temp\rl-ep-ab12"
    san = pc.Sanitizer({base: "<harness-root>", r"C:\Users\someone": "<home>"}, secrets=["sk-not-a-real-key-value"])
    report = {
        "spellings": [
            "C:/Users/someone/AppData/Local/Temp/rl-ep-ab12/rc/f05/ws/.recalith/bin/recalith",
            r"C:\Users\someone\AppData\Local\Temp\rl-ep-ab12\rc\f05\ws\.recalith\bin\recalith.cmd",
            "/c/Users/someone/AppData/Local/Temp/rl-ep-ab12/rc/f05/ws/.recalith/bin/recalith.cmd",
        ],
        "executable": r"c:\users\someone\.local\bin\claude.exe",
        "stderr": "auth sk-not-a-real-key-value failed",
    }
    out = json.dumps(san.value(report))
    assert "someone" not in out and "sk-not-a-real" not in out
    assert san.value(report)["spellings"][0] == "<harness-root>/rc/f05/ws/.recalith/bin/recalith"
    posix = pc.Sanitizer({"/home/someone": "<home>"})
    assert posix.text("/home/someone/x /HOME/SOMEONE/x") == "<home>/x /HOME/SOMEONE/x"
