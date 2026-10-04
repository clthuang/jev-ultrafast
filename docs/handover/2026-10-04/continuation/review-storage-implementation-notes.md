# Review/storage implementation preparation

Read-only preparation complete. The main risks are dependency completeness and crash accounting—not the existing summary rendering.

**Suggested module boundaries**

| Module | Minimal responsibility/API |
|---|---|
| `store_io.py` | Shared durable JSON replacement, immutable publication, and explicit publication-uncertainty errors. No domain logic. |
| `run_store.py` | Resolved-directory metadata lock; execution-field replacement preserving outcomes; outcome append preserving execution fields. |
| `review_records.py` | Canonical projections/hashes, strict versioned readers, batch/digest/attempt validation, explicit acknowledgment extraction, chronological report views. Keep independent of CLI and note mutation. |
| `site_notes.py` | Envelope reader and one `transaction(change)` API; preserve list-facing `load/update/add_note`. Extract pure `add_to_notes(notes, note, today)`. |
| `review_runs.py` | Prepare batch, verify dependencies, apply pure decisions, recover receipts, dispatch/account attempts. Reuse existing scrubber, schema validation, and launcher. |

`transaction(change)` should pass a private envelope to a **pure** callback and return its result. Ordinary `update(change)` becomes a wrapper targeting `envelope["notes"]`; it must preserve pending receipts. Avoid calling `load`, `add_note`, or another transaction inside callbacks.

**Dependency/version design**

- `run_base()` hashes only the approved semantic projection: ordered outcomes including timestamps, goal, result notes/status, resolved failure, relevant history/text values, exclusion URLs, notes shown, and linkage fields. Never hash whole run files or model requests.
- `run_review_version()` adds structured reasons, recovery eligibility, ordered chain/base-version pairs, and relation descriptors.
- Preserve explicit linkage distinctions: absent `previous_run` using legacy PID inference; explicit `null`; missing referenced parent; self-link; cycle. Existing `links()` collapses these into `None`, so it cannot supply complete dependency evidence alone.
- Record topology descriptors for **every pre-cap privacy root**, including deferred roots. A previously missing parent appearing or a new linked successor must supersede the batch even when all old contributor hashes remain unchanged. Unrelated arrivals must not.
- Use base versions inside graph descriptors, never recursively nested review versions.

**Batch construction trap**

Privacy values come from the complete eligible queue’s original chains. Identity exemptions come only from selected output evidence, including public dependency IDs actually printed—not every eligible run/site.

Selection must trial whole items with fixed per-item nonces, derive that trial’s exemptions, rerender its selected blocks, and measure actual UTF-8 bytes including separators. Adding an identity exemption can lengthen an earlier block. Test this near the byte cap, alongside deferred-name leaks and oversized-item starvation.

Persist only IDs, hashes, relation queries, and exact sanitized `sent_text`. At apply, reconstruct privacy values only after validating recorded contributors and topology. If validation fails, emit a fixed superseded message without quoting the reply or changed raw content.

**Application/receipt protocol**

1. Strictly validate batch format, semantic versions, integrity, and reply canonicalization.
2. Acquire short review lock; drain pending receipt.
3. Check committed same-batch/same-reply replay **before freshness**.
4. Under metadata → notes locks, verify dependencies and compute decisions sequentially.
5. Publish notes plus sanitized receipt in one replacement.
6. Materialize the immutable digest, then clear the matching receipt through a fresh transaction.

Separate `DecisionRefused` from storage/schema/infrastructure errors. Catch only semantic refusals per decision. A generic `ValueError/OSError` catch would preserve the existing partial-commit bug.

If replacement raises or directory fsync fails, inspect the receipt/digest before retrying. A boolean set after `os.replace()` returns is insufficient: fault injection may replace successfully and then raise. Cleanup must preserve ordinary note writes that occurred after receipt publication.

**Dispatch/accounting hazards**

