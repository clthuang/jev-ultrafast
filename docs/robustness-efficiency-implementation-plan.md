# Implementation plan: robustness and efficiency

Status: implementation candidate prepared against merged baseline `a94014bff419b939dd0f388e80c7a75d07eb41f9`. Current acceptance is recorded in `artifacts/robustness-efficiency-completion/20261004/progress.json`; the original planning decisions remain below.

Source: [reviewed design, revision 3](robustness-efficiency-proposal.md) and its
[review/validation/premortem](robustness-efficiency-review.md).
Baseline: `60f03037a713dbce10f46da015fbffccc9132fa5`, `executor-improvements-design`.
This document plans implementation; it does not implement fixes, activate migrations, or authorize a commit/push.

## 1. Objective and definition of done

Deliver the following observable behaviors while preserving one natural-language goal, one TypeSafe request per
decision, observed targets only, no mutation retries, and independent outcome verification:

| Objective | Observable completion |
| --- | --- |
| Enforce operation permissions | Every forbidden observed action produces zero input and zero text-helper calls, even with forged decision metadata |
| Select the intended option | Native fixtures select the exact observed option identity; changed options reject before input; uncertain input is never repeated |
| Bound stalled execution | Library, MCP and direct commands share limits; stale outcomes 1–119 may recover and outcome 120 stops before a recovery read |
| Preserve corrections and review evidence | Save–label–save retains labels; only exact versions actually reviewed are acknowledged; crash replay creates no duplicate notes |
| Preserve privacy under bounded reviews | Deferred/excluded contributors still redact synthetic canaries from every persisted/output surface |
| Reduce snapshot transfer | At most 250 target guards; transport at most 262,144 UTF-8 bytes excluding screenshots or explicit terminal overflow; freshness/progress semantics preserved |
| Integrate page readiness | Post-step timeout rereads, the network loading gate and two-WAIT handoff compose without repeating input or restarting loading allowances |

The original planning checkpoint started every task and gate **Not started**. Use the dated execution ledger for current acceptance. A task becomes Done only after its stated assertions
pass and evidence is saved. Gate completion is separate from task completion. Missing fixtures, skipped required
cases, an absent proposed test, or zero tests collected never count as a pass.

Code completion means GATE-RELEASE passes. Deployment/activation and paid benchmarking have separate conditions in
§8. A green offline suite alone does not establish native-browser correctness or real-site speed.

## 2. Fixed boundary contracts

These contracts bind producers and consumers. Keep the design's behavior; resolve a conflicting implementation by
changing the implementation or explicitly revising this plan and its tests, never by silently weakening a gate.

### Caller → Agent: goal and permission lifecycle

**Input:** nonempty goal plus required `allowed_operations: list[str]`; optional existing URL/site/commit controls.
Valid entries: `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`. Reject omission, null, duplicates,
unknown values, non-list input and non-string members. `DONE`/`BLOCKED` are implicit terminal choices, not entries.

**Output:** accepted goal state with an immutable normalized operation set and sorted trace representation, or a
validation error before page reads, tab closure/opening, model calls, or any prior-goal mutation. An invalid
continuation preserves browser, policy, pending decision/text, trace path, counters and loading state.
`[]` allows observation/terminal answers; `["WAIT"]` adds the existing wait behavior. Explicit URL navigation remains
separately authorized setup. Every continuation respecifies policy; `allow_commit` cannot broaden it.

**Limit:** code enforces supplied permissions, not arbitrary English or site-script behavior. Widening permissions
requires a separately authorized new goal; no automatic widening after a refusal.

### Observation → model/inspector: evidence and identity

**Input:** complete capped observed action table and control evidence, before permission filtering.
**Output:** one canonical element/option index mapping shared by model questions, inspector/overlays, traces and
execution. Preserve observed field values/options/state under `[]`. Filter only eligible operation/target/commit
heads without renumbering. Use the original full observation for progress/freshness, not the filtered view.

**Three distinct concepts:** progress fingerprint uses the baseline `browser.fingerprint()` projection, including
action geometry and scroll height; exact browser-resident evidence governs freshness; the observation token
identifies the latest baseline. Exclude all new protocol metadata, including nested tokens/guard references, from
the progress projection. A new observation of the same page must not restart the WAIT counter.

### Model decision → browser: permission, freshness and mutation

Resolve the selected target through the canonical observed mapping. Derive the actual operation from the observed
action kind/control ID; reject disagreement with model metadata. Check policy before helper calls/attempt creation
and again immediately before input. Check site/commit boundaries independently. Log intent before dispatch, execution
before post-input observation. Preserve uncertain attempts rather than treating them as unexecuted.

For SELECT, code owns `{select_id, option_id, observed_index, label, value, selected, effective_disabled}` plus its
document/token context. Validate identity/ownership/index/meaning, select/fieldset/optgroup enabled state, visibility,
guard and hit test in the SAME synchronous evaluation as `selectedIndex` assignment and one input/change pair.
Native multi-select is evidence only, with no SELECT or substitute CLICK.

The evaluation returns either `executed` or an explicit `rejected_before_input` result. Only the latter is retryable
as stale. Timeout, exception, malformed/missing result or lost response after dispatch is uncertain and terminal.
No retry wrapper may encompass the assignment/event dispatch.

### Agent → adapters: limits and terminal state

Use a monotonic 90-second execution deadline starting at the first tick/predict/act; expire when `now >= deadline`.
Setup and one best-effort final verification read are separately bounded/reported. Deadline checks precede work and
follow blocking work. HTTP phase timeouts use `min(normal_timeout, positive_remaining_budget)` before each attempt;
this remains cooperative, not a hard total-response deadline.

