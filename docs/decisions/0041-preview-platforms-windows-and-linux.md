# Decision 0041: The Claude preview is certified on native Windows and Linux; macOS is not certified for now

Status: accepted (the owner's decision, Task 18 release gate, preview) · Date: 2026-11-04 · Engine: `0.1.0.dev10` · Observed: the tenth live gate passed on native Windows (Claude Code 2.1.310)

## Context

IMPLEMENTATION_PLAN requires native Windows, macOS and Linux for platform acceptance. The release checklist's live items (`deterministic_case_variants` for its live variants, and `inference_isolation_and_delivery_certified`) were therefore blocked on "Linux and macOS live not observed".

- **Native Windows** is live-certified:
  - the curator route and all four delivery paths since 2026-10-23;
  - the tenth live gate passed there on 2026-11-04.
- **macOS:** the deterministic suites pass in CI on macOS runners. The owner has no Mac, so no live check can run there.
- **Linux:** the deterministic suites pass in CI. The owner may be able to run the live checks on a Linux machine.

## Decisions

1. **The Claude preview's platform acceptance is native Windows and Linux.** A platform is certified for the preview when its live checks pass on a native machine of that platform:
   - the provider probe and runtime check certify the route;
   - the engine-mode delivery probe finds start and prompt healthy;
   - the results are recorded, sanitized, in `docs/host-compatibility.json`.

   The comparative smoke gate need not be repeated per platform: it passed once, on Windows. Its behavior is platform-independent apart from what the deterministic suites and the per-platform §7 gate cover.
2. **macOS is not certified for the preview.** It is stated as such in OPERATIONS and the checklist. The deterministic suites keep running on macOS in CI.

   Nothing in the product changes. Readiness is decided per installation by its own live certification, so a macOS installation is ready only after its own probes pass, as on any platform.
3. **macOS can be certified later** by anyone with a Mac. They run the same live checks with their own provider credentials and submit the sanitized record. The README asks for this help.
4. **The full release is unchanged:** it still requires all three platforms. "For now" is the owner's wording, and this decision covers only the preview.

## Consequences

- IMPLEMENTATION_PLAN's platform line points here for the preview.
- In the checklist, the live items' blockers become "Linux live not observed", with macOS stated as not certified for the preview. The coverage manifest's variants keep their platform lists, and their notes record which platforms were observed live.
- The preview release still needs a Linux live run, release signing, and the owner's go-ahead to publish.
