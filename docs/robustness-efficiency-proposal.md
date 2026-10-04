# Robustness and efficiency proposal

> Current implementation note (2026-10-04): the robustness/efficiency candidate implements the policy, execution limits, versioned review storage, bounded snapshots and readiness contracts. See the [current contracts](robustness-efficiency/current-contracts.md) and its evidence/activation links. The design, planning statuses, trial counts and performance observations below are historical; they are not current release or production-activation proof.


Status: reviewed proposal, ready for implementation planning; not implemented. Revision 3, 2026-10-03.

Baseline: `60f03037a713dbce10f46da015fbffccc9132fa5`, branch `executor-improvements-design`.
The existing uncommitted changes to `docs/executor-improvements.md` are retained unchanged.
This proposal covers the five findings from the current-code review, including both review-queue defects,
and coordinates them with the already designed page-readiness work. It does not authorize a deployment,
change any live browser, or claim the proposed fixes have passed implementation tests.

## 1. Evidence and intended result

| Problem verified in the current code | Proposed result | Evidence |
| --- | --- | --- |
| A valid CLICK can execute despite a goal saying “do not click” | An explicit caller-supplied operation policy is enforced independently of the model | `agent.py:174–218`; actual trial in `executor-improvements.md:2317–2319`; offline mock reproduced one click |
| Swapping unselected dropdown option values can pass freshness and select another option | Execute only the exact observed option, after checking its current meaning | `snapshot.js:44–71`; `browser.py:138–146,218–222`; production snapshot code reproduced the mismatch in a synthetic DOM |
| Stale reads before a model choice consume no budget | Every goal has a finite recovery allowance, including the library and direct commands | `agent.py:109–149,275–278`; 1,000 mock recovery ticks remained ready with no decisions/actions |
| A later user correction is hidden by an earlier review; manual apply can acknowledge unseen runs | Review acknowledgment identifies exact item versions from an immutable batch | `review_runs.py:176–190,229–240,585–587,901–920`; both cases reproduced in temporary directories |
| Controls are capped only after guards and the global marker are built | Bound snapshot transport and target guards while preserving global freshness | `snapshot.js:49–53,94–106`; synthetic 250/1,000/5,000-control snapshots measured 1.57/6.21/30.93 MB |

The snapshot measurements used production JavaScript with a synthetic DOM and shared 6,000-character
context. They are stress-case payload sizes, not measurements of real-site latency. Mock and synthetic-DOM
tests establish reachable logic failures; they do not replace native-browser integration tests.

The baseline has 236 passing offline tests. The review also passed Ruff and both JavaScript syntax checks.
The existing checks miss the cases above. An implementation must demonstrate the new invariants, not merely
retain the test count.

## 2. Constraints and relationship to existing work

- Keep one natural-language goal. Operation permissions, budgets, and site permissions are execution controls,
  not site-specific plans or prepared field strings.
- Keep operation and operation-specific target questions in one TypeSafe request. Only the chosen operation's
  target may execute. Models never supply code, selectors, or browser coordinates.
- Preserve logging before observation, independent outcome verification, text-helper cache identity, and the
  prohibition on retrying browser mutations. An uncertain input remains “may have run.”
- Keep site notes outside the executor's model inputs. Preserve exclusions, sanitization, unapproved notes,
  the daily automatic-review limit, its $0.50 limit, and its failure cutoff.
- `executor-improvements.md` §2 v2 and §4 v4.2 remain the source for post-step timeout rereads and the final-answer
  loading gate. They are designed but unimplemented. §5's two-WAIT handoff is already implemented and remains.
- This proposal replaces the implementation approach for F2/P34 only where §6 supplies atomic note publication
  and acknowledgment. F1 and F3–F11 remain in the existing plan; their checks must still pass. In particular,
  F6–F8 sanitization fixes must precede enabling the new review-batch writer.
- This document changes neither old design files nor old evidence. During implementation, update their status
  and affected call sites together; do not apply their historical code sketches blindly over the new APIs.

## 3. Enforce an explicit operation policy

### Public contract

Add required `allowed_operations: list[str]` to `run_goal` and a required keyword-only equivalent to `Agent`
and `new_goal`. Values are a subset of `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`.
`DONE` and `BLOCKED` are always available and cannot be permission entries. Reject null, duplicates, unknown
names, strings instead of lists, and omitted policy before opening/closing a tab, reading a page, or calling a model.
The empty list is valid: inspect the current observation and choose a terminal answer without issuing UI input.
`["WAIT"]` additionally permits the existing observation-and-wait loop.

