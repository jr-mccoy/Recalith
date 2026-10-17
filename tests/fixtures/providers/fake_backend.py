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
  record OUTFILE           appends the exact request it received on stdin, its cwd, HOME and
                           environment key names (one JSON line per call), answers ok
  narrative PIDLOG [SLEEP] answers the real request it received (Task 7 preparers): a task
                           narrative patch, an episode title revision, capacity rejections for a
                           review batch, otherwise a no-op; records its pid and a grandchild's pid
                           in PIDLOG and keeps the grandchild sleeping (a tree to contain)
  stream BODY_BYTES PAD    a Claude-style stream-json envelope around a 15 KB episode body
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


def narrative_body(request: dict) -> str:
    def text(value: str) -> dict:
        return {"text": value, "evidence": [], "basis": "inferred"}

    purpose = request.get("purpose")
    if purpose == "update_task" and request.get("task_state"):
        task = request["task_state"]
        ref = {"kind": "task", "id": task["task_id"], "revision": task["revision"]}
        payload = {"task_id": task["task_id"], "expected_revision": task["revision"], "patches": [{"op": "set", "field": "next_action", "value": text("Continue from the last checkpoint.")}]}
        return json.dumps({"operations": [{"local_ref": "narrative", "kind": "update_task", "depends_on": [], "target": ref, "payload": payload, "evidence": [], "reason": "task narrative"}]})
    if purpose == "build_episode" and request.get("episodes"):
        episode = request["episodes"][0]
        ref = {"kind": "episode", "id": episode["episode_id"], "revision": episode["revision"]}
        payload = {"episode_id": episode["episode_id"], "expected_revision": episode["revision"], "patches": [{"op": "set", "field": "title", "value": ("Narrative: " + episode["title"])[:200]}]}
        return json.dumps({"operations": [{"local_ref": "narrative", "kind": "revise_episode", "depends_on": [], "target": ref, "payload": payload, "evidence": [], "reason": "episode narrative"}]})
    if purpose == "review_claims" and request.get("review_batch"):
        batch = request["review_batch"]
        ops = []
        for i, ref in enumerate(batch["candidate_refs"]):
            payload = {"batch_id": batch["batch_id"], "candidate_ref": ref, "verdict": "reject", "objections": ["review_capacity"], "evidence_ids": []}
            ops.append({"local_ref": f"a{i}", "kind": "assess_claim", "depends_on": [], "target": ref, "payload": payload, "evidence": [], "reason": ""})
        return json.dumps({"operations": ops})
    return json.dumps({"operations": [], "no_op_reason": "nothing new"})


def stream_envelope(body: str, pad: int) -> str:
    lines = [
        {"type": "system", "subtype": "init", "tools": [], "mcp_servers": [], "plugins": [{"name": "builtin-a", "path": "builtin"}], "apiKeySource": "ANTHROPIC_API_KEY", "claude_code_version": "9.9.9", "model": "fake-resolved-model"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": body}]}, "padding": "m" * pad},
        {"type": "result", "subtype": "success", "is_error": False, "result": body, "usage": {"input_tokens": 40, "cache_read_input_tokens": 2, "output_tokens": len(body) // 3}},
    ]
    return "\n".join(json.dumps(line) for line in lines) + "\n"


def main(argv: list[str]) -> int:
    mode = argv[1]
    request = sys.stdin.buffer.read()
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
    elif mode == "record":
        with open(argv[2], "ab") as fh:
            fh.write(json.dumps({"cwd": os.getcwd(), "home": os.environ.get("HOME"), "keys": sorted(os.environ), "request": request.decode("utf-8")}).encode("utf-8") + b"\n")
        answer(json.dumps({"operations": [], "no_op_reason": "nothing new"}))
    elif mode == "narrative":
        child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(120)"])
        with open(argv[2], "a", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {child.pid}\n")
        time.sleep(float(argv[3]) if len(argv) > 3 else 0.2)
        answer(narrative_body(json.loads(request)))
    elif mode == "stream":
        sys.stdout.write(stream_envelope(body_episode(int(argv[2])), int(argv[3]) if len(argv) > 3 else 0))
        sys.stdout.flush()
    else:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
