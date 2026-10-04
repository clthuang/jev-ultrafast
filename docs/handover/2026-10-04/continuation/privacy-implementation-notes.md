# PRIVACY-1 implementation preparation

Minimal patch: keep `site_notes.task_value_pattern()` unchanged and add overlap handling locally in `review_runs.py`.

1. **Overlap helpers:** compile `(?=(...))` around the existing pattern and use `match.span(1)`, not the zero-width outer span. Merge overlapping spans and rebuild text once. Keep `spans()` for kept/guard patterns only—it assumes the named `run` group exists.
2. **Used fields:** add `USED_FIELDS = {"add": ("detail",), "flag": ("note",), "retire": ("note",)}`. Schema validation still checks every field; semantic task-value refusal checks only these fields. Persisted unused fields still get sanitized.
3. **Trusted outcomes:** preserve fixed diagnostic wording; change retirement’s dynamic site slot to the validated note ID: `it cites no queued run on <note ID>'s site`. Exempt only server-constructed outcomes. Current `OSError` messages also enter `outcome`, so sanitize that exception slot before marking it trusted.
4. **Quoted errors:** add optional compatible `quote` arguments to `schema_errors()` and `result_failure()`, propagate through both recursive schema branches, and quote dynamic slots only. **Sanitize before clipping**, so a value crossing the label boundary cannot leave a leaked prefix.
5. **Shared privacy context:** construct the value pattern, kept identities, run IDs, and quoting callback once per queue/batch. Pass that context to summary, reply, refusal, provider-error, and persisted-output handling.

Required fixture assertions:

| Test | Exact assertions |
|---|---|
| `test_note_checks_read_only_the_fields_each_action_uses` | Add with canary only in `note` applies; flag with canary only in `detail` applies; flag with canary in `note` refuses with `its note holds a value from a task`. Canary absent from persisted freeform fields and printed output. Add retire-with-unused-detail as an extra case. |
| `test_a_decisions_outcome_is_kept_whole` | With `"from"` typed, refusal remains exactly `its detail holds a value from a task`. Wrong-site retirement names `<note ID>'s site`, preserving the whole permitted identity. |
| `test_a_failure_never_quotes_a_task_value` | Unknown key becomes `<value>` while trusted `reply` remains; failed result text becomes `<value>` while trusted `ended` remains. Assert persisted failure and console text. Add nested unknown-key propagation. |
| `test_overlapping_task_values_are_replaced_together` | Values `{"jane smith", "smith bo lee"}` redact `"jane smith bo lee"` to exactly `<value>` through both `scrub()` and `without_values()`. With kept `"jane smith"`, `holds_value()` must return `True`; testing without that exemption would miss the bug. |
| `test_overlap_redaction_preserves_no_canary_fragment` | Cover mixed case/separators, empty pattern, and overlap across a kept identity. Standalone `"jane smith"` stays; the crossing cluster redacts completely. No bare `"jane"`, `"bo"` or `"lee"` remains. |
| `test_all_output_surfaces_share_privacy_rules` | Feed selected/deferred/excluded synthetic canaries through dummy batch, receipt, digest, attempt, state, and console renderers using the same context. Preserve approved identities and fixed refusal wording. Mark this as prerequisite coverage; actual writer coverage comes in REVIEWS-7. |

Three additional sink cases deserve explicit assertions:

- A canary starts just before `LABEL_CHARACTERS` and ends after it: no truncated prefix survives.
- An exception or failed-result `subtype` contains a canary: those dynamic slots are sanitized too. Current `launch_review` crash formatting and `start_failure` tool/server slots need the same scrutiny.
- A model-supplied `"outcome"` key is rejected/sanitized as untrusted; its name must not grant the exemption reserved for constructed diagnostic records.

Retain the existing comprehensive summary test unchanged in meaning: URL decoding/userinfo/query removal, email handling, excluded predecessors, known versus unknown run IDs, marker defanging, and the bounded long-input check.

No source edits or test runs performed.

## Continuity and scope

- This note preserves the PRIVACY-1 matrix from executor-improvements-plan tasks 3.1, 3.2, 3.5 and 3.6 (F1/F6/F7/F8). F2 remains the atomic receipt transaction in REVIEWS-4, not a delete-ack workaround.
- Source ownership remains with the current LIMITS implementer until root explicitly hands off. Saving this file is evidence-only, not an implementation change.
- Later schemas, crash cases, dispatch accounting, and preflight behavior are recorded in `review-storage-implementation-notes.md` in the same evidence directory.
