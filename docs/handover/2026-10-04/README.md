# Jev Ultrafast implementation handover — 2026-10-04

## Read this first

**The robustness/efficiency implementation is unfinished. Do not deploy this snapshot.**
The user approved implementation of the complete reviewed plan. The immediate request for this package is to
write a comprehensive handover and push it to the fork's `main`. That push publishes documentation and a WIP
recovery patch; it does not merge the feature branch, activate the candidate, migrate production, or certify a release.

At this handover, **12 of 27 implementation subtasks and 4 of 8 gates are accepted**. The review pipeline is
partially implemented but unaccepted. Snapshot and loading-readiness stages have not been implemented.
Fresh checks on October 4 found **28 Ruff errors and 1 failing / 6 passing focused tests**. No final full-suite,
wheel, release-native, or activation/rollback acceptance exists.

**Next action:** finish and independently accept `REVIEWS-1…7`, then implement `SNAPSHOT`, `READINESS`, and
`RELEASE` in that order. Do not spend a turn recreating the design or asking whether implementation is authorized.

## Source of truth and locations

| Item | Location / identity |
| --- | --- |
| Original active worktree | `/Users/terry/projects/jev-ultrafast` |
| Original branch / source baseline | `executor-improvements-design` / `60f03037a713dbce10f46da015fbffccc9132fa5` |
| Fork remote | `origin`, `git@github.com:clthuang/jev-ultrafast.git` |
| Fork `main` before handover publication | `1231850a0bf1a0c0341fe408ef1668dbbfdfac46` |
| Evidence directory, called **E** below | `/Users/terry/projects/jev-ultrafast/artifacts/robustness-efficiency-implementation/20261003T100051Z` |
| Implementation candidate, called **C** below | `E/candidate` |
| Authoritative implementation plan | [context/robustness-efficiency-implementation-plan.md](context/robustness-efficiency-implementation-plan.md) |
| Design and review | [proposal](context/robustness-efficiency-proposal.md), [review](context/robustness-efficiency-review.md) |
| Captured task ledger | [continuation/progress.json](continuation/progress.json) |
| Latest portable WIP | [candidate-wip.patch](candidate-wip.patch), [candidate-manifest.json](candidate-manifest.json) |
| Package integrity | [package-manifest.json](package-manifest.json) |

Publication uses a temporary Git index and a documentation-only commit based on the fork's `main`, so the active
feature branch and its dirty user files need not be checked out, stashed, merged or reset. In the original feature
checkout, the handover directory may therefore appear untracked even though it is committed on remote `main`.
Verify the remote commit before deciding that it is unpublished; do not add the WIP as root runtime source.

The original E and C are ignored by Git. They are not automatically present on another machine. This package
contains a complete source-reconstruction patch, selected evidence and helper files, and the historical readiness
test source needed for continuation. It does **not** contain credentials, a virtual environment, production state,
raw browser runs, or every historical/native evidence artifact.

One packaging distinction is intentional: the recovery tree retains the base commit's unchanged `.env.example`
template, which was omitted from the original isolated copy. Its manifest has 80 paths: 79 actual candidate source
files plus that template. `inherited_base_only_paths` records it. This is not a real `.env` or a credential file;
do not copy it to `.env` for tests. All 79 original candidate source files are hash-matched.

Evidence precedence: current source and freshly run checks first; immutable checkpoint files for the source hashes
they name second; design/ledger/prose as intent or historical context. Never infer passing behavior from a test's
existence, a `done` marker alone, an agent message, or a filename containing `current` or `final`.

## Safety and authorization boundaries

1. Read `README.md` and `AGENTS.md`. Keep one natural-language goal → indexed observed elements → selected
   operation and its target → execution. No site-specific executor plans, model-generated selectors, or executable code.
2. **Run commands with C as the working directory.** `uv --project C` from the production root is insufficient:
   run files, notes, exclusions and review storage are cwd-relative.
3. The root source is used by live MCP processes; those processes can spawn `scripts/review_runs.py` afresh.
   Editing root runtime files can mix old and new generations. Keep implementation and tests in C.
4. Previously observed root MCP PIDs were `75343`, `98672`, `15994`, `35399`; browser-daemon PID was `386`.
   These are historical leads, **never signal authorization or current ownership proof**. Re-inventory live processes
   and verify kernel birth identity, UID, command and relevant paths before any lifecycle action.
