# Implementation clarifications

These preserve the approved robustness design and resolve inherited implementation details.

1. Candidate source lives below the active worktree in an ignored directory. Live MCP processes use the root checkout, so source activation is separate.
2. `review_runs.py preflight` is a third paid launcher. It shares dispatch singleflight with auto/once, preserving its $0.05 cap and absence of daily scheduling stamps/committed digests.
3. The older readiness case 25 carries the previous goal's loading state. Proposal revision 3 and READINESS-3 supersede it: a valid new goal resets tracking; invalid policy preserves it. Test the replacement explicitly.
4. The older readiness case 26 accepts a loaded DONE with a pending stop. The Agent boundary supersedes it: deadline/cancellation wins even without a loading wait; retain completed request usage and discard the result.
5. Browser Harness 0.1.13 drain_events clears the shared daemon queue. READINESS-1 requires an isolated event subscription/queue; do not call the global destructive drain. Preserve request scope, loss diagnostics, five-second input age, and no minimum wait.

Source design documents remain preserved. Every inherited acceptance case must map to an actual test or an explicit superseding contract above.
6. The inherited readiness OOPIF fixture needs an explicit second owned fixture origin (localhost alias versus 127.0.0.1) to the same fixed fixture server. Add it only for READINESS native checks, never arbitrary forwarding, and revalidate denial probes. A blocked iframe cannot establish OOPIF exclusion behavior.
7. LIMITS final verification uses a named independent five-second budget (the existing normal transport scale), one snapshot attempt plus optional screenshot within its remaining budget, and no post-input settling or retry. It records final_read_ms/fresh outcome and cannot erase execution stop/uncertain attempt. Setup remains separately bounded and timed; invalid policy/goal cannot mutate existing timers.
8. Batch privacy freshness must include relation descriptors for every pre-cap privacy root, including deferred roots: a previously missing parent appearing or new linked successor can change closure without changing existing file hashes. Recompute recorded relation queries against current inventory; unrelated arrivals remain irrelevant. Persist only IDs/base hashes/relations, never raw values.
9. Batch identity exemptions derive from selected output evidence only; privacy values derive from the complete pre-cap closure. Trial whole-item selection uses fixed per-item nonces and rerenders selected blocks before checking exact UTF-8 bytes, because a newly selected identity can lengthen an earlier block by exempting text from redaction. Saved sent_text is published once and reused verbatim.