Pass the shared stop check into `Browser.act` and `browser_operation`. Check again after blocking freshness and
hit-test reads, before a mouse press, scroll, atomic SELECT evaluation, select-all key press, or text insertion.
No new gesture/text mutation starts after expiry or cancellation. One confirmed mouse/key press may receive its
matching release once with the normal bounded transport timeout, then stop; no fresh press or text follows it.
An ambiguous press response remains uncertain and terminal. A partly completed fill retains its attempt/phase and
never becomes a completed fill history entry. A SELECT evaluation already dispatched is in flight and obeys the
cooperative limit; never split or retry its synchronous validation, assignment and event pair.

Record a completed model/helper response's request count, latency and known usage before the post-response guard
discards an expired result. Mark it discarded due to the deadline, with no executable pending decision/text. Failed
or missing response usage stays unknown, not invented as zero. Preserve existing decision/text-call accounting.

`tick` alone increments cumulative stale outcomes once when electing outer recovery. Outcomes 1–119 permit one
outer recovery read; outcome 120 stops before that read. Nested commands and the recovery read do not increment
again. Direct predict/act propagate stale errors, but their entry and later retries always share deadline/terminal
checks. Preserve the separate three-stale, action/model, two-WAIT and post-step timeout reread counters.

Use a structured execution stop (`RunStopped`, compatible with existing ValueError handling) and persisted
`stop_code`. Invalid API arguments are validation errors before a run, not fabricated run results.

| Stop code | State/result | Adapter behavior |
| --- | --- | --- |
| `operation_not_allowed` | `stopped` | Explain the denied operation; never widen policy or call helper/input |
| `execution_deadline` | `stopped` | No new work/gesture; only the paired release above may finish; late DONE cannot override it |
| `stale_recovery_limit` | `stopped` | Preserve stale reason/count; no next recovery read |
| `snapshot_too_large` | `stopped` | No stale fallback; old page diagnostic only, marked not fresh |
| `snapshot_protocol_error` | `stopped` | Malformed newly returned observations fail before model/input; old page is diagnostic and no final-read fallback runs |
| `readiness_connection_error` | `stopped` | During commands or valid continuation, observer failure clears pending decisions; preserve the original error |

Keep cancellation/shutdown and uncertain-input paths distinguishable; preserve original exceptions where the MCP
transport requires propagation. Terminal states are `done`, `blocked`, `stopped`; direct commands cannot resume any
of them. Clear pending decision/text at a stop, retain history/uncertain attempt, and best-effort save without hiding
the original error. These new stop codes are execution diagnostics, not automatic new site-note failure categories:
existing `failure_code(status, notes, history)` behavior and old files remain compatible.

### Browser → Agent: snapshot schema 2

Implementation hardening: malformed or unsupported newly returned observations raise `InvalidSnapshot` and stop with `snapshot_protocol_error` before model/input. Stored legacy snapshots remain reportable, never executable.

`observe()` returns a complete schema-2 observation or raises `SnapshotTooLarge`. `fresh()` compares against the
specified stored baseline and returns a boolean; it never installs a baseline. Overflow propagates distinctly
through both APIs. A missing/replaced cache, old token, or wrong document fails closed.

Cap executable target actions before guard construction, memoize shared scope text, retain strong reverse references
only for offered targets/options, and preserve global semantic enumeration including omitted/offscreen controls.
Serialization above 262,144 UTF-8 bytes excluding screenshot returns no executable state. Do not truncate meaningful
labels/values. Transport/guard work is bounded; arbitrary-DOM traversal time is not.

### Run publishers → storage: field ownership

For any `trace_path`, resolve the parent directory once and use its stable `.metadata.lock`; managed MCP runs use
`artifacts/runs/.metadata.lock`. Publishers of the same directory must share that lock. Under it, load the current
file, validate it and publish with a unique same-directory temporary plus replacement.

Agent owns execution fields, but MUST preserve the complete persisted `outcome` array. `report_outcome` appends labels
and preserves executor fields. Missing file or legacy absent outcome means `[]`; malformed JSON/object/outcome stops
publication without replacement. Release this lock before storing a lesson or triggering review. App-managed
exclusion changes participate in the managed metadata lock; external direct edits are outside transactional guarantees.

### Queue → batch: immutable input and versioning

Batch schema 1 requires `batch_id`, timestamps, `schema_version`, diagnostic `source_revision`, `summary_version`,
`fingerprint_version`, `scrubber_version`, item IDs/versions/reasons, chain/successor/privacy dependencies,
`exclusions_version`, exact `sent_text` and `sent_sha256`. Publish once as `batches/<batch_id>.json`; printing and
dispatch read saved bytes. Unknown semantic versions or corruption reject before mutation.

Fingerprints use the design's canonical semantic projections and complete outcome history. Explicit absent-successor
dependencies distinguish newly linked runs from unrelated arrivals. Eligibility chains exclude private attempts;
privacy closure retains them locally. Freeze the COMPLETE pre-cap eligible queue's privacy contributors, including
deferred items, and use them on every summary/reply/refusal/error surface. Persist contributor IDs/hashes, never raw
values. Apply reconstructs only verified recorded contributors. Changed contributors supersede the batch.

Choose oldest whole items under 25 runs, 5 notes, and 65,536 UTF-8 input bytes. Oversized items defer visibly without
starving smaller items. Only explicit `(ID, version)` acknowledgments suppress work; old unversioned IDs do not.

### Apply → notes/digest: one commit point

Notes envelope schema 2 is `{schema_version: 2, notes: [...], pending_review: null | receipt}`. Public notes reads still
return lists. Every ordinary writer preserves pending receipts. One lock-owning transaction API invokes pure helpers
on a private envelope; callbacks must not call lock-owning load/update/add helpers.

Acquire short locks in order: review → metadata → notes. Drain pending receipt, then check committed replay BEFORE
freshness. Same batch/reply returns its existing result; different reply conflicts. Verify dependencies and current
permissions/exclusions, compute decisions sequentially, retain valid decisions beside semantic refusals, then publish
notes plus sanitized receipt with ONE flush/fsync/replace/directory-fsync operation. The replacement is the commit
point. Infrastructure failure before it acknowledges nothing; failure after/around it requires receipt recovery.

