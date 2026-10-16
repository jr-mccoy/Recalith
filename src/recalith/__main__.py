"""`python -m recalith`: placeholder transport until Task 12a.

Every command returns an explicit ``capability_unavailable`` (exit 4) rather
than pretending to succeed (SYSTEM_SPEC §14). Task 12a replaces this with the
guarded CLI in ``recalith.cli``.
"""

from __future__ import annotations

import json
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = next((a for a in args if not a.startswith("-") and a not in _option_values(args)), None)
    print(json.dumps({"error": "capability_unavailable", "command": command, "detail": "the recalith CLI is not implemented in this engine build"}))
    return 4


def _option_values(args: list[str]) -> set[str]:
    values = set()
    for i, arg in enumerate(args[:-1]):
        if arg in ("--project", "--operator-token-file"):
            values.add(args[i + 1])
    return values


if __name__ == "__main__":
    sys.exit(main())