The policy is required on every goal, including same-tab continuations. There is no implicit inheritance or
automatic widening after a failure. The trusted caller must derive it from the user's authorization; the executor
does not infer permissions from English or add another model call to interpret them. A model acting as caller can
still choose an overly broad policy: this change enforces the supplied boundary, not arbitrary natural-language
intent. Caller/tool instructions must explicitly cover “only read,” “do not click,” and separate authorization
before broadening a failed run's policy.

An explicit `url` remains authorization for initial navigation, even with `allowed_operations=[]`. The policy
governs executor-generated UI operations after setup. It cannot prevent website scripts, network activity, or a
human from changing the page; avoid advertising it as a browser sandbox or zero-side-effect browsing.

`allow_commit` remains separate and defaults false. An allowed CLICK/SELECT still passes the existing commit
boundary; `allow_commit=true` never enables an operation absent from the allowlist. No new confirmation step is
added to ordinary operation. The caller supplies the concrete policy with the original goal.

### Enforcement and compatibility

1. Validate the policy before any setup or same-tab state reset. Store an immutable normalized set and its sorted
   trace representation. An invalid continuation leaves the existing goal and browser intact.
2. Allocate one canonical evidence table and element/option indices from the complete capped observation before
   filtering. Retain all observed labels, values, options and control state even for `[]`. Filter only eligible
   operations and target/commit heads, without renumbering. The model, inspector, overlays, trace and executor all
   use that same table and mapping. A TYPE_TEXT-only policy must not change textbox [2] into target [1].
3. In `act`, derive the actual operation from the selected observed action's kind/control ID and check it against
   the stored policy before the text helper, attempt creation, or browser call. Reject disagreement with the model's
   operation field; checking that field alone would allow a mislabeled click to bypass the policy. This also covers
   mocks, stale inspector state, and malformed responses.
4. Recheck immediately before the browser operation; policy cannot mutate within a goal. A forbidden choice stops
   with `operation_not_allowed`, preserving the attempted operation in diagnostics but executing nothing.
5. Update the MCP schema, demo request/UI, library examples, scripts, tests, and tool instructions in one change.
   The demo uses explicit presets; search/form examples explicitly allow their required operations. Missing policy
   fails with a migration message. No temporary permissive fallback.

This is an intentional API compatibility break. Requiring one transparent control is preferable to an optional
flag that old callers silently omit. Existing stored runs remain readable and are labelled “legacy: policy not
recorded”; their permissions must never be guessed from their goal.

Acceptance: a forbidden schema-valid CLICK/TYPE_TEXT/SELECT causes zero browser input and zero helper calls;
allow_commit cannot bypass the policy; [] and [WAIT] differ as specified; terminal answers remain available;
same-tab continuation never inherits a wider policy; every repository caller specifies policy explicitly.
Inject mismatched operation/action metadata and check refusal. Under TYPE_TEXT-only and empty policies, the
inspector and model retain the original field indices/values and highlight the same actual selected element.

## 4. Select the observed option, not a matching value

Record an opaque DOM identity for each offered native option, together with its owning select identity,
observed index, label, value, selected state, and effective disabled state, including its optgroup.
These are code-owned references in the same document epoch, not model-generated IDs. The model still selects
the offered element/option index; code resolves it to this descriptor.

At execution, one synchronous `Runtime.evaluate` performs all SELECT checks and assignment:

1. Resolve the same select and option nodes. Require both connected, the same owner and document epoch,
   `select.multiple === false`, and the option still at its observed index.
2. Check the select's current page/target guard, geometry and hit test, and the option's exact label, value,
   selected state and effective disabled state. Reject reordered or replaced options conservatively.
3. If every check passes, assign `select.selectedIndex` to the verified index, then dispatch the existing input
   and change events. Do not use `select.value`, which chooses the first matching value.
4. Return an explicit pre-input rejection result for stale/covered/disabled options. This can trigger an observation
   retry because nothing ran. An exception, timeout, or lost response after evaluation was sent is uncertain;
   keep the attempt and stop. Never classify that uncertainty as retryable `StalePage`.

There is no asynchronous gap between the final option check and assignment. Event handlers may change the page
after assignment; log the completed input before its observation as today. Do not attempt to undo or repeat it.

