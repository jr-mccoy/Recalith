# SPDX-License-Identifier: GPL-3.0-only
"""Project checks: unit tests plus a line-length rule (<= 100 characters).

    python tools/check.py [--jobs N]

``--jobs N`` runs the test modules in N parallel processes (default: one per CPU).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
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


def run_tests(jobs: int) -> int:
    if jobs <= 1:
        return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=ROOT).returncode
    modules = [f"tests.{path.stem}" for path in sorted((ROOT / "tests").glob("test_*.py"))]

    def one(module: str) -> int:
        return subprocess.run([sys.executable, "-m", "unittest", module], cwd=ROOT).returncode

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        codes = list(pool.map(one, modules))
    return 1 if any(codes) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fieldnotes project checks")
    parser.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 1, help="parallel test processes (default: one per CPU)")
    ns = parser.parse_args(argv)
    notes_home = os.environ["NOTES_HOME"]  # the check harness writes scratch notes here
    print(f"using NOTES_HOME={notes_home}")
    tests = run_tests(ns.jobs)
    style = line_lengths()
    return 1 if tests or style else 0


if __name__ == "__main__":
    sys.exit(main())
