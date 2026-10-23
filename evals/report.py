"""The preview evaluation report (ACCEPTANCE_TESTS §5.1, §5.2, §6.1, §6.2, §8; decision 0020).

    python evals/report.py RESULTS_DIR [--output-json FILE] [--output-md FILE]

Reads the trial records (``trials/*.json``), workload-day records
(``workload/*.json``) and demonstrations (``demonstrations.json``) that
``evals/run.py`` wrote, and computes:

* **paired outcomes** per smoke scenario, candidate versus the clean
  no-memory baseline: task success, repeated mistakes, detours, legitimate
  retry success, foreground and background tokens, elapsed time and operator
  interventions, with paired differences and 95 % intervals from resampling
  whole scenarios (a scenario's trials stay together);
* the applicable **§5.1 quality measures** on the smoke population, each with
  its numerator, denominator and a Wilson 95 % interval;
* all seven **§5.2 operational measures**, from the workload days (and the
  smoke trials where a measure applies there);
* versions, native-memory settings, scenario authorship, unsuccessful runs,
  cost and time (actual, and the §6.2 arithmetic with its inputs labeled),
  limitations, and the gate verdict.

A run's ``mode`` decides what it can establish: only ``live`` trials (a
certified route and a live host record) can count toward the preview gate.
``scripted`` trials (the scripted agent with recorded curator proposals) are
mechanics evidence and are always reported as such. No superiority claim is
made from a smoke run, whatever the numbers.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

QUALITY_TARGETS = {
    "supported_precision": (">=", 0.95),
    "useful_recall": (">=", 0.85),
    "failed_approach_recall": (">=", 0.90),
    "incorrect_confident_guidance": ("==", 0),
    "conflict_uncertainty_preservation": (">=", 0.95),
    "legitimate_retry_discouraged": ("<=", 0.05),
    "irrelevant_caution_quiet": ("<=", 0.05),
    "routine_human_maintenance": ("==", 0),
}
# Scoring keys, frozen with the smoke gold before any comparison: a gold lesson is matched by an
# admitted claim of the same kind whose proposition contains every term (case-insensitive).
GOLD_TERMS: dict[str, list[list[str]]] = {
    "smoke-L1-ledgerlite-test-command": [["pythonpath=src", "unittest"], ["pythonpath=src"]],
    "smoke-L2-fieldnotes-iso-dates": [["iso-8601"]],
    "smoke-L3-household-grocery-budget": [["600"]],
    "smoke-R1-fieldnotes-check-env-fixed": [["notes_home"]],
    "smoke-R2-ledgerlite-import-fixed": [["pythonpath"]],
    "smoke-R3-household-budget-correction": [["700"]],
    "smoke-R4-fieldnotes-storage-conflict": [["notes.json"]],
}
SEED = 20261021
RESAMPLES = 2000


# --------------------------------------------------------------------------
# Statistics


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def proportion(k: int, n: int) -> dict[str, Any]:
    return {"numerator": k, "denominator": n, "value": None if n == 0 else round(k / n, 4), "wilson_95": wilson(k, n)}


def paired_bootstrap(diffs: list[float], *, seed: int = SEED, resamples: int = RESAMPLES) -> dict[str, Any]:
    """Mean paired difference with a percentile interval from resampling whole scenarios."""
    if not diffs:
        return {"n": 0, "mean": None, "ci_95": None}
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(resamples))
    lo, hi = means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]
    return {"n": len(diffs), "mean": round(statistics.fmean(diffs), 4), "ci_95": (round(lo, 4), round(hi, 4)), "inconclusive": lo <= 0 <= hi}


def target_met(name: str, value: float | int | None) -> bool | None:
    if value is None:
        return None
    op, bound = QUALITY_TARGETS[name]
    return {"==": value == bound, ">=": value >= bound, "<=": value <= bound}[op]


# --------------------------------------------------------------------------
# Loading


def load(directory: Path) -> dict[str, Any]:
    def read_all(sub: str) -> list[dict[str, Any]]:
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((directory / sub).glob("*.json"))] if (directory / sub).is_dir() else []

    demos = directory / "demonstrations.json"
    run = directory / "run.json"
    return {
        "run": json.loads(run.read_text(encoding="utf-8")) if run.exists() else {},
        "trials": read_all("trials"),
        "workload": read_all("workload"),
        "demonstrations": json.loads(demos.read_text(encoding="utf-8")) if demos.exists() else None,
    }


def _by_scenario(trials: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for t in trials:
        out.setdefault(t["scenario"], {})[t["arm"]] = t
    return out


# --------------------------------------------------------------------------
# Paired outcomes (ACCEPTANCE_TESTS §6, §6.1)

OUTCOMES = ("task_success", "repeated_mistakes", "detours", "legitimate_retry_success", "foreground_tokens", "background_tokens", "elapsed_seconds", "operator_interventions")


def paired(trials: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for sid, arms in sorted(_by_scenario(trials).items()):
        cand, base = arms.get("candidate"), arms.get("no_memory")
        row: dict[str, Any] = {"scenario": sid, "category": (cand or base or {}).get("category")}
        for name in OUTCOMES:
            c = None if cand is None else cand["outcomes"].get(name)
            b = None if base is None else base["outcomes"].get(name)
            row[name] = {"candidate": c, "no_memory": b}
        row["labels"] = {"candidate": None if cand is None else cand["manifest"]["candidate"]["label"], "no_memory": None if base is None else base["manifest"]["no_memory"]["label"]}
        rows.append(row)
    summary: dict[str, Any] = {}
    for name in OUTCOMES:
        diffs = []
        for row in rows:
            c, b = row[name]["candidate"], row[name]["no_memory"]
            if c is None or b is None:
                continue
            diffs.append(float(c) - float(b))
        summary[name] = paired_bootstrap(diffs)
        if name == "task_success":
            succ = [r[name] for r in rows if r[name]["candidate"] is not None and r[name]["no_memory"] is not None]
            summary[name]["candidate_successes"] = sum(1 for s in succ if s["candidate"])
            summary[name]["no_memory_successes"] = sum(1 for s in succ if s["no_memory"])
            summary[name]["pairs"] = len(succ)
    relevant = [r for r in rows if r["category"] in ("learning", "revision")]
    rep_c = sum(int(r["repeated_mistakes"]["candidate"] or 0) for r in relevant)
    rep_b = sum(int(r["repeated_mistakes"]["no_memory"] or 0) for r in relevant)
    summary["repeated_failure_relative_reduction"] = {
        "candidate": rep_c, "no_memory": rep_b, "relative_reduction": None if rep_b == 0 else round(1 - rep_c / rep_b, 4),
        "full_release_target": ">= 0.25 (Cut 2 gate; not a preview gate)",
    }
    return {"scenarios": rows, "summary": summary, "claim": "No superiority claim: a 12-scenario smoke run with one trial per arm cannot establish one (ACCEPTANCE_TESTS §6.1)."}


# --------------------------------------------------------------------------
# §5.1 quality on the smoke population


def _matches(claim: dict[str, Any], terms: list[str]) -> bool:
    text = (claim.get("proposition") or "").lower()
    return all(t in text for t in terms)


def quality(trials: list[dict[str, Any]]) -> dict[str, Any]:
    cands = [t for t in trials if t["arm"] == "candidate"]
    admitted = matched_admitted = 0
    gold_total = gold_hit = fail_total = fail_hit = 0
    conflict_total = conflict_kept = 0
    retry_total = retry_discouraged = 0
    quiet_total = quiet_cautioned = 0
    incorrect = 0
    interventions = 0
    examples: dict[str, list[str]] = {"unsupported_admitted": [], "missed_lessons": [], "irrelevant_cautions": [], "discouraged_retries": [], "incorrect_guidance": []}
    for t in cands:
        sid = t["scenario"]
        gold = t["gold"]
        claims = [c for c in t.get("claims", []) if c["status"] in ("active", "disputed")]
        terms = GOLD_TERMS.get(sid, [])
        lessons = gold.get("supported_lessons", [])
        for c in claims:
            admitted += 1
            ok = any(_matches(c, ts) for ts in terms)
            matched_admitted += ok
            if not ok:
                examples["unsupported_admitted"].append(f"{sid}: {c.get('proposition', '')[:120]}")
        for i, lesson in enumerate(lessons):
            ts = terms[i] if i < len(terms) else []
            hit = bool(ts) and any(_matches(c, ts) for c in claims)
            gold_total += 1
            gold_hit += hit
            if lesson["kind"] == "failure_lesson":
                fail_total += 1
                fail_hit += hit
            if not hit:
                examples["missed_lessons"].append(f"{sid}: {lesson['proposition'][:120]}")
        for point in t.get("retrieval_points", []):
            spec = point["spec"]
            if spec.get("advice") == "conflict_or_freshness_label":
                conflict_total += 1
                conflict_kept += bool(point["satisfied"])
            if "must_not_include_caution" in spec:
                retry_total += 1
                if not point["satisfied"]:
                    retry_discouraged += 1
                    examples["discouraged_retries"].append(sid)
            if "max_caution_items" in spec:
                quiet_total += 1
                if not point["satisfied"]:
                    quiet_cautioned += 1
                    examples["irrelevant_cautions"].append(sid)
            if ("must_not_include" in spec or "must_not_include_caution" in spec) and not point["satisfied"] and not t["outcomes"]["task_success"]:
                incorrect += 1  # stale or prohibited guidance delivered and the task failed: a material consequence
                examples["incorrect_guidance"].append(sid)
        interventions += int(t["outcomes"].get("operator_interventions") or 0)
    measures = {
        "supported_precision": proportion(matched_admitted, admitted),
        "useful_recall": proportion(gold_hit, gold_total),
        "failed_approach_recall": proportion(fail_hit, fail_total),
        "incorrect_confident_guidance": {"count": incorrect, "population": len(cands)},
        "conflict_uncertainty_preservation": proportion(conflict_kept, conflict_total),
        "legitimate_retry_discouraged": proportion(retry_discouraged, retry_total),
        "irrelevant_caution_quiet": proportion(quiet_cautioned, quiet_total),
        "routine_human_maintenance": {"count": interventions, "population": len(cands)},
    }
    for name, m in measures.items():
        value = m.get("value", m.get("count"))
        m["target"] = " ".join(str(x) for x in QUALITY_TARGETS[name])
        m["met"] = target_met(name, value)
    return {"measures": measures, "examples": {k: v[:12] for k, v in examples.items()}, "population": f"{len(cands)} candidate smoke trials (one per scenario)"}


# --------------------------------------------------------------------------
# §5.2 operational measures


def operational(workload: list[dict[str, Any]], trials: list[dict[str, Any]]) -> dict[str, Any]:
    recorded = [w for w in workload if w.get("kind") == "workload_day"]
    # A day that did not run (provisioning or replay failed) has no measures: it is reported, never silently dropped.
    failed = [d for d in recorded if "budget" not in d]
    days = [d for d in recorded if "budget" in d]
    exhausted = [d for d in days if d["budget"].get("exhausted_at_hours") is not None]
    hours = [d["budget"]["exhausted_at_hours"] for d in exhausted]
    waits = {k: [x for d in days for x in d["budget"].get("wait_seconds", {}).get(k, [])] for k in ("correction_declaration_review", "ordinary_review", "ordinary")}
    budget = {
        "scenario_days": len(days), "days_not_run": [{"project": d.get("project"), "error": d.get("error"), "detail": d.get("detail")} for d in failed],
        "days_hitting_any_pool": proportion(len(exhausted), len(days)),
        "median_hours_to_exhaustion": statistics.median(hours) if hours else None,
        "nonexhausted_censored_days": len(days) - len(exhausted),
        "pools_hit": sorted({p for d in exhausted for p in d["budget"].get("pools_hit", [])}),
        "waiting_seconds": {k: _dist(v) for k, v in waits.items()},
        "priority_inversions": sum(int(d["budget"].get("priority_inversions", 0)) for d in days),
        "backlog_at_day_end": {d["project"]: d["budget"].get("backlog") for d in days},
    }
    frag = {
        d["project"]: {
            "created_tasks": d["tasks"]["created"], "gold_tasks": d["tasks"]["gold"], "ratio": None if not d["tasks"]["gold"] else round(d["tasks"]["created"] / d["tasks"]["gold"], 3),
            "provisional": d["tasks"].get("provisional"), "confirmed": d["tasks"].get("confirmed"), "linked_placeholders": d["tasks"].get("placeholders"),
            "current_nonredirected_heads": d["tasks"].get("nonredirected"), "deterministic_link_reversals": d["tasks"].get("link_reversals"),
            "boundary_precision": d["tasks"].get("boundary_precision"), "boundary_recall": d["tasks"].get("boundary_recall"), "attempt_result_severed": d["tasks"].get("severed", 0),
        }
        for d in days
    }
    visibility = {"source": "docs/host-compatibility.json (sections.delivery_engine)", "paths": _delivery_visibility()}
    suppression = _false_suppression(trials)
    latency = {
        "smoke": _same_session(trials),
        "workload": {d["project"]: d.get("same_session_learning", {}) for d in days},
    }
    throughput = {d["project"]: d.get("curation", {}) for d in days}
    strength = {d["project"]: d.get("strength", {}) for d in days}
    strength["smoke"] = _strength(trials)
    return {
        "budget_exhaustion": budget, "task_over_fragmentation": frag, "delivery_visibility": visibility, "false_suppression": suppression,
        "same_session_learning_latency": latency, "curation_throughput": throughput, "evidence_strength_distribution": strength,
    }


def _dist(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    s = sorted(values)
    return {"n": len(s), "p50": round(s[len(s) // 2], 3), "p95": round(s[min(len(s) - 1, int(0.95 * len(s)))], 3), "max": round(s[-1], 3)}


def _delivery_visibility() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "docs" / "host-compatibility.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "report_missing"}
    section = (data.get("sections") or {}).get("delivery_engine") or {}
    out: dict[str, Any] = {}
    for host, report in section.items():
        rc = report.get("request_capture") or {}
        live = report.get("live") or {}
        paths = {}
        for name, path_report in (rc.get("paths") or {}).items():
            keys = ("state", "positives_hook_emitted", "positives_visible_in_request", "negatives_clean")
            paths[name] = {"request_capture": {k: path_report.get(k) for k in keys if k in path_report}, "live": (live.get("paths") or {}).get(name, live.get("status", "not_run"))}
        out[host] = {"host_version": report.get("host_version"), "paths": paths, "live": live.get("status", live.get("reason", "not_run")), "contaminated_runs": "none recorded"}
    return out or {"state": "no_delivery_engine_section"}


def _false_suppression(trials: list[dict[str, Any]]) -> dict[str, Any]:
    opportunities = missed = 0
    examples = []
    for t in trials:
        if t["arm"] != "candidate" or t.get("category") != "revision":
            continue
        for point in t.get("retrieval_points", []):
            spec = point["spec"]
            if spec.get("advice") == "conflict_or_freshness_label" or "must_include" in spec:
                opportunities += 1
                if not point["satisfied"]:
                    missed += 1
                    examples.append(t["scenario"])
    return {**proportion(missed, opportunities), "examples": examples}


def _same_session(trials: list[dict[str, Any]]) -> dict[str, Any]:
    values = [x for t in trials if t["arm"] == "candidate" for x in t.get("same_session_learning", [])]
    return {"observations": values[:20], "count": len(values)}


def _strength(trials: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for t in trials:
        if t["arm"] != "candidate":
            continue
        for c in t.get("claims", []):
            key = f"{c['status']}:{c.get('strength')}:{c.get('basis')}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def retrieval_summary(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Every gold expected retrieval point of the candidate trials: satisfied or not, with what was delivered."""
    rows = []
    for t in trials:
        if t["arm"] != "candidate":
            continue
        for point in t.get("retrieval_points", []):
            rows.append({"scenario": t["scenario"], "spec": point["spec"], "satisfied": point["satisfied"], "delivered_items": len(point.get("items", []))})
    met = sum(1 for r in rows if r["satisfied"])
    return {**proportion(met, len(rows)), "unmet": [r for r in rows if not r["satisfied"]]}