Initially omit native `select[multiple]` from executable actions and describe it as unsupported in observed
diagnostics. Single-option assignment clears other selections; inventing multi-selection semantics is outside
this fix. Do not expose it as CLICK instead. Unsupported control evidence must not disappear from the page read.

Tests: swapped values with unchanged labels; duplicate values with different labels; a disabled first duplicate;
option removal/replacement/reordering; changed optgroup disabled state; same labels across different selects;
document navigation; multi-select retaining all selected options because no action is offered; and exceptions
before/after assignment. Native-browser fixture checks must assert the selected option identity and event counts,
not merely its value. Each successful SELECT fires exactly one input/change pair; uncertain results never replay.

## 5. Bound recovery in the Agent itself

Move the execution deadline into `Agent`, retaining MCP's cancellation/shutdown callback. Proposed defaults:
`RUN_SECONDS = 90` and `MAX_STALE_RECOVERIES = 120`. The latter matches the existing model-call budget's scale;
it is a conservative administrative cap, not a measured page-readiness threshold.

- Start the monotonic execution deadline at the first `predict`, `tick`, or `act` of a goal, not during constructor
  navigation. Setup retains its existing separate timeouts; final verification is separately reported overhead.
- Call one internal `check_run_limits()` at every public command entry, before every model/helper request, before
  every input, and before each retry/readiness poll. It checks the Agent deadline, recovery cap, then the caller's
  cancellation/shutdown callback. `Agent.run`, direct ticks, the demo, and MCP share it.
- Count every caught `StalePage` that would continue the run, whether from pre-choice freshness, a read, a selected
  target, or the post-input observation. Consume one allowance before beginning its recovery read. On the 120th
  such outcome, stop instead of retrying. Successful reads and changing pages never reset this cumulative count.
- `tick` owns outer recovery accounting: one caught stale outcome increments once, never again in nested
  `predict`/`act` or in the recovery read. Recoveries 1–119 may read; outcome 120 stops before that read. Direct
  predict/act propagate stale errors rather than internally retrying; every subsequent call still checks the shared
  deadline and terminal state before any work. `stale_recoveries` counts handled stale outcomes, including the
  terminal one. Keep this definition in metric labels and boundary tests.
- Keep existing `stale_streak`, `wait_streak`, step and model budgets for their distinct meanings. Do not reinterpret
  navigation as permission for unlimited retries. Add no automatic new goal, reload, or timer-based re-ask.
- Record `stale_recoveries`, last stale reason, stop code and remaining budget. Budget exhaustion sets terminal
  status `stopped`, clears pending decision/text, saves when possible, and preserves history plus any uncertain
  attempt. All loops/UI controls must recognize `stopped` as terminal; `new_goal` explicitly resets the counters.
- Keep `observe()`'s existing local retry limit; the Agent checks before the next outer retry. §2's two timeout
  rereads remain a separate post-step counter and call the same limit check. No timeout around an input is retried.

Check limits after blocking work as well as before it. A terminal DONE/BLOCKED arriving after execution expiry
does not override the budget stop. Final evidence collection is one separately timed best-effort read, using its
own transport timeout and no added retries; its success does not erase the original stop or enable more input.

The deadline is cooperative, not a hard wall-clock guarantee. An in-flight browser or synchronous HTTP call can
overrun it; HTTPX phase timeouts do not constitute a total request deadline. Check the remaining budget before
each HTTP retry, cap per-phase timeouts to the remaining positive budget, and perform no new request or input
after expiry. Esc cannot preempt arbitrary synchronous I/O. Hard process-level request cancellation is deferred;
document the limit rather than claiming a 90-second hard stop.

Tests use an injected monotonic clock, mocked requests, and bounded iteration: perpetual stale pre-choice reads;
alternating changed pages; transient recovery; exact 119/120 boundary; direct predict/act; generator run; expiry
during helper and HTTP retry; cancellation during rereads; and post-input stale reads with one input only. Browser
constructor failure, final-read failure, and uncertain mutation tests remain distinct.

## 6. Review exact batches and acknowledge exact versions

### Immutable batch

`review_runs.py queue` creates an immutable batch in ignored `artifacts/reviews/batches/`, rather than only printing
an ephemeral queue. Use a collision-resistant random ID, not a second-resolution timestamp. Publish after writing
the complete batch to a temporary file in the same directory. The terminal output includes the batch ID and exact
sanitized summaries. Automatic review uses the same batch creator and sends those exact stored bytes.

