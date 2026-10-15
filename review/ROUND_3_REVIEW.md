# Project Memory — Review Round 3 (v1.2)

Oct 15, 2026 · @Jeremy Mccoy

## Verdict

Start building. Revision 1.2 is the version to implement: all 38 round-two dispositions are in the documents, the six qualifications are correct, and the preview cut is now a real stage with its own gate and dependency order. The seven items below are worth fixing, but they are the kind an implementer resolves as Task 0 and Task 1 preconditions, not reasons for a v1.3 package.

One of them is serious enough to fix before Task 15 core is written: the preview's 180-day expiry withdraws every claim whose only evidence is an event, which in preview is every claim, including typed operator declarations. The rest are seams of the new operator guard (the host marker leaking into the curator launch, no non-interactive `init` for the evaluation harness, IDE-terminal operators locked out), a missing early probe for the delivery paths that readiness now depends on, and two definitional gaps (profile transition, declaration priority).

The yield of review is falling: round one found 10 inconsistencies and 11 gaps, round two found 8, this round finds 7 of lower severity. What remains uncertain is empirical, the provider isolation probe, hook latency on Windows, the budget under real days, and only implementation answers those. Further package revisions will cost more than they return.

## Round-two dispositions

I diffed every v1.1 document against v1.2 rather than reading the response, and each of the 38 dispositions lands where it says. The six qualifications are all right, and four improved on the proposal:

- **Removing the declaration bypass entirely** instead of guarding it is the better fix for N1; the guard then only has to reduce confused-agent mistakes, which is what it can do.
- **Separating the raw wire cap from the decoded body cap** and reserving per purpose resolves N2 cleanly; the 48-call worked example makes the 90-call ceiling honest.
- **`FailureRecheck` as a `context` counter-observation rather than `contradicts`** is epistemically right: a success with the database up does not refute a failure with it down. Capping caution deterministically is what mattered, and it now happens in the ingestion transaction with zero budget.
- **Keeping backup, restore and safe expiry in preview** was the correct amendment to my cut; I had treated Task 15 as one unit when its recovery half is a forgetting prerequisite.

The two remaining qualifications (markers are friction not authentication; a deadline cannot complete I/O by decree) are stated accurately in the spec and need nothing further.

Two dispositions created the new issues below: C06's safe-expiry rule (R1) and N1's marker refusal, which now needs an environment rule for the processes pmem itself spawns (R2) and an explicit non-interactive path (R3).

## New issues introduced by v1.2

Ranked by what it costs to discover them late. Each names the owning document and the acceptance case to amend.

### R1. Preview memory has a 180-day cliff

C06 correctly refused to let expired payloads keep supporting claims. But in preview there are no capsules, so on day 181 §11 removes the payload of every event older than 180 days and "caps inadequately supported claims at weak, withdraws their automatic guidance". Every claim's evidence is an event. A `user_declared` decision made on day 1 ("this repo uses pnpm"), a typed `pmem declare` submission, and a failure lesson with a certified tool root all lose their guidance on day 181, because "retained independent support" does not exist without capsules and "an episode summary alone is not preserved primary support". A35's preview variant asserts exactly this behavior as correct. The effect is a memory with a six-month half-life for everything, which is worse than the problem C06 was avoiding.

Resolution: pin-on-reference retention. An event payload that is a root for an active, disputed or candidate claim, or for an open task or episode, is exempt from age-based expiry until every referencing record is retired, superseded, forgotten or archived; only unreferenced payloads expire at 180 days. Storage is bounded by live claims, not by time. Forgetting still purges pinned payloads. This also simplifies Cut 2: capsules become a space optimization and the export mechanism rather than the thing that keeps memory alive. Owner: SYSTEM\_SPEC §11 and §1.2 table, Task 15 core; replace A35's preview variant with "day 181 expires only unreferenced payloads; a referenced root's claim keeps its strength and guidance", and keep the honest-downgrade path for the forgetting and import cases where a root is removed.

### R2. The host marker reaches the curator

§13.1 makes `CLAUDECODE` a refusal signal, and §2.2 has the session-start hook start the persistent worker. That worker is a descendant of a Claude Code tool process and inherits the marker. It then launches the Claude CLI curator. §9.1 says to "strip unrelated credential environment variables" but says nothing about host markers, so the curator inherits `CLAUDECODE` too. If the host treats its own marker as a nested-session signal, or changes behavior under it, the curator fails only when the worker was started by a hook and works when a person started it from a terminal, which is the hardest kind of bug to reproduce. The same inheritance makes any internal path that consults the guard refuse inside the worker.