5. C must not contain `.env` or use production writable state. Tests must deny real providers and unsolicited
   browser/reviewer launches. No paid API calls, live-site benchmarks, production migration or activation are authorized
   by this handover. Real final activation remains separate from implementation readiness.
6. Use one source implementer at a time. Other agents can independently inspect frozen checkpoints, review tests,
   or perform a premortem without overlapping source edits. Prior agent handles are not resumable assumptions;
   create fresh agents with explicit ownership and C/E paths.
7. Preserve existing user work. Before handover publication, root had only modified `docs/executor-improvements.md`
   and three untracked robustness documents. Exact copies are in `context/`; they were not overwritten or reverted.
8. Do not retry a browser mutation. Log execution before observing its result. A lost reply remains uncertain.
   Verify actual final outcomes independently; model `DONE` is not proof of success.
9. The user explicitly authorized this handover commit/push. Do not treat that as permission to publish unfinished
   implementation as working runtime code or to force-push/rewrite either branch.

The captured 63 production-baseline paths were hash-identical during the latest status audit; C had no `.env`.
The handover adds new documentation files. Recheck preserved paths before continuing; do not assume the old
process inventory or filesystem state is still current.

## Resume on the original machine

1. Inspect root branch, status, remotes, `E/isolation.json`, and `E/progress.json`. Do not switch the live root to a
   different source generation. Recheck every captured production hash and the candidate's `.env` absence.
2. Compare current C to this package's candidate manifest; it may have advanced after this snapshot.
   If it differs, inspect the changes before applying anything. Never overwrite a newer C with this package.
3. Use C for all edits/tests. Keep raw command results, acceptance assertions and revisioned source manifests in E.
4. Start at the review-pipeline checklist below. The ledger intentionally remains unaccepted until evidence is complete.

```sh
cd /Users/terry/projects/jev-ultrafast/artifacts/robustness-efficiency-implementation/20261003T100051Z/candidate
uv run ruff check .
uv run pytest -q tests/test_review_runs.py::test_apply_refuses_bad_replies tests/test_mcp_server.py::test_background_review_launch_arguments
```

These are diagnostic commands; their currently failing status is expected and must be resolved, not ignored.

## Recover on another machine / a fresh clone

Fork `main` at publication contains this handover, **not** the seven feature commits after `1231850a` and not an
activated implementation. The patch is based on **`60f03037a713dbce10f46da015fbffccc9132fa5`**, not on `main`.
Never apply it to the live root or directly to `main`.

From the fork checkout, fetch the feature branch if the base object is missing, then restore into a new ignored
directory inside this worktree. The restoration helper refuses an existing destination or a destination outside
`artifacts`, prevents parent Git discovery while applying the patch, and verifies every source hash and file mode.

```sh
git fetch origin executor-improvements-design
python3 docs/handover/2026-10-04/restore_candidate.py \
  --destination artifacts/robustness-efficiency-resume/2026-10-04/candidate
```

Use Python 3.12+ for the helper. It does not install dependencies or run application code. If restoration fails,
inspect the new directory; the helper deliberately leaves it for inspection and refuses reuse. Do not reuse or
delete a path belonging to another task.

For a portable continuation environment:

1. Copy `continuation/` contents into the **parent** of the restored `candidate`, not into its source tree. The helper
   scripts resolve their own directory as E and expect `E/candidate`; `check_required_results.py` additionally requires
   the adjacent `readiness-required-tests.json`.
2. Keep copied absolute-path records as historical evidence. **Do not execute `record_stage.py`, `export_candidate.py`
   or wheel helpers against the copied `isolation.json` without establishing new local isolation.** Set up new local
   source/baseline manifests and storage boundaries first. Do not retarget files to an unrelated existing production
   checkout or pretend a new baseline proves the old machine's runtime safety.
3. Preserve original task records separately if starting a new ledger. The original `required_tests.py` reads the plan
   under `E/baseline/docs/`; reconstruct that baseline intentionally from the base commit plus preserved context docs,
   or adapt the helper's input path transparently. Do not silently replace accepted checkpoint evidence.
4. `cd` into the restored C and install pinned dependencies with `uv sync --frozen` (use `--offline` when the cache
   permits). Keep `.env` absent; the pytest harness establishes isolated directories and denies real I/O.
5. Rerun relevant acceptance checks on the new source/harness before relying on historical pass counts. No old
   native lab manifest is portable or reusable.