Batch schema version 1 contains:

| Field | Meaning |
| --- | --- |
| `batch_id`, `created_at`, `schema_version` | Identity and format, independent of mutable queue state |
| `source_revision`, `summary_version`, `fingerprint_version` | Code and semantic formats used to prepare the batch |
| `items` | Run/note IDs, item versions, reason codes, and dependency versions |
| `sent_text`, `sent_sha256` | Exact sanitized model input and its integrity check |
| `exclusions_version` | Fingerprint of parsed exclusions; changed exclusions invalidate pending application |

Persist no extra raw page text, screenshots, credentials, or model requests. Raw run files stay in their existing
location. Item fingerprints are local bookkeeping, not extra model context. All stored/freeform reply text follows
the existing scrubbing and untrusted-block rules, including error paths. Implement the planned sanitization fixes
before producing the first new batch.

Use SHA-256 of canonical JSON (`sort_keys=True`, fixed separators, UTF-8, explicit schema version, reject non-finite
numbers). A run's base material includes goal; all ordered outcome entries (including timestamp); result status/notes;
resolved failure code; history fields used in summaries and value scrubbing; text-helper values used in scrubbing;
final page URL/title; call URL; every visited URL used in exclusions; notes shown; and previous-run or legacy PID
linkage. Exclude execution clocks, random summary nonces and screenshot bytes.

The review version additionally includes structured reasons, recovery eligibility, ordered chain IDs/base versions,
and relevant successor IDs/base versions for `possible_false_dones`. A previously empty successor set is an explicit
dependency: a newly linked successor changes it, while an unrelated new run does not. Use base versions here, never
recursive review versions. Preserve chain partition/loop protection and deterministically encode missing parents
and cycles. Changes in predecessor labels, privacy inputs, or recovery evidence invalidate the derived version.
Note versions retain content, approval, retirement and failed-after counters; exclude only `shown` and `last_shown`
as current `note_hash()` does. Those two display counters are recorded as-of preparation, not freshness guarantees.

Queue membership is `(item ID, review version)`, not ID alone. New labels and changed chain evidence create new
eligible versions; unchanged versions stay acknowledged. A completed review of A never acknowledges newer A or B.

### Application and concurrency

Manual application becomes `review_runs.py apply --batch <id>` with the existing JSON reply on stdin. Omitted,
unknown, corrupt or unsupported batches fail before mutation. Do not rebuild the reviewer's input at apply time.
Keep response validation and note approvals unchanged: a review may add only unapproved notes and may not modify
or retire approved ones.

Take locks in one global order: review lock, run-metadata lock, then notes lock. All run-file publishers, including
`Agent.save` and `report_outcome`, use the same stable `.metadata.lock` in the managed runs directory for their short
read/replace critical section. `report_outcome` releases it before storing a lesson or triggering review. Ordinary
note writers take only the notes lock and preserve receipts. Never hold these locks while a model runs.
Locking does not make a stale full-file replacement safe: under the metadata lock, `Agent.save` must preserve the
complete existing on-disk `outcome` array while replacing executor-owned fields. `report_outcome` owns append-only
label publication and preserves executor fields. A malformed existing outcome/file stops publication without
overwriting it. New files start with an empty outcome array. Test sequential as well as concurrent saves after a
correction, including active traces and finalization; neither may erase or reorder a persisted label.
Under these locks, reread the batch dependencies,
exclusions, and current note store. If any recorded dependency changed, reject this application as stale without
mutating notes or acknowledging items; prepare a fresh batch on the next review. Never silently rebase its reply.
An unrelated new run outside the batch is not a dependency and does not invalidate it. Prepare batch dependencies
under the same short metadata/notes locks so label publication cannot tear their source view. App-managed exclusion
changes must also take the metadata lock; manually editing artifacts outside this protocol is not transactional.
An exclusion added after dispatch cannot retract text already sent, but prevents a pending reply from being applied.
Check for an already committed receipt/digest BEFORE freshness checks: same-batch/same-reply replay returns the
recorded result even though its own successful note changes altered dependencies. Unknown schema, summary,
fingerprint or scrubber versions reject before mutation. `source_revision` is diagnostic, not a requirement to run
the same commit; supported semantic versions and current validation rules determine compatibility.