- Auto, once, and **preflight** share dispatch singleflight; only that lock survives the paid wait.
- Preflight retains its $0.05 budget, fixed prompt, no batch acknowledgment, and no automatic scheduling/streak effect. Its child still participates in liveness checks.
- Persist claim and reserved timing before launch. Distinguish “claimed, never entered launch” from “launch started, child identity unknown”; the latter blocks another paid launch.
- Record PID **and start identity/process group**. Verify exit; reap only an owned child. Never kill a reused PID.
- Persist failure-counter changes and an `accounted_attempt_ids` marker **together in one state replacement**. Separate attempt-accounted/state-counter writes can lose or double-count failures after crashes. Preserve markers when enabling reviews.
- Receipt/digest success outranks an abandoned-attempt failure. Superseded attempts neither clear nor increment the streak.

**Reporting and validation**

Use one reader to separate legacy history, committed digests, and attempts. Only explicit acknowledgment maps suppress work; input membership and successful-looking attempt states do not. Deduplicate known cost by attempt ID; preserve unknown cost. Choose latest successful review by validated timestamps, never filename order.

Hardest additional cases: deferred-root topology changes; exemption-driven byte growth; crash between attempt settlement and state accounting; unknown child after launch; and schema/error output when privacy dependencies cannot be reconstructed.

No source edits, test runs, launches, or storage changes performed.

---

## Confirmed decisions from root

This evidence-only note was requested after the preparation above; writing it does not change candidate source or activate storage migration.

- Preflight preserves its existing **no daily scheduling stamp and no automatic failure-streak effect** on success, failure, or abandoned-attempt settlement. It shares paid singleflight and child-liveness checks with auto/once, retains its $0.05 cap, and never acknowledges review items.
- Failure-counter effects and accounted-attempt markers must be written atomically in the same `state.json` replacement. `enable` preserves those markers while resetting failure/off fields.
- Distinguish a claim published before spawning from a spawning attempt with unknown child identity. Unresolved ownership/liveness blocks another paid dispatch; do not guess that the child exited.
- Every frozen privacy root, including deferred roots, carries missing-parent/successor relation descriptors. A newly related contributor supersedes the batch before reply sanitization. Unrelated arrivals remain irrelevant. Store IDs, base hashes, and relation queries only; raw privacy values stay local.
- Privacy closure stays pre-cap, while exemptions stay limited to selected output evidence. Use fixed per-item nonces, rerender selected trials, and measure exact UTF-8 totals. Test selecting an identity that changes an earlier block's redaction length near the cap, and ensure deferred names never become kept exemptions.

## Transaction crash matrix

All cases use disposable stores and fake launchers. Assert note contents, exact acknowledgment versions, receipt/digest state, and launch count after recovery; successful recovery never reapplies note decisions.

| Crash/failure point | Authoritative evidence | Required recovery/result |
|---|---|---|
| Before notes+receipt replacement | Original notes, no matching receipt/digest | No note changes or acknowledgments; same batch may retry subject to scheduling rules. |
| Replacement raises before returning; replacement may have happened | Read current envelope and matching batch/reply receipt under locks | Determine visibility from stored evidence. Do not infer “nothing changed” from the exception or a local boolean. |
| Notes+receipt replacement succeeded; directory fsync fails | Visible matching receipt; durability uncertain | Preserve receipt and block new application/paid dispatch until recovery succeeds; never rerun decisions. |
| Receipt committed; digest absent or digest temporary write fails | Receipt contains complete sanitized digest material and exact acknowledgments | Materialize that digest without the raw reply or model launch. Keep receipt if recovery cannot write. |
| Digest replacement raises or its directory fsync fails | Receipt plus possibly visible matching digest | Verify exact digest identity/content, finish durability, then clean receipt; conflicting digest stops recovery. |
| Digest durable; crash before receipt cleanup | Durable digest and matching receipt | Clear matching receipt without replaying decisions. |
| Ordinary note writer runs between receipt publication and cleanup | Current envelope has writer's changes and same receipt | Cleanup loads latest envelope and preserves the writer's changes. |
| Cleanup replacement succeeds but directory fsync fails | Durable digest; receipt may be present or absent | Digest proves committed result. Recover cleanup as needed; never claim no commit or repeat notes. |
| Same batch/same raw canonical reply replay after commit | Matching digest or recovered receipt | Return recorded result before dependency freshness checks. |
| Same batch/different reply after commit | Existing committed batch/reply identity | Conflict; immutable digest/notes unchanged. |
| Semantic refusal among valid decisions | Pure sequential calculation before one publication | Refuse only that decision; publish valid neighbors and sanitized decision outcomes once. |
| Infrastructure failure while preparing changes | No successful notes+receipt replacement | Publish no partial decisions or acknowledgments. |

