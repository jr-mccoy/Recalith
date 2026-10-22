# Typed-state latency attribution series (decision 0022)

`tools/measure_worker_latency.py` reports from `.github/workflows/measure.yml` runs on the GitHub runners, plus one local run. The reports are compact JSON with the same fields the tool writes. Typed state means the event is committed and its ingest job is completed. It is timed from the hook's acknowledgment; the target is p95 ≤ 5 s with 5 s idle polling.

Every report keeps:
- the per-trial `series`;
- the worker's `poll_timeline`, with `poll.timing` step offsets, the sleep before each poll, and checkpoints;
- the observer's records: store-file writes, its own scheduling stalls, and slow store reads.

## Before the tool fix (stale arrival planning possible)

| File | Run, commit | Trials | Fresh plans | p95 / max (s) | What it shows |
|---|---|---|---|---|---|
| `worker-*-run10.json` | 10, 0b0af8a | 20 per OS | Linux 18, macOS 19, Windows 9 | Windows 4.958 / 6.003 | The first instrumented full run |
| `worker-Windows-run11.json` | 11, 0b0af8a | 40 | 15 | 4.678 / 5.02 | The cadence is exact and no segment is missed; 25 of 40 plans are stale |
| `worker-Windows-run13.json`, `-run14.json` | 13, 14, 8caa1cb | 60 | 24, 10 | 5.133 / 8.34 and 4.908 / 5.009 | Ingesting polls of up to about 5 s; checkpoints observed, none in a late trial |

## After the tool fix (36bbc06: every arrival planned from a fresh idle cycle)

| File | Run, commit | Worker | Trials | p95 / max (s) | Checkpoints |
|---|---|---|---|---|---|
| `worker-Windows-run16.json`, `-run17.json` | 16, 17, 36bbc06 | SQLite auto-checkpoint | 60 | 4.743 / 5.539 and 4.908 / 6.376 | Inside ingesting polls |
| `worker-Windows-run19.json`, `-run20.json` | 19, 20, 2190a38 | Deferred, after every burst | 60 | 5.354 / 9.156 and 4.635 / 4.972 | 61 each; up to 7.6 s on run 19's stalled runner |
| `worker-Windows-run22.json`, `-run23.json` | 22, 23, b3f1f1f | Deferred, at most once a minute (final) | 60 | 4.746 / 5.2 and 4.62 / 5.469 | 6 and 7 |
| `worker-*-run21.json`, `release-latency-*-run21.json` | 21, b3f1f1f (push; full default set) | Final | 20 per OS | Linux 4.476, macOS 4.545, Windows 4.821 / 8.59 | Hook gate met on all three |
| `worker-*-run24.json`, `release-latency-*-run24.json` | 24, b3f1f1f (dispatch; full default set) | Final | 20 per OS | Linux 4.469, macOS 4.393, Windows 4.923 / 5.208 | Hook gate met on all three |
| `worker-Linux-local-b3f1f1f.json` | This container, b3f1f1f | Final | 100 (plus 30 start trials, 600 s idle) | 4.74 / 4.965 | 11; idle 0.162 % of one core, 46.6 MiB |

Runs 11–23 except 21 are worker-only dispatches (`runners=["windows-latest"]`, `worker_only=true`, `idle_seconds=30`). Their idle window is 30 s, not the 600 s footprint measurement.