## What has been accepted

| Subtasks | Status | Implemented boundary and evidence |
| --- | --- | --- |
| SETUP-1…3 | Accepted | Recoverable baseline; offline/native isolation; candidate separated from active writers. GATE-BASELINE passed. |
| POLICY-1…3 | Accepted | Explicit immutable `allowed_operations` through Agent, MCP, UI and examples; atomic validation; canonical indices before filtering; dispatch derives actual operation from observed action. GATE-POLICY: 274 focused tests. |
| SELECT-1…2 | Accepted | Exact observed option identity/index/state/document/cache; one atomic validate-and-select evaluation; one input/change pair; only tagged pre-input rejection is stale. GATE-SELECT: 333 offline tests and 30 native tests. |
| LIMITS-1…2 | Accepted | Shared Agent terminal state/deadline; stale budget; cooperative transport budget; late-response accounting; uncertainty preserved. GATE-LIMITS: 422 focused tests; 15 required named nodes / 45 variants. |
| PRIVACY-1 | Accepted prerequisite | Union overlapping task-value matches before exemptions; action-consumed fields validated and all persisted fields scrubbed; dynamic error slots sanitized before clipping. Independent review: 32 focused tests. |
| RUNS-1 | Accepted prerequisite | Stable metadata lock; execution save preserves disk labels; label append preserves execution fields; malformed state refuses replacement; durable publication and honest uncertainty. Independent review: 338 focused tests. |

These counts are separate checkpoint results, **not additive** and not a claim that the current WIP passes a full
suite. Accepted earlier source manifests do not certify subsequent changes to the same files.

Important retained contracts:

- Invalid new-goal policy leaves all old state intact. An empty allowed-operation list remains evidence-only.
- Multi-select controls supply evidence, not executable SELECT targets. A malformed/lost SELECT response is terminal
  uncertainty; no mutation retry wrapper is allowed.
- The shared limit is 90 monotonic seconds, starts at first tick/predict/act, and expires at `>=`. External callback
  time counts. Stale outcomes 1–119 may recover; tick stops on 120 before a recovery read. Progress does not refill it.
- Completed late decision/helper responses are accounted before discard. Unknown or partial usage stays explicit;
  known zero is distinct. No new gesture/helper starts after stop. A confirmed key press may receive its matching release once.
- Partial fill records intent and phase without completed-fill history. Lost transport, cancellation and failed saves
  must not erase an uncertain attempt. Direct callers cannot resume after failed started-input persistence.
- MCP final verification has an independent five-second, one-attempt budget; skips settling; preserves the original stop.
- Privacy regression: `Jane----------------Smith` and `Jane Smith Bo Lee` must redact the entire latter string even
  when `Jane Smith` is an exempt identity. `observed_url` from a discarded late decision contributes to exclusion checks.
- Run locks use the resolved parent `.metadata.lock`; callbacks that store lessons/review run after releasing it.
  Preserve complete ordered outcome history and lone-surrogate text via deterministic ASCII JSON escaping.

## Current review-pipeline implementation and immediate work

Ledger: `REVIEWS-1…5` are `in_progress`; `REVIEWS-6/7` and GATE-REVIEWS are `not_started`. **That is acceptance
state, not a source inventory:** dispatcher, process-identity, migration and sink-privacy code/tests already exist.
Do not rebuild those features merely because the ledger lags.

Primary files: `jev_ultrafast/{review_records,review_processes,store_io,run_store,site_notes,agent,mcp_server}.py`,
`scripts/{review_runs,report_runs,migrate_review_storage}.py`, and their tests. Read
[review storage notes](continuation/review-storage-implementation-notes.md),
[privacy notes](continuation/privacy-implementation-notes.md), and
[clarifications](continuation/implementation-clarifications.md) before editing.

Fresh handover verification, **2026-10-04 14:26 Asia/Taipei**:

- `uv run ruff check .`: exit 1, **28 findings**, largely line lengths/import placement plus an unused f-string prefix.
  Exact output: [ruff log](continuation/handover-status-ruff.log), [command record](continuation/handover-status-ruff.json).
- Focused review-refusal and MCP background-launch tests: exit 1, **1 failed, 6 passed**.
  Exact output: [test log](continuation/handover-status-tests.log), [command record](continuation/handover-status-tests.json).
