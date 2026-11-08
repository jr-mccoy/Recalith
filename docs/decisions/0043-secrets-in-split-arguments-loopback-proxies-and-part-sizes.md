# Decision 0043: Secrets are scrubbed across split arguments, a loopback request is never proxied, and message parts are sized as stored

Status: accepted (Task 3 capture, Task 3b fast path and Task 7 provider boundary, preview) · Date: 2026-11-08 · Engine: `0.1.0.dev11` · Observed: the pre-publication audit of `0.1.0.dev10` ([report](../audits/2026-11-06-memory-system-audit.md), Phase 0 of [the fix plan](../audits/2026-11-06-fix-plan.md))

## Context

The audit reproduced four defects that let a credential leave the scrubber or let a user's message be lost without a trace. Each was reproduced against a real installation; each sat in code the deterministic suite passes, because no test asserted it.

- **FP-1 (critical): a secret passed as its own argument survived.** For a Bash call, `claude_capture.build_action` splits the command into `action.argv` with `shlex`, and the normalizer then scrubs every string on its own. `mytool --password hunter2 --host db` was stored with `arguments.command` redacted and `argv: ["mytool", "--password", "hunter2", "--host", "db"]` intact, under `coverage.redacted: true`. The value reached the durable spool, the store, the session overlay that the next hook delivers to the model (`delivery._outcome_text` joins argv), and the curator's requests to the provider. No single element shows a flag/value pair, so no rule could see it.
- **CAP-2, CAP-3 (high, medium): common secret names and shapes were missed in text.** The text `assignment` rule required the secret word to end the name, so `SECRET_KEY=`, `SECRET_KEY_BASE=`, `JWT_SIGNING_KEY=`, `ENCRYPTION_KEY=` and `DB_PASS=` were stored verbatim, while `scrub_json` already redacted `SECRET_KEY` as a JSON key. URL passwords containing `/`, `Cookie`/`Set-Cookie` headers, `mysql -pVALUE`, `curl -u user:pass`, signed-URL signatures and GitLab, SendGrid, Twilio and bare AWS secret keys were missed. `psql --password mydb` lost its database name, because `--password` is a prompt switch there.
- **PROV-1 (high): a named proxy received a loopback request.** The transport child allows plain `http` only to a loopback host, then hands the request to urllib's `ProxyHandler`. urllib proxies `127.0.0.1` and `localhost` whenever `HTTP_PROXY`/`ALL_PROXY` is set, and live mode forwards a route's `network_env_keys` without `NO_PROXY`. A local-server route with a corporate proxy named sent the whole curator request, and its bearer key, in plaintext to the proxy host. A unit test asserted that behavior as intended.
- **Found while fixing these: the scrubber could take seconds.** The text `assignment` rule matched a name as a free run of name characters before the secret word, with `\b` allowing a start after every `.` or `-`. On 16 KiB of `a.key-` or `a.pass-` (a minified file, a generated identifier list), the `0.1.0.dev10` scrubber took 8.2 and 7.7 seconds. The scrubber runs in the hook, whose whole budget is 250 ms (SYSTEM_SPEC §5.1.1); capture has priority and is not abandoned, so every later step of that hook and the host's own wait paid for it.
- **CAP-1 (high): large escape-heavy messages were lost.** `_partition` cut an oversized message into 48 KiB of raw UTF-8 per part, but the 64 KiB cap is enforced on the part's canonical JSON, where `"`, `\` and control characters expand. A pasted JSON blob or a Windows-path log produced parts over the cap. The worker refused the whole message; the hook spooled only the last part, leaving `text_part index=2 count=3` with no siblings and no gap naming the cause.

## Decisions