Receipt contains batch/reply hashes, complete sanitized digest material and exact acknowledgments. Materialize the
immutable committed digest `<batch_id>.json`, make it durable, then clear receipt. Digest schema 2 contains all design
fields plus optional paid `attempt_id`. Input membership is separate from acknowledgment maps. Replays never repeat
note changes. Old list readers/writers cannot run after envelope activation.

### Review runner → scheduling/reporting: attempts are not commits

Two plan-level clarifications are required to implement the reviewed short-lock design safely:

1. A separate `dispatch.lock` provides singleflight for BOTH paid `auto` and `once`. Acquire it nonblockingly before
   short review/metadata/notes locks. Persist dispatch claim/daily slot before launching the child; release all short
   locks while waiting, retaining only dispatch lock. Manual queue/apply never waits on a model. Global order, where
   applicable: dispatch → review → metadata → notes; never acquire dispatch while holding another lock.
2. Running/failed/superseded/uncertain attempts live in `attempts/<attempt_id>.json`; they never occupy the canonical
   committed digest path and never acknowledge items. Required fields: schema version, IDs, kind/status,
   start/deadline/finish timestamps, optional cost and sanitized error. A committed digest links its paid attempt
   for exactly-once accounting of reported cost, not a promise of exactly-once provider billing.

Repair receipts before paid launch. A claim remains running until verified completion or its recorded deadline.
An abandoned/expired claim settles once to `dispatch_uncertain`, retains its consumed slot and any known cost,
and never redispatches that attempt. Record owned child process-group identity with the claim; on expiry verify
identity before bounded termination and exit verification; reap only when it is this process's child. Unresolved
child ownership or liveness blocks any new paid dispatch;
do not kill unrelated processes. Read-only reporting can show an expired claim as uncertain without writing state.
After settlement and verified child exit, a fresh batch may run at the existing automatic next-due time, subject
to the current cap/disable rules. Manual `once` timing remains explicit and shares the same singleflight checks.

`superseded` consumes its original daily slot/cost but does not increment or clear the failure streak. Abandoned
execution counts once under the existing infrastructure-failure rule unless a committed receipt establishes success.
Receipt recovery, attempt settlement, cost and failure counting are idempotent. Preserve the current automatic
cutoff/daily cadence, $0.50 **per-review** budget cap, 15-minute reviewer timeout and three-failure disable rule.

## 3. Work ownership, dependencies and evidence

Use one active implementer in the implementation checkout verified by SETUP-3 for these sequential stages.
Agents may independently review fixed
candidates or develop isolated test ideas, but must not concurrently edit overlapping Agent/browser/snapshot/store
files. Each task lists its file boundary; unrelated refactors and historical experiment edits are excluded.

Order: GATE-BASELINE → GATE-POLICY → GATE-SELECT → GATE-LIMITS → GATE-REVIEWS → GATE-SNAPSHOT → GATE-READINESS → GATE-RELEASE.

For every task, record in ignored `artifacts/robustness-efficiency-implementation/<run_id>/progress.json`:
task ID/status, baseline and candidate file hashes, changed paths, assertions, exact command/exit status, raw output
path, reviewer verdict, and remaining gaps. Store native fixture reports and immutable experiment results alongside
it. Never store credentials or copy `.env`. Preserve all three pre-existing design documents and user diffs.

**Verification convention:** test names below are proposed implementation targets, not existing/passing tests.
For each listed node, run `uv run pytest -q <file>::<test_name>`; parameterized variants must all pass with no skipped
or xfailed required case. Bare test names use the file named in that task's Verify line; `::test_name` uses the
immediately preceding fully qualified file. Every native node is fully qualified. Missing nodes fail the task.
Gates add the named existing suites and review requirements.
No fixed total count is assumed: compare coverage/assertions, not “baseline plus N.” A task's focused checks may pass
before every caller is migrated; only a green stage gate is an integration checkpoint.

## 4. Runtime implementation tasks

### SETUP-1 — Record a recoverable baseline
Depends: none.

- Files: evidence directory only. Record worktree/branch/SHA, status, patches, and hashes/copies of files that this
  plan will change. Capture the untracked proposal/review as well as tracked user edits. Refuse to overwrite evidence.
- Verify: `git status --short`, `git rev-parse HEAD`; `uv run ruff check .`; `uv run pytest`;
  `node --check jev_ultrafast/static/app.js`; `node --check jev_ultrafast/snapshot.js`; `uv build`.
- Pass: raw results recorded, existing baseline failures explicitly resolved or documented as a blocking prerequisite,
  and original user files hash-identical after capture. No API/browser activity.

### SETUP-2 — Establish isolated test harnesses
Depends: SETUP-1.

- Files: new focused tests/helpers, local HTML fixtures, `pyproject.toml` test configuration, existing
  `scripts/check_guards.py` and a narrowly scoped `scripts/validation_lab.py` lifecycle helper.
- Offline tests fail on attempted live HTTP/model/CDP access. Both modes deny provider HTTP and paid review launch;
  native mode permits only manifest-owned CDP and local fixture endpoints, with disposable run/note/review storage.
  Fake clocks and scripted decisions exercise real Agent
  guards; do not use a FakeAgent.command override that bypasses the behavior under test.
- Add `native` pytest marker and default deselection, so plain `uv run pytest` remains offline. Native tests require
  `--lab-manifest`; no default connection to the owner's Chrome. Share assertions with check_guards rather than
  maintaining two divergent suites. The manifest records owned process identities, temporary profile, daemon name,
  debugging endpoint and fixture origin. Preparation verifies endpoint ownership before any browser action.
- Verify: `tests/test_validation_harness.py::test_offline_mode_denies_network_and_browser`,
  `::test_native_runner_refuses_missing_or_foreign_manifest`, `::test_cleanup_targets_only_recorded_owned_processes`,
  `::test_native_mode_still_denies_model_and_review_dispatch`.