- Failing case: `tests/test_review_runs.py::test_apply_refuses_bad_replies[a retirement citing no queued run on the note's site]`,
  assertion at captured line 443. Expected `cites no queued run on example.com`; actual `the note is not selected in this batch`.
  Reconcile the fixture/expected validation boundary without weakening the refusal. The unsafe reply is rejected.
- `test_background_review_launch_arguments` now passes. Do not carry forward its older failure as an open defect.
- Prior narrow checkpoints: 182 integration tests passed; 104 identity tests passed; strict checkpoint 1 failed / 126 passed.
  These are not full GATE-REVIEWS acceptance.

Concrete next checklist:

1. Fix lint and reconcile the failing refusal fixture/assertion. Use focused tests; do not loosen validation merely to pass.
2. Finish CLI reporting of **complete input membership separately from acknowledgments**, including ID/version evidence.
   Current internal maps exist; the audited `review_lines` output still omits this required distinction.
3. Independently verify nested record/attempt validation, embedded IDs versus filenames, selected-note scope for flag/retire,
   and deferred recovery restriction. Tests exist for several fixes; obtain a frozen source review and exact results.
4. Recheck dispatcher safety: same singleflight for auto/once/preflight; no short locks during model wait; live/unknown
   ownership blocks new dispatch; timers cannot signal a reused/reaped PID; no-work scheduling updates atomically.
5. Recheck automatic eligibility against the **full pre-cap queue**, not only selected batch items. Five eligible runs
   must not be delayed merely because fewer than five fit the byte cap. Deferred items remain unacknowledged.
6. Complete digest publication/crash tests: directory-fsync uncertainty, conflicting/malformed existing digest,
   receipt retention, same-reply replay before freshness, different-reply conflict, settlement idempotence.
7. Finish real-pipeline privacy/migration proofs through actual output sinks (batch, receipt, digest, attempt, state,
   CLI/errors/reports), not only dummy sanitization sinks. Keep all named plan tests and assertions.
8. Freeze revisioned checks/source manifests, get independent execution/storage and reporting/privacy review, resolve
   all blockers/should-fix findings, then update all seven review subtasks and GATE-REVIEWS with evidence.

Do not blindly reimplement historical fixes:

- `review_processes.py` now uses Darwin kernel birth microseconds and Linux `/proc` start ticks; the older
  `ps lstart` second-resolution concern prompted this change. Final integrated acceptance is still required.
- `store_lesson` now distinguishes uncertain publication and warns that a note may already be stored. The earlier
  misleading `Note not stored` wording is fixed in draft, awaiting final gate acceptance.
- Reporting tests cover null-digest cost fallback, duplicate attempt-cost deduplication, malformed legacy decisions,
  and non-finite cost. Verify them; do not count known linked cost twice or turn unknown cost into zero.
- Shared `review_records.Inventory` already indexes chain/successor relations to avoid repeated whole-graph scans.

Review contracts that must survive fixes:

- Batch/attempt schema 1; notes/digest schema 2. Strict fields include `sent_sha256`, `reply_sha256`, `finished_at`,
  semantic versions, complete `input_items`, and separate `acknowledged` maps. Unknown/corrupt records fail closed.
- Only explicit `(ID, version)` acknowledgment suppresses work. Legacy IDs requeue once; do not invent old versions.
- Freeze the complete pre-cap privacy closure, including excluded/deferred contributors, missing parents and successor
  relations. New unrelated runs do not invalidate a batch. Exempt identities derive only from selected output evidence.
- Caps: 25 runs, 5 notes, 65,536 UTF-8 bytes. Use fixed per-item nonces and rerender trial selections because new
  exemptions can lengthen prior blocks. Defer whole items; oversized items must not block smaller later items.
- Notes plus receipt replacement is the commit point. Recover receipts and check same-reply replay **before** freshness.
  Infrastructure failure never becomes semantic acknowledgment or permission to repeat decisions.
- Lock order: dispatch → review → metadata → notes. Paid auto/once/preflight retain only dispatch lock during model wait.
- Preserve automatic cutoff/cadence, $0.50 review cap, 15-minute timeout, three-failure disable rule; preflight has $0.05
  cap and no automatic cadence, failure-streak or acknowledgment effect. `superseded` uses its slot/cost but neither
  increments nor clears the streak. Counter effects and `accounted_attempt_ids` must publish together.
