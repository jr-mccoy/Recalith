"""Build one self-contained review packet for an outside reviewer of a live gate's labels.

Mechanical: everything comes from the sanitized record and the fixture sources. It deliberately leaves out this
repository's drafted suggestions, their reasons and the term-match heuristic, so the outside review is not anchored on them.

Usage: review-packet.py <sanitized record dir> <repo root> <output .md> "<title, e.g. tenth live gate, 2026-11-05>"
"""
import json
import os
import re
import sys
from pathlib import Path

rec, repo, out, title = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
template = json.loads((rec / "adjudication.template.json").read_text(encoding="utf-8"))
claim_keys = sorted(template["claims"])
lesson_keys = sorted(template["lessons"])

L = [f"# Recalith preview gate: label review packet ({title})", "",
     "This file is the whole evidence for the review. It contains no labels and no one's suggested labels.", "",
     "## What is being labeled", "",
     "Recalith is a per-project memory system for a coding agent (here, Claude Code). In each of 12 scripted scenarios, a live agent worked in "
     "a small fixture project over two or three separate sessions (A, B and sometimes C). Recalith captured what happened, and a curator "
     "model proposed durable claims (facts, decisions, preferences, failure lessons, procedures). Deterministic code admitted them, a review "
     "model assessed inferred ones, and later sessions were given relevant claims as advisory context (\"deliveries\").", "",
     f"You label two kinds of item: {len(claim_keys)} admitted claims and {len(lesson_keys)} gold lessons.", "",
     "### Claim labels: `supported` or `unsupported`", "",
     "Label each admitted claim (status active or disputed) against the trial's evidence, scope included: a prohibited generalization is "
     "unsupported. The evidence is what the sessions show: the user's prompts, the agent's tool actions and their exit codes, the agent's "
     "replies, the fixture files and overlays below, and the oracle's checks of the final workspace. The trial stores and full tool outputs "
     "were not kept, so judge from what is here and say when something cannot be verified. Judge a claim against the evidence when it was "
     "admitted: when later evidence in the same trial (an overlay that changes a file, or a user's correction) makes a claim stale, it stays "
     "supported here, because going stale is scored by other measures (the owner's rule).", "",
     "### Lesson labels: `recalled`, `missed` or `evidence_absent`", "",
     "Each scenario's gold lists the reusable lessons the trial could teach. For each one:", "",
     "- `recalled`: the system's admitted durable memory holds the lesson;",
     "- `missed`: the trial produced sufficient evidence for it, but the admitted memory does not hold it. Abstaining when the evidence was "
     "sufficient counts as missed;",
     "- `evidence_absent`: the trial's sessions never produced the lesson's evidence.", "",
     "The claims listed for each scenario show their status at the end of the trial: active, disputed, candidate (not admitted as guidance), "
     "superseded, and so on. The deliveries show what earlier claims were given to later sessions. Say in your reason which claim, if any, holds "
     "the lesson, and how you treated a claim's status changing during the trial.", "",
     "The targets, for context only: at least 95 % of admitted claims supported, at least 85 % of the labeled lessons recalled, and at least "
     "90 % of the labeled failure lessons recalled. `evidence_absent` lessons leave both denominators. Judge each item on its evidence, not on "
     "the totals.", "",
     "## How to answer", "",
     "Reply with exactly one JSON object and nothing else:", "",
     "```json",
     '{"reviewer": "<your name and version>",',
     ' "read_system_spec_7": true,',
     ' "claims": {"<claim key>": {"label": "supported|unsupported", "reason": "<one or two sentences>"}},',
     ' "lessons": {"<lesson key>": {"label": "recalled|missed|evidence_absent", "reason": "<one or two sentences>"}}}',
     "```", "",
     "Use every key in the lists below exactly as written, once each. Set `read_system_spec_7` to true if you wrote or have read the Recalith "
     "SYSTEM_SPEC section 7.", ""]

L += ["### Claim keys", ""] + [f"- `{k}`" for k in claim_keys] + ["", "### Lesson keys", ""] + [f"- `{k}`" for k in lesson_keys] + [""]

