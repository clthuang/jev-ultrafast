# Review store activation and compatible rollback

Status: rehearsed on disposable stores only (`scripts/rehearse_activation.py`, RELEASE-3). No real store was migrated
and no production process was stopped or restarted. Activating a real store is a separate step, done by its owner with
this procedure, after GATE-RELEASE.

## What changes, and where

The review store is the `artifacts/` folder of the checkout the server runs from, resolved from its working directory:

| Path | Before (baseline `3efae4f`) | After |
| --- | --- | --- |
| `artifacts/site-notes.json` | a list of notes | the schema-2 envelope: the same notes, field for field, and a `pending_review` receipt slot |
| `artifacts/runs/*.json`, `*.jpg` | run files and screenshots | unchanged by the migration; new runs gain fields older readers ignore |
| `artifacts/reviews/<YYYYMMDD-HHMMSS>.json` | review digests | kept as history; they acknowledge nothing (below) |
| `artifacts/reviews/<batch ID>.json`, `batches/`, `attempts/` | — | committed digests, immutable batches, paid attempts |
| `artifacts/reviews/state.json` | the review schedule | the same keys, plus `schema_version` and `accounted_attempt_ids` |
| `artifacts/review-exclude.txt` | exclusions | unchanged |

Writers take the store's locks in one order: `reviews/.dispatch.lock` (held for a paid review's whole run),
`reviews/.lock`, `runs/.metadata.lock`, then `site-notes.lock`. Every command below takes them without waiting, so a
held lock means a writer is running and the command refuses, having changed nothing.

`scripts/migrate_review_storage.py` runs from the checkout whose store it serves and never signals a process, launches
a review or calls a model.

## 1. Inventory and quiescence

```sh
uv run python scripts/migrate_review_storage.py inventory
```

It prints the store's notes format and counts, any pending receipt, the review records, the four locks, leftover
temporaries, and the writers it finds. It exits 0 only when nothing blocks.

- **Blocking:**
  - a held lock;
  - a writer: a process running `jev-mcp`, `jev`, `jev_ultrafast.mcp_server` or `.demo`, `scripts/review_runs.py`, a
    recorder or an example, whose working directory is this checkout, or cannot be read;
  - a review attempt that is claimed, spawning, running or returned;
  - a review state still marked running.
- **Damaged:** a record no reader accepts. A backup still copies it as evidence. The migration and the compatible export
  refuse until you repair it from that evidence, never by starting from an empty store.

Stop each writer through the application that owns it, never by a process number found earlier:

1. Quit the Claude Code sessions that run the server, and close the inspector.
2. Set `JEV_AUTO_REVIEW=0` in `.env`, so no new automatic review starts while you work.
3. Let a running paid review finish, or settle it with `uv run python scripts/review_runs.py resolve <attempt ID>`,
   which never signals a process.

Run `inventory` again until it exits 0. A writer you cannot attribute to an owner blocks activation.

## 2. Backup

```sh
uv run python scripts/migrate_review_storage.py backup --to <a new, private folder outside artifacts/>
```

It holds all four locks, copies every store file (locks and crash temporaries are not state), and writes
`backup-manifest.json` with each file's SHA-256. It then reads every copy back against the live file, still under the
locks. It refuses an existing folder, a folder inside the store, a symbolic link in the store, and any blocking item.
Keep the backup. It is evidence of this moment, never something to restore over later work (§5).

## 3. Switch the source

Check out the release commit and run `uv sync`. Before any writer starts, check that the code you will run is that
commit:

```sh
git rev-parse HEAD
uv run python scripts/wheel_smoke.py
```

`wheel_smoke.py` imports the public API from an isolated install of the built wheel.

## 4. Migrate

```sh
uv run python scripts/migrate_review_storage.py migrate --backup <the backup folder>
```

It holds the dispatch, review and metadata locks. Then, in one notes transaction, it does three things:

1. It checks that the store is still exactly the backup. If anything changed since, it refuses: take a new backup.
2. If a review receipt is pending, it publishes the exact digest that receipt holds, without applying any decision
   again.
3. It writes the notes as the schema-2 envelope.