- Unknown child ownership blocks dispatch; never signal by PID alone. Abandoned uncertain dispatch consumes its
  original slot once; it is not an exactly-once billing guarantee and must not be automatically relaunched as that attempt.
- Reports are read-only, chronological, and count cost once per attempt. Eligible notes sort by creation date and
  stable ID before the five-note cap; verify this instead of relying on file order.

## Remaining stages after GATE-REVIEWS

### SNAPSHOT-1/2 and GATE-SNAPSHOT

Preparation: [snapshot-preparation.json](continuation/snapshot-preparation.json). The preserved SELECT implementation
is [snapshot-select-baseline.js](continuation/snapshot-select-baseline.js); maintain its accepted guarantees.

- Implement schema-2 compact protocol tokens with exact browser-held freshness. `fresh()` must never replace the baseline.
- Keep progress distinct from protocol identity: retain geometry, scroll height and multi-select evidence, exclude
  nested protocol metadata. Reset/navigation/observe invalidate old tokens.
- Apply guard caps before construction; scope memoization correctly; hold strong references only to offered controls/options.
- Limit transport to 262,144 bytes or propagate terminal overflow through every adapter. Legacy snapshots may report,
  but cannot execute. Normal dense 250/1,000/5,000-control fixtures must fit; oversized labels are a separate case.
- Run exact plan tests, native freshness/SELECT parity and payload measurements. No general speed claim follows from fixtures.

### READINESS-1…3 and GATE-READINESS

Read [readiness-test-map.md](continuation/readiness-test-map.md),
[readiness-required-tests.json](continuation/readiness-required-tests.json) (45 inherited/composition nodes),
[executor design](context/executor-improvements.md), and
[historical executable readiness tests](context/readiness-design-v41.diff).
The diff is reference source, **not** a patch to apply wholesale or proof that old behavior is current.

- Use an owned private CDP connection/session/event queue. **Never call the global destructive Browser Harness event drain.**
- Installed pins already support the adapter: `browser-harness==0.1.13`, `cdp-use==1.4.5`, `websockets==15.0.1`.
  No dependency upgrade is required. `get_ws_url()` does not spawn, but configure isolated environment before imports;
  bound discovery and setup; verify the exact target; never log a credential-bearing endpoint.
- Preserve request seen-time, frame/type/session scope, loss diagnostics, consumer-thread joins, five-second input age,
  and no minimum wait. Quiet is not inferred from a dead/disconnected receiver.
- Retry only approved post-step read timeouts, after execution is logged/saved. Never wrap input dispatch, helper calls,
  freshness, recovery reads or independent final verification in that retry loop. Do not reset loading age on reread.
- Valid continuation resets loading; invalid policy preserves it. Deadline/cancellation beats a late DONE even if the
  page has loaded. Preserve completed-call usage. Verify existing two-unchanged-WAIT handoff composition.
- The real OOPIF fixture requires a second exact owned local fixture origin. Add it only for this stage and rerun egress
  denial proofs. First prove a separate iframe target/session exists; a blocked iframe is not OOPIF coverage.

### RELEASE-1…3 and GATE-RELEASE

- Reconcile README, public APIs/examples, integration/failure-review/executor docs and old plan statuses. Preserve user
  edits. Avoid false hard-timeout, exactly-once billing, general performance or DONE-success claims.
- Freeze one source manifest and run Ruff, full offline pytest, both JS syntax checks, build, and relevant full native suite.
  Required cases must execute with no skip/xfail; validate every parameter variant, not just function names.
- Inspect wheel assets and import public APIs in an isolated offline wheel environment. This has **not** run on a final wheel.
- Obtain independent implementation review and a separate premortem against exact hashes and fault-injection evidence.
- Rehearse writer detection/quiescence, backup checksums, migration, pending-receipt recovery and compatible rollback/export
  in disposable state. Preserve new notes/outcomes/ack history; never restore stale backups over newer user work.
- `scripts/migrate_review_storage.py` exists in draft. Finalize/verify it with the rehearsal. The draft activation runbook
  is included; it is not a record of a completed rehearsal. No live activation has occurred.
- Export the final validated patch only after GATE-RELEASE. Deliver exact evidence and explicitly unrun live-site checks.

## Validation commands and helper pitfalls

Normal application checks run **from C**:

