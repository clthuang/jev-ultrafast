# Robustness and efficiency: status and continuation

This file is the ledger for [the implementation plan](../robustness-efficiency-implementation-plan.md). It replaces
the handover's machine-bound ledger (`artifacts/robustness-efficiency-implementation/<run_id>/progress.json` on the
original Mac, preserved in history at `1bb0449:docs/handover/2026-10-04/continuation/progress.json`). The plan's
contracts, task boundaries and acceptance criteria are unchanged; only where work runs and how evidence is kept
changed, as §2 and §3 record.

## 1. Task status

| Stage | Tasks | Status | Evidence |
| --- | --- | --- | --- |
| Baseline | SETUP-1…3, GATE-BASELINE | Done, 2026-10-03 | Original machine: 34 harness tests, native egress proof (zero forbidden connections), production files hash-identical |
| Policy | POLICY-1…3, GATE-POLICY | Done, 2026-10-03 | Original machine: 10 named nodes, 274 focused tests; reviewer `browser_review` READY |
| Select | SELECT-1…2, GATE-SELECT | Done, 2026-10-03 | Original machine: 333 offline + 30 native; 19 changed-state cases reject before input; reviewer `execution_review` READY |
| Limits | LIMITS-1…2, GATE-LIMITS | Done, 2026-10-04 | Original machine: 15 named nodes / 45 variants, 422 focused tests; reviewer `browser_review` READY |
| Prerequisites | PRIVACY-1, RUNS-1 | Done, 2026-10-04 | Original machine: 32 and 338 focused tests; reviewer `execution_review` READY |
| Reviews | REVIEWS-1…7, GATE-REVIEWS | In progress | See §4 |
| Snapshot | SNAPSHOT-1…2, GATE-SNAPSHOT | Not started | — |
| Readiness | READINESS-1…3, GATE-READINESS | Not started | — |
| Release | RELEASE-1…3, GATE-RELEASE | Not started | — |

Re-run in the cloud on 2026-10-04 at `a94014b` (main after consolidation): every plan-named node through REVIEWS-7
exists and passes — 90 nodes, 244 variants, none skipped or xfailed, the 3 native SELECT nodes included
(`scripts/plan_tests.py SETUP POLICY SELECT LIMITS PRIVACY RUNS REVIEWS --native`). The full offline suite passes
(597) and the full native suite passes (30). This re-run confirms the earlier gates still hold on the consolidated
tree; it is not a substitute for GATE-REVIEWS' independent review.

## 2. Building and testing in the cloud

**Can this be implemented and tested in a cloud container? Mostly yes, with three explicit limits.**

What works here (verified 2026-10-04, Linux container, Playwright Chromium 141 headless):

- **All offline work.** Every runtime change in the remaining stages is Python or in-page JavaScript, and the
  plan's correctness checks are offline tests with fakes, a fake clock and the node-based snapshot harness.
- **Native browser checks.** `scripts/validation_lab.py` starts an owned headless Chrome with a fresh profile, a local
  fixture server and a deny-by-default proxy; every other destination is refused and audited. It needed three
  portability fixes (no sandbox only as root, `/proc`-based process identity, an explicit browser path). All 30
  native tests pass; `validation_lab.py run` closes the lab even when tests fail.
- **Evidence and review.** Git commits identify every source state; independent reviewers are fresh agents given a
  fixed commit and scope.

What cannot be validated here, and stays an explicit limit in every gate report:

1. **Live sites and paid models.** No `TYPESAFE_API_KEY`/`TEXT_MODEL_API_KEY` exist here, the plan authorizes no paid
   call in these stages, and datacenter IPs see consent and bot pages that make Google Flights timings
   unrepresentative. Performance claims need the separate paid protocol in the plan's §8.
2. **Headful, user-profile behaviour.** Window placement and focus (`foreground_window`, `show_window`, the background
   window), extensions such as 1Password, and a signed-in profile behave differently in headless Chrome. The lab
   proves DOM, CDP, freshness, SELECT and network-readiness logic, not these.
