# Independent review, validation and premortem

Date: 2026-10-03. Scope: [robustness and efficiency proposal](robustness-efficiency-proposal.md).
Implementation baseline: `60f03037a713dbce10f46da015fbffccc9132fa5`.
Status: all three independent passes complete; no unresolved design blockers. No implementation has been changed.

## Review method and evidence

The primary agent researched the existing designs, drafted the proposal and owns its revisions. Three separate
agents researched bounded areas first, then read the complete draft in distinct review roles:

| Agent | Research | Independent review role |
| --- | --- | --- |
| Archimedes (`browser_review`) | WHATWG/MDN select semantics, snapshot/guard design | Adversarial design review |
| Kepler (`review_pipeline`) | Existing review contract, file publication, versioned acknowledgment | Code and contract validation |
| Ramanujan (`execution_review`) | Operation permissions, shared budgets, timeout/cancellation semantics | Premortem across all proposed changes |

The proposal's research table links primary sources fetched live. AnyIO's documentation site returned 403, so its
official repository documentation was used. Repository claims were checked against current files, not memory.
Research and reviews used no paid API calls, active browser access, real run/note mutations, or database writes.
Disposable offline reproductions used synthetic data and temporary directories.

Draft 2 reviewed by all three agents was 397 lines, SHA-256
`fc01bea01a62946c116009bf37f65440feff6fb31e42ffb6f06839b42e7e6554`.
All initially returned HOLD. The proposal was revised before requesting a final pass; initial approval is not implied.

## Findings and revisions

| Finding from the first review | Severity / reviewer | Resolution in revised proposal |
| --- | --- | --- |
| Using global freshness as progress would reset WAIT on offscreen changes and lose scroll-height progress | Blocker, Archimedes | §7 retains the existing progress projection; exact freshness and observation identity remain separate |
| Filtering before indexing could highlight the wrong inspector element and hide read-only field values | Blocker, Archimedes | §3 allocates one full canonical evidence table and filters heads without renumbering |
| Locking whole-state saves still erases independently appended user corrections | Blocker, Kepler/Ramanujan; warning, Archimedes | §6 assigns field ownership and requires Agent saves to preserve persisted outcome arrays under the metadata lock |
| Batch caps could remove cross-run/excluded-chain privacy inputs | Blocker, Kepler | §6 freezes the complete pre-cap privacy closure; contributor versions are checked and no raw values are persisted |
| Digest identity/schema and readers were unspecified; timestamp collisions could lose acknowledgments | Blocker, Kepler/Ramanujan; warning, Archimedes | §6 defines immutable batch-ID v2 digests, separate membership/acknowledgment, shared legacy/new reader and timestamp sorting |
| A post-replace fsync error was incorrectly treated like no publication | Blocker, Kepler | §6 distinguishes precommit failure from visible or uncertain commit and requires receipt recovery before any replay |
| Calling existing lock-owning note helpers inside the transaction could deadlock | Implementation warning, Kepler | §6 requires one lock-owning transaction API and pure in-memory callbacks |
| Replay could fail its own freshness checks after successfully changing notes | Validation warning, Kepler | §6 checks committed receipt/digest before dependency freshness; same reply returns the recorded result |
| Direct/nested commands could double-count recovery; overflow could fall back to actionable stale evidence | Premortem warning, Ramanujan | §5 assigns recovery to tick; §7 makes overflow terminal through every adapter |
| Stale reviews and dispatch uncertainty could cause immediate paid retries | Premortem warning, Ramanujan | §6 defines superseded work, daily-slot consumption and no redispatch during receipt recovery |

The required operation allowlist is an explicit compatibility break. It enforces the supplied policy; the caller
still must faithfully translate user authorization. The proposal does not claim to enforce arbitrary English goals
or prevent website-side effects. The reviewers accepted those limits when stated clearly.

## Validation actually performed

These checks validate findings and design contracts, not an implemented candidate:

- Prior current-code review: 236 offline tests passed, Ruff passed, both JavaScript syntax checks passed.
  Production code remains at that baseline; those results do not prove the proposed changes.
- Archimedes executed production `action_space()` and `fingerprint()` on offline examples. They confirmed target
  renumbering/evidence loss under naive filtering and the difference between progress and freshness projections.
- Kepler reproduced a completely sequential persisted label followed by `Agent.save`: outcome count fell from
  one to zero. The reproduction confirms why a lock without a merge contract is insufficient.
- Kepler reproduced privacy-set regression with a synthetic canary in selected run A and typed only by deferred B:
  full-queue redaction removed it, selected-only redaction exposed it.