- Pass: injected wrong port/profile/PID identity causes zero browser action/cleanup; fake Agent path still calls real
  guards. Stop only recorded lab processes; no process-name kill patterns or user-profile changes.

### SETUP-3 — Isolate implementation from active writers
Depends: SETUP-2.

- Files: evidence and isolated checkout/launch configuration only. Before editing runtime source, inventory active
  MCP/demo/reviewer launch paths, imports, working directories and storage roots. An existing MCP server can launch
  `scripts/review_runs.py` afresh, so keeping a server on old imported modules is insufficient isolation.
- Use a separate implementation checkout containing the recorded baseline plus preserved user changes, its own
  dependency environment and disposable state. Keep production launch/import paths pointing at the unchanged
  baseline. Record resolved paths and hashes; no shared source symlinks, editable installs or production state paths.
  The current checkout may serve as implementation checkout only if the inventory proves it is unreachable from
  every active/scheduled runtime trigger. Recheck before each stage; uncertainty blocks source edits.
- Verify: `tests/test_validation_harness.py::test_production_trigger_cannot_reach_candidate_writers_or_state` uses
  the recorded launch/path mapping with a fake child. Inject a candidate writer that would publish an envelope;
  simulated production dispatch must resolve baseline code and leave production fixture storage hash-identical.
- Pass: candidate tests/subprocesses resolve candidate source/disposable state; production dispatch resolves
  baseline source/state; neither loads the other's writer. No production services or state change for setup.

### GATE-BASELINE
Depends: SETUP-3.

Baseline evidence exists, harness safeguards and runtime isolation pass, and required native dependencies are identified. A missing
browser can defer execution of later native gates, never mark those gates complete. No production files migrated.

### POLICY-1 — Validate policy atomically at every goal entry
Depends: GATE-BASELINE.

- Files: agent, MCP, demo and their tests. Implement required keyword/tool field and immutable stored policy.
- Verify in `tests/test_execution_contracts.py`: `test_policy_rejects_before_setup` (all invalid shapes),
  `test_invalid_continuation_preserves_entire_old_goal`, `test_every_new_goal_requires_explicit_policy`.
- Pass: zero observation/tab/model calls for invalid input; old pending cache, trace path and loading state unchanged.

### POLICY-2 — Share canonical evidence and filter only eligibility
Depends: POLICY-1.

- Files: model.action_space/choose, Agent.snapshot, inspector/overlays and tests. Allocate canonical indices once;
  retain read-only evidence; construct only permitted target/commit heads without adding model round trips.
- Verify in `tests/test_execution_contracts.py`: `test_policy_preserves_canonical_element_indices`,
  `test_empty_policy_retains_field_values_and_options`, `test_only_allowed_target_heads_are_requested`.
- Pass: button [1]/textbox [2] remains that mapping under TYPE_TEXT-only; [] offers DONE/BLOCKED with field evidence;
  [WAIT] additionally offers WAIT; mock captures exactly one decision request.

### POLICY-3 — Enforce actual action and migrate all callers
Depends: POLICY-2.

- Files: Agent.act, MCP instructions/schema, demo UI, examples/run.py, examples/flights.py,
  scripts/smoke.py, scripts/measure_flights.py, scripts/record_flights.py and all affected test fixtures.
  Inspect prompt-driven scripts/phase10 callers too; update explicit policy examples without changing benchmark goals.
- Verify in `tests/test_execution_contracts.py`: `test_forbidden_action_executes_nothing`,
  `test_mislabeled_action_cannot_bypass_policy`, `test_allow_commit_does_not_broaden_operations`,
  `test_callers_supply_policy_and_share_target_mapping`.
- Pass: forbidden fill produces no helper/attempt/input; mislabeled click is stopped; caller inventory has no implicit
  permissive fallback; UI selected index resolves the same actual node. Trace policy and diagnostic stop_code persist.

### GATE-POLICY
Depends: POLICY-3.

Run execution-contract tests plus existing test_agent.py/test_mcp_server.py; Ruff and app.js syntax check. Reviewer
traces one restricted goal from public entry through model and browser boundary and verifies no index renumbering.

### SELECT-1 — Observe stable option descriptors
Depends: GATE-POLICY.

- Files: snapshot.js, model mapping and new `tests/test_browser_contracts.py`/fixtures.
- Verify: `test_select_descriptor_tracks_identity_and_effective_state`, `test_multiple_select_is_evidence_only`.
- Pass: record actual tree index separately from model option index; distinct duplicate-value options remain distinct;
  all selected multi-select values remain visible as evidence, but no SELECT/substitute CLICK is offered.

### SELECT-2 — Validate and mutate once in one evaluation
Depends: SELECT-1.

- Files: browser.py, Agent error/attempt integration and native fixtures. Implement tagged pre-input rejection versus
  executed result. Treat response loss/malformed responses/dispatch exceptions as uncertain, preserving attempt.
- Verify: `tests/test_browser_contracts.py::test_select_rejects_changed_observed_option` (swapped values, label,
  replacement, removal, reorder, owner, selected state, optgroup/fieldset disabled, navigation),
  `::test_select_uncertainty_never_retries` and `tests/test_browser_native.py::test_select_targets_exact_option`,
  `tests/test_browser_native.py::test_select_emits_one_event_pair`, `tests/test_browser_native.py::test_lost_reply_after_select_preserves_single_execution`.
- Pass: changed descriptor gives zero events; second duplicate is selected by exact identity; disabled alias is not;
  lost reply leaves exactly one input/change pair and no second dispatch.

### GATE-SELECT
Depends: SELECT-2.

Offline browser/Agent suites pass, snapshot.js syntax passes, and the three native SELECT tests pass in the isolated
lab. Record exact selected identities and event counts. Native command convention is defined in §7. If unavailable,
gate stays incomplete; do not substitute a mocked value-setter assertion.

