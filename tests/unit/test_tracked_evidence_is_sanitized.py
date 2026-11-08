"""Tracked evidence holds no machine path, user home or agent scratch path (AGENTS.md; audit 2026-11-06 REL-6).

Measurement reports, live-gate records and the host compatibility report are committed. They may name
placeholders (``<home>``, ``<repo>``, ``<run>``, ``<scratch>``) and fixture paths, never a real location.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import measure_worker_latency as mwl  # noqa: E402

TRACKED_EVIDENCE = [ROOT / "docs" / "measurements", ROOT / "docs" / "evaluations", ROOT / "docs" / "host-compatibility.json"]

MACHINE_PATHS = re.compile(
    r"/tmp/claude-\d"  # a coding agent's session scratch
    r"|/home/[a-z][a-z0-9_-]*/"  # a POSIX home
    r"|/Users/[A-Za-z][^/\s\"]*/"  # a macOS home
    r"|[A-Za-z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)[A-Za-z]"  # a Windows home, raw or JSON-escaped
)


def _files():
    for base in TRACKED_EVIDENCE:
        yield from ([base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file()))


def test_tracked_evidence_names_no_machine_path():
    hits = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="replace")
        hits += [f"{path.relative_to(ROOT)}: {m.group(0)}" for m in MACHINE_PATHS.finditer(text)]
    assert hits == []


def test_measurement_reports_record_only_the_output_file_name():
    for argv in (["--output", "/tmp/claude-0/x/scratchpad/logs/w.json"], ["--output=C:\\Users\\a\\w.json"]):
        recorded = " ".join(mwl.recorded_args(argv))
        assert "w.json" in recorded and not MACHINE_PATHS.search(recorded) and "scratchpad" not in recorded