- Kepler ran the existing focused `test_summaries_skip_excluded_and_reviewed_runs`; it passed. The broader new
  migration/crash tests remain implementation requirements, not completed tests.
- Earlier source-grounded reproductions established forbidden clicks, permanent stale recovery, option-value
  substitution, corrected-run suppression, unseen-run acknowledgment, and large synthetic snapshot payloads.
- The primary agent checked document structure, source/caller references and preservation of the pre-existing
  user document. Its SHA-256 remains `cae57d73c9de9a4995084e4e0dec66d49d549fae76d19df441ebdb80ded460e7`.

No local-browser SELECT integration, live latency benchmark, paid-model quality comparison, migration of real notes,
or proposed-fix test suite has been run. These are explicit implementation/release gates in the proposal.

## Premortem: assume the change failed after one week

| Scenario, ranked | Likelihood / impact | Early detection | Prevention and objective acceptance |
| --- | --- | --- | --- |
| A correction vanishes or a completed batch loses its receipt | Medium / high | Outcome count decreases; reviewed batch queues again; digest path reused | Preserve persisted outcomes; immutable batch-ID digests; inject save-label-save, concurrent labels and same-timestamp commits across all crash boundaries |
| Caller grants CLICK for “only read” | Medium / high | Restrictive goal paired with broad policy; automatic widening after refusal | Explicit caller examples and no implicit widening; table-test intended policies and inject mislabeled observed actions; accepted caller-trust limit remains |
| SELECT executes once, loses its reply, then runs again | Medium / high | Two event pairs for one attempt; uncertain attempt disappears | Only explicit pre-input rejection is retryable; inject lost reply after assignment and assert one selection/event pair and retained uncertainty |
| Freshness helper overwrites its own baseline or overflow reuses old actions | Medium / high | Changed omitted control accepted; repeated overflow; old pending action remains executable | Freshness never publishes a baseline; distinct terminal overflow; call freshness twice after mutation and require both false plus zero input |
| Nested commands double-count recovery or direct act bypasses stopped state | Medium / medium-high | Counter advances twice; model calls after stop; late DONE overrides expiry | Tick alone owns recovery; check every public entry and after I/O; fake-clock tests for 119/120, nested calls, HTTP retry and helper expiry |
| Readiness and new snapshot identities reset waits or extend the loading window | Medium / medium | Two WAITs never hand back; wait exceeds original input-age cap; continuation inherits old requests | Preserve progress fingerprint and last-input timestamp; combine real snapshot adapter with readiness fixtures and physical input counters |

Additional migration controls: stop old list-only notes writers before publishing the envelope; ordinary new writers
preserve the pending receipt; a post-rename directory-sync failure stops further dispatch and recovers before another
application. Rollback must retain new notes, outcomes and receipts instead of restoring an old copy over newer work.

Accepted residual risks: incorrect caller authorization; synchronous I/O extending cooperative deadlines; global
DOM scan cost; website script side effects; external artifact edits that ignore locks; and unknown live latency or
model-quality changes. The implementation gates must report these honestly rather than converting them into claims
of a hard timeout, browser sandbox, exactly-once billing, or universal website support.

## Final independent pass

All three agents verified the frozen 459-line Draft 3, SHA-256
`7cac11f636b584585d818b524e70560dcdd88d303afa0ef2ebef7ad405f12693`.
Only its status line was subsequently changed to record completion; the reviewed design text is unchanged.

| Reviewer | Verdict | Scope of final verification |
| --- | --- | --- |
| Archimedes | READY for implementation; no remaining blockers | Canonical indices/evidence, progress versus freshness, preserved outcomes, collision-free digests |
| Kepler | READY for implementation planning; no remaining blockers | Outcome ownership, privacy closure, digest/readers migration, post-replacement uncertainty and transaction contracts |
| Ramanujan | READY for implementation; no remaining premortem blockers | Publication recovery, recovery counter ownership, terminal overflow, review scheduling, combined readiness gates |

The final passes inspected the fixed revision and immediate interactions; they did not rerun a complete test suite
or test an implementation. All three confirmed this record accurately represents their earlier findings and checks.

During implementation, explicitly test that transient observation tokens and guard references, including any nested
inside action descriptors, never enter the preserved progress fingerprint. Also retain the policy/inspector mapping,
native SELECT event counts, concurrent label publication, batch replay, privacy, crash/migration, and integrated
readiness gates. The verdict establishes design readiness, not deployed behavior or measured performance gains.

Open design blockers: 0. Implementation and release checks: not yet performed for a candidate implementation.
