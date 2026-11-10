# SPDX-License-Identifier: GPL-3.0-only
"""Copy a live gate's results into the repository with machine paths replaced, then scan the copy by count.

    python tools/live_gate/sanitize_record.py C:\\Code\\rl-gate10 docs/evaluations/preview-live-2026-11-04-gate10

The results directory becomes ``<run>``, temporary directories ``<temp>`` and the home directory ``<home>``. The copy is
replaced if it exists. Every count printed after the copy must be 0 before the record is committed (AGENTS.md: no
private local paths, user names, keys or model identifiers in tracked reports).
"""
import os
import re
import shutil
import sys
from pathlib import Path

FILES = ["report.json", "report.md", "run.json", "demonstrations.json", "adjudication-sheet.md", "adjudication.template.json",
         "adjudication.suggested.json", "adjudication.json", "outside-review.json"]
TEMP = re.compile(r"(?i)[A-Z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)[^\\/\"'\s]+(?:\\\\|\\|/)AppData(?:\\\\|\\|/)Local(?:\\\\|\\|/)Temp(?:(?:\\\\|\\|/)[^\s\"'`)]*)?")
HOME = re.compile(r"(?i)[A-Z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)[^\\/\"'\s]+|/(?:home|Users)/[^/\"'\s]+")


def variants(path: str) -> list[str]:
    fwd = path.replace("\\", "/")
    back = path.replace("/", "\\")
    out = {fwd, back, back.replace("\\", "\\\\"), fwd.lower(), back.lower(), back.lower().replace("\\", "\\\\")}
    drive = re.match(r"^([A-Za-z]):(.*)$", fwd)
    if drive:
        out.add(f"/{drive.group(1).lower()}{drive.group(2)}")
    return sorted(out, key=len, reverse=True)


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    names = FILES + [f"trials/{p.name}" for p in sorted((src / "trials").glob("*.json"))]
    names += [f"workload/{p.name}" for p in sorted((src / "workload").glob("*.json"))]
    names += [f"sensitivity/{p.name}" for p in sorted((src / "sensitivity").glob("*.json"))]  # decision 0049, reported apart
    if dst.exists():
        shutil.rmtree(dst)
    for name in names:
        path = src / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for v in variants(str(src)):
            text = text.replace(v, "<run>")
        text = HOME.sub("<home>", TEMP.sub("<temp>", text))
        out = dst / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
    users = {u for u in (os.environ.get("USERNAME"), os.environ.get("USER"), Path.home().name) if u}
    scan = {"user name": "(?i)" + "|".join(re.escape(u) for u in sorted(users)), "drive path": r"(?i)\b[a-z]:(\\|/)",
            "posix home": r"/(?:home|Users)/(?!<)", "posix drive": r"/c/(?:Users|Code)", "key": r"sk-ant|ANTHROPIC_API_KEY=",
            "email": r"[\w.]+@[\w.]+\.(?:com|org|net)",
            "model id": r"(?i)claude-(?:opus|sonnet|haiku|fable|\d)|\b(?:opus|sonnet|haiku|fable)[- ]?\d"}
    total = 0
    for label, pattern in scan.items():
        hits = [(p.relative_to(dst).as_posix(), m.group(0)) for p in dst.rglob("*") if p.is_file()
                for m in re.finditer(pattern, p.read_text(encoding="utf-8"))]
        total += len(hits)
        print(f"{label}: {len(hits)}", hits[:6])
    print("files:", sum(1 for p in dst.rglob("*") if p.is_file()))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