### LIMITS-1 — Put terminal state and budgets in Agent
Depends: GATE-SELECT.

- Files: agent.py, MCP/demo adapters and tests. Implement shared guard, monotonic deadline, exact stale count, typed
  stop codes and stopped-state UI behavior. Remove duplicate MCP deadline ownership while preserving cancellation.
- Verify in `tests/test_execution_contracts.py`: `test_terminal_state_precedes_all_work`,
  `test_stale_outcomes_119_and_120`, `test_nested_commands_count_one_recovery`,
  `test_changing_pages_do_not_replenish_budget`, `test_direct_commands_share_deadline`,
  `test_stopped_ui_and_mcp_use_the_same_state`.
- Pass: no model/read/input after terminal state; no recovery read on outcome 120; standalone generator and direct
  calls bound the original infinite-recovery case; new valid goal resets counters exactly once.

### LIMITS-2 — Propagate remaining budget through blocking work
Depends: LIMITS-1.

- Files: model.post_json/choose/field_text, Agent hooks, browser.py dispatch/preflight, MCP finish and tests. Check
  before/after requests, observation retries, helper work and browser preflight; retain retryable HTTP statuses and
  cap phase timeouts. Apply the shared browser guard and paired-release contract in §2. Preserve late-response usage.
- Verify in `tests/test_execution_contracts.py`: `test_expiry_during_helper_prevents_input`,
  `test_expiry_between_http_attempts_prevents_retry`, `test_late_done_cannot_override_stop`,
  `test_wall_clock_jump_does_not_change_deadline`, `test_final_read_cannot_resume_or_hide_stop`,
  `test_post_input_failure_preserves_one_execution`, `test_expiry_during_browser_preflight_prevents_input`
  (freshness and hit-test reads; deadline and cancellation), `test_partial_fill_releases_pair_once_then_stops`
  (after confirmed mouse press and select-all key press; ambiguous response),
  `test_late_successful_model_response_is_counted_but_not_executed` (decision and text-helper variants).
- Pass: `now == deadline` stops; final verification has separate duration and no new retries; recorded completed or
  uncertain input is never replayed; no new gesture/text after expiry; confirmed release occurs once; no false
  completed fill. Late successful calls remain counted; original cancellation/error survives a failed save.

### GATE-LIMITS
Depends: LIMITS-2.

Run all execution-contract and existing Agent/MCP/site-note tests. Reviewer checks direct predict/act/run plus
inspector paths, verifies exact counter meaning, and confirms new diagnostic codes do not silently change learned
failure categories. No new re-ask timer or mutation retry exists.

## 5. Review and storage implementation tasks

Finding IDs F1–F11 refer to the reviewed follow-ups in
[the earlier implementation plan](executor-improvements-plan.md). They provide traceability; the concrete behavior,
file boundary and verification for each task are specified below.

### PRIVACY-1 — Complete accepted sanitization prerequisites
Depends: GATE-LIMITS.

- Files: scripts/review_runs.py, relevant site_notes pure helpers and tests. Implement F1/F6/F7/F8 per the existing
  executor-improvements-plan tasks 3.1/3.2/3.5/3.6: validate used fields, scrub every stored field; preserve fixed code
  wording; scrub model-derived error quotes; redact unions of overlapping matches with retained identity exemptions.
- Verify: retain those tasks' case matrices; add `tests/test_review_batches.py::test_all_output_surfaces_share_privacy_rules`
  with dummy batch/receipt/digest/attempt/state renderers, and `::test_overlap_redaction_preserves_no_canary_fragment`.
- Pass: synthetic values absent from every emitted/persisted freeform surface, fixed trusted messages remain intact;
  changing a used field refuses only that semantic decision, not unrelated valid decisions.

### RUNS-1 — Centralize run publication and preserve label ownership
Depends: PRIVACY-1.

- Files: new small `jev_ultrafast/run_store.py`, Agent.save, report_outcome and tests. Implement one resolved-directory
  metadata lock/publisher used by both writers; labels append and execution saves merge persisted outcomes.
- Verify in `tests/test_run_store.py`: `test_save_preserves_sequential_user_correction`,
  `test_save_and_reporters_preserve_all_writes`, `test_malformed_existing_run_is_not_overwritten`,
  `test_custom_trace_directory_uses_one_lock`, `test_metadata_lock_is_released_before_lesson_and_review`.
- Pass: save-label-save and finalization retain every label in lock-acquisition order; corrupt existing data unchanged;
  custom path aliases resolving to the same directory serialize; observer fields remain intact after labeling.

### REVIEWS-1 — Define pure projections, schemas and shared record readers
Depends: RUNS-1.

- Files: scripts/review_runs.py, small shared record helpers (prefer `jev_ultrafast/review_records.py`), report consumers
  and tests. Define batch schema 1, notes envelope/digest schema 2 and attempt schema 1,
  semantic versions, supported fields and typed outcome distinctions.
  Build pure canonical base/derived projections, note hash and explicit missing-parent/cycle/successor dependencies.
- Verify in `tests/test_review_batches.py`: `test_unknown_record_versions_fail_closed`,
  `test_correction_changes_review_version`, `test_changed_predecessor_invalidates_recovery`,
  `test_new_successor_changes_absence_dependency`, `test_execution_clocks_do_not_change_review_version`,
  `test_attempt_records_never_acknowledge_items`.
- Pass: timestamped labels change versions; random nonces/screenshots/runtime clocks do not; unrelated new runs do
  not change existing item versions; no reader infers acknowledgment from membership or a failed attempt.

### REVIEWS-2 — Prepare immutable, bounded batches with full privacy closure
Depends: REVIEWS-1.

- Files: review_runs queue/preparation and tests. Capture dependencies under short metadata/notes locks, freeze
  redaction contributors before caps, serialize exact sanitized input once and print that stored input/batch ID.
