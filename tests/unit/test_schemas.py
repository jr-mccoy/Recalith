"""Schema snapshots and shared wire fixtures (Task 1 gate)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import generate_schemas  # noqa: E402
from recalith.contracts.events import EventEnvelope  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "contracts" / "envelopes"


def test_schema_snapshots_have_no_unversioned_drift():
    assert generate_schemas.drift() == []


def test_snapshots_cover_every_model_the_provider_schema_is_built_from():
    """Audit 2026-11-06 CAP-8: a change to an operation payload, a tool payload or an observation is schema drift."""
    from recalith.contracts import events, operations

    covered = set(generate_schemas.MODELS.values())
    assert set(operations.PAYLOAD_MODELS.values()) <= covered
    assert {events.ToolPayload, events.ObservationDescriptor, events.AgentAttemptPayload} <= covered


def test_every_snapshot_forbids_unknown_top_level_fields():
    for name in generate_schemas.MODELS:
        schema = json.loads((generate_schemas.SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert schema.get("additionalProperties") is False, name


@pytest.mark.parametrize("path", sorted((FIXTURES / "valid").glob("*.json")), ids=lambda p: p.stem)
def test_valid_wire_fixtures_accepted(path):
    EventEnvelope.model_validate_json(json.dumps(json.loads(path.read_text(encoding="utf-8"))["envelope"]))


@pytest.mark.parametrize("path", sorted((FIXTURES / "invalid").glob("*.json")), ids=lambda p: p.stem)
def test_invalid_wire_fixtures_rejected(path):
    text = path.read_text(encoding="utf-8")
    start = text.index('"envelope"')
    body = text[text.index("{", start) : text.rindex("}")]
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate_json(body)
