# Current executor and review contracts

This document describes the robustness and efficiency implementation candidate. The original design documents and performance recordings retain their historical evidence. Deployment, storage migration, service restart and paid real-site benchmarking are separate actions.

## Goal and execution boundaries

Every `Agent` construction, `new_goal` and MCP `run_goal` call requires an explicit `allowed_operations` list. Supported entries are `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN` and `WAIT`. Empty lists permit observation and terminal answers. `DONE` and `BLOCKED` are implicit terminal choices. Invalid goals or policies are rejected before browser work or previous-goal changes. `allow_commit` does not expand the operation policy.

The model chooses from observed targets. It cannot supply selectors or executable code. Policy checks precede text generation and input. A SELECT validates the observed option identity, owner, index, meaning and enabled state in the same synchronous evaluation that changes selection. Multi-select controls remain evidence only. For atomic SELECT, only a tagged rejection before input is retryable as stale; policy refusal and snapshot overflow remain terminal. An ambiguous dispatched mutation is never retried.

Execution has one cooperative 90-second monotonic deadline beginning at the first tick, prediction or action. HTTP phase limits and browser response limits are capped by remaining time; this is not a hard total-response deadline. Late model results are accounted before being discarded. Cancellation or expiry prevents new input. A confirmed press may receive one matching release. The 120th stale recovery stops before another recovery read. Final MCP verification is independently bounded to five seconds and one observation attempt.

Terminal state is `done`, `blocked` or `stopped`. Stops clear executable pending decisions and text while preserving history and uncertain input phases. Stop codes include `operation_not_allowed`, `execution_deadline`, `stale_recovery_limit`, `snapshot_too_large`, `snapshot_protocol_error` and `readiness_connection_error`. A model DONE choice alone is never outcome proof.

## Snapshot and readiness boundaries

Schema-2 observations keep exact freshness baselines in the browser and transport bounded tokens and guard references. A freshness check compares against the installed observation without replacing it. The progress fingerprint excludes protocol identity but preserves meaningful geometry, scrolling and multi-select state. Legacy stored observations remain readable as history and cannot authorize execution. A newly returned malformed or unsupported observation is rejected before model work or input with `snapshot_protocol_error`; it cannot trigger a fallback final read.

The action cap is applied before target guard construction. At most 250 target guards are built, shared scope text is memoized and strong node references are limited to offered controls/options. Serialized observation content is limited to 262,144 UTF-8 bytes, excluding screenshots. Oversize observations stop execution explicitly; an old diagnostic page is not fresh outcome evidence. These limits bound transferred data and guard work, not arbitrary DOM traversal time.

Readiness uses an owned CDP connection, session and event queue for the exact target. It does not drain a shared daemon event buffer. Request/frame scope, event loss, disconnects, observer closure and bounded setup are observable. During a command or valid continuation, observer connection/cleanup failure stops execution and clears pending decisions. Context-manager cleanup preserves an existing body exception with a fixed diagnostic; standalone close failures still raise. Loading can hold a decision without inserting a minimum wait, with a five-second input-age cap. The existing two-unchanged-WAIT handoff remains in force.

Only a post-step observation timeout is eligible for up to two extra observation reads, after execution has been logged and saved. Input, text generation, freshness checks and final verification are not retried by this mechanism. A valid new goal resets loading state; invalid arguments preserve the previous goal. Deadline and cancellation checks take precedence over late DONE.

## Run and review storage boundaries

Execution writers and outcome-label writers share the stable metadata lock for their run directory. Saving execution preserves the complete persisted outcome history; adding a label preserves execution fields. Malformed persisted data fails publication without replacement.

Review batches and paid-attempt records use schema 1; note envelopes and committed digests use schema 2. A batch freezes exact input text and version dependencies. Input membership is separate from acknowledgment: only the exact versions actually reviewed are acknowledged. Privacy closure includes deferred and excluded contributors before the 25-run, five-note and 65,536-byte input caps. Corrupt or incomplete privacy dependencies fail closed.

The note envelope contains `schema_version`, `notes` and `pending_review`. Notes plus the pending receipt are published atomically at the note replacement commit point. The receipt is recovered into a durable immutable batch-named digest before it is cleared. Identical replay returns the prior result; conflicting replies are rejected. Ordinary note writers preserve a pending receipt.

Lock order is dispatch → review → metadata → notes. Only the dispatch singleflight lock is held during a model wait. Automatic reviews, manual `once` and preflight share dispatch ownership. Preflight does not alter automatic scheduling or failure streaks. Recovery requires precise child ownership; a PID alone is insufficient. Reported cost is deduplicated by attempt; this does not promise exactly-once provider billing.

Reports are read-only and chronological. They distinguish paid attempts, committed reviews, complete input membership and exact acknowledgments, while respecting exclusions and redaction. Legacy history remains visible.

## Activation and evidence

Use the [activation runbook](activation-runbook.md) before any real migration. Old list-only note writers must be stopped before activating envelope storage. A rollback must preserve new outcome labels, notes, receipts, attempts and acknowledgments; do not copy an old backup over current data.

The candidate, immutable stage manifests, raw test results, native measurements, independent reviews, migration rehearsal and patch reconstruction are recorded under `artifacts/robustness-efficiency-completion/20261004/`. The final completion record names the accepted source revision and any validation limits. Offline/native fixture results do not establish paid-provider billing behavior, general website support or real-site speed.
