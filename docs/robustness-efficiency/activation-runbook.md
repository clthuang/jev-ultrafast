# Candidate activation and compatible rollback

Status: draft operational procedure. No activation, live migration, or production restart has been performed. This document will be reconciled with the final tested CLI and the disposable rehearsal before RELEASE-3 can pass.

## Release prerequisites

Use the reviewed candidate under `artifacts/robustness-efficiency-implementation/20261003T100051Z/candidate`. Every gate through GATE-RELEASE must have raw validation output, an immutable source hash manifest, and zero unresolved review blockers. Native fixtures prove only their observed correctness and transfer measurements; no paid or public-site benchmark has been run.

`export_candidate.py` builds a binary-capable patch from the captured baseline and candidate, checks that production source and the captured baseline still match, dry-runs and applies the patch in a disposable copy, and verifies that every reconstructed source file has the final candidate hash. It does not apply the patch to the running checkout. Production drift or an already-existing export directory causes refusal. Do not bypass a drift refusal: review and reconcile concurrent user changes, then recapture/revalidate the affected candidate.

## Writer inventory and quiescence

The production checkout is `/Users/terry/projects/jev-ultrafast`. Its cwd-relative state includes `artifacts/runs/`, `artifacts/site-notes.json`, `artifacts/review-exclude.txt`, and `artifacts/reviews/`. Include the entire review directory so batches, attempts, committed digests, state, and any pending receipt remain available for recovery. Do not copy `.env` into the candidate or release evidence.

Observed live source users at resumption were MCP processes 75343, 98672, 15994, and 35399, and browser-harness daemon 386. These IDs are an inventory observation, not a future permission to signal them. Before activation, resolve current command, executable, cwd, parent, and process start identity again. Identify any new MCP, demo, manual review, automatic review, recording/example runner, and owned review child. A running root MCP can spawn `scripts/review_runs.py` afresh, so replacing source while leaving it running would mix generations.

For the actual activation window, stop old writers through their owning application/session, disable new launches temporarily, and verify exit and identity. Do not kill a process merely because its PID matches this document. Review launch ownership that cannot be established blocks activation. Browser processes may serve unrelated work; do not close them globally. Quiesce each source/storage writer before publishing a notes envelope. Keep the dispatch → review → metadata → notes lock order when acquiring implementation locks; no short metadata/notes lock may be held during a model wait.

## Backup and source switch

After quiescence, capture a complete backup of current state and source patch with SHA-256 manifest in an access-controlled location. Validate the backup by reading it back and comparing hashes. Record the current source hash manifest, schema versions, process inventory, and whether a receipt is pending. Do not treat an earlier implementation baseline as a backup of current user state.

Apply only the reconstructed, reviewed patch after its current-baseline check passes. Install the compatible tested runtime and dependencies, then verify imports and shipped snapshot/static assets. An old executable entrypoint that imports changed files from an unexpected path is a failed activation check.

Migrate only with the final release's tested migration/recovery API. Legacy list notes become schema 2 without dropping approvals, retirement, counters, or pending receipt data. Run outcome corrections remain in order. Resolve pending receipts into the exact immutable digest before permitting another apply or paid dispatch. Unknown schemas, corrupt files, dependency conflict, or publication uncertainty stop the operation; preserve evidence and do not overwrite it with an empty store.

## Restart verification

Start new readers/writers with automatic paid review disabled for the initial check. Verify the runtime source path and schema support, read notes and mixed legacy/current review records, and inspect a disposable run through the public API. Confirm explicit `allowed_operations`, stopped-state behavior, no duplicate input, and receipt/acknowledgment reporting. No live goal or paid review is needed to validate the source switch. Restore the previously intended review setting only after the activation checks pass and record that action separately.

## Compatible rollback

A code rollback after schema migration must use a tested schema-2-compatible reader/writer or the tested export route. Do not restart old list-only note writers against an envelope; do not restore stale notes/runs/review backups over newer labels, notes, receipts, or acknowledgment history. First quiesce current writers, recover pending receipts if supported, and export all current state with a checksum manifest. A compatibility export must retain both the legacy-facing data and the authoritative current metadata needed to avoid duplicate notes or reviews. If this cannot be proved, leave writers stopped and keep the current data intact.

Rollback rehearsal must demonstrate that notes and outcomes added after migration survive, that already committed decisions are not repeated, and that pending receipt and exact-version acknowledgment history remain recoverable. No fixture or backup is promoted into production by the rehearsal.

## Required disposable rehearsal evidence

The rehearsal will use separate fixture storage and fake launchers. It must cover legacy approved/retired notes, corrected labels, legacy digests, a versioned batch and attempt, pending receipt recovery, a post-migration note/outcome write, compatible export/reload, and zero paid launches. Capture process detection/quiescence against owned dummy writers, backup readback checksums, all commands and results, before/after state assertions, and cleanup proof. This draft is not evidence that the rehearsal has passed.