# Fixture sources and overlays.
L += ["## Fixture projects (each trial starts from a fresh copy)", ""]
for project in ("ledgerlite", "fieldnotes", "household"):
    root = repo / "evals" / "projects" / project
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        L += [f"### {project}: `{rel}`", "", "```", text.rstrip("\n") if text else "(empty file)", "```", ""]

scenarios = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((repo / "evals" / "scenarios" / "smoke").glob("smoke-*.json"))}
overlay_dir = repo / "evals" / "scenarios" / "smoke" / "overlays"

L += ["## Scenarios (candidate arm, with Recalith)", ""]
for sid, scen in scenarios.items():
    t = json.loads((rec / "trials" / f"{sid}.candidate.json").read_text(encoding="utf-8"))
    L += [f"### {sid}", "", f"- **Project:** {scen['project']}; **category:** {scen['category']}"]
    L += ["- **Gold:**", "", "```json", json.dumps(scen["gold"], indent=1, ensure_ascii=False), "```", ""]
    for s in scen["sessions"]:
        L.append(f"- **Session {s['name']} prompt(s):** " + " / ".join(json.dumps(p, ensure_ascii=False) for p in s["prompts"]))
        for target, source in (s.get("overlay_files") or {}).items():
            body = (overlay_dir / source.removeprefix("@file:")).read_text(encoding="utf-8") if source.startswith("@file:") else source
            L += [f"  - Before session {s['name']}, the harness overwrote `{target}` with:", "", "```", body.rstrip("\n"), "```", ""]
    L.append("")
    for sess in t["sessions"]:
        L += [f"#### Recorded session {sess['name']}", ""]
        L.append("Actions (tool, command or path, exit code):")
        L.append("")
        for a in sess.get("actions", []):
            what = a.get("command") or a.get("path") or ""
            L.append(f"- {a['tool']}: `{what}` → exit {a.get('exit_code')}" if "\n" not in what else f"- {a['tool']} → exit {a.get('exit_code')}:\n\n```\n{what}\n```\n")
        if not sess.get("actions"):
            L.append("- (none: the agent only replied)")
        L.append("")
        for d in sess.get("deliveries", []):
            if d.get("purpose") in ("session_start", "prompt") and d.get("context"):
                L += [f"Delivered at {d['purpose']}:", "", "```", d["context"].rstrip("\n"), "```", ""]
        L += ["Agent's final reply:", "", "```", (sess.get("reply") or "").rstrip("\n"), "```", ""]
    oracle = t.get("oracle") or {}
    L += [f"- **Oracle (final workspace):** passed={oracle.get('passed')}; checks {json.dumps(oracle.get('checks'))}", ""]
    L += ["- **Claims at the end of the trial:**", ""]
    for c in t.get("claims", []):
        key = f"{sid}:{c['claim_id']}"
        review = c.get("review") or {}
        tag = " (TO LABEL)" if key in template["claims"] else ""
        L.append(f"  - `{c['claim_id']}`{tag}: {c['status']}, {c.get('strength')}, {c['kind']}, basis {c['basis']}: {c['proposition']}"
                 + (f" — review: {review.get('verdict')}" + (f"; objections: {' / '.join(review.get('objections') or [])}" if review.get('objections') else "") if review else ""))
    if not t.get("claims"):
        L.append("  - (none)")
    L += ["", "- **Lessons to label:** " + (", ".join(f"`{k}`" for k in lesson_keys if k.startswith(sid + "#")) or "none"), ""]

text = "\n".join(L) + "\n"
users = {u for u in (os.environ.get("USERNAME"), os.environ.get("USER"), Path.home().name) if u}
for pattern in ("(?i)" + "|".join(re.escape(u) for u in sorted(users)), r"(?i)\b[a-z]:(\\|/)Users", r"sk-ant", r"(?i)claude-(?:opus|sonnet|haiku|fable|\d)|\b(?:opus|sonnet|haiku|fable)[- ]?\d"):
    assert not re.search(pattern, text), pattern
out.write_text(text, encoding="utf-8", newline="\n")
print(out, len(text), "chars;", len(claim_keys), "claims;", len(lesson_keys), "lessons")