## Dispatch/accounting crash matrix

The global acquisition order is dispatch → review → metadata → notes. Manual queue/apply never needs dispatch. No short commit lock is held while waiting for a model or child exit.

| Crash/failure point | Required behavior |
|---|---|
| Before durable claim | No paid child may have been launched. A later invocation follows ordinary cadence/eligibility. |
| Durable claim before entering spawn | Evidence distinguishes “never entered launch.” Settle once without redispatching the old attempt; preserve its consumed reservation where applicable. |
| Spawning marker durable, but child identity absent/unknown | Treat possible paid launch as uncertain. Block new paid dispatch until ownership/liveness is resolved. |
| Child identity recorded and same child is live | Block overlap. At expiry, verify identity before bounded termination, verify exit, and reap only if it is this process's child. |
| Recorded PID has been reused or process ownership cannot be established | Never signal a foreign/reused process. Unresolved liveness blocks a new paid dispatch. |
| Child returned result, but no committed receipt/digest | Persist any known cost; abandoned application stays unacknowledged. Do not automatically replay a paid request. |
| Receipt/digest committed before attempt settlement | Committed evidence proves success; receipt recovery and attempt accounting must not count an infrastructure failure. |
| Terminal attempt persisted before state counter accounting | Reconcile the terminal attempt; apply effect and accounted-ID marker in one state replacement. |
| State replacement succeeded, but process died before a secondary attempt update | Accounted-ID marker prevents duplicate cost/failure effects on reconciliation. |
| `enable` runs after an attempt was accounted | Preserve accounting markers; reset only intended failure/off fields so old attempts cannot count again. |
| Superseded review | Preserve slot and cost; neither increment nor clear failure streak; prepare a new batch only at eligible timing. |
| Abandoned auto/once after verified child exit | Settle uncertainty once. A new attempt may run at allowed timing; never redispatch the old attempt. |
| Preflight succeeds, fails, or is abandoned | Retain separate attempt/liveness evidence and known cost, but do not stamp automatic cadence, modify automatic failure streak, or acknowledge items. |
| Report encounters expired running claim | Display uncertain/expired state without writing or settling storage. |
| Report encounters attempt plus matching committed digest | Join by attempt ID and count known cost once; preserve unknown cost rather than inventing zero. |

## Additional implementation acceptance cases

- Deferred privacy root references a missing parent; that parent appears after preparation while old hashes stay unchanged: supersede.
- A new linked successor extends a deferred privacy root after preparation: supersede.
- A new unrelated run appears: batch membership, input bytes, and freshness remain unchanged.
- New selected identity changes an earlier summary from redacted value to permitted identity near 65,536 UTF-8 bytes: rerender and enforce exact whole-item cap.
- Deferred run/site/note identities matching a task canary never become retained exemptions.
- Changed/deleted privacy contributor prevents reconstruction: refuse with fixed sanitized diagnostics, never echo reply contents or raw parse errors.
- Provider/schema/semantic failures and post-rename recovery exercise actual batch, envelope/receipt, digest, attempts/state, and reporting sinks; inspect all output and files for selected/deferred/excluded canaries.

## Preparation status

This note is design/preparation evidence, not implementation or passing-test evidence. Candidate source ownership remains with the assigned stage implementer. No source edits are authorized by this note.