3. **Production activation.** The live `jev-mcp` servers and the real `artifacts/` store are on the user's machine.
   RELEASE-3 rehearses detection, backup, migration and rollback on disposable state; the real activation is the
   user's step, with the runbook.

## 3. How evidence is kept now

- **Source identity is a commit SHA**, replacing the hash manifests that guarded a separate candidate directory.
  There is no live writer in the container, so SETUP-3's isolation concern does not arise here; it returns at
  activation (RELEASE-3).
- **Each gate records**, in §1 and its stage section: the commit, the exact commands, exit status and counts, the
  named-node result from `scripts/plan_tests.py`, the reviewer's scope and verdict, and every finding's resolution.
  Raw logs are not committed; each is reproducible by re-running the command at the recorded commit.
- **Named acceptance nodes** are checked by `uv run python scripts/plan_tests.py <stage> [--native]`: it extracts the
  plan's Verify nodes (plus the 45 inherited readiness nodes for GATE-READINESS), fails on a missing node, an empty
  collection, or any failed, skipped or xfailed variant, and runs native nodes in a fresh owned lab.
- **Independent review** is a fresh agent with no implementation context, a fixed commit and an explicit scope,
  matching the plan's reviewer roles (`execution_review`, `browser_review`, `review_pipeline`). Blockers and
  should-fix findings are resolved before a gate closes.
- **Never counted as a pass:** a missing or skipped required case, zero tests collected, a mocked substitute for a
  native requirement, or a test whose assertions are weaker than the plan's Pass line.

## 4. Remaining work: designs and order

Order is unchanged: GATE-REVIEWS → GATE-SNAPSHOT → GATE-READINESS → GATE-RELEASE, one implementer at a time,
independent reviewers on frozen commits. The designs below come from the current code (audits on 2026-10-04 at
`979067a`); file:line references are to that commit.

### 4.1 REVIEWS: close the audit's defects, then the gate

Code and all 46 plan-named nodes (62 variants) exist and pass, but the audit found defects that the named tests do not
catch. Each fix lands with a test that fails before it.

| ID | Defect (severity) | Design |
| --- | --- | --- |
| R1 | A paid attempt's short sections (`transition`, batch verification, apply, final settlement) take the review lock with `LOCK_NB` (`review_runs.py:841-850`). A concurrent manual `queue`/`apply`/`enable` makes the attempt fail: a child killed before its identity is saved leaves `child: null`, which blocks every later dispatch; a paid reply returned during contention is discarded and the attempt later counts as a failure (High) | Internal paid sections wait for the review lock up to a bound (`SHORT_LOCK_SECONDS`); manual commands keep the immediate BUSY reply. The global order dispatch → review → metadata → notes keeps waiting deadlock-free (manual commands never take dispatch). Save known cost and the reaped-child fact as soon as `launch` returns, in memory first and then under the lock, so neither is lost to a later failure. Tests hold the lock from another thread during each transition: one launch, reply applied or cost kept, no failure counted from contention, next dispatch not blocked |
| R2 | A blocked dispatch can never be cleared, and a legacy `running` timestamp from the baseline's `begin()` blocks every dispatch forever (`1166-1167`); neither `enable` nor migration clears it (High) | Holding the review lock proves no baseline review is alive (the baseline held the same lock for its whole run), so a legacy, non-attempt `running` value settles once as one failure — the baseline `settle()` rule — in one state replacement. Add `resolve <attempt_id>`: confirmed at a terminal like `approve`, refuses while the recorded process group is alive, settles an unknown-ownership attempt once as abandoned |
| R3 | After notes+receipt commit, a digest-recovery error reaches `apply`'s generic "Reply could not be applied" (`1354-1357`), a false "nothing changed" (Medium-high) | A distinct committed-but-recovery-pending error after the commit point, with its own wording; add a `recover` command. Tests through the CLI: wording, receipt retained, and both another batch's apply and a paid dispatch refused until recovery; conflicting and malformed existing digests |
| R4 | Batch membership and deferred items are never shown: `queue` prints "Nothing is queued." when everything is deferred, and `report_runs` omits input membership (Medium) | `queue` prints the selected items (kind, ID, version prefix) and every deferred item with its reason to stderr; `report_runs` prints `input:` and `acknowledged:` per v2 digest through its privacy-safe `shown()` |
| R5 | Test gaps (see below) | Strengthen the named tests whose assertions are weaker than the plan's Pass lines; add tests for pre-cap eligibility, the three-failure disable rule, expired-child termination, the timer/reap guard and `review_processes.process_identity` |
| R6 | Batch `since` and attempt `error` unvalidated; `queue` catches only `ValueError`; dead helpers that bypass the commit protocol (`apply_decision`, `write_digest`, `begin`/`finish`/`settle`) (Low) | Validate; catch `PublicationUncertain`/`OSError` with fixed wording; delete the dead helpers (move a test-only writer into the test) |
| R7 | `review_records.timestamp` reads naive local times as UTC, so `last_start` comparisons are off by the UTC offset (Low) | Interpret naive stored times as local, as they are written |
| R8 | Docs show `apply` without `--batch`; preflight lost its diagnostic lines; REVIEWS-7's backlog/cutoff note is missing (Low) | Fix the docs and restore the preflight lines |

