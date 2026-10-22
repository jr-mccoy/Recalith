# Decision 0022: Typed-state latency on Windows — the measurement's arrival model and the worker's deferred WAL checkpoint

Status: accepted (Task 4 preview slice follow-up; ACCEPTANCE_TESTS §7) · Date: 2026-10-22 · Host observed: Claude Code CLI 2.1.307 installed (not certified; request capture only); no live route (B1)

## Context

ACCEPTANCE_TESTS §7 requires typed event to working-state availability with a healthy idle worker at p95 ≤ 5 s with 5-second idle polling. SYSTEM_SPEC §6.1 says this is measured "with the idle-to-active transition and actual reduction time" and is not a maximum-latency guarantee. Before this decision, `tools/measure_worker_latency.py --trials 20` on the CI runners gave Linux 4.25–4.84 s and macOS 4.25–4.84 s. Windows gave 4.914, 5.152, 5.226 and 6.544 s (measure runs 5–8).

Run 8's per-trial series looked like two things:

- missed poll cycles with fast polls;
- an idle cycle running 1–1.5 s past its 5 s cadence.

Neither was established. The previous session could not instrument the worker's cycle on a Windows runner.

This session added measurement-only instrumentation:

- the worker's status gained `poll.timing`;
- the tool gained an outside observer.

It then dispatched Windows worker-only runs of `.github/workflows/measure.yml`: runs 11, 13, 14, 16 and 17, with 40–60 trials each. The series are kept in `docs/measurements/ci-typed-state-2026-10-22/`.

## Findings

1. **The worker's cadence is exact on Windows.** In every run:
   - each sleep slept what it requested within about 10–15 ms;
   - no poll drifted;
   - every segment was ingested by the first poll that started after it became visible.

   There is no cadence drift and no missed segment.
2. **The "1–1.5 s past the cadence" was the tool.** The tool planned each arrival from the worker's idle status. After a trial, the ingesting poll has not yet replaced that status, so the file still holds the idle status from *before* it. The tool then planned against a cycle that had already ended. The arrival landed after the active poll at +6 s while its phase was recorded against +5 s.
   - Windows run 11: 25 of 40 trials were planned from a stale status. Linux CI: 2 of 20.
   - Windows hit it more because its post-ingest status write lands later.
   - This made the recorded phases wrong, not the latencies worse. A stale plan sometimes put the arrival inside the 1 s active window, where latency is short.
3. **The "fast polls" were a one-poll lag.** The worker set `poll.last_poll_seconds` after writing the status, so each status reported the *previous* poll's duration. Run 8's late trials 5 and 14 (6.54 and 6.60 s) are each followed by a "slow poll" (2.82 and 2.33 s) on trials 6 and 15. Those were the late trials' own ingesting polls.
4. **The real Windows outliers are slow ingesting polls during runner-wide stalls.** With the arrival model fixed (runs 16 and 17: 60 of 60 plans fresh), p95 was 4.743 and 4.908 s, with max 5.539 and 6.376 s.
   - Each late trial's ingesting poll took 1.8–3.3 s, against a typical 0.05–0.15 s. That time was split between `ingest_ready`'s commit and the ingest job's lease and completion commits. These are fsync'd commits under `synchronous=FULL`.
   - In the same windows the tool's own file-only loop, which does no SQLite work, stalled for 0.25–0.73 s. The whole runner was slow, not only the worker.
   - Linux and macOS polls stayed ≤ 0.1 s.
5. **The WAL auto-checkpoint sits on the typed-state path.** SQLite runs it inside whichever commit crosses 1000 WAL pages. That is about one event in twelve here, and in practice it is the ingesting poll's own `ingest_ready` or job commit.
   - The ingest connection was a separate, newly opened one with SQLite's defaults.
   - Locally, the main file grew from 0.75 MB to 5.7 MB before the ingest job committed.
   - On the Windows runners the checkpoint was usually quick: polls of 0.13–0.53 s against about 0.1 s without it. None of the late trials of runs 13, 14, 16 or 17 contained one.

   It is not the main cause of the outliers. It is the heaviest avoidable I/O on the path: a 4 MB copy plus a flush of the main file, which a storage stall amplifies.

## Decisions

1. **The measurement plans arrivals from a fresh idle cycle.** `idle_status(root, after=...)` accepts only an idle poll that started after the previous trial reached typed state. The platform test `test_idle_poll_state_available_within_five_seconds` does the same.
   - This is the specified arrival model ("uniformly random phase of an idle worker's 5-second cycle").
   - It is stricter than before.
   - The target, the 5 s idle polling, the n and the denominators are unchanged.
2. **`poll.last_poll_seconds` describes the poll it follows.** It is set in `poll_once`, before the status write, and includes the deferred checkpoint below.
3. **`poll.timing` stays in the worker status as a record, not a switch.** It holds:
   - step offsets from poll start;
   - the segments the scan saw;
   - the sleep before the poll (requested, slept, slices, worst slice overshoot);
   - the previous status write's duration;
   - the previous poll's duration and offsets, because a poll that overran its interval is followed at once and its own status may live only milliseconds.

   `counters` gains `status_write_failures` and `checkpoints`. It costs a few clock reads per poll.
4. **The worker defers WAL checkpoints off the typed-state path.**
   - Its own write connection sets `wal_autocheckpoint = 0`.
   - `pipeline.ingest_ready` takes the worker's connection, so ingestion's commits never checkpoint.
   - After a poll's work, a checkpoint is owed. A poll with nothing waiting runs `PRAGMA wal_checkpoint(PASSIVE)`, which never waits on a hook reader. Frames a reader still needs stay owed for the next such poll.
   - Under continuous work, the checkpoint runs after the poll's work once `CHECKPOINT_DEFER_SECONDS` (60 s) have passed since the last one, so the WAL stays bounded.
   - The worker owes one when it opens its connection, because an inherited WAL may be waiting.
   - Every other connection (service, CLI, model lane, backup, forget) keeps SQLite's default. Forgetting keeps its own `TRUNCATE` checkpoint after the purge.
5. **Kill/restart coverage.** `failpoints.CHECKPOINT` (`worker.before_checkpoint`, `worker.after_checkpoint`) joins the worker family. A real child killed at either point and restarted must reproduce the reference store and pass `PRAGMA integrity_check`, with no model job relaunched.
6. **What is not changed.**
   - `synchronous=FULL` and the per-commit durability of ingestion stay. A segment is removed only after its commit is durable.
   - The ingest job keeps its own fenced transaction.
   - Storage stalls on a runner are not something the worker can remove, and no target is weakened to absorb them.

## Consequences

- The Windows typed-state verdict is decided by the corrected measurement on the runners. The results are recorded in BUILD_PROGRESS.
- The checklist item `hook_latency_usefulness_per_platform` becomes `passed` only if every platform meets every healthy §7 target.
- A typed-state p95 over 5 s on a later Windows run is read from `poll.timing` and the observer's stall records before anything else is changed.
- Full release (IPC wake, 2 s target) is unaffected. A wake hint shortens the wait for the next poll, not a stalled commit.