- Verify in `tests/test_review_batches.py`: `test_queue_prints_exact_saved_bytes`,
  `test_deferred_and_excluded_contributors_still_redact`, `test_batch_caps_defer_whole_items`,
  `test_oversized_item_does_not_starve_following_items`, `test_new_unrelated_run_is_not_added_at_apply`.
- Pass: 25/5/65,536 limits include UTF-8 multibyte cases; no partial item or raw privacy values in artifacts; immutable
  batch A never contains subsequently arriving B. Excluded data contributes only local redaction/hash metadata.

### REVIEWS-3 — Add the notes envelope and pure transaction callback
Depends: REVIEWS-2.

- Files: site_notes store API, all ordinary note writers and tests. Read legacy lists and schema-2 envelopes; preserve the list-facing
  public API. Provide one lock-owning transaction boundary; apply decisions sequentially on a private copy.
- Verify in `tests/test_review_batches.py`: `test_legacy_notes_migrate_without_losing_fields`,
  `test_all_note_writers_preserve_pending_receipt`, `test_transaction_callback_does_not_reenter_lock`,
  `test_two_decisions_cannot_duplicate_one_recovery`, `test_unknown_notes_schema_stops_publication`.
- Pass: approvals, retirement, counters and all pending receipt fields preserved; second decision sees first one's
  reservations/site limits; callback never recursively enters a lock or creates a seed file.

### REVIEWS-4 — Apply exact batches and recover one committed receipt
Depends: REVIEWS-3.

- Files: record/application helpers, site_notes transaction, pure durable file publisher and tests. Replace the earlier F2
  acknowledgment fix with the §2 commit protocol. Require `apply --batch`; use receipt/digest replay before freshness.
- Verify in `tests/test_review_batches.py`: `test_changed_dependency_supersedes_before_mutation`,
  `test_changed_privacy_contributor_supersedes_batch`, `test_storage_failure_acknowledges_nothing`,
  `test_semantic_refusal_preserves_valid_neighbor`, `test_same_reply_replay_ignores_its_own_note_changes`,
  `test_different_reply_after_commit_conflicts`, `test_crash_at_each_publication_boundary`,
  `test_directory_fsync_failure_after_replace_never_replays`.
- Pass: inject failure before notes replace, after notes replace, during directory fsync, before/after digest replace,
  and before receipt cleanup. Assert exact notes/ack versions and no duplicate note, false “nothing changed” or paid
  relaunch. Pending recovery failure blocks subsequent application/dispatch.

### REVIEWS-5 — Integrate legacy/v2 reporting without false acknowledgment
Depends: REVIEWS-4.

- Files: reviewed(), report_runs, shared record readers and tests. Reserve `<batch_id>.json` for committed receipts;
  migrate discovery, chronological selection, legacy reporting and running/failed attempt views. Implements F4/F11.
- Verify in `tests/test_review_batches.py`: `test_same_second_batches_remain_distinct`,
  `test_failed_attempt_does_not_occupy_committed_digest_path`, `test_legacy_requeue_happens_once`;
  in `tests/test_report_runs.py`: `test_mixed_legacy_and_v2_reporting`,
  `test_running_attempt_is_not_failed`, `test_random_filenames_do_not_choose_latest`,
  `test_attempt_and_digest_do_not_double_count_cost`; retain F11's look-alike-host case and untrusted-block tests.
- Pass: reports are read-only; acknowledged exact versions stay suppressed, later corrections requeue, no old ID
  suppresses current versions, and complete input membership remains visible separately from acknowledgments.

### REVIEWS-6 — Preserve singleflight and scheduling with short commit locks
Depends: REVIEWS-5.

- Files: review_runs auto/once/begin/finish/launch, MCP trigger tests and state schema. Add dispatch lock and attempt
  claim; share them across both paid entrypoints; settle counters once; retain F5/F9 behavior and launch arguments.
- Verify in `tests/test_review_batches.py`: `test_auto_and_once_cannot_dispatch_together`,
  `test_manual_apply_finishes_while_model_waits`, `test_crash_after_claim_does_not_redispatch`,
  `test_superseded_consumes_slot_not_failure_streak`, `test_recovery_settles_attempt_once`,
  `test_unreadable_exclusions_change_no_state_or_dispatch`, `test_abandoned_claim_settles_uncertain_once`,
  `test_next_due_allows_new_batch_after_uncertain_dispatch`, `test_live_or_unknown_child_blocks_new_dispatch`;
  in `tests/test_report_runs.py`: `test_expired_attempt_is_not_reported_running`;
  in `tests/test_mcp_server.py`: `test_background_review_launch_arguments`.
- Pass: fake child/recorded launch count is 0 or 1 as specified; no commit locks held during wait; argv/stdin/log/session
  match current isolation contract; no lost receipt, double cost/failure count, immediate paid retry or silent
  daily-cap bypass. Crash-before-result settles once; old live/unknown child prevents a new launch; verified exit
  permits only a new attempt at the allowed time. Reused PID never causes a foreign process to be killed.

### REVIEWS-7 — Verify migration and legacy follow-ups in disposable storage
Depends: REVIEWS-6.

- Files: migration/export helper, site_notes/review tests and affected docs. Complete F3 signature correction and F10
  bounded lesson-chain test; document temporary backlog and current automatic cutoff. Do not migrate real storage yet.
- Verify in `tests/test_review_batches.py`: `test_auto_cutoff_and_exclusions_survive_migration`,
  `test_export_preserves_new_notes_outcomes_receipts_and_ack_history`,
  `test_real_pipeline_redacts_every_publication_surface`;
  `tests/test_mcp_server.py::test_a_looping_chain_ends_the_lesson_walk`.