Tests that assert less than the plan, to strengthen: `test_real_pipeline_redacts_every_publication_surface` (check the
report output and stderr, run the CLI, exercise a valid decision beside a refusal, an excluded predecessor, the start
failure / did-not-start / crash messages, a migration step); `test_attempt_records_never_acknowledge_items` (a real
failed attempt); `test_unknown_record_versions_fail_closed` (through the readers); `test_crash_at_each_publication_boundary`
(receipt survives, CLI wording, pending recovery blocks work, a paid-path and a conflicting-digest variant);
`test_all_note_writers_preserve_pending_receipt` (add `record_failure`); `test_auto_cutoff_and_exclusions_survive_migration`
(a real state file and a paid `auto`); `test_export_preserves_new_notes_outcomes_receipts_and_ack_history` (legacy
digests, legacy state, retired notes); `test_mixed_legacy_and_v2_reporting` (membership);
`test_live_or_unknown_child_blocks_new_dispatch` (an expired child is terminated only after identity checks).

**Gate.** `scripts/plan_tests.py REVIEWS`, the full offline suite, Ruff; then two independent reviews of the frozen
commit — execution/storage (locks, crash points, dispatch, migration) and reporting/privacy (every output sink) — with
all blockers and should-fix findings resolved. The compatible rollback export is RELEASE-3's.

### 4.2 SNAPSHOT: schema-2 snapshots

