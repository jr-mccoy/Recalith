#!/usr/bin/env python3
"""Check the preview release checklist (ACCEPTANCE_TESTS §8, preview column; decision 0020).

    python tools/release_checklist.py [--checklist docs/release/claude_preview_checklist.json]

The checklist is an itemized JSON record: every §8 bullet maps to at least one
item, and every item records its status (``passed``, ``blocked``, ``failed``,
``pending`` or ``not_applicable``), the evidence paths that support it and a
detail line. This tool verifies the record, not the release: every bullet is
covered, statuses are registered values, evidence paths exist in the
repository, a ``passed`` item names evidence, a ``blocked`` or ``failed`` item
names its blocker, the release verdict is ``ready`` only when every item
passed, and the readiness item names ``claude_preview`` and every deferred
capability of this engine. It prints the verdict and each item's status.

Exit 0 when the record is consistent (whatever the verdict), 1 when it is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"passed", "blocked", "failed", "pending", "not_applicable"}


def section_8_bullets() -> list[str]:
    doc = (ROOT / "docs" / "ACCEPTANCE_TESTS.md").read_text(encoding="utf-8")
    body = doc.split("## 8. Release checklist", 1)[1]
    return [line[2:].strip() for line in body.splitlines() if line.startswith("- ")]


def check(path: Path) -> tuple[list[str], dict]:
    sys.path.insert(0, str(ROOT / "src"))
    from recalith.contracts.health import DEFERRED_FULL_CAPABILITIES

    data = json.loads(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    bullets = section_8_bullets()
    if data.get("profile") != "claude_preview":
        problems.append("the checklist is not for claude_preview")
    covered: set[int] = set()
    for item in data.get("items", []):
        name = item.get("id", "?")
        if item.get("status") not in STATUSES:
            problems.append(f"{name}: status {item.get('status')!r} is not registered")
        for index in item.get("section_8", []):
            if not 1 <= index <= len(bullets):
                problems.append(f"{name}: no §8 bullet {index}")
            covered.add(index)
        evidence = item.get("evidence", [])
        for ref in evidence:
            target = ref.split("::", 1)[0].split("#", 1)[0]
            if not (ROOT / target).exists():
                problems.append(f"{name}: evidence {ref} does not exist")
        if item.get("status") == "passed" and not evidence:
            problems.append(f"{name}: passed without evidence")
        if item.get("status") in ("blocked", "failed") and not item.get("blocker"):
            problems.append(f"{name}: {item['status']} without its blocker")
        if not item.get("detail"):
            problems.append(f"{name}: no detail")
    missing = sorted(set(range(1, len(bullets) + 1)) - covered)
    if missing:
        problems.append(f"§8 bullets without an item: {missing}")
    statuses = [i.get("status") for i in data.get("items", [])]
    expected = "ready" if statuses and all(s in ("passed", "not_applicable") for s in statuses) else "blocked"
    if data.get("verdict") != expected:
        problems.append(f"verdict {data.get('verdict')!r} but the items say {expected!r}")
    readiness = next((i for i in data.get("items", []) if i.get("id") == "readiness_names_profile_and_unavailable_features"), None)
    if readiness is None:
        problems.append("no readiness item")
    else:
        named = set(readiness.get("unavailable_features", []))
        if readiness.get("profile") != "claude_preview" or named != set(DEFERRED_FULL_CAPABILITIES):
            problems.append(f"readiness must name claude_preview and exactly the {len(DEFERRED_FULL_CAPABILITIES)} deferred capabilities")
    focus = next((i for i in data.get("items", []) if i.get("id") == "review_focus_rechecked"), None)
    if focus is None or len(focus.get("focus_items", [])) != 5:
        problems.append("the review focus item must recheck all five items")
    summary = {"verdict": data.get("verdict"), "items": {i.get("id"): i.get("status") for i in data.get("items", [])}, "bullets": len(bullets)}
    return problems, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checklist", type=Path, default=ROOT / "docs" / "release" / "claude_preview_checklist.json")
    ns = parser.parse_args(argv)
    problems, summary = check(ns.checklist)
    print(json.dumps({**summary, "problems": problems}, indent=1, sort_keys=True))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