- The real-pipeline privacy test exercises queue preparation, manual apply, fake paid launch, schema/semantic/provider
  failures, pending-receipt recovery and reporting. Use canaries from selected/deferred runs and excluded predecessors;
  inspect actual batch, envelope/receipt, digest, attempt/state files and captured output. This supersedes dummy-sink
  coverage as release evidence: no fragments leak, trusted diagnostic wording survives, and valid decisions beside
  semantic refusals still commit. All storage and launchers remain disposable/fake.
- Pass: a legacy fixture migrates, receives new label/note, crashes with pending receipt, recovers, and exports without
  dropping any new state; cyclic lesson walk terminates through the real bound, not a swallowed test exception.

### GATE-REVIEWS
Depends: REVIEWS-7.

Run all new run-store/review tests and existing site_notes/review_runs/report_runs/MCP suites. Reviewer checks every
publisher and lock edge, schema reader and privacy surface. All F1–F11 contracts are covered: F1/6/7/8 in PRIVACY-1;
F2 in REVIEWS-4; F4/11 in REVIEWS-5; F5/9 in REVIEWS-6; F3/10 in REVIEWS-7. Every process-crash and post-rename error
point has a passing observable assertion. No real notes file or active review has been changed for this gate.

## 6. Snapshot and readiness tasks

### SNAPSHOT-1 — Separate progress identity from exact browser freshness
Depends: GATE-REVIEWS.

- Files: snapshot.js/browser.py, adapters and `tests/test_snapshot_contracts.py`. Introduce schema 2 and browser-owned
  baseline/token while preserving baseline progress projection. Freshness reads never install a baseline.
- Verify: `test_freshness_does_not_replace_baseline`, `test_progress_excludes_nested_protocol_identity`,
  `test_progress_and_freshness_keep_distinct_projections`, `test_old_tokens_reject_after_observe_reset_or_navigation`.
- Pass: observe A/mutate B/check twice yields false twice; identical reobservation keeps progress fingerprint;
  offscreen/omitted change invalidates freshness without new progress; scroll-height change still counts.

### SNAPSHOT-2 — Bound transport and guard construction, propagate overflow
Depends: SNAPSHOT-1.

- Files: snapshot/browser/Agent/MCP/inspector/report compatibility and tests. Cap before guards, deduplicate scopes,
  restrict strong references, enforce byte ceiling without meaningful-value truncation; keep global enumeration.
- Verify in `tests/test_snapshot_contracts.py`: `test_guard_work_and_transport_are_bounded`,
  `test_strong_references_cover_only_offered_targets`, `test_overflow_is_terminal_at_each_adapter`,
  `test_legacy_snapshots_report_but_cannot_execute`; parameterize 250/1,000/5,000 controls, shared context and long labels.
- Pass: <=250 guard builds, one scope read per unique scope, <=262,144 bytes or explicit overflow; old page diagnostic
  only, no pending input/model/recovery fallback. After-input overflow keeps exactly one executed step.

### GATE-SNAPSHOT
Depends: SNAPSHOT-2.

Run snapshot/browser/Agent/inspector offline checks and `tests/test_browser_native.py::test_snapshot_freshness_parity`,
`tests/test_browser_native.py::test_snapshot_payload_and_progress_contracts` in the lab. Every mutation rejected by baseline stays rejected,
including omitted/offscreen fields; SELECT identity adds rejection, never removes it. Store baseline/candidate bytes,
guard/scope/reference counts, scan latency distributions and every attempt. Dense canonical stress fixtures must
successfully return evidence below the ceiling; a separate deliberately oversized-label fixture must stop. Passing
by making every large page overflow does not satisfy the efficiency objective.

### READINESS-1 — Adapt the approved network loading gate
Depends: GATE-SNAPSHOT.

- Files: browser/Agent and readiness tests. Implement executor-improvements.md §4 v4.2 against current interfaces,
  not by blindly applying its historical diff. Preserve tracked request scope, background drain/loss accounting,
  five-second input-age cap, no minimum wait and every-final-answer rule.
- Verify the executor-improvements.md §4.6 cases, ported with unchanged assertions; record a case-to-node/assertion
  mapping in evidence with no missing case. Also run
  `tests/test_readiness_contracts.py::test_loading_gate_respects_shared_deadline_and_policy`,
  `::test_gate_wait_does_not_install_freshness_baseline`, `::test_loading_gate_records_loss_and_cap`.
- Pass: no consumer drains another session's events; cancellation stops polls; no action repeats; waits cannot restart
  the last-input clock or authorize a terminal answer solely because the network is quiet.

### READINESS-2 — Add only the approved post-step timeout rereads
Depends: READINESS-1.

- Files: Agent/report counters/MCP comments and tests. Implement §2 v2: at most 2 additional post-step observation
  retries for TimeoutError, never an input retry; check limits before each; keep other timeout paths distinct.
- Verify executor-improvements.md §2.5 offline cases with the same explicit case-to-node/assertion mapping, plus
  `tests/test_readiness_contracts.py::test_timeout_reread_does_not_restart_loading_age`,
  `::test_timeout_retries_preserve_single_input_and_uncertain_attempt`, `::test_stop_before_retry_does_not_count_it`.
- Pass: one input, up to 3 post-step reads, repeats count only reads started; cancellation or deadline cannot be erased
  by later observation success; original dialog handling remains documented and independently exercised.

### READINESS-3 — Verify composition and the existing WAIT handoff
Depends: READINESS-2.

- Files: integration/native fixtures and docs. Use actual snapshot adapter with scripted model and fake clock for
  offline composition, then local native scenarios. Preserve existing two-WAIT behavior and no new re-ask timer.
- Verify in `tests/test_readiness_contracts.py`: `test_two_unchanged_waits_hand_back_once`,
  `test_five_second_reread_leaves_no_new_loading_allowance`, `test_changed_results_drop_pending_done`,
  `test_valid_continuation_resets_loading_but_invalid_policy_preserves_it`;
  native `tests/test_browser_native.py::test_busy_page_and_loading_gate_compose_without_repeated_input`.