Resolution: provider launch and worker spawn build an explicit allowlisted environment rather than filtering the inherited one: selected auth variables, locale, path, temp, plus `PMEM_CURATOR_INSTALLATION`; every registered host marker is removed. Task 0's probe runs once from a shell that has `CLAUDECODE` set, to certify that the backend launches under inheritance and that the strip works. Owner: SYSTEM\_SPEC §9.1 and §6.1, Task 0, Task 4, Task 7; amend **A28** and **A67** to include an inherited host marker.

### R3. `init` cannot run non-interactively

§13.1: "First `init` requires a TTY; a later operator may provision a random token file." The evaluation harness in §6.2 runs parallel slots with "separate evaluation installations", so Task 18 needs to create hundreds of installations from a script. Dev containers, CI bootstraps and the Task 0/3b fixtures have the same need. As written, none of them can initialize an installation, and the token that would allow it can only be created after `init`.

Resolution: `pmem operator-token create` works before `init` (it writes a standalone token file; `init --operator-token-file PATH` installs its verifier into the new `local.toml`). The marker refusal still applies, so an agent cannot use this path; a human or a harness without a marker can. Owner: DATA\_CONTRACTS §12, SYSTEM\_SPEC §13.1, Task 12a, **A73** (add the pre-init token case).

### R4. Delivery paths now gate readiness but are first probed at package 19

Readiness depends on session-start and prompt injection passing the nonce protocol, and the pre-action path decides whether cautions arrive before a tool runs or only on the next prompt. Those are host facts, not engine facts, yet the first time they are tested is Task 13, after sixteen packages. Task 3b proved the value of a capture-only spike; delivery deserves the same.

Resolution: add **Task 0b**, a standalone delivery probe beside Task 0: a stub hook that injects a nonce through each of the four paths on the installed host version, with the three-positive/three-negative controls, and writes the per-path verdict to `docs/host-compatibility.json`. No engine is required. If the prompt path fails, that is known in week one; if pre-action is unavailable, §8.2's prompt fallback is designed with that knowledge. Task 13 reuses the harness. Owner: IMPLEMENTATION\_PLAN early spike stage, SOURCES §5 item 8, **A61** harness mechanics.

### R5. Operators in IDE terminals are locked out

§13.1 says a marker refusal wins over TTY and token, and notes that IDE terminals inherit `CLAUDECODE`. A person working in VS Code's integrated terminal, the most common place to run `pmem forget` or `pmem declare`, is refused with no override. Agent tool shells have no controlling TTY, so TTY plus token is already a two-factor signal the ordinary agent cannot produce.

Resolution, as a choice rather than a correction: allow marker-present commands when both a controlling TTY and a valid token file are present, with the attempt audited at a higher level; or keep the strict rule and document that operators must use a non-IDE terminal. The strict rule is defensible; the cost is support burden and people disabling the guard. Owner: SYSTEM\_SPEC §13.1, **A73**.

### R6. Declarations should outrank ordinary review under budget pressure

Every declaration now waits for review, and Task 9 says "do not admit a declaration when its review is budget-paused." A user's explicit decision is the cheapest, highest-precision memory the system has; under exhaustion it should be the last thing left waiting. §6.2's priority list (ingestion, corrections, completed attempts, extraction, revalidation, consolidation) does not place declaration review.

Resolution: declaration review batches rank with high-impact corrections, ahead of extraction review. Owner: SYSTEM\_SPEC §6.2, Task 4; add to **A50**.

### R7. The preview-to-full transition is undefined

`init --release-profile` fixes a profile per installation, and §10 mentions baselining the chain when full activates on a preview store, but nothing defines the transition: retention drops from 180 to 30 days (with R1, pinned payloads must become capsules before expiry resumes), the capability registry changes, and deferred commands become available. Without a defined path, the first full release either requires re-initialization, which loses memory, or improvises.

