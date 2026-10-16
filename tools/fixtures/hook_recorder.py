"""Owned, capture-only recorder hook used by tools/capture_claude_fixtures.py.

It appends the exact hook stdin, the event name it was registered for and the
transcript's byte length at the moment the hook fired, then exits 0 with no
output, so the host continues unchanged. It is a fixture, not a product hook:
it never injects context and never reads the transcript's contents.

    python -I hook_recorder.py --log PATH --event NAME
"""

from __future__ import annotations

import json
import os
import sys
import time


def main(argv: list[str]) -> int:
    log = argv[argv.index("--log") + 1]
    event = argv[argv.index("--event") + 1]
    data = sys.stdin.buffer.read()
    transcript_bytes = None
    try:
        payload = json.loads(data)
        path = payload.get("transcript_path") if isinstance(payload, dict) else None
        if isinstance(path, str):
            transcript_bytes = os.lstat(path).st_size
    except (ValueError, OSError):
        pass
    record = {"event": event, "monotonic": time.monotonic(), "transcript_bytes": transcript_bytes, "stdin": data.decode("utf-8", "replace")}
    with open(log, "ab") as fh:
        fh.write(json.dumps(record).encode("utf-8") + b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