1. **The shared scrubber scrubs an argument array across neighbouring elements** (`redact.scrub_argv`). `scrub_json` applies it to every `argv` array it meets, so the hook, the worker, every adapter and the pre-action query all get it from one place. The element after a secret flag (the `cli_secret` vocabulary) becomes the marker; so does the password half of `-u|--user|--proxy-user user:pass` (not a numeric `uid:gid`) and the attached value of `-pVALUE` for the MySQL family. Every other element is scrubbed as text. The array keeps its length, so the action stays `exact` and its family digest is computed over the scrubbed array, consistently for stored lessons and queries.
   - The plan proposed splitting the scrubbed command instead. That would mark every secret-bearing command `unknown` (the marker's brackets are shell glob characters) and fix only the Claude adapter. The scrubber rule is stricter and general.
2. **Text redaction gains the missing names and shapes.**
   - An assignment's name is judged by `sensitive_name`: the JSON-key token rules, plus a name ending in a secret word (`PGPASSWORD`, `oauth`), plus an abbreviated `*_PASS` when the name is upper-case or its owner is a database, mail, proxy or admin word. `scrub_json` uses the same rule for keys, so text and JSON agree. The pairs `signing key`, `encryption key` and `master key` join the sensitive pairs.
   - New rules: URL passwords up to the `@` (not a port and path such as `localhost:4873/@scope`); whole `Cookie`/`Set-Cookie` header values; `sig=`/`X-Amz-Signature=`/`X-Goog-Signature=` query values; `glpat-`, `SG.`, `SK`+32 hex; a bare 40-character AWS secret key (mixed case, a digit and `/` or `+`, never a path).
   - `--password` on a PostgreSQL client line is a prompt switch and keeps its next word. `Authorization: Bearer X` keeps its scheme word.
   - Scrubbing stays idempotent over the whole corpus.
   - **No rule backtracks quadratically.** An assignment's name is matched once: it starts only where no name character precedes it, is taken whole (possessive, at most 128 characters) and must hold a secret word within its first 64. The widened URL-password run is bounded to 256 characters, possessively. Every adversarial 16 KiB input now scrubs in under 11 ms, and ordinary text within a few milliseconds of `0.1.0.dev10`.
3. **A loopback endpoint is never proxied.** The transport builds its opener with no proxies when the host is a loopback name; remote hosts still use only the proxies a route names. A proxy variable is refused in `nonsecret_env`, so it can reach the curator only as a named network key.
4. **A message part is sized by its canonical JSON**, including the largest `text_part` it can carry, shrinking in proportion to the overshoot. 48 KiB of raw text stays the upper bound, so ordinary text partitions exactly as before.
5. **Measurement reports record the output's file name only**, on every platform, and a test scans all tracked evidence (`docs/measurements/`, `docs/evaluations/`, `docs/host-compatibility.json`) for agent scratch paths and user homes. The one scratch path the audit found (REL-6) is removed.
6. **Engine `0.1.0.dev11`.** The wheel changes. The transport source is part of the shipped API adapter digest, so a route certified on `0.1.0.dev10` reports `adapter_changed` until it is certified again; the next live run uses a fresh pilot (decision 0030 item 2). The release checklist marks the smoke gate blocked: it passed on `0.1.0.dev10`, and this engine changes capture, partitioning and the transport.

## Rejected

- **Drop `argv` for any command that held a secret.** The action identity would become unknown for exactly the commands whose failures matter (a deploy, a database migration), and caution could never match them. Replacing only the value keeps the identity.
- **Treat any element after `-u` as a credential.** `docker run -u 1000:1000` and `pip install --user requests` would lose meaningful words; only a non-numeric `user:pass` pair is redacted.
- **Disable proxies for every plain-`http` request only.** A loopback `https` endpoint has the same property: it must not leave the machine. The rule is by host, not by scheme.
- **Keep the old proxy test and document the behavior.** SYSTEM_SPEC §9.1 allows plain HTTP only to a loopback host; a request that reaches another host is a violation, whatever a route names.

## Tests

- `tests/unit/test_redaction.py`: every new shape with its kept prefix; fourteen look-alikes that must stay untouched (`psql --password mydb`, `mkdir -p`, `ssh -p 2222`, `docker run -u 1000:1000`, a port-and-scope URL, `test_pass`, paths of 40 characters); `sensitive_name` cases; JSON keys and text agreeing; `scrub_argv` on ten arrays, through `scrub_json` too; idempotence over the corpus; five adversarial 16 KiB inputs each scrub in under a second (two take 7–8 s on `0.1.0.dev10`; the bound is loose so a slow runner never flakes).
- `tests/platform/test_capture_only_claude.py::test_split_command_secrets_never_reach_spool_scratch_store_or_overlay`: five split-secret commands through the real hook entry in fresh `-I` processes; no byte of any secret in the spool, the session scratch, the store after ingestion, or the overlay text a delivery would render. It fails on `0.1.0.dev10`.
- `tests/unit/test_api_providers.py`: a loopback endpoint with a live proxy named in four variables reaches the endpoint and the proxy sees nothing (fails on `0.1.0.dev10`); named proxies still apply to a remote host; proxy names are refused in `nonsecret_env`.
- `tests/unit/test_normalize.py`: four escape-heavy messages partition into parts that pass both the strict model and the hook's wire validator and reassemble exactly (two of the four fail on `0.1.0.dev10`).
- `tests/unit/test_tracked_evidence_is_sanitized.py`: the evidence scan and the measurement tools' recorded command line.
- The deny-spelling test is re-pinned to `0.1.0.dev11`.

## Limits

- **Scrubbing is still a guard, not a guarantee** (SYSTEM_SPEC §13). A secret in an unrecognized shape, a secret flag outside the vocabulary, or a value an operator passes through an environment variable with an ordinary name is not detected. The vocabulary is shared by text and argv rules, so a later addition reaches both.
- **What was captured before `0.1.0.dev11` is not rewritten.** Existing installations may hold split-argument secrets in stored events, scratch and older backups. The forget command can remove them by source range; nothing scans for them automatically.
- **A name longer than 128 characters is not judged** as an assignment name; its value is still scrubbed by every other rule.
- **The bare AWS rule can redact a 40-character mixed-case token that is not a key.** It masks text; it never weakens evidence of anything else.

## Consequences

The owner re-certifies the curator route and delivery on a fresh pilot from the `0.1.0.dev11` wheel before any live run. The smoke gate is re-run on the engine that ends the audit's Phase 3 (fix plan Phase 5), not on this one alone.