Resolution: `pmem upgrade --release-profile full` is a maintenance-mode migration: baseline the chain, convert pinned-but-expiring payloads to capsules, re-register capabilities, and record the transition in the autonomy log. Owner: SYSTEM\_SPEC §1.2 and §10, DATA\_CONTRACTS §12, Task 17 full; add a variant to **A02**/**A40**.

## Smaller fixes by document

**SYSTEM\_SPEC**

- §6.1: the session-start hook starts the persistent worker from inside a host tool process; say that the worker fully detaches (new session/process group on POSIX, detached process on Windows) so host process-tree termination at SessionEnd does not kill it, and that Task 13's termination test covers a worker started this way.
- §7.2: `revise` verdicts are limited to two objections of 160 bytes; say that a `revise` whose objections do not fit is returned as `reject` with a `review_capacity` objection rather than a truncated revise, so a resubmission is not built on a cut-off reason.
- §8.2: when pre-action is unavailable, cautions ride the next prompt packet "under its ordinary cap"; the 1,000-token prompt cap can be smaller than the 400-token pre-action budget times several pending cautions. Allow the prompt packet to carry the pre-action allowance in addition when it is substituting for that path.
- §13.1: `worker start|stop|run` is agent-refusable; state that the hook's worker start uses the internal registered path and is exercised by A73's negative control so a future refactor cannot route it through the CLI.

**DATA\_CONTRACTS**

- §1.1: `EnvironmentObservation.freshness` is `current|unknown`; add `stale` with the rule that an observed version older than the executable's registered fingerprint change is stale, so a query does not silently use a pre-upgrade Python version.
- §3: `TaskState.status` gains `linked`; the reducer must never produce `next_action` or `pending_actions` for a linked placeholder; say so, since §8.2's "bound active task" row could otherwise serve tentative context from it.
- §12: list `operator-token` and `--release-profile` under the agent-refusable forms table with their TTY/token requirement, and name the exit code for a missing or revoked token file (6, not 2).

**ACCEPTANCE\_TESTS**

- A35 preview variant: replace per R1.
- A58: the WAL/SHM case should also cover a worker that is alive and mid-checkpoint, since that is when a read-only open is most likely to see a transient lock.
- §6.1: the preview gate compares against the clean no-memory baseline only; say that the Breadcrumbs baseline is not run for preview, so nobody reads its absence as a missing result.

**IMPLEMENTATION\_PLAN**

- Add Task 0b (R4) to the early-spike stage row and to the dependency sequence before Task 1.
- Task 15 core: the preview test names assume expiry withdraws guidance; rename per R1 to `test_referenced_roots_do_not_expire` and `test_unreferenced_payloads_expire_at_180_days`.
- Task 17 full: add the profile-transition migration (R7).

**README**

- State that round-three items are to be resolved in the repository's own docs as Task 0/1 preconditions, not as a further package revision, so the package stops being the place where design lives once the repository exists.

## Consistency checks performed

All pass unless noted.

- Output allowances: 3 × 1,500 = 4,500; 3 × 8,000 = 24,000; 3 × 3,000 = 9,000 bytes, consistent across §6.3, `BudgetReservation` and the plan's global constraints. The 48-call example: 12 × 8,000 + 16 × 1,500 = 120,000 ordinary; 20 × 3,000 = 60,000 protected; both at their pool ceilings.
- Review batching: 8 × 768 + 2,000 = 8,144 < 9,000 bytes; `3 + 3K` matches two expansions per extraction and per batch; A50's two-call case agrees with §6.3.
- Preview coverage: 73 − 6 excluded = 67 IDs; the six excluded (A38, A39, A42, A46, A55, A71) all depend on transfer, capsule or MCP components; A37 is retained as the response says.
- Dependency sequence: 15 core and 16 and 17 health precede 13 and 18 preview; Task 16 depends on Task 15 core only, as stated in both the stage table and the Task 16 slice note.
- Action family and trigger keys: family excludes task ID and includes working directory; trigger adds task ID; `FailureRecheck` uses certified source order, not receipt time. Consistent between §6.3, §7.3 and DATA\_CONTRACTS §8.
- Manifest: 38 dispositions = 8 + 11 + 19; 21 packages; 73 cases; 67 preview IDs; file digests listed for all ten files. The combined download opens with the no-second-policy statement and the modular-wins rule.
- SOURCES: the new environment-variable and permissions references are the only additions besides the probe report items 13 and 14; the probe report's "TODO" wording became "passed" wording, which is the right correction.
- Not consistent, carried as R1: §1.2's table says preview has "safe expiry/downgrade" and A35's preview variant asserts guidance withdrawal at day 181, while §3.1 says a claim "may be derived from one decisive explicit instruction" with no repetition threshold. In preview those two statements cannot both hold past day 180.
