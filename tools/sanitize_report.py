#!/usr/bin/env python3
"""Apply the probes' own sanitizer to a compatibility report written before one of its rules existed.

    python tools/sanitize_report.py --config LOCAL_CONFIG --report docs/host-compatibility.json

The probes sanitize each section before writing it (``probe_common.Sanitizer``:
local paths in every spelling, secret-shaped text, and since decision 0027 the
configured model identifiers by role, ``<curator-model>`` and ``<agent-model>``).
This tool re-applies exactly that sanitizer to every section already in the
report, with the local configuration's models and this machine's home and
repository paths, so a rule added later reaches earlier evidence without hand
edits. It changes no recorded verdict, count or time: it only replaces strings
that the probes would not have written under the current rules. Key values are
never read; ``--config`` supplies names only.

Exit codes: 0 rewritten (or already sanitized), 2 invalid input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import probe_common as pc  # noqa: E402


def sanitizer(config: dict) -> pc.Sanitizer:
    replacements = {str(Path.home()): "<home>", str(ROOT): "<repo>"}
    replacements.update(pc.model_placeholders(config.get("provider") or {}, "curator"))
    replacements.update(pc.model_placeholders(config.get("delivery") or {}, "agent"))
    return pc.Sanitizer(replacements)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    ns = parser.parse_args(argv)
    try:
        config = json.loads(ns.config.read_text(encoding="utf-8"))
        report = json.loads(ns.report.read_text(encoding="utf-8"))
        sections = report["sections"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return pc.die_usage(f"cannot read the configuration or the report: {type(exc).__name__}")
    san = sanitizer(config)
    changed = 0
    for entries in sections.values():
        for key, value in list(entries.items()):
            clean = san.value(value)
            if clean != value:
                entries[key] = clean
                changed += 1
    ns.report.write_text(json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"report": ns.report.name, "sections_changed": changed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