Measured on the current code with a synthetic page (one form, 6,000-character shared context): one observation of
250 / 1,000 / 5,000 buttons serializes to 1.60 / 6.22 / 30.90 MB, almost all per-action guards (each carries its
scope's text, and guards are built before the 250-action cap). Every global freshness check re-runs the whole snapshot
and returns a 25 KB–1 MB marker. The same pages' schema-2 observation is about 52 KB.

**In-page protocol** (`snapshot.js` becomes a side-effect-free library returning `observe`, `fresh`, `reference`):

- One `scan()` shared by observe and fresh: today's candidate rules, weak IDs only (a `WeakMap`), no retention.
- `observe` offers the first 250 target actions, builds guards only for those nodes (each distinct scope's text read
  once), and stores in the page a baseline: the exact global semantic marker (all candidates, evidence and form controls,
  as today), the page/form key, guards, deduplicated scopes and the offered action JSON. Strong references (`nodes`)
  cover only offered targets and their offered options (≤ 500). The reply carries `snapshot_schema: 2` and an
  `observation_token` `{schema, epoch, generation, document_id}` instead of `marker`/`page_key`/`guards`.
- The reply is measured in the page with `TextEncoder.encodeInto` against 262,144 bytes. Over the ceiling, the page
  drops its baseline and retained nodes and returns only a `snapshot_too_large` envelope with counts — no actions, no
  token, no truncated labels. Success and overflow are each a single commit point (`generation += 1`).
- `fresh(token, action)` is read-only: it never installs a baseline, advances the generation or retains a node; no
  cache, another epoch, an old generation or another document all return false. CLICK/SELECT compare the page key and
  that action's one guard against the baseline; every other check compares the full global marker string.
- CLICK/fill hit-testing and the SELECT evaluation resolve their node through `reference(token, action)`; the SELECT
  payload becomes `{action, token}` with its validation, assignment and one input/change pair still in one synchronous
  evaluation, plus a tagged pre-input `snapshot_too_large` result.

**Python and adapters.** `SnapshotTooLarge` is a `RunStopped` (`snapshot_too_large`), never a `StalePage`, so no
recovery read or observe retry can swallow it. `Agent.command` catches it before its generic handler, stops the run
(clearing the pending decision and text), and — after an input — keeps exactly the one logged step. MCP's final read
reports it as a failed fresh read; a `done` run becomes `stopped` with that code, while blocked/stopped runs keep their
codes so failure codes are unchanged. The inspector returns the stop like any `RunStopped`; `report_runs` totals it.
Pages without a valid schema-2 token (old run files, legacy dicts) remain readable by every report but `fresh` returns
false and `act` raises `StalePage` with zero browser calls. The progress fingerprint keeps today's projection (URL,
text, capped actions with geometry, scroll with height, evidence) and recursively strips protocol identity
(`observation_token`, `snapshot_schema`, `snapshot_stats`, `document_id`, `cache_epoch`), so schema-1 fingerprints are
unchanged.

**Parity with the baseline** (snapshot-preparation.json's seven cases) holds by construction: an unchanged page observed
twice gets a new token and the same fingerprint; freshness after a mutation is false every time it is asked; geometry
and scroll height count as progress but not as staleness; offscreen or omitted controls and title changes make global
freshness false without counting as progress; multi-select selections are evidence and progress, never targets.

**Tests.** `tests/test_snapshot_contracts.py` runs offline against a scalable fake DOM (`tests/fixtures/dense_dom.cjs`)
evaluated by Node — the same approach as today's `select_dom.cjs` — including 250/1,000/5,000 controls, shared and
per-row scopes, long and multibyte labels and an oversize fixture. Native lab tests compare the new freshness against
the frozen schema-1 script (`git show c8a467c:jev_ultrafast/snapshot.js`) on the native mutation list, rerun every
native SELECT test, and record bytes, guard builds, scope reads and references for dense pages. Known consequences:
every observe advances the generation, so a decision becomes stale after any re-observe (READINESS must use non-installing
reads); a real page with very long labels can now stop with `snapshot_too_large` instead of transferring megabytes.

### 4.3 READINESS

Design in preparation from the current code; recorded here before implementation starts.

### 4.4 RELEASE

1. **RELEASE-1:** reconcile README, `docs/claude-code-integration.md`, `docs/failure-review.md`,
   `docs/executor-improvements.md` statuses and examples with the shipped API; label old trials historical.
2. **RELEASE-2:** Ruff, full offline and native suites at one commit, both JS checks, `uv build`,
   `scripts/wheel_smoke.py`; an independent implementation review and a separate premortem.
3. **RELEASE-3:** finish `scripts/migrate_review_storage.py`: writer detection and quiescence (dispatch lock, live
   attempts), a verified backup (hash under locks, read back), state migration, a dry-run inventory, refusal of a missing
   store, and a compatibility export the baseline code can read (notes list; v2 acknowledgments as legacy digests so a
   rollback does not requeue everything). Rehearse the runbook end to end on disposable state with fake launchers.
