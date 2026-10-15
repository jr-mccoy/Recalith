"""The acceptance coverage manifest keeps every case mapped (ACCEPTANCE_TESTS §2.1, §3)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "tests" / "coverage_manifest.json").read_text(encoding="utf-8"))
PREVIEW_EXCLUDED = {"A38", "A39", "A42", "A46", "A55", "A71"}
PARTIAL = {"A02", "A03", "A04", "A27", "A35", "A40", "A45", "A47", "A53", "A58", "A61", "A65"}
TASKS = {"0", "0b", "1", "2", "3", "3b", "4", "5", "6", "7", "8", "9", "10", "11", "12a", "12b", "13", "14", "15", "16", "17", "18"}


def cases():
    return {c["id"]: c for c in MANIFEST["cases"]}


def test_manifest_covers_A01_through_A73_by_profile():
    ids = cases()
    assert sorted(ids) == [f"A{i:02d}" for i in range(1, 74)]
    preview = {i for i, c in ids.items() if c["in_preview"]}
    assert len(preview) == 67 and set(ids) - preview == PREVIEW_EXCLUDED


def test_ids_match_acceptance_document():
    doc = (ROOT / "docs" / "ACCEPTANCE_TESTS.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| (A\d\d) \|", doc, re.M))
    assert documented == set(cases())


def test_partial_variants_are_exactly_section_2_1():
    for cid, case in cases().items():
        names = [v["variant"] for v in case["variants"]]
        if cid in PREVIEW_EXCLUDED:
            assert names == ["full"]
        elif cid in PARTIAL:
            assert names == ["preview", "full_only"], cid
        else:
            assert names == ["complete"], cid


def test_deferred_variants_are_unavailable_in_preview_never_passed():
    for case in cases().values():
        for v in case["variants"]:
            assert v["status"] in MANIFEST["status_values"]
            if "claude_preview" not in v["profiles"]:
                assert v["preview_status"] == "unavailable" and v["unavailable_reason"]
                assert v["status"] != "passed" or "full" in v["profiles"]


def test_every_case_has_owning_tasks_and_existing_tests():
    for cid, case in cases().items():
        assert case["owning_tasks"] and set(case["owning_tasks"]) <= TASKS, cid
        for v in case["variants"]:
            assert v["platforms"] == ["linux", "macos", "windows"]
            for test in v["tests"]:
                assert (ROOT / test.split("::")[0]).exists(), test


def test_live_variants_cannot_pass_on_harness_evidence_alone():
    for case in cases().values():
        for v in case["variants"]:
            if v["requires_live_host"] and v["status"] == "passed":
                assert v.get("live_evidence"), f"{case['id']} passed without recorded live evidence"