Preserve per-decision semantic refusal from `failure-review.md` v4.4: an invalid task-bearing detail, unsupported
hint, or protected approved note refuses that decision while other valid decisions and proposals remain useful.
Compute all valid changes on a private notes copy, collecting sanitized refusal results. A notes-store infrastructure
failure BEFORE replacement publishes neither changes nor acknowledgment (F2/P34). Failure during/after a replacement
that may have succeeded requires receipt recovery, as below; never report “nothing changed” merely from an exception.
Use one lock-owning notes transaction API. Its callback receives an in-memory envelope and calls pure validation/
transformation helpers, never lock-owning `add_note`, `update`, or seed-creating `load` recursively.

### Atomic publication and crash recovery

Two separate `os.replace` calls do not create a transaction. Extend the notes store from its current list into a
versioned envelope containing `notes` and a pending review receipt. Publish the proposed notes plus receipt in ONE
atomic replacement under the existing notes lock. A receipt contains batch ID, reply hash, exact acknowledged item
versions, sanitized decision outcomes and digest material. That publication is the commit point.

Every ordinary notes writer must preserve the envelope and pending receipt. `site_notes.load()` continues to return
the notes list to its callers. Accept legacy list files on read and migrate on the first successful write; refuse
unknown schema versions. Stop old server/reviewer processes before migration so no old writer can erase receipts.

Publish terminal v2 digests as `artifacts/reviews/<batch_id>.json`, never a second-resolution filename. Required
fields: `schema_version=2`, `batch_id`, `created_at`, `finished_at`, `reply_sha256`, complete `input_items` (IDs and
versions), separate `acknowledged.runs` and `acknowledged.notes` maps, `sent_text`/`sent_sha256`, sanitized decisions,
flags, proposals and summary, and cost. Only acknowledgment maps suppress queue versions; input membership is audit
evidence, not a receipt. A matching existing digest is immutable; a conflicting file stops application.
One shared reader serves `reviewed`, `report_runs`, running-review state and crash recovery. Accept legacy timestamp
digests for historical reporting, and v2 by schema/ID. Select the latest by recorded timestamps, never random filename
order. Migrate discovery, report formatting, failure handling and state readers with the writer.

After publication, materialize the digest from that receipt, flush and fsync the file, replace it atomically, then
fsync its directory. Clear the pending receipt only after the digest is durable, using another notes-store update.
The notes-store publication itself uses flush/fsync/replace/directory-fsync. If replacement succeeds but directory
fsync fails, changes are visible and durability is uncertain: retain/recover the receipt under locks, block further
application and paid dispatch, and do not repeat note decisions. If replacement's outcome is unknown, inspect the
batch/reply receipt before deciding whether to retry. Test the post-replace fsync error explicitly. The process-crash
recovery table is:

| Crash boundary | Recovery |
| --- | --- |
| Before publishing notes+receipt | No changes or acknowledgment; retry the same batch |
| After publishing, before durable digest | Receipt proves exact committed result; recreate digest without replaying decisions |
| After digest, before clearing receipt | Verify matching batch/reply hash, then clear receipt; no duplicate notes |
| After clearing | Digest supplies acknowledgment; repeated same batch/reply returns the recorded result |

Drain any pending receipt before applying another batch. The same batch with a different reply after commit is
refused. Startup or command recovery repairs a receipt without calling a model. If recovery cannot write, surface
the error and keep the receipt; do not launch another paid review. Local file fsync improves durability but does
not claim immunity to broken hardware/filesystems. The artifact directory is trusted local application storage.

Semantic refusals are recorded as reviewed decisions; infrastructure failures remain queued and retryable, which
is the distinction F2 requires. A stale batch receives no acknowledgment. Subsequent automatic runs retain existing
daily/cost/failure limits; a corrected item never bypasses those controls.
Classify stale application as `superseded`, consuming the original dispatch's daily slot/cost but not incrementing
the provider/infrastructure failure streak. Retry on the next eligible cycle with a new batch, not immediately.
Record dispatch before starting the model. Recovery never claims exactly-once billing: a process can die after a
provider accepted a request. An uncertain dispatch keeps its daily slot consumed; never automatically redispatch it
while repairing receipts or digests.

### Legacy records and batch size