Afterwards it checks that every note equals the backup's and that no run file changed. It refuses an unreadable notes
file. A store without a notes file has nothing to convert; the server creates the file on first use, as before.

## 5. Restart and verify, automatic reviews still off

Start the server again. Then check these before restoring `JEV_AUTO_REVIEW`:

- `uv run python scripts/report_runs.py` reads every run, label, note and review: old and new formats together.
- `uv run python scripts/review_runs.py queue` prints what the next review would read. A run whose label changed after
  its review is listed again.
- One disposable run, through the server, ends with an explicit `allowed_operations` and a run file. No live goal or
  paid review is needed.

Record when you restore `JEV_AUTO_REVIEW`, separately from the activation.

**The temporary backlog.** A legacy digest is history: it acknowledges nothing, because it cannot say which version of
a run it reviewed. After activation, a review therefore sends again any run the baseline already reviewed, if it still
has a reason to wait. Automatic reviews look only at runs from `BUILD_DATE` (2026-09-27) on (`AUTO_FROM`). The backlog
drains at most 25 runs, 5 notes and 65,536 bytes per batch, at one automatic review a day, each capped at $0.50.

## 6. Compatible rollback

Never restore the backup over a store that changed after it: labels, notes, receipts and acknowledgments written since
would be lost. `migrate` refuses such a backup too. To go back to the baseline code:

1. Quiesce again (§1).
2. If the inventory shows a pending receipt, run `uv run python scripts/review_runs.py recover`.
3. Export:

   ```sh
   uv run python scripts/migrate_review_storage.py export --to <a new folder> --compatible
   ```

   It refuses while a receipt is pending, a record is damaged or a writer blocks.
4. In a checkout of the baseline, move its `artifacts/` aside (never delete it) and put the export in its place.

What the export holds:

- every current file, every v2 record included, so the store can be reactivated later;
- the notes as the list the baseline reads;
- the review state with only the baseline's keys, its failure count kept and nothing running;
- one more legacy digest. It lists the runs and notes that committed reviews acknowledged at the version the store holds
  now, with the baseline's own note hash.

So the baseline neither reviews again what was acknowledged, nor skips what changed after its review.
`tests/test_storage_activation.py` proves this with the baseline's own code, frozen byte for byte in
`tests/fixtures/baseline/`.

A plain `export --to <folder>` is the current-format copy, with a pending receipt kept as it is, for a reader that
understands the new format.

## Rehearsal evidence

```sh
uv run python scripts/rehearse_activation.py
```

The rehearsal runs two disposable stores. One is as the baseline left it: list notes with approved and retired ones,
a corrected label, a legacy digest, a screenshot and the baseline state. The other is a mixed store with a committed v2
review, its attempt, and a pending receipt. Every command runs as an operator runs it, from the disposable checkout,
and a fake `claude` first on `PATH` records any paid launch.

Each store goes through these checks:

1. Two owned stand-ins for old writers (a server holding the review lock, and the review CLI) make `inventory` exit 1
   and name both.
2. A backup attempted then is refused and changes nothing.
3. Once they are stopped, the store is quiescent and the backup holds every store file, read back.
4. The migration converts the notes and recovers the receipt. Today's report and its automatic review (off) run.
5. A new note and a new label are written. The stale backup is then refused.
6. The baseline code reads the compatible export: every note, the new one included, well formed. It waits for what
   today's code waits for, less the runs only its own legacy digests reviewed, and the export's digest marks nothing
   that still waits. It keeps the failure count.
7. No review attempt was created after the store was built. The fake `claude` never ran.

Result on 2026-10-04: every check passed. The evidence file is `<root>/rehearsal.json` with each command, exit code
and output.

## Limits

- **Writer detection was rehearsed on Linux only** (`/proc`). On macOS it uses `ps` and `lsof`, untested here, so read
  the inventory's writer list yourself before trusting an empty one.
- **Detection finds what runs from this checkout.** A writer started from another folder writes another store.
- **The rehearsal's writers are stand-ins** with the real programs' names and working directory. No real server, review
  or browser was stopped.
