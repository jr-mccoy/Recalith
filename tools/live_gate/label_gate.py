# SPDX-License-Identifier: GPL-3.0-only
"""Write a reviewer's adjudication.json from a live gate's adjudication.suggested.json.

Read every item and its reason first (labels-to-review.md in the results directory). Then, from the repository root:

    .venv\\Scripts\\python.exe tools\\live_gate\\label_gate.py C:\\Code\\rl-gate10 --reviewer "<the route>" --independent no
        [--set KEY=LABEL ...]

Each item's label becomes its suggestion unless --set names it. KEY is the item's key or a unique prefix of it, such as
smoke-L1-ledgerlite-test-command#1. Claim labels are supported|unsupported; lesson labels are
recalled|missed|evidence_absent. --independent says whether you wrote your labels without having read SYSTEM_SPEC §7.
The helper never overwrites an existing adjudication.json. Afterwards run evals\\run.py report on the same directory.
"""
import argparse
import json
import os
import sys
from pathlib import Path

CLAIM = ("supported", "unsupported")
LESSON = ("recalled", "missed", "evidence_absent")

ap = argparse.ArgumentParser()
ap.add_argument("results", type=Path)
ap.add_argument("--reviewer", required=True)
ap.add_argument("--independent", required=True, choices=("yes", "no"))
ap.add_argument("--set", action="append", default=[], metavar="KEY=LABEL")
ns = ap.parse_args()

suggested = ns.results / "adjudication.suggested.json"
out = ns.results / "adjudication.json"
if out.exists():
    sys.exit(f"{out} exists; move it aside first")
data = json.loads(suggested.read_text(encoding="utf-8"))
overrides = {}
for item in ns.set:
    key, _, label = item.partition("=")
    hits = [(sec, k) for sec in ("claims", "lessons") for k in data[sec] if k.startswith(key)]
    if len(hits) != 1:
        sys.exit(f"--set {item}: {len(hits)} items match {key!r}")
    sec, full = hits[0]
    if label not in (CLAIM if sec == "claims" else LESSON):
        sys.exit(f"--set {item}: {label!r} is not a {sec[:-1]} label")
    overrides[full] = label
for sec in ("claims", "lessons"):
    for key, item in data[sec].items():
        item["label"] = overrides.get(key, item["suggested"])
data["reviewers"] = [{"route": ns.reviewer, "independent_of_system_spec_7": ns.independent == "yes"}]
data["labeled_from"] = "adjudication.suggested.json, adopted by the reviewer" + (f" with {len(overrides)} change(s)" if overrides else "")
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
for key, label in overrides.items():
    print(f"changed: {key} -> {label}")
claims = [v["label"] for v in data["claims"].values()]
lessons = [v["label"] for v in data["lessons"].values()]
print(f"wrote {out}: claims {claims.count('supported')}/{len(claims)} supported; lessons "
      f"{lessons.count('recalled')} recalled, {lessons.count('missed')} missed, {lessons.count('evidence_absent')} evidence_absent")
print(f"next: .venv\\Scripts\\python.exe evals\\run.py report {ns.results}")
