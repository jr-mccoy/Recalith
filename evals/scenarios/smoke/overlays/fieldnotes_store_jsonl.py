"""JSON-lines note storage (one JSON object per line)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def notes_path() -> Path:
    return Path(os.environ["NOTES_HOME"]) / "notes.jsonl"


def load() -> list[dict]:
    path = notes_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add(text: str, *, now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    note = {"text": text, "created": moment.isoformat()}
    with notes_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(note) + "\n")
    return note
