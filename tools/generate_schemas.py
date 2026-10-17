#!/usr/bin/env python3
"""Generate (or check) the approved JSON Schema snapshots of the strict contracts.

    python tools/generate_schemas.py          # rewrite src/recalith/contracts/schemas/
    python tools/generate_schemas.py --check  # exit 1 on unversioned schema drift

Provider output schemas are generated from these same Pydantic models; the
engine still validates every returned operation locally (SYSTEM_SPEC §10).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recalith.contracts import config, context, events, health, jobs, memory, operations, privacy, transfers  # noqa: E402

SCHEMA_DIR = ROOT / "src" / "recalith" / "contracts" / "schemas"
MODELS = {
    "EventEnvelope": events.EventEnvelope,
    "Segment": events.Segment,
    "CaptureReceipt": events.CaptureReceipt,
    "SourceConflict": events.SourceConflict,
    "EnvironmentObservation": events.EnvironmentObservation,
    "TaskState": memory.TaskState,
    "TaskBoundaryCandidate": memory.TaskBoundaryCandidate,
    "TaskBindingRevision": memory.TaskBindingRevision,
    "Episode": memory.Episode,
    "ClaimRevision": memory.ClaimRevision,
    "EvidenceCapsule": memory.EvidenceCapsule,
    "RootClass": memory.RootClass,
    "ReviewBatch": memory.ReviewBatch,
    "ModelRequest": operations.ModelRequest,
    "ModelProposalBody": operations.ModelProposalBody,
    "ModelResponse": operations.ModelResponse,
    "AdmissionDecision": operations.AdmissionDecision,
    "ApplyResult": operations.ApplyResult,
    "UndoPreview": operations.UndoPreview,
    "ContextQuery": context.ContextQuery,
    "ContextPacket": context.ContextPacket,
    "DeliveryReceipt": context.DeliveryReceipt,
    "OutcomeLink": context.OutcomeLink,
    "SessionScratch": context.SessionScratch,
    "ResolvedEvidence": context.ResolvedEvidence,
    "Job": jobs.Job,
    "FailureTrigger": jobs.FailureTrigger,
    "FailureRecheck": jobs.FailureRecheck,
    "BudgetReservation": jobs.BudgetReservation,
    "IngestResult": jobs.IngestResult,
    "DependencyChange": jobs.DependencyChange,
    "ForgetSelector": privacy.ForgetSelector,
    "ForgetPreview": privacy.ForgetPreview,
    "ForgetRequest": privacy.ForgetRequest,
    "ForgetResult": privacy.ForgetResult,
    "Tombstone": privacy.Tombstone,
    "OperatorTokenFile": privacy.OperatorTokenFile,
    "RestoreResult": privacy.RestoreResult,
    "ExportSelection": transfers.ExportSelection,
    "ArtifactManifest": transfers.ArtifactManifest,
    "ImportResult": transfers.ImportResult,
    "UpgradeResult": transfers.UpgradeResult,
    "HealthReport": health.HealthReport,
    "ProjectConfig": config.ProjectConfig,
    "ProviderConfig": config.ProviderConfig,
}


def render(name: str) -> str:
    schema = MODELS[name].model_json_schema(mode="validation")
    schema["$id"] = f"recalith:contracts/{name}"
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def expected_files() -> dict[str, str]:
    files = {f"{name}.schema.json": render(name) for name in MODELS}
    index = {name: hashlib.sha256(files[f"{name}.schema.json"].encode()).hexdigest() for name in MODELS}
    files["index.json"] = json.dumps({"schema_set": 1, "schemas": index}, indent=2, sort_keys=True) + "\n"
    return files


def drift() -> list[str]:
    want = expected_files()
    have = {p.name for p in SCHEMA_DIR.glob("*.json")} if SCHEMA_DIR.exists() else set()
    problems = [f"stale or extra snapshot: {n}" for n in sorted(have - set(want))]
    for name, text in sorted(want.items()):
        path = SCHEMA_DIR / name
        if not path.exists():
            problems.append(f"missing snapshot: {name}")
        elif path.read_text(encoding="utf-8") != text:
            problems.append(f"schema drift: {name}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    ns = parser.parse_args()
    if ns.check:
        problems = drift()
        for p in problems:
            print(p, file=sys.stderr)
        return 1 if problems else 0
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for stale in SCHEMA_DIR.glob("*.json"):
        stale.unlink()
    for name, text in expected_files().items():
        (SCHEMA_DIR / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(MODELS)} schemas to {SCHEMA_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