Old digests have IDs but no trustworthy run version. Retain them as history; do not fabricate historical versions
from current files. Requeue eligible legacy runs once under the new fingerprint scheme. Keep the existing automatic
date cutoff and exclusions. This may create a one-time backlog; report it clearly.

Before applying item/byte caps, freeze the privacy closure of the COMPLETE eligible queue: all queued runs' original
chains, including excluded attempts, and note-related values used by today's scrubber. Eligibility chains apply
exclusions; privacy chains retain excluded attempts only as local redaction inputs. Use the same closure for all
selected summaries, reply fields, refusal/error fields and receipts. Record hashes of all existing contributing
run dependencies, including deferred items; a changed contributor invalidates application. New unrelated runs do
not retroactively change a prepared batch. Keep run ID/host exemptions limited to selected output evidence; never
store raw privacy values. At apply, rebuild the closure from the recorded contributors only after verifying their
versions, so reply sanitization uses the prepared evidence. This preserves v4.4's cross-run redaction rule.

Bound new batches to proposed constants `MAX_REVIEW_RUNS=25`, `MAX_REVIEW_NOTES=5`, and
`MAX_REVIEW_INPUT_BYTES=65536` of UTF-8 sanitized input, with oldest eligible runs first. These administrative caps
protect the existing review budget, not a provider context-limit claim. Never truncate an item halfway; defer whole
items. A single oversized item is reported for manual handling and must not block smaller later items or be silently
acknowledged. Version dependencies can include non-reviewed chain members, but acknowledgment lists only items sent.

Tests: user correction after review; changed predecessor; new unrelated B between queue/apply; changed note;
new exclusion; unchanged note/run; legacy one-time requeue; corrupt batch; oversized item; same reply replay;
different reply replay; note-store failure; partial semantic refusals; every crash boundary; concurrent note writer;
and normal note writers preserving pending receipts. Include two commits with the same fake timestamp, replay after
note changes, fsync failure after rename, and a value in selected A that only deferred B or an excluded predecessor
reveals as private. Assert both resulting notes and exact acknowledged versions.

## 7. Reduce snapshot transfer without weakening freshness

Do not replace the existing guards with a MutationObserver count or a short non-cryptographic hash. DOM property
changes can evade mutation records, and hash collisions would weaken a correctness boundary. Preserve exact global
semantic comparison inside the browser and return a compact, code-owned observation token to Python.

- Scan the same global semantic evidence as today, including omitted controls, offscreen form properties, viewport,
  document identity, URL, title and visible text. Include option descriptors needed by §4. Geometry alone continues
  not to invalidate a choice; execution resolves geometry and hit-tests again.
- Keep three separate concepts: the existing progress fingerprint, exact freshness evidence, and an observation
  token identifying its baseline. Preserve `browser.fingerprint()`'s current projection: URL, visible text, capped
  actions INCLUDING geometry, and scroll data INCLUDING height. Its Python SHA-256 remains a progress indicator,
  never the authority for action freshness. Policy filtering must not change this projection. In particular, an
  offscreen field or omitted control changing does not newly reset WAIT, while scroll-height changes still count.
- The unique observation token identifies only the latest successful observation's stored guard baseline. It
  must not be used as `page_changed`, and observing an unchanged page must not count as progress.
- A freshness call receives that observation token and optional action, compares current exact evidence with
  the stored baseline in the browser, and returns a boolean. It does not update the baseline, progress fingerprint,
  or observation token. A missing/recreated cache has a new random epoch and rejects old references. No hash of
  page semantics replaces exact comparison; the random epoch is identity, not a semantic checksum.
- Truncate offered actions to 250 BEFORE materializing per-target guards. Memoize each scope's context text once
  per snapshot. Keep exact target-guard baselines in the browser and transmit compact references, not repeated
  6,000-character strings. Include target identity and snapshot generation; obsolete references reject safely.
- Freshness calls compare the current evidence with the relevant stored baseline; a fresh-read helper must not
  overwrite that baseline before comparing. Retain only the current observation's target baselines; the sequential
  Agent has at most one pending decision. A new observation intentionally invalidates an older pending decision.
- Keep the small observed action table and visible text for the model, inspector and logs. Introduce
  `snapshot_schema=2`; old run files remain reportable, but old recorded tokens are never executable in a new session.
  Guard creation is bounded by offered distinct targets; global DOM enumeration remains proportional to page size.
- Separate weak identity allocation from strong reverse references: keep strong references only to offered
  controls/options. Global/offscreen signature entries need stable weak identities but no retained node map.