- Pass: independent fixture counters prove input exactly once; results checked outside DONE; full run evidence
  distinguishes timeout repeats, loading waits, stale recovery, stop code and separately timed final read.

### GATE-READINESS
Depends: READINESS-3.

Reconcile old plan tasks 0–2/5–6/§4 acceptance with this stage's interfaces. Retain its synthetic busy-page, dialog,
request-event and no-daemon-in-offline-test checks. Historical live-site trials are evidence only; do not claim the
new build reproduces them without running their acceptance protocol. Any paid/live-site experiment not performed
remains an explicit validation limit. All local correctness/native gates above must pass, including the fully
qualified native composition node in READINESS-3 and every mapped inherited acceptance case.

## 7. Commands and final delivery tasks

The native harness implements this interface. Each new run needs its own verified local lab; past checks are not a substitute for the final fixed-source evidence:

```sh
uv run python scripts/validation_lab.py prepare --fixtures tests/fixtures --output artifacts/robustness-efficiency-completion/<run_id>/lab.json
uv run pytest -q -o addopts='' -m native tests --lab-manifest artifacts/robustness-efficiency-completion/<run_id>/lab.json
uv run python scripts/validation_lab.py close --manifest artifacts/robustness-efficiency-completion/<run_id>/lab.json
```

Replace `<run_id>` with the recorded concrete evidence directory before execution. Prepare must use a fresh owned
profile/daemon and local fixtures, verify process/endpoint ownership, and fail if isolation cannot be established.
Close verifies recorded process identity again, never kills by name, and refuses a foreign/reused PID. No paid model
is used. Each native test must fail rather than skip if its manifest/browser prerequisite is wrong.

### RELEASE-1 — Reconcile documentation, contracts and old-plan status
Depends: GATE-READINESS.

- Files: README, integration/failure-review/executor design/status docs, this plan evidence and public examples.
- Verify: documented signatures match actual public API/tool schema; statuses name implemented behavior; error/limit
  semantics and schema migration match tests; old raw trials and performance claims remain historically labelled.
- Pass: user-edited design content preserved/reconciled intentionally; no false DONE/90-second-hard-timeout/exactly-once
  billing claims; old plan follow-ups map to passing current tests, not historical counts.

### RELEASE-2 — Run repository checks and independent implementation review
Depends: RELEASE-1.

- Run `uv run ruff check .`, `uv run pytest`, both JS syntax checks and `uv build`; rerun relevant native suite against
  the same recorded candidate hashes. Do not conflate source tests and wheel contents: inspect built wheel for required
  snapshot/static files and import public APIs from an isolated wheel install without contacting providers/browser.
- Independent reviewer checks final diff, task evidence and boundary matrix; another reviewer replays the premortem
  with fault injection records. Every blocker/should-fix is resolved before closing this task.
- Pass: all selected checks exit 0, required cases execute without skip/xfail, wheel smoke succeeds, and final reviews
  report zero unresolved blockers with exact candidate hashes. Plain pytest has native cases deselected by design.

### RELEASE-3 — Rehearse safe activation and rollback without production changes
Depends: RELEASE-2.

- Files: disposable state, operational runbook/evidence only. Rehearse old-writer detection, quiescence, backup checksum,
  migration, pending-receipt recovery, restart with new readers and compatible rollback/export.
- Verify: fixture includes legacy approved/retired notes, corrected labels, legacy digests, v2 attempts and a pending
  receipt. After rehearsal, all new notes/outcomes/ack history preserved and no paid dispatch occurred.
- Pass: runbook identifies exact processes/paths and compatibility checks, requires stopping old writers before real
  envelope publication, and never restores stale backups over newer user work. Real activation remains separate.

### GATE-RELEASE
Depends: RELEASE-3.

Deliver code/test/doc change summary; filled task evidence; schema/API migration notes; independent reviews; native
correctness and snapshot measurement reports; and explicit unrun live-site/performance checks. Verify no unrelated
or user-owned change was lost. Do not commit, push, alter live model settings, or activate production storage without
the corresponding task authorization. This gate establishes code readiness under the stated verification limits.

## 8. Activation and performance claims

Actual activation uses RELEASE-3's rehearsed procedure and requires all running old writers to be stopped and
verified backups/compatible reader/export available. Record activation separately; code completion does not imply it.

Paid live-site benchmarking is not needed to write this plan or execute its offline/local correctness work. Before
running it, record fixed goals/models/profile, interleaved baseline/candidate order, attempt count, budget cap,
independent success checks and predeclared pass criteria. Report end-to-end medians/tails, pass/false-DONE rates,
handoffs, model cost, snapshot work/bytes and every failed attempt. Do not assert a speedup from synthetic byte tests.

## 9. Plan review and execution status

All three independent agents reviewed the revised plan on 2026-10-03 and returned **READY**, with no unresolved
blockers in their scopes. This is approval of the plan's contracts and acceptance criteria, not implementation proof.

| Reviewer | Scope | Verdict |
| --- | --- | --- |
| execution_review | Policy, limits, final browser dispatch, partial inputs, late-response accounting and task executability | READY |
| browser_review | SELECT identity, snapshot bounds/freshness, native isolation and readiness gate coverage | READY |
| review_pipeline | Privacy, schemas, concurrent writers, crash recovery, dispatch settlement and migration | READY |

The review closed gaps in authoring-time runtime isolation, actual privacy publication tests, abandoned-dispatch
recovery, browser preflight deadline checks, paid-call denial in native tests, and inherited/native test coverage.
The final pass verified unique task IDs, dependency closure, local links, Markdown fences, whitespace and preservation
of the source design/review/user-edited documents. The plan contains **27 implementation subtasks and 8 gates**.

Historical planning checkpoint (2026-10-03): all tasks and gates were **Not started**. No runtime code was changed, no storage migrated, and no proposed implementation tests were run during planning. Current implementation and gate acceptance are recorded in the dated execution ledger; validation in the source design remains historical evidence.
