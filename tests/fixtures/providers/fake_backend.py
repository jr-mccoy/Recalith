"""Deterministic stand-in for a provider CLI, used only by worker tests (never certified).

    python -I fake_backend.py MODE [ARGS...]

Reads the request from stdin and answers with a host-style JSON envelope
``{"type": "result", "result": <body as a JSON string>, "usage": {...}}``.

Modes:
  ok BODY_BYTES PAD        a valid no-op body; PAD bytes of envelope metadata
  episode BODY_BYTES PAD   a valid build_episode body of about BODY_BYTES
  hang                     never answers (the worker's timeout must kill it)
  flood                    writes far more than 256 KiB of stdout
  stderr_flood             writes 200 KiB of stderr, then answers ok
  grandchild PIDFILE       starts a long-lived grandchild, records its pid, hangs
  env OUTFILE              records its environment key names and role markers, answers ok
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time


def body_episode(size: int) -> str:
    count = max(2, -(-size // 6000))
    per_step = max(100, (size - 1200) // count - 260)
    supported = lambda text: {"text": text, "evidence": [], "basis": "observed"}  # noqa: E731
    episode = {
        "task_id": "task_00000000-0000-4000-8000-000000000000",
        "title": "Fix import path",
        "started_at": "2026-10-15T12:00:00.000000Z",
        "objective": supported("Make the test suite import the package."),
        "steps": [{"ordinal": i, "action": supported("x" * per_step), "outcome": "failure" if i % 2 == 0 else "success"} for i in range(count)],
        "outcome": supported("Tests pass."),
        "source_event_ids": ["evt_" + "0" * 64],
    }
    op = {"local_ref": "op1", "kind": "create_episode", "depends_on": [], "target": None, "payload": episode, "evidence": [], "reason": "because"}
    return json.dumps({"operations": [op]})


def answer(body: str, pad: int = 0) -> None:
    sys.stdout.write(json.dumps({"type": "result", "result": body, "usage": {"input_tokens": 40, "output_tokens": len(body) // 3}, "session_id": "fake", "padding": "m" * pad}))
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    mode = argv[1]
    sys.stdin.buffer.read()
    if mode == "ok":
        answer(json.dumps({"operations": [], "no_op_reason": "nothing new"}), int(argv[3]) if len(argv) > 3 else 0)
    elif mode == "episode":
        answer(body_episode(int(argv[2])), int(argv[3]) if len(argv) > 3 else 0)
    elif mode == "hang":
        time.sleep(3600)
    elif mode == "flood":
        chunk = "z" * 65536
        for _ in range(64):
            sys.stdout.write(chunk)
        sys.stdout.flush()
    elif mode == "stderr_flood":
        sys.stderr.write("e" * 200_000)
        sys.stderr.flush()
        answer(json.dumps({"operations": [], "no_op_reason": "nothing new"}))
    elif mode == "grandchild":
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(3600)"])
        with open(argv[2], "w", encoding="utf-8") as fh:
            fh.write(str(child.pid))
        time.sleep(3600)
    elif mode == "env":
        record = {"keys": sorted(os.environ), "worker_marker": os.environ.get("RECALITH_WORKER_INSTALLATION"), "curator_marker": os.environ.get("RECALITH_CURATOR_INSTALLATION")}
        with open(argv[2], "w", encoding="utf-8") as fh:
            fh.write(json.dumps(record))
        answer(json.dumps({"operations": [], "no_op_reason": "nothing new"}))
    else:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
