# SPDX-License-Identifier: GPL-3.0-only
"""The baseline-sensitivity set through the real engine (decision 0049), scripted: mechanics, never a live result.

The scripted candidate reads only the context the engine delivered; the scripted baseline has no memory. A scenario in
this set is useful only if the baseline can register the repeated mistake while a candidate that received the
corrected fact does not, and the report keeps the set apart from the gate's 12.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SIDS = sorted(p.stem for p in (ROOT / "evals" / "scenarios" / "sensitivity").glob("sens-*.json"))


@pytest.mark.parametrize("sid", SIDS)
def test_scripted_trial_registers_the_repeat_in_the_baseline_only(tmp_path, sid):
    from evals import trial

    cand = trial.run_trial(sid, "candidate", tmp_path / "t")
    base = trial.run_trial(sid, "no_memory", tmp_path / "t")
    assert not cand.get("error") and not base.get("error"), (cand.get("error_detail"), base.get("error_detail"))
    assert cand["outcomes"]["task_success"] is True and cand["outcomes"]["repeated_named_mistake"] == 0, cand["oracle"]
    assert base["outcomes"]["task_success"] is False and base["outcomes"]["repeated_named_mistake"] == 1, base["oracle"]
    assert [p["satisfied"] for p in cand["retrieval_points"]] == [True], cand["retrieval_points"]  # the corrected fact reached session B


def test_the_report_keeps_the_set_apart_from_the_gate(tmp_path):
    from evals import report

    (tmp_path / "sensitivity").mkdir()
    for sid in report.SENSITIVITY_IDS:
        for arm in ("candidate", "no_memory"):
            record = {"scenario": sid, "arm": arm, "category": "learning", "manifest": {arm: {"label": arm}},
                      "outcomes": {"task_success": arm == "candidate", "repeated_named_mistake": int(arm == "no_memory"), "repeated_mistakes": 0}}
            (tmp_path / "sensitivity" / f"{sid}.{arm}.json").write_text(json.dumps(record), encoding="utf-8")
    (tmp_path / "run.json").write_text(json.dumps({"mode": "scripted"}), encoding="utf-8")
    built = report.build(tmp_path)
    sens = built["sensitivity"]
    assert sens["counts_toward_gate"] is False and not sens["missing"]
    assert sens["summary"]["repeated_named_mistake"] == {"candidate": 0, "no_memory": 4, "relative_reduction": 1.0}
    assert built["paired_outcomes"]["scenarios"] == []  # none of it is read as a gate trial
    assert built["completeness"]["smoke_trials_missing"] == 24 and built["gate"]["state"] == "blocked"
    assert "Baseline-sensitivity set" in report.markdown(built)
    assert report.sensitivity([]) is None