# --------------------------------------------------------------------------
# Cost and time (ACCEPTANCE_TESTS §6.2)


def cost_and_time(run: dict[str, Any], trials: list[dict[str, Any]], workload: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = sum(len(t.get("sessions", [])) for t in trials)
    elapsed = sum(float(t["outcomes"].get("elapsed_seconds") or 0) for t in trials)
    background_calls = sum(int(t.get("background", {}).get("model_calls", 0)) for t in trials) + sum(int(d.get("curation", {}).get("calls", 0)) for d in workload)
    live = run.get("mode") == "live"
    illustrative = {"sessions_per_scenario": 2.5, "foreground_cost_per_session_usd": 0.30, "background_share": 0.25, "minutes_per_session": 4, "overhead": 0.25}
    comparative = 12 * 1 * 2 * illustrative["sessions_per_scenario"]
    foreground_usd = round(sum(float(t["outcomes"].get("foreground_cost_usd") or 0.0) for t in trials), 4) if live else 0.0
    background_tokens = sum(int(t.get("background", {}).get("tokens", 0)) for t in trials) + sum(sum((d.get("curation", {}).get("estimated_tokens_by_purpose") or {}).values()) for d in workload)
    return {
        "actual": {
            "mode": run.get("mode"), "foreground_sessions": sessions, "background_model_calls": background_calls, "elapsed_seconds": round(elapsed, 1),
            "provider_cost_usd": None if live else 0.0, "provider_cost_note": "recorded mode: no provider call was made; the background calls were answered by the recorded curator" if not live else
            "foreground: the host's reported session cost; background: tokens from the budget ledger (provider-reported where available), not priced here",
            "foreground_cost_usd": foreground_usd, "background_tokens": background_tokens,
        },
        "pilot": {"state": "not_run" if not live else "see actual", "reason": "a live pilot needs a certified route (B1)" if not live else None},
        "illustrative_estimate": {
            "inputs": illustrative, "label": "ACCEPTANCE_TESTS §6.2 arithmetic, not measured costs or current prices",
            "comparative_smoke_sessions": comparative,
            "comparative_smoke_cost_usd": round(comparative * illustrative["foreground_cost_per_session_usd"] * (1 + illustrative["background_share"]) * (1 + illustrative["overhead"]), 2),
            "serial_hours": round(comparative * illustrative["minutes_per_session"] / 60, 2),
        },
    }


# --------------------------------------------------------------------------
# The report


def build(directory: Path) -> dict[str, Any]:
    data = load(directory)
    run, trials, workload = data["run"], data["trials"], data["workload"]
    unsuccessful = [{"scenario": t["scenario"], "arm": t["arm"], "reason": t.get("error") or "task_failed"} for t in trials if t.get("error") or not t["outcomes"].get("task_success")]
    unsuccessful += [{"workload_day": d.get("project"), "reason": d.get("error")} for d in workload if d.get("error")]
    mode = run.get("mode", "unknown")
    report = {
        "report_schema": 1,
        "profile": "claude_preview",
        "mode": mode,
        "counts_toward_gate": mode == "live",
        "mode_note": {
            "live": "live working agent and certified inference route",
            "scripted": "MECHANICS ONLY: scripted working agent and recorded curator proposals through the real engine; never a live pass",
        }.get(mode, "unknown mode"),
        "versions": run.get("versions", {}),
        "scenario_authorship": run.get("authorship", {}),
        "native_memory": run.get("native_memory", {}),
        "baselines": {"run": ["candidate", "no_memory"], "not_run": {"breadcrumbs": "full release only", "notes": "full release only"}},
        "paired_outcomes": paired(trials),
        "quality_5_1": quality(trials),
        "operational_5_2": operational(workload, trials),
        "retrieval_points": retrieval_summary(trials),
        "demonstrations_6_1": data["demonstrations"],
        "completeness": completeness(trials, workload, data["demonstrations"]),
        "unsuccessful_runs": unsuccessful,
        "cost_and_time": cost_and_time(run, trials, workload),
        "limitations": run.get("limitations", []),
    }
    report["gate"] = gate(report, run)
    return report


SMOKE_IDS = tuple(sorted(p.stem for p in (Path(__file__).resolve().parent / "scenarios" / "smoke").glob("smoke-*.json")))
DEMONSTRATIONS = ("fresh_session_reuse", "changed_condition_revision", "forgetting_and_restore", "isolation", "zero_interventions")
WORKLOAD_DAYS = 3


def completeness(trials: list[dict[str, Any]], workload: list[dict[str, Any]], demos: dict[str, Any] | None) -> dict[str, Any]:
    """What ACCEPTANCE_TESTS §6.1 requires to have run: every smoke scenario in both arms without a run error and with a
    clean label, three workload days with measures, and every demonstration shown. Task failure is an outcome, not a gap."""
    have = {(t.get("scenario"), t.get("arm")): t for t in trials}
    missing = [f"{sid}.{arm}" for sid in SMOKE_IDS for arm in ("candidate", "no_memory") if (sid, arm) not in have]
    errors = [f"{t['scenario']}.{t['arm']}:{t['error']}" for t in trials if t.get("error")]
    contaminated = [f"{t['scenario']}.{t['arm']}" for t in trials if ((t.get("manifest") or {}).get(t.get("arm")) or {}).get("label") != t.get("arm")]
    days = [d for d in workload if d.get("kind") == "workload_day"]
    ran = [d for d in days if "budget" in d and not d.get("error")]
    shown = ((demos or {}).get("demonstrations") or {})
    unmet = [n for n in DEMONSTRATIONS if not (shown.get(n) or {}).get("demonstrated")]
    return {"smoke_trials_missing": len(missing), "missing": missing[:24], "trial_errors": errors, "contaminated_arms": contaminated, "workload_days_run": len(ran),
            "workload_days_not_run": [d.get("project") for d in days if d not in ran], "demonstrations_unmet": unmet,
            "complete": not missing and not errors and not contaminated and len(ran) >= WORKLOAD_DAYS and not unmet}


def gate(report: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    reasons = list(run.get("blockers", []))
    if report["mode"] != "live":
        reasons.append("not_live: scripted/recorded runs cannot pass the preview gate")
    failed = [n for n, m in report["quality_5_1"]["measures"].items() if m.get("met") is False]
    if failed:
        reasons.append("quality_targets_unmet:" + ",".join(failed))
    done = report.get("completeness") or {}
    if done.get("smoke_trials_missing"):
        reasons.append(f"smoke_trials_missing:{done['smoke_trials_missing']}")
    if done.get("trial_errors"):
        reasons.append("trial_errors:" + ",".join(done["trial_errors"])[:400])
    if done.get("contaminated_arms"):
        reasons.append("contaminated_arms:" + ",".join(done["contaminated_arms"])[:400])
    if done and done.get("workload_days_run", 0) < WORKLOAD_DAYS:
        reasons.append(f"workload_days_short:{done.get('workload_days_run', 0)}/{WORKLOAD_DAYS}")
    if done.get("demonstrations_unmet"):
        reasons.append("demonstrations_unmet:" + ",".join(done["demonstrations_unmet"]))
    incomplete = bool(done) and not done.get("complete")
    return {"state": "blocked" if report["mode"] != "live" else ("failed" if failed or incomplete else "passed_smoke"), "reasons": reasons, "superiority_claim": False}


def markdown(report: dict[str, Any]) -> str:
    lines = [f"# Preview evaluation report ({report['mode']})", "", f"**{report['mode_note']}.** Counts toward the preview gate: **{report['counts_toward_gate']}**. Gate: **{report['gate']['state']}**.", ""]
    for reason in report["gate"]["reasons"]:
        lines.append(f"- {reason}")
    lines += ["", "## Paired outcomes (candidate vs clean no-memory baseline)", "", "| Scenario | Success C/B | Repeated mistakes C/B | Detours C/B | Retry C/B | Foreground tok C/B | Background tok C | Elapsed s C/B | Labels C/B |", "|---|---|---|---|---|---|---|---|---|"]
    for row in report["paired_outcomes"]["scenarios"]:
        def pair(name: str, row: dict[str, Any] = row) -> str:
            v = row[name]
            return f"{_fmt(v['candidate'])}/{_fmt(v['no_memory'])}"

        lines.append(f"| {row['scenario']} | {pair('task_success')} | {pair('repeated_mistakes')} | {pair('detours')} | {pair('legitimate_retry_success')} | {pair('foreground_tokens')} | {_fmt(row['background_tokens']['candidate'])} | {pair('elapsed_seconds')} | {row['labels']['candidate']}/{row['labels']['no_memory']} |")
    lines += ["", "Paired differences (candidate − baseline), mean with a 95 % interval from resampling whole scenarios:", ""]
    for name, s in report["paired_outcomes"]["summary"].items():
        if name == "repeated_failure_relative_reduction":
            lines.append(f"- repeated failures on relevant scenarios: candidate {s['candidate']}, baseline {s['no_memory']}, relative reduction {s['relative_reduction']} ({s['full_release_target']})")
        else:
            lines.append(f"- {name}: n={s['n']}, mean={s['mean']}, CI95={s['ci_95']}{', inconclusive' if s.get('inconclusive') else ''}")
    lines += ["", report["paired_outcomes"]["claim"], "", "## §5.1 quality on the smoke population", "", "| Measure | Value | Numerator/denominator | Wilson 95 % | Target | Met |", "|---|---|---|---|---|---|"]
    for name, m in report["quality_5_1"]["measures"].items():
        nd = f"{m['numerator']}/{m['denominator']}" if "numerator" in m else f"count over {m['population']}"
        lines.append(f"| {name} | {_fmt(m.get('value', m.get('count')))} | {nd} | {m.get('wilson_95')} | {m['target']} | {m['met']} |")
    lines += ["", "## §5.2 operational measures", "", "```json", json.dumps(report["operational_5_2"], indent=1, sort_keys=True)[:12000], "```", ""]
    rp = report["retrieval_points"]
    lines += ["## Expected retrieval points (candidate)", "", f"{rp['numerator']}/{rp['denominator']} satisfied (Wilson 95 % {rp['wilson_95']}). Unmet:", ""]
    lines += [f"- {u['scenario']}: {json.dumps(u['spec'], sort_keys=True)} ({u['delivered_items']} items delivered at that point)" for u in rp["unmet"]] + [""]
    lines += ["## §6.1 demonstrations", "", "```json", json.dumps(report["demonstrations_6_1"], indent=1, sort_keys=True)[:8000], "```", ""]
    lines += ["## Unsuccessful runs", ""] + [f"- {u}" for u in report["unsuccessful_runs"]] + [""]
    lines += ["## Cost and time", "", "```json", json.dumps(report["cost_and_time"], indent=1, sort_keys=True), "```", ""]
    lines += ["## Versions, authorship and native memory", "", "```json", json.dumps({"versions": report["versions"], "authorship": report["scenario_authorship"], "native_memory": report["native_memory"], "baselines": report["baselines"]}, indent=1, sort_keys=True), "```", ""]
    lines += ["## Limitations", ""] + [f"- {x}" for x in report["limitations"]] + [""]
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4g}" if abs(value) < 10 else f"{value:.1f}"
    return "–" if value is None else str(value)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("results", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    ns = parser.parse_args(list(argv) if argv is not None else None)
    report = build(ns.results)
    if ns.output_json:
        ns.output_json.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if ns.output_md:
        ns.output_md.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"mode": report["mode"], "gate": report["gate"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
