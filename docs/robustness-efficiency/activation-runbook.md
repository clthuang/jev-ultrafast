# Activation and compatible rollback

This runbook is for a separately authorized deployment. Implementing and validating the candidate does not migrate production storage, restart services or authorize paid reviews.

Candidate and evidence: `artifacts/robustness-efficiency-completion/20261004/`. Use the final immutable source manifest, completed release checks, independent review, premortem, storage rehearsal and reconstructed patch from that directory. Earlier dated candidate directories are historical.

## Before activating

1. Confirm the exact checkout, its current revision and its local changes. Validate the exported patch against the recorded merged baseline. Preserve unrelated work.
2. Inventory every MCP server, review child and other process that can write the chosen artifact tree. Identify each by executable, full arguments, cwd and birth identity. Historical PIDs are not shutdown instructions. Disable new dispatch and stop the identified writers through their owning service/session; verify they have exited. An unknown owner blocks activation.
3. With writers stopped, create a new backup outside the active artifact tree and record its exact file inventory and checksums. Include runs, reviews, notes, exclusions and scheduling/attempt state. Read the backup back and verify it.
4. Review the installed wheel/import check and native local-fixture evidence for the exact candidate. Keep credentials server-side and `.env` out of the candidate and exported patch. Choose the activation checkout and service configuration explicitly.

The migration CLI does not stop legacy writers for you. Short storage locks cannot make an old list-only writer safe after envelope activation.

## Migration and restart

Run these commands from the selected source checkout with its installed environment. The storage tools live in `scripts/`; a wheel-only installation does not provide this operational interface. Replace the paths with the explicitly chosen artifact tree and a new external export directory; these are operational examples, not commands already run on production.

```sh
uv run python -m scripts.migrate_review_storage --artifacts /absolute/active/artifacts --migrate
uv run python -m scripts.migrate_review_storage --artifacts /absolute/active/artifacts --export /absolute/new-export
```

Migration retains legacy note fields and creates the schema-2 envelope. Unknown versions or malformed storage must be investigated rather than overwritten. Export copies `runs/*.json`, `reviews/**/*.json`, `site-notes.json` and `review-exclude.txt` with a checksum manifest. It does not copy screenshots, process logs or arbitrary artifact files; keep the full backup separately. Verify this complete expected export file set and every checksum against the active source; checking only whatever happened to be copied is insufficient.

Review storage paths are cwd-relative. Before starting new writers or enabling automatic/paid dispatch, recover any `pending_review` receipt using the new implementation and confirm that its immutable digest is durable. The following snippet checks that its cwd targets the SAME artifact tree used for migration/export and holds the required review lock. Run it from the operational source checkout. The absolute path is an example to replace deliberately:

```sh
JEV_ACTIVE_ARTIFACTS=/absolute/active/artifacts uv run python - <<'PY'
import os
from pathlib import Path

expected = Path(os.environ['JEV_ACTIVE_ARTIFACTS']).resolve()
if expected != Path('artifacts').resolve():
    raise SystemExit('Wrong operational cwd: artifacts path does not match migration/export')
from scripts.review_runs import recover_pending, review_lock

with review_lock():
    recovered_digest = recover_pending()
print('Receipt recovery completed:', recovered_digest)
PY
```

Recovery must not be replaced with a paid `once` or `preflight` command. After verification, start only the new envelope-aware readers/writers with this same checked cwd.

Verify note readability, complete outcome histories, pending receipt state, exact acknowledgment versions, exclusion/cutoff configuration and the previous attempt/scheduling state. Enable dispatch only after these checks. Keep the original backup as audit evidence.

Manual review uses a frozen batch. `uv run python -m scripts.review_runs queue > /absolute/review-input.txt` prints its batch identity; apply a reply to that exact identity using `uv run python -m scripts.review_runs apply --batch BATCH_ID < reply.json`. Queue membership is not acknowledgment. Never substitute a current queue for the saved batch.

## Failure or rollback

Stop new dispatch and quiesce the exact current writers again. Export the current run/review JSON state, notes and exclusions to a new external directory with the command above. Preserve all new notes, labels, attempts, exclusions and receipts, including work written after the original backup. Retain both the active and exported trees while investigating.

If note replacement committed but digest publication failed, the pending receipt is the recovery authority. Start a fresh process using the new code against the exported state, recover the receipt, and replay the same reply only against its original batch. Verify no duplicate notes and exact acknowledgment versions. A conflicting digest or reply needs investigation; do not clear the receipt manually.

A rollback can use only a reader/writer version compatible with the schema-2 envelope and receipts, or an explicitly reviewed compatibility conversion that preserves current state. Restoring a pre-migration list or stale backup over the current tree loses committed work and is not a supported rollback.

## Rehearsal scope

The disposable release rehearsal seeds legacy data, refuses migration while its verified dummy writer is alive, confirms writer exit, verifies backup completeness, migrates, writes a new note and outcome correction, injects post-commit digest failure, exports pending state, recovers in a fresh process and verifies identical replay plus complete current export. Its synthetic attempt fixture makes no paid model call. Read the recorded assertions and checksums before treating the rehearsal as passed. It does not establish real-service startup or live-site performance.
