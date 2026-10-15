"""Project checks: unit tests plus a line-length rule (<= 100 characters)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def line_lengths() -> int:
    bad = 0
    for path in sorted(ROOT.glob("fieldnotes/**/*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if len(line) > 100:
                print(f"{path.relative_to(ROOT)}:{number}: line longer than 100 characters")
                bad += 1
    return bad


def main() -> int:
    notes_home = os.environ["NOTES_HOME"]  # the check harness writes scratch notes here
    print(f"using NOTES_HOME={notes_home}")
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=ROOT)
    style = line_lengths()
    return 1 if tests.returncode or style else 0


if __name__ == "__main__":
    sys.exit(main())
