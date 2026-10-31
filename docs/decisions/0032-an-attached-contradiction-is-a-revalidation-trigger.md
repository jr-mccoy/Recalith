# Decision 0032: An attached contradiction is a revalidation trigger

Status: accepted (Task 10 slice, preview) · Date: 2026-10-29 · Engine: `0.1.0.dev4` · Schema: 12 · Decided by: the owner's delegation ("recommend what to do … and do that")

## Context

SYSTEM_SPEC §3.5 lists "relevant file/configuration change, contradiction, or review due" as the causes of revalidation. Decision 0012 item 1's recheck reasons covered every cause but the contradiction. In all three live R4 reruns, extraction attached session C's read of the changed `store.py` to the stale fact as `contradicts`, and admission accepted it. The fact stayed `active` and `current`, with no recheck and no revalidation (decisions 0030 and 0031 Limits).

## Decisions

1. **A new recheck reason, `contradiction`.** Schema 12 rebuilds `claim_rechecks` with it, as migration 0009 did for `support_lost`. It is a freshness reason and one a model can settle.
2. **When it is recorded.** A `contradicts` link newly attached to live guidance (`active` or `disputed`) records one recheck per contradicting record, through `attach_evidence` or a duplicate proposal that merges new contradicting evidence. The claim needs revalidation at once, its review is due now, the guidance epoch advances, and a protected revalidation job is queued that reads the contradicting evidence. Claims that depend on it are marked `dependency_changed`, as for any freshness reason.
3. **What is not marked.**
   - **A candidate.** Its own review reads its contradictions, and attaching evidence already queues that review again.
   - **A user's declared decision or preference.** It states intent, which an observation cannot refute. Conflicting declarations become an intent question, and an automatic process may never retire a declaration (SYSTEM_SPEC §7.2).
4. **Settling.** A revalidation that read the contradiction settles it.
   - A revision, a status change (dispute, supersede, invalidate) or a keep clears it.
   - A keep leaves the link attached, so the claim still cannot be corroborated.
   - The freshness is `current` again once nothing else is pending.
5. **`revalidate@2`.** The revalidation prompt names "evidence attached against it (its contradicts links)" among the causes. `@1` stays in the build for jobs that pinned it.

## Why this is safe

The trigger can only make guidance more cautious: a freshness label and a revalidation call from the protected pool. A model that attaches contradicting evidence gains no power it lacked, because it could already propose a dispute, and admission still checks every link. Rechecks are idempotent per claim and record, and revalidation jobs coalesce.

## Tests

`test_an_attached_contradiction_makes_live_guidance_need_revalidation` (integration, consolidation) checks:

- the trigger: the label, the pending recheck, and the queued job that reads the contradiction;
- that a duplicate attachment records nothing more;
- the keep: `current` again, with the link still attached;
- the two exclusions.

It failed before the change. `test_revalidate_prompt_is_versioned_package_data` pins both prompt digests.

## Limits

- It labels sessions after the one whose read contradicted the claim, not that session's own prompt. R4's measured point depends on decision 0033.
- It applies to links the curator proposes and code admits. It never asserts the claim false; only a revalidation's reviewed decision can retire it.

## Consequences

Engine `0.1.0.dev4` and schema 12. The general engine and schema upgrade is not built (decision 0026), and the bootstrap refuses a second artifact under a provisioned version, so live runs need a fresh pilot.
