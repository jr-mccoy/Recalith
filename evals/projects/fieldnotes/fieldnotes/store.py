"""JSON-file note storage."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def notes_path() -> Path:
    return Path(os.environ["NOTES_HOME"]) / "notes.json"


def load() -> list[dict]:
    path = notes_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def add(text: str, *, now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    note = {"text": text, "created": moment.isoformat()}
    notes = load()
    notes.append(note)
    notes_path().write_text(json.dumps(notes, indent=2), encoding="utf-8")
    return note