Add `MAX_SNAPSHOT_BYTES=262144` as a proposed transport ceiling excluding an optional screenshot. Measure serialized
UTF-8 size in the browser. If the output still exceeds it, return a non-retryable `snapshot_too_large` result with
counts and no executable actions; do not truncate labels/values that determine meaning. This protects transfer,
not the cost of traversing an arbitrary DOM. Validate the ceiling against representative fixtures before release.
Carry overflow as a distinct terminal observation error through `Browser.observe`, freshness, Agent and MCP. Clear
pending choices; an old page is diagnostic only and is marked not fresh. Do not map overflow to `StalePage`, reuse
the old action table, ask the model to continue, or enter recovery. Test overflow immediately before input and after
an already logged input; the former executes nothing and the latter never repeats the completed input.

Acceptance: for the same 1,000- and 5,000-control stress fixtures, snapshot transport is at most 256 KiB or returns
the explicit overflow outcome, and per-target guard materialization is at most 250. Compared with baseline, fixtures
below the ceiling must continue to offer the same supported actions (except §3 policy and §4 multi-select changes).
Test unchanged pages, geometry-only motion, omitted controls changing, offscreen values, duplicate labels, cache
reset, navigation, and option mutation. Every mutation the old freshness guard rejects must remain rejected;
newly covered option changes must also reject. Repeated identical observations must preserve `page_changed=false`, the existing
two-WAIT stop and no-progress detection. Compare browser-side work as well as wire bytes.

## 8. Improve end-to-end time in the measured order

The September 24 comparison reported median 32.1 s sessions, 4.0 s in Jev's loop, and 85% of session time in Claude's
turns (`performance.md:116`). That is historical evidence, not a fresh production measurement. It motivates reducing
premature stops and extra handoffs before optimizing tiny Python operations.

Implement the existing §2/§4 page-readiness design as a separate stage after §5 recovery limits and §4 SELECT
correctness. Adapt it to compact snapshots without changing its request-tracking scope, five-second input-age cap,
no-minimum-wait rule, and independent final verification. Preserve §5's two-WAIT handoff and at-most-two re-asks
guidance; add no timer that starts a new goal and never retry a mutation. A loading gate is not proof of completion.

Combined integration fixtures must use the actual snapshot adapter with the readiness state machine: two identical
observations plus WAIT still hand back once; a five-second post-input timeout reread does not restart the loading
gate's five-second input-age window; changed results invalidate pending DONE; valid continuation resets old request
tracking and invalid-policy continuation changes nothing. Across all combinations assert one physical input, not
only matching status strings. Retain the original last-input timestamp through observations and retries.

Keep commit judgments in the same request. TypeSafe documents independent parallel questions, and the prior probe
found 82% more input tokens with commit heads but inconclusive latency impact. Do not remove the safety boundary
or split it into another sequential request merely to make a local benchmark smaller. Further request-size tuning
requires measured token/cost/latency tradeoffs and unchanged decision quality.

Record: whole session and run_goal time; model/helper requests and latency; stale recoveries; readiness waits;
handoffs; verified passes and false DONEs; snapshot time/bytes; run-file bytes; and review items queued/acknowledged.
Compare alternating baseline/candidate trials with fixed goals/models/browser profiles and all attempts retained.
Report medians and tail times alongside correctness. No performance release claim from mocked tests or a single run.

## 9. Implementation order, gates, and rollback

| Stage | Main files | Completion gate |
| --- | --- | --- |
| Operation policy | agent/model/MCP/demo, static UI, examples and scripts | Forbidden-operation fault injection, caller migration, existing suite |
| Option identity | snapshot/browser, guard fixtures | Real local HTML selects; exact option and event counts; no mutation retries |
| Recovery limits | agent/model/MCP/demo | Shared entrypoint tests with fake clock and bounded iteration; no §5 regression |
| Review batches | review_runs/site_notes/agent.save/MCP report_outcome/report_runs | Planned scrubber fixes; versioning, preserved labels, stale dependencies, crash and migration tests |
| Snapshot transport | snapshot/browser plus consumers | Freshness parity matrix, native-browser guards, byte and latency measurements |
| Page readiness | Existing plan's executor files and tests, adapted to above | Existing §2/§4 gates plus integrated no-retry/policy/timeout checks |
| Integrated release | README and affected design/status docs | Whole suite, lint, both JS syntax checks, build, independent outcome checks |

