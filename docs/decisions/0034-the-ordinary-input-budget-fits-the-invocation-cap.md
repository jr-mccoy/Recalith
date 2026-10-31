# Decision 0034: The ordinary input budget fits the invocation cap

Status: accepted (SYSTEM_SPEC §6.3 default, preview) · Date: 2026-10-29 · Engine: `0.1.0.dev4` · Decided by: the owner's delegation

## Context

The daily defaults are 90 invocations, 900,000 input estimates and 180,000 output estimates. A protected reserve of 30 / 300,000 / 60,000 is kept for reviews, corrections and revalidation, leaving 60 / 600,000 / 120,000 for ordinary extraction and narrative work. Both live gates' workload days ran out of the ordinary input pool long before the invocation cap:

| Run | Day | Exhausted at | Calls by then |
|---|---|---:|---:|
| First gate | ledgerlite | 3.89 h | 21 |
| First gate | fieldnotes | 3.84 h | 29 |
| First gate | household | 7.72 h | 30 |
| Second gate | ledgerlite | 3.96 h | 20 |
| Second gate | fieldnotes | 4.21 h | 24 |
| Second gate | household | not exhausted | 28 |

In the second gate, calls averaged about 24,000 ledger tokens each, nearly all input. That is 3,432,043 tokens over 145 calls. The 600,000 pool was sized as if each call used 10,000 (600,000 / 60). Once it runs out, the project stops learning for the rest of the UTC day: extraction and narrative jobs wait with `budget_exhausted:ordinary.input_estimate`. In an eight-hour day that means half the day.

## Decision

1. **The default daily input estimate becomes 1,800,000.** The ordinary pool is then 1,500,000, about 60 calls at the observed size. The invocation cap becomes the limit that binds first, as the spec's call arithmetic assumes.
2. **Everything else is unchanged:** the invocation cap (90 / 60 ordinary), the output pools, and the protected reserve (30 / 300,000 / 60,000).
3. Budgets stay per-project settings: a `[budgets]` table in `.recalith/project.toml`. A project that wants the old ceiling sets `daily_input_estimate = 900000` there.

## Why this keeps cost safe

- **The invocation cap is still the runaway guard.** No more calls are possible than before.
- **The output pools are unchanged.** For a reasoning model they carry most of a call's cost.
- **The worst case is still a bound.** For a typical small curator model, priced at $0.10 per million input tokens and $0.50 per million output, the whole daily ceiling rises from about $0.18 to about $0.27. A larger model costs proportionally more, and its operator can lower the budget. The status output keeps reporting exhausted pools, hours to exhaustion and per-purpose usage.

## Tests

`test_ordinary_cannot_spend_protected_pool` (integration, worker) now fills the 1,500,000 ordinary pool before showing that a waiting extraction cannot spend the protected reserve. The schemas are regenerated for the new default.

## Limits

- The fix sizes the ceiling to the requests, not the requests to the ceiling. Narrative `update_task` calls carried about half of one day's input in the first gate. Making them smaller is separate work.
- Hours to exhaustion are reported per workload day, and the next live gate measures the new default. Nothing is extrapolated here.

## Consequences

Engine `0.1.0.dev4`. `init` writes no `[budgets]` table, so an installation uses its pinned engine's defaults: one on an earlier engine keeps 900,000 until it moves to this one. A `[budgets]` table in the project configuration overrides either.