```sh
uv run ruff check .
uv run pytest
node --check jev_ultrafast/static/app.js
node --check jev_ultrafast/snapshot.js
uv build
```

Native lab commands, only after checking current harness isolation; always create a fresh manifest:

```sh
uv run python scripts/validation_lab.py prepare --output artifacts/new-lab.json --fixtures tests/fixtures
uv run pytest -q -m native --lab-manifest artifacts/new-lab.json
uv run python scripts/validation_lab.py close --manifest artifacts/new-lab.json
```

Close in cleanup even on test failure. Verify owned-process exit; never reuse a closed manifest or globally kill Chrome.
Prior SELECT lab processes were confirmed absent. Proxy-death and WebRTC UDP native probes remain explicitly unrun;
hostile raw CDP outside the bounded harness is outside the established proof.

Release helper review is captured in `continuation/release-helper-verification-v3.json`; its SHA-256 was
`0c23183356963b79ba5ed780754a147e4fcc8ebc81901e46c3b5d119aba5451d`.
Helpers are not evidence that release itself passed:

- `record_stage.py`: refuses production drift and candidate `.env`; records new root files and five source trees;
  writes new manifest files exclusively. Use a new revision name after changes; never overwrite accepted evidence.
- `pytest_evidence.py`: requires full `tests` collection (no `-k`, node/file narrowing, ignore or last-failed selection).
  Allows normal offline or `-m native`; captures variants before deselection, results, collection errors and source drift.
- `check_required_results.py`: combines plan requirements and inherited readiness nodes; rejects missing variants,
  failures, xfail, differing source manifests, source drift and missing JUnit evidence.
- `wheel_smoke.py`: verifies shipped source/assets against C, creates a fresh offline environment, installs runtime I/O
  denial before public imports, and checks import origins and required `allowed_operations` signatures.
- `export_candidate.py`: final-release helper, requires an existing immutable stage manifest and original baseline files;
  checks root/candidate hashes, reconstructs a binary patch in disposable storage, never activates root.

For final pytest runs, load the plugin by making E importable, use `-o xfail_strict=true`, `--junitxml`,
`--validation-source E/<fixed-stage>-hashes.json`, and a new `--validation-evidence E/<mode>-execution.json`.
Use the same fixed source manifest for offline and native runs. Keep output files outside C's source inventory.
Reconcile absolute paths and plugin loading with the actual environment before executing; this is not a ready-made
release command against an unaccepted candidate.

## Evidence inventory and limitations

Included continuation files preserve policy/SELECT/LIMITS/privacy/run checks, source manifests, independent reviews,
selected raw pass logs, current failing-check logs, task ledger, preparation notes and release helpers. The original E
also contains more detailed frozen directories, harness logs, baseline source, temporary investigations and diagnostics.
Do not claim those omitted files are present in a fresh clone or that the current portable tree matches old stage hashes.

Accepted manifest identifiers useful for matching the original evidence:

- LIMITS source acceptance: `2480807e6fc9f3d15e4667a58d147d6e0f2a4327539a576c5ba2c07c07cec069`.
- PRIVACY source acceptance: `c2ea980ac70d2c5e426d75e4ce26977d04b909a5f80292acb30f52d8e0b38f71`.
- RUNS source acceptance: `01307d41c991ec7401f71f23dd549511dde724b0d29042612230822fc7015c5b`.

`candidate-manifest.json` identifies this **latest unaccepted WIP**, including 47 changed paths relative to its base
and the explicitly retained base template described above.
`package-manifest.json` checksums the handover files. `reconstruction-verification.json` records recovery verification;
that verifies portability, not runtime correctness. Do not reuse the WIP patch as the final release export.

## Suggested next-agent workflow

1. Read this note, the current plan and implementation clarifications; verify checkout/candidate/process isolation.
2. Assign one implementation owner to REVIEWS and independent reviewers to execution/storage and reporting/privacy.
3. Fix known current issues and run the exact required tests, then freeze and review. Close GATE-REVIEWS only on evidence.
4. Transfer sole source ownership to the snapshot implementer. Repeat independent review and native measurement.
5. Implement readiness with its inherited test map and owned event source; verify composition and native isolation.
6. Complete all release tasks, review/premortem, wheel checks and disposable operational rehearsal.
7. Report what passed, exact artifact locations, remaining limitations, and whether activation happened. A saved plan,
   handover, candidate patch or successful documentation push is not completed implementation.