One writer owns overlapping files at each stage. Reviewers may work in parallel against a fixed candidate; do not
land concurrent edits to agent/browser/snapshot or the notes store. No commit or push is implied by this proposal.

At implementation start, save the baseline SHA, patch and hashes of user changes. Keep raw experiments immutable.
For notes migration, stop all notes writers, copy the legacy file and review artifacts, verify restore procedures,
then start only upgraded writers. Code rollback after migration requires a compatible reader/export procedure;
never run an old list-only writer on an envelope. Preserve new notes, corrections and receipts in any export.

Run `uv run ruff check .`, `uv run pytest`, `node --check jev_ultrafast/static/app.js`,
`node --check jev_ultrafast/snapshot.js`, and `uv build`. Native-browser checks use a dedicated temporary profile
and local fixtures, not the user's active Chrome. Paid live benchmarks are a later implementation activity with
an explicit experiment protocol and budget; none is required to finish or review this document.

## 10. Research and alternatives

Primary sources were fetched on 2026-10-03. Repository line references above name the baseline, not future code.

| Source | What it establishes | Design consequence |
| --- | --- | --- |
| [WHATWG select element](https://html.spec.whatwg.org/multipage/form-elements.html#the-select-element) | `value` chooses the first matching option; assignment clears other selections | Exact option identity, checked selectedIndex, omit multiple initially |
| [MDN selectedIndex](https://developer.mozilla.org/en-US/docs/Web/API/HTMLSelectElement/selectedIndex) | Setting an index selects that option and deselects the others | Single-select scope is explicit |
| [MDN option disabled](https://developer.mozilla.org/en-US/docs/Web/API/HTMLOptionElement/disabled) | An optgroup's disabled state is not reflected by option.disabled | Check effective enabled state, not one property |
| [MDN dispatchEvent](https://developer.mozilla.org/en-US/docs/Web/API/EventTarget/dispatchEvent) | Handlers run synchronously before dispatch returns | Exceptions/interruptions after mutation do not permit replay |
| [MDN MutationObserver](https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver/observe) | Watches child, attribute and character-data changes | Retain direct form-property comparisons |
| [Python monotonic clock](https://docs.python.org/3/library/time.html#time.monotonic) | Clock cannot go backwards and is unaffected by wall-clock updates | Deadlines use monotonic time; stored timestamps are separate |
| [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/) | Connect/read/write/pool timeouts have separate semantics | Do not claim synchronous phase limits are a total wall-clock deadline |
| [AnyIO official thread documentation](https://raw.githubusercontent.com/agronholm/anyio/master/docs/threads.rst) | Worker code checks cancellation cooperatively; Python cannot forcibly cancel thread code | Shared checks before side effects, explicit in-flight limitation; official source used because documentation site returned 403 |
| [Python os.replace and fsync](https://docs.python.org/3/library/os.html#os.replace) | Successful rename is atomic for one path; flush/fsync are separate durability operations | One notes+receipt publication, recoverable digest projection |
| [Python flock](https://docs.python.org/3/library/fcntl.html#fcntl.flock) | LOCK_EX coordinates cooperating users of a stable lock file | One explicit lock order, no claims about outside writers |
| [TypeSafe speculative fan-out](https://docs.typesafe.ai/patterns/fan-out) | Independent questions run in parallel; extra questions usually have little latency impact | Preserve one request, measure cost separately |
| [TypeSafe application design](https://docs.typesafe.ai/concepts/how-to-build-with-system-one) | “Keep control flow, deterministic rules, and side effects in code” | Enforce permissions and budgets outside model instructions |

Alternatives rejected: optional read-only flag silently omitted by old callers; English permission parsing;
option-value-only identity; resetting recovery budget on every changing page; queue/apply rereading the live queue;
pretending two file replacements are a transaction; inferring legacy reviewed versions; MutationObserver-only
freshness; and shortening guards by dropping evidence without a parity test. A database could provide transactions,
but is unnecessary for this single-file notes store and one serialized review applier.

## 11. Independent review and remaining validation

The companion [review record](robustness-efficiency-review.md) records independent design review, code/contract
validation, a premortem, revisions, and final dispositions. The document's acceptance tests are requirements for
future implementation; a reviewed proposal is not evidence that the implementation exists or is production-ready.
