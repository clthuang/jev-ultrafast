# Implementation plan: failure log, review and site notes

**Source design:** `docs/failure-review.md` v4.4, "the design" below. The user approved v4 on 2026-09-26, with the
decisions in its §12; v4.1–v4.3 add details found while planning, and v4.4 is the user's fix after 8.2's first attempt.

**Status:** done on 2026-09-29. Every task below is done; `artifacts/failure-review-implementation/phase-8-record.md`
records the paid phase.

**Review of this plan:** reviewed on 2026-09-26 by one independent reviewer and by calvin, over both halves; then
broken into dependent tasks, and the breakdown reviewed independently. See "Review of this plan" at the end.

**Status (2026-09-27):** in progress. Nothing in this plan is committed. Each task's status is in the task graph.

**How to use this plan:**

- **Order:** the task graph below is the source of truth.
  - **When a task may start:** once every task in its "Depends on" column is done.
  - **When it is done:** when its check passes.
  - **The listed order** is one valid order.
- **Status:** one of `Not started`, `In progress` or `Done`. Only the person or agent running the plan edits the
  Status column; lanes report their tasks done to them.
- **Lanes:** each task belongs to one lane, and each lane owns its files. No task edits another lane's files.
  - **At once:** tasks in different lanes may run at the same time.
  - **In order:** within a lane, each task depends on the one before it, so they never overlap. The setup and QA
    lanes are the exceptions: their tasks touch different files, or none.

  | Lane | Files it owns | Test files its tasks run |
  | --- | --- | --- |
  | setup | `artifacts/review-exclude.txt`, `scripts/phase10/run_arm.py`, `AGENTS.md` | all, at Gate 0 |
  | site notes | `jev_ultrafast/site_notes.py`, `tests/test_site_notes.py` | `tests/test_site_notes.py` |
  | server | `jev_ultrafast/mcp_server.py`, `tests/test_mcp_server.py` | `tests/test_mcp_server.py`, `tests/test_site_notes.py` |
  | review | `scripts/review_runs.py`, `tests/test_review_runs.py` | `tests/test_review_runs.py`, `tests/test_site_notes.py` |
  | report | `scripts/report_runs.py`, `tests/test_report_runs.py` | `tests/test_report_runs.py`, `tests/test_site_notes.py` |
  | docs | `README.md`, `docs/claude-code-integration.md`, `docs/failure-review.md` | all, at Gate 6 |
  | QA | nothing tracked, until Gate 6 closes the other lanes | all |
  | paid | `artifacts/reviews/` | none |

- **Checks:** every task ends with a **Check**: a command or file condition, with its expected result.
  - **Also part of every check, where they apply:**
    - the lane's test files pass, with no failure;
    - `uv run ruff check <the files the task changed>` → `All checks passed!`.
  - **A task's tests run by name,** so its check holds in any valid order. For task 2.1:

    ```sh
    uv run pytest -q tests/test_site_notes.py -k "test_site_key_strips_www_and_keeps_subdomains or test_hints_are_the_four_with_a_sentence_and_a_short_form or test_seeds_are_the_four_approved_notes_of_the_design"
    ```

  - **`→ 3 passed`** means the last line starts with `3 passed` and holds no `failed` or `error`. The deselected count
    does not matter.
  - **Cases:** a test listed "with N cases" is parametrized into N. Any other test is one function, not parametrized.
  - **Raw output:** where a hook rewrites commands, as RTK does in this environment, prefix each check with
    `rtk proxy`, so pytest prints its own last line.
- **Gates:** each of Phases 0–6 ends with a gate. No task that depends on a gate starts before it closes.
  1. **Independent review:** a reviewer who did not write the phase's changes reads its diff against the design
     sections in the phase's "Read first" and this plan. It writes `$S/review-phase-<n>.md`, ending with the line
     `Open blockers: <count>`.
  2. **Fixes:** the lane fixes each blocker, and the reviewer updates the file.
  3. **QA:** every check of the phase runs again, after the fixes, and then the gate's own checks.
  - **Reading the review's verdict:** `awk 'NF{l=$0} END{print l}'` prints its last non-blank line.
  - **Full repo checks** run at Gates 0, 1, 2 and 6, and at 7.5, when no lane is mid-edit. Gates 3–5 check only
    their own lane, since the other two lanes may be mid-edit then.
- **Where commands run:** from the repo root, `/Users/terry/projects/jev-ultrafast`.
- **One command is one shell call, and shell variables do not persist between calls:**
  - each fenced block runs as one call;
  - every command that uses `$S` starts with `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation;`;
  - git ignores that folder.
- **Test counts are relative to Phase 0's baseline,** so the plan holds whether or not the executor plans
  (`docs/executor-improvements-plan.md`, and one for that design's §4) land first.
  - **What "baseline plus K" means:** the last line of `uv run pytest -q` has no `failed` or `error`, and its passed
    count minus the baseline's is K.
  - **How to count:** this prints the difference. For one test file, set `TESTS` and `BASELINE` to that file and its
    baseline, as the checks say.

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; TESTS=tests; BASELINE=baseline.txt; now=$(uv run pytest -q $TESTS | tail -1); echo "$now"; echo "added: $(( ${now%% passed*} - $(cut -d' ' -f1 "$S/$BASELINE") ))"
    ```

- **Line numbers** are for commit `215381e`. Each "Read first" also names the function, which survives edits.

## The problem, and how we will know it is solved

- **Today:**
  - a failed run leaves only free-text stop notes;
  - Claude learns a site's quirk again in every session: 7 of 30 Phase 10 sessions needed more than one run, and in 4
    of them Claude tried to read the failed run's file and was denied;
  - no review runs unless someone asks.
- **Solved when:**
  1. every offline check in Phases 0–7 passes, with no paid call;
  2. Phase 8's first real review writes a digest holding the exact text sent, costs at most $0.50, and its start
     check shows no MCP server and no tool beyond structured output;
  3. the docs describe what was built (Phase 6).
- **In real use:** `scripts/report_runs.py` ends with failures by site and code, runs per sub-goal, what each note
  changed, and reviews and their cost.
  - **Your measure:** runs per sub-goal, against Phase 10's 7 of 30 sessions.
  - **Telling notes from executor changes:** the report splits runs per sub-goal by whether a note was shown. The
    executor plans change both groups; notes change only the first.

## When a check fails

- **Never loosen a check or its expected value to make it pass.**
- **Offline phases (0–7):** if the cause is inside the task's own change, and the fix stays within the design, fix it
  and run the check again. Otherwise stop, and report the check's command and its output.
- **A gate's blockers** are fixed, never waived. A blocker that needs a design change stops the plan, for you.
- **A defect in a closed lane,** found by a later task or gate:
  1. pause every task that depends on that lane's gate;
  2. reopen the lane: it fixes the defect, recorded in the Status column of the task that found it;
  3. rerun the lane's gate: its review of the fix, and its checks;
  4. resume the paused tasks.
- **Phase 8's paid calls:** never re-run one to get a pass. Stop and report.

## Task graph

**At a glance:**

```
Phases 0-2, one lane at a time:
  0.1 ─▶ 0.4, 0.5 ─┐
  0.2, 0.3 ────────┴─▶ Gate 0 ─▶ 1.1 ─▶ 1.2 ─▶ Gate 1 ─▶ 2.1 ─▶ 2.2 ─▶ 2.3 ─▶ 2.4 ─▶ 2.5 ─▶ 2.6 ─▶ Gate 2

Phases 3-5, three lanes at once, after Gate 2:
  server:  3.1 ─▶ 3.2 ─▶ 3.3 ─▶ 3.4 ─▶ 3.5 ─▶ 3.6 (also after Gate 4) ─▶ Gate 3
  review:  4.1 ─▶ 4.2 ─▶ 4.3 ─▶ 4.4 ─▶ Gate 4
  report:  5.1 ─▶ 5.2 (also after Gate 4) ─▶ Gate 5

Phase 6, docs:
  6.1 (after Gate 4) ─▶ 6.2 (also after Gate 3) ─▶ Gate 6 (also after Gate 5)

Phases 7-8:
  Gate 6 ─▶ 7.1, 7.2, 7.3 ─▶ 7.4 ─▶ 7.5 ─▶ 8.1 ─▶ 8.2 ─▶ 8.3
```

**Parallel work, with up to 6 agents:**

- **Phases 0–2:** one implementer, since every task edits `site_notes.py` or waits for it. Reviewers take the gates.
- **Phases 3–5:** three implementers, one per lane. As each lane reaches its gate, a reviewer takes it: at most three
  implementers and three reviewers. The server lane's last task, 3.6, waits for Gate 4.
- **Phase 7:** 7.1, 7.2 and 7.3 at once; they only read, apart from a test 7.3 adds for a surviving variant.

**Why Phase 4's rows come first:** the trigger, 3.6, waits for Gate 4, and the listed order must stay valid. The
server and review lanes still start together, after Gate 2.

| ID | Task | Depends on | Lane | Status |
| --- | --- | --- | --- | --- |
| 0.1 | Record the baseline | — | setup | Done |
| 0.2 | Write the exclude file | — | setup | Done |
| 0.3 | Confirm the CLI has the review's flags | — | setup | Done |
| 0.4 | Turn learning off in experiments | 0.1 | setup | Done |
| 0.5 | Add the AGENTS.md line | 0.1 | setup | Done |
| Gate 0 | Phase 0 reviewed and checked | 0.2, 0.3, 0.4, 0.5 | setup | Done |
| 1.1 | Failure codes | Gate 0 | site notes | Done |
| 1.2 | Next-step sentences | 1.1 | site notes | Done |
| Gate 1 | Phase 1 reviewed and checked | 1.2 | site notes | Done |
| 2.1 | Keys, hints and seeds | Gate 1 | site notes | Done |
| 2.2 | Run helpers | 2.1 | site notes | Done |
| 2.3 | Note checks | 2.2 | site notes | Done |
| 2.4 | The store | 2.3 | site notes | Done |
| 2.5 | Rendering | 2.4 | site notes | Done |
| 2.6 | The review state | 2.5 | site notes | Done |
| Gate 2 | Phase 2 reviewed and checked | 2.6 | site notes | Done |
| 4.1 | `queue` | Gate 2 | review | Done |
| 4.2 | `apply` | 4.1 | review | Done |
| 4.3 | `approve`, `retire`, `restore`, `enable` | 4.2 | review | Done |
| 4.4 | `auto`, `once` and `preflight` | 4.3 | review | Done |
| Gate 4 | Phase 4 reviewed and checked | 4.4 | review | Done |
| 3.1 | `build_server()` and `main()` | Gate 2 | server | Done |
| 3.2 | Run-file fields | 3.1 | server | Done |
| 3.3 | Notes in the result, and their counters | 3.2 | server | Done |
| 3.4 | The next step | 3.3 | server | Done |
| 3.5 | Lessons in `report_outcome` | 3.4 | server | Done |
| 3.6 | The review trigger | 3.5, Gate 4 | server | Done |
| Gate 3 | Phase 3 reviewed and checked | 3.6 | server | Done |
| 5.1 | The report's run and note sections | Gate 2 | report | Done |
| 5.2 | The report's review sections | 5.1, Gate 4 | report | Done |
| Gate 5 | Phase 5 reviewed and checked | 5.2 | report | Done |
| 6.1 | README | Gate 4 | docs | Done |
| 6.2 | `docs/claude-code-integration.md` | 6.1, Gate 3 | docs | Done |
| Gate 6 | Phase 6 reviewed; every lane joined | 6.2, Gate 5 | docs | Done |
| 7.1 | Only allowed files changed | Gate 6 | QA | Done |
| 7.2 | Every delegated decision has its comment | Gate 6 | QA | Done |
| 7.3 | Mutation testing | Gate 6 | QA | Done |
| 7.4 | Final independent review | 7.1, 7.2, 7.3 | QA | Done |
| 7.5 | Final checks | 7.4 | QA | Done |
| 8.1 | Preflight | 7.5 | paid | Done |
| 8.2 | The first review | 8.1 | paid | Done: the repeat passed its six checks for $0.0663, see phase-8-record.md |
| 8.3 | Status lines | 8.2 | docs | Done |

## Decisions made on your behalf

The design's D1–D17 (its §11) go into the code, with one comment per decision naming the design and its section. This
plan adds P1–P22. Those with code (P2, P3, P7–P11 and P14–P22) get the same kind of comment, naming this plan.

| # | Decision | Why | Where to change it |
| --- | --- | --- | --- |
| P1 | The module is `jev_ultrafast/site_notes.py`, and its constants take the names in design §11 (`FAILURE_RULES`, `MAX_NOTES_SHOWN`, `UNAPPROVED_DAYS` and the rest) | `notes` already means stop notes in `mcp_server.py`; the module name keeps the two apart | the file name |
| P2 | `build_server()` in `mcp_server.py` loads `.env`, builds the instructions, creates the server and adds the two tools; `main()` calls it | mcp 2.1.1's `instructions` has no setter, and loading `.env` at import would put the real keys in every test process, since tests import the module | `build_server()` |
| P3 | The report's new sections go after its existing lines, and each prints only when it has something to show. A new `--artifacts DIR`, by default the parent of `--runs`, locates the notes file, the reviews and the exclude file, which the report only reads | its tests read the first lines by position, one unpacks exactly three lines, and a test's `--runs tmp_path` must never read your real files | `main()` in `scripts/report_runs.py` |
| P4 | New tests go in `tests/test_site_notes.py` and `tests/test_review_runs.py`, each with an autouse `monkeypatch.chdir(tmp_path)`; server-path tests extend `tests/test_mcp_server.py`, and report tests `tests/test_report_runs.py` | one test file per module, as today, and no test touches the real `artifacts/` | the test files |
| P5 | Phase 8 makes two paid calls, after the mutation tests and the independent review: a preflight capped at $0.05, then one review of the runs recorded from 2026-09-24 on, capped at $0.50 | your §12 decision 1 and the design's §16 allow one review. Without the preflight, a broken login, flag or schema would use up that review, which the plan never re-runs | tasks 8.1 and 8.2 |
| P6 | The two private runs go in `artifacts/review-exclude.txt` in Phase 0, before any check reads the runs | every later check then honours the exclusion | task 0.2 |
| P7 | Seed notes live in code (`SEEDS`), with the build date as a literal for `created` and `approved`; the notes file is created from them when missing | `artifacts/` is git-ignored, so the seeds cannot be committed there. A fixed date means a recreated file does not restart their 180 days (D12) | `SEEDS` in `site_notes.py` |
| P8 | An unreadable or unparseable notes file: no notes are shown, nothing writes the file until it parses again, and replies and the report show the error | the file may hold your approvals, which a rewrite would lose | `load()` in `site_notes.py` |
| P9 | A new note on a site whose 5 notes are all approved is refused, with the reason in the reply | the design replaces only unapproved notes, and your approvals outrank a new lesson | `add_note()` in `site_notes.py` |
| P10 | Notes gain `last_shown`, a date. The instructions line takes whole notes, most recently shown first, then never-shown ones by newest approval; the report lists any left out | design §6.4 orders by most recently shown, and its note had no field for it | `instructions_line()` in `site_notes.py` |
| P11 | The review trigger never changes `report_outcome`'s reply: a start error goes to `artifacts/reviews/auto.log` | the label is already saved, and an error reply would invite Claude to label the run again | the trigger in `mcp_server.py` |
| P12 | The AGENTS.md line and experiments' `JEV_LEARNING=0` go in first, in Phase 0 | implementing agents read AGENTS.md, whose rule against site-specific plans could otherwise stop them building site notes; a Phase 10 comparison run during the build must never see notes | tasks 0.4 and 0.5 |
| P13 | Each phase's gate holds back every task that depends on it until its independent review has no open blocker; Gates 3–5 check only their own lane. The trigger (3.6) also waits for Gate 4 | your standing instruction that each phase gets independent review and QA. Three lanes build on Phase 2, so a flaw found late there would cost all three. A restarted real server must never start a half-built review | the gates, and 3.6's row, in the task graph |
| P14 | A chain is the attempts at one sub-goal: runs linked by `previous_run`, or by `pid` before the build, cut where the site changes or after a run labelled passed. The links set the order, not the IDs, since two runs saved in one second sort by their random suffix. A possible false DONE follows the link, not the chain | the design names the link but not where a sub-goal ends. This cut keeps lessons to the failures since the last pass on the site, and the link rule still flags the census's 3 early DONEs, 2 of which Claude had labelled passed | `chains()` and `possible_false_dones()` in `site_notes.py` |
| P15 | `review_runs.py` writes `next_due` and `off` into `state.json`, and `site_notes.py` owns reading it | the server and the report need the stamp and the off state, but not D16's constants, which stay in `review_runs.py`; one reader means one format across three lanes | `read_review_state()` and `review_due()` in `site_notes.py`; `next_due` in `review_runs.py` |
| P16 | Task values match as whole values, and as each of their words of 4 characters or more, at word boundaries, ignoring case; runs of 4 or more digits match between non-digits, so `UA1234` holds `1234`. A `start_at_url` URL is checked without its host | the design says "per word": a surname from a typed name must not reach a note, or a summary that leaves the machine. Shorter words are mostly common ones, such as "the" and "new", which would refuse nearly every detail. The host is the note's own site, already stored and shown, so a search for "mozilla" must not refuse MDN's URL | `task_values()`, `MIN_WORD_CHARACTERS` and `check_note()` in `site_notes.py` |
| P17 | Restoring a retired note also resets its `failed_after` to 0 | your restore overrides the retirement; keeping the count would retire it again at its next failure | `set_state()` in `site_notes.py` |
| P18 | A review's summaries also replace every e-mail address and every run of 4 or more digits, wherever they appear in their free text; run IDs, note IDs and sites stay, since the reviewer cites them | Claude's evidence and stop notes can hold an address or a number the goal never did, and summaries leave the machine | the summary builder in `scripts/review_runs.py` |
| P19 | The report's "open proposals and label flags" are those of the latest successful review, each group under its digest's path; older ones stay in their digests, whose paths the report lists | nothing records a proposal or flag as acted on, so the report cannot tell which older ones are still open, and a list of every review's would only grow | the review sections in `scripts/report_runs.py` |
| P20 | A failure counts against an unapproved note only when this server's results have shown it; an approved note counts as today | an unapproved note is not in the instructions, so a new session's first run on its site fails before Claude could read it, and two such failures retired notes that help (7.4's review) | `record_failure()`'s `shown` in `site_notes.py`, and `SHOWN_NOTES` in `mcp_server.py` |
| P21 | One definition of a failed run, `run_failed()`: it did not end done, or its latest label is failed. The server's lessons, the review's queue and its recoveries all use it; a run with no result has not finished, so the queue skips it and it counts as no false DONE's next run | the server counted only runs labelled failed, the review counted any run not done, so they disagreed on one chain; a run file saved mid-run was queued as failed (7.4's review) | `run_failed()` and `possible_false_dones()` in `site_notes.py`; `build_queue()` in `scripts/review_runs.py` |
| P22 | The review's instructions ask a note's detail to name its site as its run's "site" line writes it, never as "the site" | "site" can be a task value (P16), as it is in the first review's queue, so a note decision saying it is refused (design v4.4); the instructions' own "how the site behaves" invited it. The site line's name is a kept name (P18), so it passes the reply check, and has no "www.", which `check_note()` refuses as a URL. `check_note()` (§6.5) still refuses a site whose word the chain typed (8.2's fix review: N1, R2-S1 and R2-N1) | `REVIEW_INSTRUCTIONS` in `scripts/review_runs.py` |

## Global rules

- **Repo rules:** follow `AGENTS.md`.
  - Never retry a browser mutation, and log execution before observing its result.
  - Tests must not call paid APIs.
  - Keep README claims, evidence and model-call counts consistent.
  - Do not commit or push unless the user asks.
- **Full repo checks:** at Gates 0, 1, 2 and 6, and at 7.5. All must pass.
  - `uv run ruff check .` → `All checks passed!`
  - `uv run pytest -q` → no failures, at the count the gate gives
  - `node --check jev_ultrafast/static/app.js` and `node --check jev_ultrafast/snapshot.js` → exit 0
  - `uv build` → a wheel is built
- **Cost:** Phases 0–7 are offline, with no model calls. Phase 8 makes two Claude calls, capped at $0.05 and $0.50,
  and no Jev call.
- **Automatic reviews during the build:** from 3.6 on, which waits for Gate 4, a real session's server, restarted on
  the new code, could start `auto`.
  - **What limits it:** it waits for 5 runs recorded after the build (`AUTO_FROM`), and keeps its $0.50 cap.
  - **To rule it out until Phase 8:** you can set `JEV_AUTO_REVIEW=0` in the server entry's `env`.
- **Privacy:**
  - never open the private runs: the two run IDs that `artifacts/review-exclude.txt` lists. Git ignores that file, so
    their IDs stay out of this plan, and checks read them from it with
    `grep -x -E '[0-9]{8}-[0-9]{6}-[0-9a-f]{4}' artifacts/review-exclude.txt`;
  - never read or print `.env`.
- **Files this plan may change,** and no others:
  - new: `jev_ultrafast/site_notes.py`, `scripts/review_runs.py`, `tests/test_site_notes.py` and
    `tests/test_review_runs.py`;
  - `jev_ultrafast/mcp_server.py`, `scripts/report_runs.py`;
  - `scripts/phase10/run_arm.py`: its server entry's `env` only;
  - `tests/test_mcp_server.py`, `tests/test_report_runs.py`;
  - `README.md`: the file list, one sentence in "Use from Claude Code" on codes, notes and reviews, and the line
    naming what makes paid calls; `AGENTS.md` (one line);
  - `docs/claude-code-integration.md`: §6.1, §6.2 (a paragraph after its status table), §6.3, §6.4, §7.1, §7.4 (one
    line on the report's new sections), §7.5 item 4, §7.6 and §9 item 7;
  - `docs/failure-review.md` (its status line, and §12 decision 1's list of what is sent, which gains the note
    summaries its §7.2 queues and what "typed values" covers), and this plan;
  - git-ignored files under `artifacts/`.

**Files and formats,** named once:

- **Run files, `artifacts/runs/<run ID>.json`:** a run's ID is its file's stem, and the file stores none, so the
  helpers take runs as a dict from ID to run, in ID order. The build adds three top-level keys:
  - `previous_run` (3.2): the ID of the run this server saved before, or null for its first, as in
    `"20260924-113417-40d8"`;
  - `failure` (3.2): a failure code, or null, as in `"covered_target"`;
  - `notes_shown` (3.3): the IDs of the notes the result kept, as in `["clinicaltrials.gov-1"]`; empty when none.
- **`artifacts/site-notes.json`:** a JSON list of notes shaped as the design's §6.1, `last_shown` included (P10), at
  `NOTES_PATH`. Its lock is `artifacts/site-notes.lock`. The report reads it with `create=False`.
  - **`runs`:** `{"failed": [run IDs], "recovered": a run ID or null}`; `failed` is required, and a fallback note
    has no recovered run.
  - **`retired`:** the date a note retired, or null. `load()` checks every field's type, and a file that fails shows
    no notes and reports its error (P8).
- **`artifacts/review-exclude.txt`:** `#` starts a comment; otherwise one run ID or host per line, and a host covers
  its subdomains.
- **`artifacts/reviews/`:**
  - `.lock`, held for a whole review;
  - `state.json`, at `REVIEW_STATE`, which only `review_runs.py` writes, through `write_review_state()`, and every
    lane reads through `read_review_state()` (P15):
    - `last_start`, the last start, as in `"2026-09-26T19:43:05"`;
    - `next_due`, when the next automatic review may start, in seconds since the epoch;
    - `running`, the start of a review with no end yet, or null;
    - `failures`, the failures in a row;
    - `off`, true after 3 failures in a row, until `enable`;
  - `auto.log`, the output of automatic starts, and trigger errors (P11);
  - `<YYYYMMDD-HHMMSS>.json`, one digest per review, named by its start time:
    - its keys: `queue`, `sent`, `decisions`, `flags`, `proposals`, `summary` and `cost`;
    - a failed review writes one too, with a `failure` key giving the reason, so what it sent is on record. `queue`
      ignores such digests, so their runs stay queued;
    - `queue` holds the queued run IDs, and each queued note's ID with a hash of its content, so the next `queue`
      can tell reviewed runs and unchanged notes;
    - `decisions` holds each note decision, applied or refused, with its reason;
    - the preflight writes no digest and no stamp; `once` writes both.
- **Paths:**
  - the server's and `review_runs.py`'s are relative to the working directory, like `RUNS` and `.env`. The server is
    launched with `uv run --directory <repo>`, and the script runs from the repo root. Neither anchors a path on
    `__file__`, so tests that change directory stay in their temporary folder;
  - the report's come from `--runs` and `--artifacts`.

**Anti-patterns, in every phase:**

- **The executor reading notes:** `agent.py`, `browser.py`, `model.py` and `questions.py` never import
  `site_notes`. Jev never sees a note.
- **Importing across lanes:** `site_notes.py` imports nothing from this repo, and the server and the two scripts
  import only `site_notes` from each other's lanes, so no lane's tests load another lane's half-edited file.
- **Site text in Jev's questions:** `questions.py` does not change (design D14).
- **A shell for the review:** no `shell=True`, no command string, and never the `claude` alias.
- **The parent's environment for the review:** only the six variables the design lists.
- **`notes_shown` parsed from the result's text:** a page could imitate a note ID.
- **Approval without a terminal:** `approve` never accepts a confirmation from stdin or an argument.
- **Writing outside `artifacts/`,** from the server or the scripts; and any write from the report.
- **Any network or model call in a test.**

## Phase 0: Setup

**Read first:**

- **The design:** §3–§7, §11, §12 and §16.
- **Code:**
  - `mcp_server.py`: `INSTRUCTIONS` (27–39), `NEXT` (56–61), `SERVER` (63), `start_run` (107–170), `finish`
    (182–203), `render` (238–276), `report_outcome` (279–304), `main` (324–331);
  - `demo.py`: `load_environment` (23–31);
  - `agent.py`, in `Agent.command`: the stale-streak stop (121–124), the model-call budget (136–138), history steps
    (211–241);
  - `browser.py`, in `browser_operation`: the covered-target message (226–231);
  - `scripts/report_runs.py`: `STOP_NOTES` (20–25), `facts` and `main` (59–149);
  - `scripts/phase10/run_arm.py`: the server entry (44–46).
- **Tests:**
  - `tests/test_mcp_server.py`:
    - `FakeBrowser`, `FakeAgent` and the autouse `server` fixture (47–127);
    - the `render` and `report_outcome` tests (461–564);
    - the import and server-process tests (580–618);
  - `tests/test_report_runs.py`: `DECISION`, `write_run` and `report` (9–41).

**Tasks:**

- **0.1 Record the baseline.** Save a manifest and a copy of every file git tracks or would add, for later diffs, and
  the test counts.

  ```sh
  S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; [ -e "$S/before.sha" ] && { echo "baseline exists; not overwritten"; exit 1; }; mkdir -p "$S"
  git ls-files -co --exclude-standard -z | xargs -0 shasum -a 256 > "$S/before.sha"
  git ls-files -co --exclude-standard -z | rsync -a --from0 --files-from=- ./ "$S/before/"
  uv run pytest -q | tail -1 | tee "$S/baseline.txt"
  uv run pytest -q tests/test_mcp_server.py | tail -1 > "$S/baseline-mcp-server.txt"
  uv run pytest -q tests/test_report_runs.py | tail -1 > "$S/baseline-report-runs.txt"
  ```

  - **A baseline is taken once, on unchanged files.** The command refuses to overwrite one.
  - **Check 1:** this prints three `N passed` lines, with no failure: 120, 34 and 4 on 2026-09-26, more if the
    executor plans landed.

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; cat "$S/baseline.txt" "$S/baseline-mcp-server.txt" "$S/baseline-report-runs.txt"
    ```

  - **Check 2:** `uv run ruff check .` → `All checks passed!`.
  - **Check 3:** each prints `1`:
    - `grep -c 'instructions=INSTRUCTIONS' jev_ultrafast/mcp_server.py`
    - `grep -c 'Jev answered BLOCKED' jev_ultrafast/mcp_server.py`
    - `grep -c "Reached the demo's model-call budget" jev_ultrafast/agent.py`
    - `grep -c 'went stale while the page read stayed the same' jev_ultrafast/agent.py`
    - `grep -c 'Target is covered by' jev_ultrafast/browser.py`

- **0.2 Write the exclude file (P6).** Written only if missing, so your later edits survive. `PRIVATE_1` and
  `PRIVATE_2` stand for the two private run IDs, which this plan does not print:

  ```sh
  [ -e artifacts/review-exclude.txt ] || printf '%s\n' '# Run IDs and hosts kept out of site notes, reviews and printed report text: docs/failure-review.md §6.7' "$PRIVATE_1" "$PRIVATE_2" > artifacts/review-exclude.txt
  ```

  - **Check:** `grep -c -x -E '[0-9]{8}-[0-9]{6}-[0-9a-f]{4}' artifacts/review-exclude.txt` → `2`, and
    `git check-ignore -q artifacts/review-exclude.txt && echo ignored` → `ignored`.

- **0.3 Confirm the CLI still has all 14 flags of the design's §7.4 review command.** Each must start an option line,
  so a mention in another flag's help does not count.
  - **Check:** this prints 14 `ok` lines and no `MISSING`:

    ```sh
    for f in '-p, --print' --model --tools --restricted --safe-mode --strict-mcp-config --no-chrome --permission-prompts --system-prompt --output-format --verbose --json-schema --max-budget-usd --no-session-persistence; do "$HOME/.local/bin/claude" --help | grep -q -E -- "^ *(-[a-zA-Z], )?$f( |,|$)" && echo "ok $f" || echo "MISSING $f"; done
    ```

- **0.4 Turn learning off in experiments (P12):** `scripts/phase10/run_arm.py`'s server entry `env` gains
  `"JEV_LEARNING": "0"`, before Phase 3 can show a note.
  - **Check:** `grep -c '"JEV_LEARNING": "0"' scripts/phase10/run_arm.py` → `1`, and only the `env` line changed, even
    after a commit:
    `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; diff "$S/before/scripts/phase10/run_arm.py" scripts/phase10/run_arm.py | grep -c -E '^[<>]'`
    → `2`.
- **0.5 Add the AGENTS.md line (P12):** from the design's §12 decision 3, verbatim.
  - **Check:** this prints `1`:

    ```sh
    grep -c -F 'Site notes for Claude are allowed (`docs/failure-review.md`); the executor never takes site-specific plans.' AGENTS.md
    ```

- **Gate 0.** The review confirms the three baseline files, and that 0.4 and 0.5 match the design.
  - **Check:** `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; awk 'NF{l=$0} END{print l}' "$S/review-phase-0.md"`
    → `Open blockers: 0`, and the full repo checks pass, with the suite at the baseline plus 0.

## Phase 1: Failure codes and next-step sentences (offline)

**Read first:**

- **The design:** §4 and §5.
- **Where each stop note comes from:**
  - `agent.py`, in `Agent.command`: the stale-streak stop (121–124) and the model-call budget (136–138);
  - `mcp_server.py`, in `start_run`: how stops become notes (143–170);
  - `browser.py`, in `browser_operation`: the covered-target message (226–231);
  - browser-harness's timeout message: `.venv/lib/python3.13/site-packages/browser_harness/helpers.py` line 64.

**Allowed APIs:** plain Python and `re` on the run's `result.status`, its first stop note,
`history[-1]["page_changed"]`, `decisions` and `stale_decisions`.

**Anti-patterns:**

- **A code with no sentence** (design D8).
- **Classifying from page text:** the rules read stop notes and run-state fields only.
- **Reading any note but the first:** the first is the stop reason. Later ones, such as "fresh read failed: …", are
  not.

**Tasks:**

- **1.1 Failure codes:** `FAILURE_RULES`, `failure_code(status, notes, history)` and `stale_budget(run)`, in the new
  `jev_ultrafast/site_notes.py`.
  - **One rule at most:** each rule reads the status and only the first note, and their fixed texts differ.
  - **Page text:** every rule matches fixed server text from the note's start, so page text quoted in a note, such as
    a commit stop's label, can at worst pick the wrong one of three fixed sentences.
  - **`covered_target`:** status `blocked`, and a first note that starts with "Three choices in a row went stale while
    the page read stayed the same:" and contains "Target is covered by <".
  - **`jev_blocked`:** status `blocked`, and a first note equal to "Jev answered BLOCKED".
  - **`busy_after_step`:** status `stopped`, a first note whose start matches browser-harness's timeout form,
    `[\w.]+ timed out after [\d.]+s`, and a last history step whose `page_changed` is None.
  - **None** otherwise. A done run matches no rule, and a cancelled run's first note is "cancelled".
  - **`stale_budget(run)`, the report's flag:** a note equal to "Reached the demo's model-call budget", with
    `stale_decisions` above half of `decisions`.
  - **Tests,** in the new `tests/test_site_notes.py`:
    - `test_covered_target_needs_a_stale_streak_note_naming_a_cover`
    - `test_stale_streak_without_a_named_cover_has_no_code`
    - `test_jev_blocked_is_the_blocked_stop`
    - `test_busy_after_step_needs_a_timeout_and_an_unfinished_step`
    - `test_a_timeout_before_any_step_has_no_code`
    - `test_done_and_cancelled_runs_have_no_code`
    - `test_stale_budget_flag_needs_mostly_stale_decisions`
  - **Check 1:** its tests → `7 passed`.
  - **Check 2:** the design's census gives its counts. The census is the 78 runs recorded on 2026-09-24, less the two
    private ones; later runs do not match the glob. This prints
    `76 {'busy_after_step': 1, 'covered_target': 1, 'jev_blocked': 6, 'stale_budget': 4}`:

    ```sh
    uv run python - <<'EOF'
    import collections, json, pathlib
    from jev_ultrafast.site_notes import failure_code, read_exclude, stale_budget
    private = read_exclude("artifacts/review-exclude.txt")
    counts, runs = collections.Counter(), 0
    for path in sorted(pathlib.Path("artifacts/runs").glob("20260924-*.json")):
        if path.stem in private:
            continue
        runs += 1
        run = json.loads(path.read_text())
        result = run.get("result") or {}
        if code := failure_code(result.get("status"), result.get("notes", []), run["history"]):
            counts[code] += 1
        if stale_budget(run):
            counts["stale_budget"] += 1
    print(runs, dict(sorted(counts.items())))
    EOF
    ```

- **1.2 Next-step sentences:** `NEXT_BY_FAILURE`, verbatim from the design's §5 table, with the comment "Delegated
  decision D8 (docs/failure-review.md §11)".
  - **Uses:** `FAILURE_RULES` (1.1).
  - **Test:** `test_every_code_has_a_next_step_sentence`: each equals the design's §5 text.
  - **Check 1:** its tests → `1 passed`.
  - **Check 2:** the sentences match the design, however the source wraps them. This prints `True`:

    ```sh
    uv run python -c "from jev_ultrafast.site_notes import NEXT_BY_FAILURE as n; print('never choose an entry from a password manager' in n['covered_target'] and 'first run a goal that only scrolls until it shows' in n['jev_blocked'] and 'check the page before running the goal again' in n['busy_after_step'])"
    ```

- **Gate 1.** The review reads the diff against the design's §4 and §5.
  - **Check:** `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; awk 'NF{l=$0} END{print l}' "$S/review-phase-1.md"`
    → `Open blockers: 0`; `uv run pytest -q tests/test_site_notes.py` → `8 passed`; and the full repo checks pass,
    with the suite at the baseline plus 8.

## Phase 2: Site notes (offline)

**Read first:**

- **The design:** §3, §6 in full, §7.4 "When", and D1–D7 and D11–D13.
- **This plan:** "Files and formats", under the global rules.
- **The run-file fields these tasks read:**
  - `call.url`: `mcp_server.py`, in `start_run` (136–137);
  - the final page's `page.url`: `finish` (190);
  - each decision's `request.state.page.url`: `model.py` (136);
  - typed text: each step's `text`, and each `text_calls` entry's `value`: `agent.py`, in `Agent.command` (194, 203
    and 220);
  - `pid`: `start_run` (136–142); and `previous_run`, which 3.2 adds.

**Allowed APIs:**

| API | Use |
| --- | --- |
| `fcntl.flock(fd, fcntl.LOCK_EX)` on `artifacts/site-notes.lock` | one writer at a time, across servers |
| `os.replace(temporary, path)` | atomic write, as `report_outcome` does |
| `urllib.parse.urlsplit`, `urlunsplit`, `parse_qsl` | the host key, and removing query values |
| `datetime.date` | expiry and dates |
| `re`, `json` | the task-value check, and storage |

**Anti-patterns:**

- **A URL from free text:** only `call.url` of the recovered run, checked.
- **A hint outside the set,** or a free-form hint: the design cut `other`.
- **Writing without the lock.**

**Tasks:**

- **2.1 Keys, hints and seeds.**
  - **`site_key(url)`:** the host without `www.` (D1).
  - **`HINTS`:** the four, each with its sentence and short form, from the design's §6.1 table.
  - **`SEEDS`:** the four notes of §6.2, which you approved on 2026-09-26. The build date is a literal for `created`
    and `approved` (P7).
  - **Tests:**
    - `test_site_key_strips_www_and_keeps_subdomains`
    - `test_hints_are_the_four_with_a_sentence_and_a_short_form`
    - `test_seeds_are_the_four_approved_notes_of_the_design`: the sites, hints, details and MDN URL of §6.2, approved
      on the build date.
  - **Check:** its tests → `3 passed`.

- **2.2 Run helpers,** used by the server, the review script and the report, so the three lanes agree. Runs arrive as
  a dict from run ID to run, in ID order.
  - **`chains(runs)` (P14):** a list of chains, each a dict from run ID to run, oldest first.
    - **The link:** a run's `previous_run`; for runs recorded before the build, the latest earlier run with the same
      `pid`; none when a run has neither key.
    - **A new chain starts** at a run with no link, a run whose link ended on another site (`site_key` of the final
      `page.url`), or a run whose link's latest label is passed.
  - **`possible_false_dones(runs)`:** the IDs of DONE runs whose next linked run, on the same site, took no step
    (design §4), whatever the DONE's label.
  - **`visited_urls(run)`:** `call.url`, each decision's `request.state.page.url`, each step's `url`, and the final
    `page.url` (design §6.7).
  - **`read_exclude(path)` and `excluded(run_id, run, exclude)`:** a run is excluded when its ID is listed, or when any
    URL it visited is on a listed host or one of its subdomains.
  - **`task_values(chain)`:** text of 3 characters or more typed in the chain's runs, and the quoted values, e-mail
    addresses and runs of 4 or more digits in their goals (design §6.5). Each value matches whole, and by each of its
    words of 4 characters or more (P16).
  - **Uses:** `site_key` (2.1).
  - **Tests:**
    - `test_chains_link_by_previous_run_or_pid_and_cut_at_a_pass_or_a_new_site`, which also checks that a run with
      neither key is its own chain
    - `test_a_possible_false_done_is_a_done_before_a_run_with_no_step`, which also flags a DONE labelled passed
    - `test_exclusion_matches_every_url_a_run_visited`, with 5 cases:
      - an excluded host seen only in `call.url`, only in a decision's page URL, only in a step's `url`, or only in
        the final `page.url`;
      - a listed run ID.
    - `test_task_values_are_matched_per_word_ignoring_case`
  - **Check 1:** its tests → `8 passed`.
  - **Check 2:** on the design's census, this prints
    `['20260924-052252-e4b2', '20260924-100333-757e', '20260924-111852-243b']`, its 3 early DONEs:

    ```sh
    uv run python -c "import json, pathlib; from jev_ultrafast.site_notes import possible_false_dones, read_exclude; private = read_exclude('artifacts/review-exclude.txt'); runs = {p.stem: json.loads(p.read_text()) for p in sorted(pathlib.Path('artifacts/runs').glob('20260924-*.json')) if p.stem not in private}; print(sorted(possible_false_dones(runs)))"
    ```

- **2.3 Note checks (design §6.5).**
  - **`check_note(note, chain, exclude)`:** returns the reasons a note is refused.
  - **`note_url(chain)`:** for `start_at_url`, the last run's `call.url`, only if it is https on the note's site or a
    subdomain, without its query values; otherwise None.
  - **`strip_query(url)`:** a URL without its query values, which `queue` also uses.
  - **Uses:** `site_key` and `HINTS` (2.1); `excluded` and `task_values` (2.2).
  - **Tests:**
    - `test_a_note_is_refused_for_each_failed_check`, with 14 cases:
      - a hint not in the set;
      - a site other than the run's final page;
      - a detail over 300 characters, and a detail holding a URL;
      - typed text in the detail;
      - a quoted goal value, an e-mail address, and 4 or more digits;
      - an excluded site, and an excluded run;
      - `start_at_url` without a `call.url`;
      - a URL that is not https, one on another host, and one over 100 characters.
    - `test_start_at_url_comes_from_call_url_without_query_values`
  - **Check:** its tests → `15 passed`.

- **2.4 The store,** with `NOTES_PATH`, `artifacts/site-notes.json`, relative to the working directory:
  - **`load(path=NOTES_PATH, create=True)`:** creates the file from `SEEDS` when missing, unless `create` is false. An
    unreadable or unparseable file gives no notes and its error, and nothing writes it until it parses again (P8).
  - **`update(change, path=NOTES_PATH)`:** takes the lock, loads, applies `change`, and replaces the file atomically.
    Every write goes through it:
    - **`add_note(note, path=NOTES_PATH)`:** at most 5 notes per site. A new note replaces the oldest unapproved one,
      and is refused when all 5 are approved (P9);
    - **`record_shown(ids, path=NOTES_PATH)`:** `shown`, and `last_shown` (P10);
    - **`record_failure(site, code, path=NOTES_PATH, shown=None)`:** `failed_after`, for the site's notes with that
      code that a result has shown, and retirement (D6). An unapproved note counts only when `shown` holds its ID
      (P20);
    - **`set_state(note_id, state, path=NOTES_PATH)`:** approve, retire or restore. A restore also resets
      `failed_after` to 0 (P17).
  - **Expiry (D5):** an expired note stays in the file, like a retired one, and is never shown.
  - **Uses:** `SEEDS` (2.1).
  - **Tests:**
    - `test_a_missing_file_starts_with_the_approved_seeds`, which also checks that `create=False` returns no notes
      and writes nothing
    - `test_a_writer_waits_for_the_lock`: the test holds the lock, and a writer thread signals and then adds a note.
      0.5 s after the signal the file is unchanged; after the test releases the lock, the note is stored.
    - `test_notes_expire_after_30_or_180_days`
    - `test_an_unapproved_note_retires_after_two_failures_and_an_approved_one_is_flagged`
    - `test_a_sixth_note_replaces_the_oldest_unapproved_or_is_refused`, with 2 cases:
      - 4 approved and 1 unapproved: the unapproved one goes;
      - 5 approved: the new note is refused.
    - `test_an_unreadable_notes_file_shows_no_notes_and_is_never_overwritten`
  - **Check:** its tests → `7 passed`.

- **2.5 Rendering.**
  - **`learning_on()`:** false when `JEV_LEARNING` is `0` (D10).
  - **`render_site_notes(site, code, notes)`:** returns the block, at most 900 characters, and the IDs placed. It
    checks exclusions again, and shows no expired or retired note.
  - **`instructions_line(notes)`:** lists approved notes only, at most 400 characters. It takes whole notes, most
    recently shown first, then never-shown ones by newest approval (P10).
  - **`note_excluded(note, exclude)`:** true when the exclude list names the note's site, a domain above it, or one of
    its runs. `render_site_notes()` uses it; the server and the report filter the notes they pass to
    `instructions_line()` with it, since that takes no exclude list.
  - **Uses:** `FAILURE_RULES` (1.1), `excluded` (2.2), and the store (2.4).
  - **Tests:**
    - `test_render_places_at_most_three_notes_in_900_characters_matching_first`
    - `test_instructions_line_lists_approved_notes_most_recently_shown_first_within_400_characters`
    - `test_excluded_sites_get_no_notes`
    - `test_learning_off_renders_nothing`
  - **Check 1:** its tests → `4 passed`.
  - **Check 2:** the seeds' line fits. This prints `True True`:

    ```sh
    uv run python -c "from jev_ultrafast.site_notes import SEEDS, instructions_line; line = instructions_line(SEEDS); print(len(line) <= 400, all(n['site'] in line for n in SEEDS))"
    ```

- **2.6 The review state (P15),** with `REVIEW_STATE`, `artifacts/reviews/state.json`, relative to the working
  directory:
  - **`read_review_state(path=REVIEW_STATE)`:** the file's keys, or `{}` when it is missing or unreadable.
  - **`write_review_state(state, path=REVIEW_STATE)`:** replaces the file atomically. Only `review_runs.py` calls it.
  - **`review_due(state, now)`:** true unless `off`, or `next_due` is later than `now`.
  - **Tests:**
    - `test_review_due_reads_the_state`, with 5 cases: no file; no `next_due`; a `next_due` later than now; one
      earlier; `off`.
    - `test_review_state_round_trips_and_an_unreadable_file_reads_as_empty`
  - **Check:** its tests → `6 passed`.

- **Gate 2.** The review reads the diff against the Read first's design sections. Three lanes start from this gate,
  and use only what this phase names, so the gate also pins its names.
  - **Check 1:** `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; awk 'NF{l=$0} END{print l}' "$S/review-phase-2.md"`
    → `Open blockers: 0`; `uv run pytest -q tests/test_site_notes.py` → `51 passed`; and the full repo checks pass,
    with the suite at the baseline plus 51.
  - **Check 2:** every function has the arguments this plan gives. This prints `all 25 match`:

    ```sh
    uv run python - <<'EOF'
    import inspect
    import jev_ultrafast.site_notes as site_notes
    expected = {
        "failure_code": ["status", "notes", "history"], "stale_budget": ["run"], "site_key": ["url"],
        "chains": ["runs"], "possible_false_dones": ["runs"], "visited_urls": ["run"], "read_exclude": ["path"],
        "excluded": ["run_id", "run", "exclude"], "task_values": ["chain"],
        "check_note": ["note", "chain", "exclude"], "note_url": ["chain"], "strip_query": ["url"],
        "load": ["path", "create"], "update": ["change", "path"], "add_note": ["note", "path"],
        "record_shown": ["ids", "path"], "record_failure": ["site", "code", "path", "shown"],
        "set_state": ["note_id", "state", "path"], "learning_on": [], "render_site_notes": ["site", "code", "notes"],
        "instructions_line": ["notes"], "note_excluded": ["note", "exclude"], "read_review_state": ["path"],
        "write_review_state": ["state", "path"], "review_due": ["state", "now"],
    }
    wrong = {}
    for name, params in expected.items():
        function = getattr(site_notes, name, None)
        found = list(inspect.signature(function).parameters) if function else "missing"
        if found != params:
            wrong[name] = found
    print(wrong or f"all {len(expected)} match")
    EOF
    ```

  - **Check 3:** `grep -c -E '^\s*(from|import) (\.|jev_ultrafast|scripts)' jev_ultrafast/site_notes.py` → `0`.

## Phase 3: The server path (offline)

**Read first:**

- **The design:** §3, §5, §6.3, §6.4, §6.7 and §7.4 "When".
- **This plan:** "Files and formats", under the global rules.
- **Code:** `mcp_server.py` in full; the functions Phase 2 named.
- **Tests:** those named in Phase 0, including the server-process tests, which start a real `subprocess.Popen`
  (`start_server`, 592).

**Allowed APIs:**

| API | Use | Source |
| --- | --- | --- |
| `MCPServer(name, instructions=...)`, `.add_tool(fn)`, `.run()` | build the server in `build_server()` (P2) | mcp 2.1.1, `mcpserver/server.py` 290–291 and 603 |
| `load_environment()` | read `.env` in `build_server()`; a `ValueError` is printed to stderr, and each run still reports it, as today | `demo.py` 23–31 |
| `subprocess.Popen([...], stdin=DEVNULL, stdout=log, stderr=log, start_new_session=True)` | inside `start_review()`, the one function that starts `review_runs.py auto` | stdlib |

**Anti-patterns:**

- **Reading `.env` or the notes file at import.**
- **Notes after the fields:** the result's cap cuts the fields first, and the notes must survive it.
- **Changing `result`'s three keys:** a test pins them. The new fields go at the top level of the run file.
- **Patching `subprocess.Popen` in tests:** the server-process tests use it. Replace `start_review()` instead.

**Tasks:**

- **3.1 `build_server()` and `main()` (P2).**
  - **The server:** remove the import-time `SERVER`. `build_server()` appends `instructions_line()` unless
    `JEV_LEARNING=0`, passing only the notes `note_excluded()` does not exclude, by the exclude file.
  - **The tools:** the `@SERVER.tool()` decorators become `add_tool` calls in `build_server()`, so the tools stay plain
    functions for the tests.
  - **The fixture:** the autouse `server` fixture removes `JEV_LEARNING`, so your shell's settings do not change
    results.
  - **Uses:** `read_exclude` (2.2), `load` (2.4), and `learning_on`, `instructions_line` and `note_excluded` (2.5).
  - **Tests:**
    - `test_server_instructions_list_the_approved_notes`, which also checks that an approved note on an excluded site
      is left out
    - `test_import_reads_no_env_and_no_notes`: importing, with an unreadable `.env` and a notes file in the working
      directory, reads neither.
  - **Check 1:** its tests → `2 passed`.
  - **Check 2:** this prints `False True`:
    `uv run python -c "from jev_ultrafast import mcp_server as m; print(hasattr(m, 'SERVER'), hasattr(m, 'build_server'))"`.
  - **Check 3:** with the four seeds, the instructions fit. This prints `True`:

    ```sh
    D=$(mktemp -d); uv run --directory /Users/terry/projects/jev-ultrafast python -c "import os; os.chdir('$D'); from jev_ultrafast import mcp_server; print(len(mcp_server.build_server().instructions) <= 1500)"
    ```

- **3.2 Run-file fields `previous_run` and `failure`.**
  - **`previous_run`** (D9): a module global, set only once the run file exists, after the run's keys are set. The
    autouse `server` fixture resets it, as it resets `AGENT`.
  - **`failure`:** from `failure_code()`.
  - **Uses:** `failure_code` (1.1).
  - **Test:** `test_run_file_records_previous_run_and_failure`.
  - **Check:** its tests → `1 passed`.

- **3.3 Notes in the result, and their counters.**
  - **Where:** after the "page now" line and before "fields:", inside the untrusted block.
  - **`notes_shown`:**
    - `finish()` calls `render_site_notes()` and passes its block and IDs to `render()`;
    - `render()` still returns text. It places the block, and sets `state["notes_shown"]` to the IDs whose lines
      survive the result's cut, since 60 steps can push the notes past 8,000 characters.
  - **Counters:** for a failed run, `finish()` first calls `record_failure()`, which counts against the notes earlier
    results showed, an unapproved one only if this server's results showed it (P20); then it calls `record_shown()`
    for the notes this result shows.
  - **Uses:** `site_key` (2.1); `load`, `record_shown` and `record_failure` (2.4); `render_site_notes` (2.5).
  - **Tests:**
    - `test_notes_sit_before_the_fields_and_survive_the_cut`
    - `test_notes_shown_counts_only_placed_notes`, with 2 cases:
      - a page quoting a note ID does not count;
      - a note the cut removed does not count.
    - `test_results_count_shown_notes_and_later_failures`: a failure on a note no result has shown counts nothing,
      and its result shows the note; a second failure then counts against it before its own result shows it again,
      leaving `shown` 2 and `failed_after` 1; a result whose cut took the notes counts none.
  - **Check:** its tests → `4 passed`.

- **3.4 The next step.** With a failure code, and learning on, `render` uses the code's sentence, and adds "see the site
  notes below" when it placed notes.
  - **Uses:** `NEXT_BY_FAILURE` (1.2), `learning_on` (2.5).
  - **Test:** `test_next_step_names_the_recovery_for_a_failure_code`.
  - **Check:** its tests → `1 passed`.

- **3.5 Lessons in `report_outcome`.** Two optional arguments, `lesson` and `lesson_detail`, and a tool description
  that says when to pass them.
  - **The chain:** the one ending with the run being labelled: `chains()` over the runs up to and including it, then
    the last chain.
  - **What code adds, and when it stores a note:** the design's §6.3.
  - **The reply:** "note stored", or "note not stored:" with the reason.
  - **Uses:** `site_key` (2.1); `chains` and `read_exclude` (2.2); `check_note` and `note_url` (2.3); `load` and
    `add_note` (2.4).
  - **Tests:**
    - `test_a_lesson_after_a_recovery_stores_an_unapproved_note`, which also passes `by="user"` and checks that the
      note stays unapproved
    - `test_a_lesson_is_refused_without_a_recovery_or_fallback`, with 3 cases:
      - a pass with no failed run before it;
      - a failed run with a hint other than `use_claude_in_chrome`;
      - an unknown hint.
    - `test_a_fallback_lesson_records_claude_in_chrome`
  - **Check:** its tests → `5 passed`.

- **3.6 The review trigger,** once Gate 4 has closed (P13).
  - **When it starts:** after `report_outcome` records the label, only if all of these hold:
    - `JEV_AUTO_REVIEW` is not `0`, and `learning_on()`;
    - `scripts/review_runs.py` exists, relative to the working directory, like `RUNS`; a built wheel run elsewhere has
      none;
    - `review_due(read_review_state(), time.time())`.
  - **How:** `start_review()` starts `review_runs.py auto`, with stdin from `/dev/null` and its output going to
    `auto.log`. An error goes to `auto.log` and never changes the reply (P11).
  - **The fixture:** the autouse `server` fixture replaces `start_review()` with a recorder and sets
    `JEV_AUTO_REVIEW=0`, so no existing test starts a review.
  - **Uses:** `learning_on` (2.5); `read_review_state` and `review_due` (2.6).
  - **Tests:**
    - `test_review_trigger_starts_only_when_due`, with 7 cases:
      - it starts with no state, or a `next_due` passed;
      - it does not start with a `next_due` later than now, with either switch at `0`, or with the script missing;
      - a start error leaves the reply unchanged.
    - `test_learning_off_restores_todays_result`
  - **Check:** its tests → `8 passed`.

- **Gate 3.** The review reads the diff against the Read first's design sections. The other lanes may be mid-edit, so
  this gate checks only its own.
  - **Check:** each holds:
    - `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; awk 'NF{l=$0} END{print l}' "$S/review-phase-3.md"`
      → `Open blockers: 0`;
    - `tests/test_mcp_server.py` → its baseline plus 21, counted with
      `TESTS=tests/test_mcp_server.py; BASELINE=baseline-mcp-server.txt`;
    - `uv run pytest -q tests/test_site_notes.py` → `51 passed`;
    - `uv run ruff check jev_ultrafast/mcp_server.py tests/test_mcp_server.py` → `All checks passed!`;
    - `grep -c 'site_notes' jev_ultrafast/agent.py jev_ultrafast/browser.py jev_ultrafast/model.py jev_ultrafast/questions.py`
      prints `0` for each file;
    - `grep -c -E '^\s*(from|import) .*(review_runs|report_runs)' jev_ultrafast/mcp_server.py` → `0`;
    - `grep -v -E '^\s*#' jev_ultrafast/mcp_server.py | grep -c 'shell=True'` → `0`.

## Phase 4: `scripts/review_runs.py` (offline)

**Read first:**

- **The design:** §3, §6.5, §6.7, §7 and §8.1.
- **This plan:** "Files and formats", under the global rules.
- **Code:**
  - `jev_ultrafast/site_notes.py`, from Phases 1 and 2;
  - `scripts/phase10/run_arm.py` 150–200, for its `Popen` and timeout.
- **The CLI:** `claude-help.txt` in `artifacts/experiments/2026-09-26/failure-review/`.

**Allowed APIs:**

| API | Use |
| --- | --- |
| `fcntl.flock(fd, fcntl.LOCK_EX \| fcntl.LOCK_NB)` on `artifacts/reviews/.lock` | one review at a time |
| `tempfile.mkdtemp()` | the review's working directory |
| `shutil.which("claude")`, resolved to an absolute path | the binary, never the shell alias |
| `subprocess.Popen(argv, cwd=..., env=..., stdin=file, stdout=PIPE, start_new_session=True)` | the launch |
| `os.killpg(pid, signal.SIGTERM)` | the 15-minute limit, and a failed start check |
| `secrets.token_hex(4)` | the nonce around each summary, as `render()` does |
| `open("/dev/tty")`, inside one `open_terminal()` | `approve`'s confirmation; tests replace `open_terminal()` |

**Anti-patterns:**

- **`--bare`,** which never reads your login, and `--dangerously-skip-permissions`. Name them in no string.
- **Page text in a summary:** no visible text, no screenshots and no full Jev requests.
- **A review approving a note,** or retiring or changing an approved one.

**Tasks:**

- **4.1 `queue [--since DATE]`.** Summaries per design §7.2, each in a nonce-marked block.
  - **What it prints:** the exact text a review sends, apart from the nonces.
  - **What it queues:** design §7.1.
  - **Left out:** excluded runs, and runs a digest already lists.
  - **Notes:** queued only when new, or changed since the last digest.
  - **Uses:** `failure_code` (1.1); `chains`, `possible_false_dones`, `read_exclude`, `excluded` and `task_values`
    (2.2); `strip_query` (2.3); `load` (2.4).
  - **Tests:**
    - `test_summaries_hold_no_typed_values_page_text_or_query_values`: a canary value typed in the run, and written
      into its goal, is replaced
    - `test_summaries_skip_excluded_and_reviewed_runs`: the excluded run touches its host only in a decision's page
      URL
  - **Check:** its tests → `2 passed`.

- **4.2 `apply`.** Validate the reply in code, and apply note decisions through `site_notes`' checks.
  - **`REVIEW_SCHEMA`:** the reply's JSON schema (design §7.5), which 4.4 passes to `--json-schema`.
  - **Never:** approve a note, or retire or change an approved one (design §7.5).
  - **The digest:** as under "Files and formats".
  - **Uses:** `read_exclude` and `task_values` (2.2); `check_note` (2.3); `update`, `add_note` and `set_state` (2.4).
  - **Tests:**
    - `test_apply_applies_checked_note_decisions_and_writes_the_digest`
    - `test_apply_refuses_bad_replies`, with 6 cases:
      - an approval;
      - an unknown note;
      - a retirement citing no queued run on the note's site;
      - retiring an approved note;
      - an over-long field;
      - a task value.
  - **Check:** its tests → `7 passed`.

- **4.3 `approve`, `retire`, `restore`, `enable`.**
  - **`approve`:** prints the exact line it will add to the instructions, then reads its confirmation through
    `open_terminal()`, which opens `/dev/tty`.
  - **`enable`:** sets `failures` to 0 and `off` to false.
  - **Uses:** `set_state` (2.4), `instructions_line` (2.5), `read_review_state` and `write_review_state` (2.6).
  - **Tests:**
    - `test_approve_needs_a_terminal_and_shows_the_line`, with `open_terminal()` replaced
    - `test_retire_restore_and_enable`
  - **Check:** its tests → `2 passed`.

- **4.4 `auto`, `once` and `preflight`.**
  - **The lock.**
  - **The stamp:** at every start of `auto` and `once`, `last_start`, `running`, and `next_due`, the start plus
    `REVIEW_EVERY_HOURS` (D16), so `auto` starts at most once a day.
  - **The queue threshold:** only runs count.
  - **`AUTO_FROM`:** the build date, where `auto`'s window starts.
  - **`once --since DATE`:** for Phase 8.
  - **`preflight`:** the same launch on a one-line prompt, with `--max-budget-usd 0.05`. It writes no digest and no
    stamp.
  - **The launch:** the design's §7.4 argv, environment, working directory and stdin, pinned.
  - **The stream's first event:** if it lists an MCP server, or a tool beyond the structured-output one, kill the
    group and count a failure.
  - **Limits:**
    - kill after 15 minutes;
    - a start that finds `running` set counts the earlier start as a failure;
    - after 3 failures in a row, `off` is set, and automatic reviews stop until `enable`.
  - **Uses:** `queue` (4.1), `apply` and `REVIEW_SCHEMA` (4.2), `read_review_state` and `write_review_state` (2.6),
    and the flags 0.3 confirmed.
  - **Tests,** with a fake `Popen`:
    - `test_auto_launch_is_pinned`: `auto`, `once` and `preflight` build the same argv, environment and working
      directory
    - `test_auto_kills_a_session_with_tools_or_mcp_servers`: one init event lists both
    - `test_auto_respects_lock_stamp_threshold_and_failure_limit`, with 4 cases
    - `test_auto_kills_after_15_minutes`
    - `test_once_reviews_a_window_and_records_cost`
  - **Check:** its tests → `8 passed`.

- **Gate 4.** The review reads the diff against the Read first's design sections. The other lanes may be mid-edit, so
  this gate checks only its own.
  - **Check:** each holds:
    - `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; awk 'NF{l=$0} END{print l}' "$S/review-phase-4.md"`
      → `Open blockers: 0`;
    - `uv run pytest -q tests/test_review_runs.py` → `19 passed`;
    - `uv run pytest -q tests/test_site_notes.py` → `51 passed`;
    - `uv run ruff check scripts/review_runs.py tests/test_review_runs.py` → `All checks passed!`;
    - `grep -c -E '^\s*(from|import) .*(mcp_server|report_runs)' scripts/review_runs.py` → `0`;
    - `grep -v -E '^\s*#' scripts/review_runs.py | grep -c 'shell=True'` → `0`;
    - `grep -v -E '^\s*#' scripts/review_runs.py | grep -c -E -- '--bare|dangerously'` → `0`.

## Phase 5: The report (offline)

**Read first:**

- **The design:** §3, §4, §7.5 and §9.
- **This plan:** "Files and formats", under the global rules.
- **Code:** `scripts/report_runs.py` in full; `jev_ultrafast/site_notes.py`, from Phases 1 and 2.
- **Tests:** `tests/test_report_runs.py` in full, including `test_report_marks_small_groups_as_anecdotes`, which
  unpacks exactly three lines.

**Anti-patterns:**

- **New lines above the existing summary** (P3).
- **A section with nothing to show that prints anyway:** the existing tests must see only today's lines.
- **A test reading your real files:** tests pass `--artifacts`.
- **Any write:** the report loads notes with `create=False`.
- **Stop-note or reviewer text outside a nonce-marked block.**
- **`run["failure"]`:** old runs lack the new keys, and any exception skips the whole file. Use `.get()`, and
  compute codes for old runs with `failure_code()`.

**Tasks:**

- **5.1 The report's run and note sections,** after the existing lines, each printed only when it has something to
  show:
  - failure codes by site, the host of `page.url`;
  - stale-budget stops;
  - chains. When a sub-goal took more than one run: runs per sub-goal, split by whether a note was shown;
  - possible false DONEs;
  - notes:
    - shown, failed after, and retired;
    - the characters notes add;
    - those left out of the instructions line (P10);
    - those waiting for approval, each with its command;
    - the notes file's error, if it cannot be read (P8);
  - excluded runs left out.
  - **`--artifacts DIR` (P3):** the folder holding `site-notes.json`, `reviews/` and `review-exclude.txt`. By default
    it is the parent of `--runs`.
  - **Output format:**
    - a line `failure codes: <code> <count>, …`, by count, then by name;
    - a line `stale-budget stops: <count>`;
    - a line `possible false DONEs: <count>`.
  - **Uses:** `failure_code` and `stale_budget` (1.1); `site_key` (2.1); `chains`, `possible_false_dones`,
    `read_exclude` and `excluded` (2.2); `load` (2.4); `instructions_line` and `note_excluded` (2.5).
  - **Tests,** each passing `--artifacts`:
    - `test_report_ends_with_failure_codes_chains_and_notes`
    - `test_report_marks_possible_false_done_and_stale_budget`
    - `test_report_skips_excluded_runs`
    - `test_old_runs_without_new_keys_still_count`
  - **Check 1:** its tests → `4 passed`.
  - **Check 2:** on a copy of the design's census, the 76 public runs of 2026-09-24, this prints exactly three lines:
    `failure codes: jev_blocked 6, busy_after_step 1, covered_target 1`, `stale-budget stops: 4` and
    `possible false DONEs: 3`.

    ```sh
    D=$(mktemp -d); mkdir "$D/runs"; for f in artifacts/runs/20260924-*.json; do grep -qxF "$(basename "$f" .json)" artifacts/review-exclude.txt || cp "$f" "$D/runs/"; done; uv run python scripts/report_runs.py --runs "$D/runs" --artifacts "$D" | grep -E '^(failure codes|stale-budget stops|possible false DONEs):'
    ```

- **5.2 The report's review sections,** after 5.1's:
  - reviews: count, failures and cost;
  - every review's decisions, with its digest's path;
  - whether automatic reviews are off;
  - open proposals and label flags, inside a nonce-marked block.
  - **Uses:** `read_review_state` (2.6), and the digests that Phase 4 writes, as under "Files and formats".
  - **Tests,** each passing `--artifacts`:
    - `test_report_lists_reviews_their_decisions_and_cost`
    - `test_report_prints_reviewer_text_only_inside_a_marked_block`
  - **Check:** its tests → `2 passed`.

- **Gate 5.** The review reads the diff against the Read first's design sections. The other lanes may be mid-edit, so
  this gate checks only its own.
  - **Check:** each holds:
    - `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; awk 'NF{l=$0} END{print l}' "$S/review-phase-5.md"`
      → `Open blockers: 0`;
    - `tests/test_report_runs.py` → its baseline plus 6, counted with
      `TESTS=tests/test_report_runs.py; BASELINE=baseline-report-runs.txt`;
    - `uv run pytest -q tests/test_site_notes.py` → `51 passed`;
    - `uv run ruff check scripts/report_runs.py tests/test_report_runs.py` → `All checks passed!`;
    - `grep -c -E '^\s*(from|import) .*(mcp_server|review_runs)' scripts/report_runs.py` → `0`;
    - 5.1's Check 2 prints the same three lines.

## Phase 6: Docs

**Read first:**

- **The design:** §3, §6.3, §6.4 and §12, decision 1.
- **The docs:**
  - `README.md`'s file list;
  - `docs/claude-code-integration.md`: §6.1, §6.3, §6.4, §7.1, §7.5 item 4, §7.6 (line 410) and §9 item 7 (line
    489).

**Tasks:**

- **6.1 README:** add `jev_ultrafast/site_notes.py` and `scripts/review_runs.py` to the file list. "Use from Claude
  Code" gains one sentence on failure codes, site notes and what an automatic review sends, and the line naming
  what makes paid calls gains run reviews (Gate 6).
  - **Check:** `grep -c -E 'site_notes.py|review_runs.py' README.md` → `2`.
- **6.2 `docs/claude-code-integration.md`,** so no section contradicts the build. Besides the sections below, §6.2
  gains a paragraph on the failure code's next step, and §7.4 a line on the report's new sections (Gate 6):
  - **§6.1:** `report_outcome`'s signature gains `lesson` and `lesson_detail`, with one line on when Claude passes
    them;
  - **§6.3:** the block's order names the site notes, between the page's URL and title and the fields;
  - **§6.4:** after the instructions, the line of approved notes that the server appends, as the design's §6.4 gives
    it;
  - **§7.1:** the run file's new keys, `previous_run`, `failure` and `notes_shown`;
  - **§7.5 item 4:** point it at `scripts/review_runs.py` and the design;
  - **§7.6:** rewrite the "never uploaded" line to say what an automatic review sends, per the design's §12 decision
    1;
  - **§9 item 7:** rewrite "review Jev runs weekly": automatic reviews run at most once a day, once 5 runs wait, and a
    review on request runs any time.
  - **Check 1:** each prints `0`:
    - `grep -c -F 'report_outcome(run_id, passed, evidence, by="claude")' docs/claude-code-integration.md`
    - `grep -c 'are never uploaded' docs/claude-code-integration.md`
    - `grep -c 'review Jev runs weekly' docs/claude-code-integration.md`
  - **Check 2:** each prints `1` or more:
    - `sed -n '/^### 6.1/,/^### 6.2/p' docs/claude-code-integration.md | grep -c 'lesson_detail'`
    - `sed -n '/^### 6.3/,/^### 6.4/p' docs/claude-code-integration.md | grep -c 'site notes'`
    - `sed -n '/^### 6.4/,/^## 7/p' docs/claude-code-integration.md | grep -c 'Site hints from earlier runs'`
    - `sed -n '/^### 7.1/,/^### 7.2/p' docs/claude-code-integration.md | grep -c 'previous_run'`
    - `sed -n '/^### 7.1/,/^### 7.2/p' docs/claude-code-integration.md | grep -c 'notes_shown'`
    - `grep -c 'failure-review.md' docs/claude-code-integration.md`, which must print `2` or more
- **Gate 6.** Every lane joins here. The review checks the docs' claims against the code, and that 0.4 and 0.5 are
  still in place.
  - **Check:** `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; awk 'NF{l=$0} END{print l}' "$S/review-phase-6.md"`
    → `Open blockers: 0`, and the full repo checks pass, with the suite at the baseline plus 97.

## Phase 7: Review and QA

**Read first:** the design's §11; this plan's decisions, anti-patterns and "Files this plan may change". Gate 6 has
closed every lane, so Phase 7's fixes may edit any file this plan may change.

- **7.1 Only allowed files changed.**
  - **Check 1:** comparing against the baseline, this prints nothing:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; git ls-files -co --exclude-standard -z | xargs -0 shasum -a 256 | diff "$S/before.sha" - | grep -E '^[<>]' | awk '{print $3}' | sort -u | grep -v -x -E 'jev_ultrafast/(site_notes|mcp_server)\.py|scripts/(review_runs|report_runs)\.py|scripts/phase10/run_arm\.py|tests/test_(site_notes|review_runs|mcp_server|report_runs)\.py|README\.md|AGENTS\.md|docs/(claude-code-integration|failure-review|failure-review-plan)\.md'
    ```

  - **Check 2:** `run_arm.py` still changed only its `env` line:
    `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; diff "$S/before/scripts/phase10/run_arm.py" scripts/phase10/run_arm.py | grep -c -E '^[<>]'`
    → `2`.
- **7.2 Every delegated decision has its comment.**
  - **The comment format:** one per decision.
    - `Delegated decision D<n> (docs/failure-review.md §11): …`
    - `Delegated decision P<n> (docs/failure-review-plan.md): …`
  - **No code:** D14 and D15. `questions.py` stays unchanged, and per-site executor settings are not built. Nor P1,
    P4–P6, P12 or P13, which are about files, tests and order.
  - **Check:** this prints nothing:

    ```sh
    for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 16 17; do grep -q -E "decision D$n \(docs/failure-review\.md" jev_ultrafast/site_notes.py jev_ultrafast/mcp_server.py scripts/review_runs.py scripts/report_runs.py || echo "missing D$n"; done; for n in 2 3 7 8 9 10 11 14 15 16 17 18 19 20 21 22; do grep -q -E "decision P$n \(docs/failure-review-plan\.md" jev_ultrafast/site_notes.py jev_ultrafast/mcp_server.py scripts/review_runs.py scripts/report_runs.py || echo "missing P$n"; done
    ```

- **7.3 Mutation testing.** A script in `$S` breaks each variant in a copy of the repo, then checks that the tests
  catch it.
  - **The copy:** the files git tracks or would add, in `$S/mutant/`.
  - **Each variant:**
    - one exact text replacement, which must match once and pass `py_compile`;
    - the suite runs as `/Users/terry/projects/jev-ultrafast/.venv/bin/python -m pytest -q` from the copy's root, so
      the copy's package is the one imported;
    - the file is restored afterwards.
  - **Killed:** at least one test fails, and the expected test is among the failures.
  - **The variants,** each with the test expected to kill it:
    1. the notes lock removed → `test_a_writer_waits_for_the_lock`;
    2. the exclusion check skipped when rendering → `test_excluded_sites_get_no_notes`;
    3. `excluded()` ignoring decisions' page URLs → `test_exclusion_matches_every_url_a_run_visited`;
    4. `approve` accepting stdin → `test_approve_needs_a_terminal_and_shows_the_line`;
    5. `--tools ""` dropped → `test_auto_launch_is_pinned`;
    6. the review inheriting `os.environ` → `test_auto_launch_is_pinned`;
    7. the review's working directory set to the repo → `test_auto_launch_is_pinned`;
    8. notes placed after the fields → `test_notes_sit_before_the_fields_and_survive_the_cut`;
    9. `notes_shown` parsed from the text → `test_notes_shown_counts_only_placed_notes`;
    10. `finish()` never calling `record_failure()` → `test_results_count_shown_notes_and_later_failures`;
    11. unapproved notes in the instructions →
        `test_instructions_line_lists_approved_notes_most_recently_shown_first_within_400_characters`;
    12. `by="user"` approving a note → `test_a_lesson_after_a_recovery_stores_an_unapproved_note`;
    13. retirement after 1 failure → `test_an_unapproved_note_retires_after_two_failures_and_an_approved_one_is_flagged`;
    14. query values kept in `start_at_url` → `test_start_at_url_comes_from_call_url_without_query_values`;
    15. the trigger ignoring `JEV_AUTO_REVIEW` → `test_review_trigger_starts_only_when_due`;
    16. the start check skipped → `test_auto_kills_a_session_with_tools_or_mcp_servers`;
    17. typed values kept in summaries → `test_summaries_hold_no_typed_values_page_text_or_query_values`;
    18. `covered_target` without its cover check → `test_stale_streak_without_a_named_cover_has_no_code`;
    19. `apply` retiring an approved note → `test_apply_refuses_bad_replies`;
    20. `review_due()` ignoring `off` → `test_review_due_reads_the_state`;
    21. the report loading notes with `create=True` → `test_report_marks_small_groups_as_anecdotes`.
  - **A survivor means a missing test:**
    - add one that fails on that variant;
    - rerun until all are killed;
    - name each added test in the task graph's status, and add it to 7.5's count.
  - **Check:** the script prints `21 of 21 killed`.
- **7.4 Final independent review** of the whole diff against the design, by a reviewer who wrote none of it. It
  covers what the gates could not: the paths between lanes, such as the review state between the script and the
  server, the digests between the script and the report, and the notes file they all share.
  - **Its record:** it writes `$S/review.md`, ending with the line `Open blockers: <n>`.
  - **Blockers:** fixed before 7.5, and the file updated.
  - **Check:** `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; awk 'NF{l=$0} END{print l}' "$S/review.md"`
    → `Open blockers: 0`.
- **7.5 Final checks,** after 7.4's fixes:
  - **Check 1:** 7.1's and 7.2's checks, and 7.3's script, give their results again.
  - **Check 2:** the full repo checks pass, with the suite at the baseline plus 97, plus any test 7.3 added.

## Phase 8: The first review (paid)

**Read first:** the design's §7.4, §7.5 and §12 decision 1; P5; "When a check fails".

- **8.1 Preflight, capped at $0.05:** `uv run python scripts/review_runs.py preflight` runs the pinned command on a
  one-line prompt.
  - **Check:** exit 0. It prints:
    - the login check;
    - the schema check;
    - the first event's tools and MCP servers: none but structured output, and none;
    - a cost of $0.05 or less.
- **8.2 The first review, capped at $0.50.**
  1. **Before paying:** save offline what it will send, the tree, and the approved notes. This also prints the number
     of bytes it will send.

     ```sh
     S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; uv run python scripts/review_runs.py queue --since 2026-09-24 > "$S/queue-before-review.txt"; wc -c < "$S/queue-before-review.txt"; git status --short > "$S/status-before-review.txt"; uv run python -c "import json; print(sorted(n['id'] for n in json.load(open('artifacts/site-notes.json')) if n['approved']))" > "$S/approved-before-review.txt"
     ```

     - **Check:** no private run in it:
       `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; grep -c -F -f <(grep -x -E '[0-9]{8}-[0-9]{6}-[0-9a-f]{4}' artifacts/review-exclude.txt) "$S/queue-before-review.txt"`
       → `0`.
  2. **The review:** `uv run python scripts/review_runs.py once --since 2026-09-24`.
     - **Check 1:** exit 0, and a new digest in `artifacts/reviews/` with the keys `queue`, `sent`, `decisions`,
       `flags`, `proposals` and `cost`.
     - **Check 2:** `cost` is 0.50 or less.
     - **Check 3:** `grep -c -F -f <(grep -x -E '[0-9]{8}-[0-9]{6}-[0-9a-f]{4}' artifacts/review-exclude.txt)` on the
       new digest → `0`.
     - **Check 4:** the review changed no file git sees. This prints nothing:
       `S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; git status --short | diff "$S/status-before-review.txt" -`.
     - **Check 5:** the review approved and unapproved nothing. Git ignores the notes file, so this compares the
       approved IDs, and prints nothing:

       ```sh
       S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; uv run python -c "import json; print(sorted(n['id'] for n in json.load(open('artifacts/site-notes.json')) if n['approved']))" | diff "$S/approved-before-review.txt" -
       ```

- **After 8.2's first attempt (2026-09-29):** the reply check refused the whole reply, as `phase-8-record.md` records.
  You chose its recommended fix, which changes the design (v4.4), and one more attempt:
  1. **Reopen two lanes,** as "When a check fails" says, recorded in 8.2's Status: the review lane for the code and
     tests, and the docs lane for the design's text.
     - **One scope for task values:** every summary, of a run or of a note, replaces the task values of every queued
       run's chain of attempts. `build_queue()`'s `values` becomes that one set, which the reply's checks use too. A
       value typed only in a run outside those chains, such as one already reviewed, is not replaced: those chains
       are the runs whose text is sent.
     - **Only a note decision is refused for a value:** a decision whose `note` or `detail` holds a task value outside
       the names a reply may cite (P18) is refused on its own, and changes nothing. Code applies every other decision
       as written, then records it with the task values in its texts replaced by `<value>`, apart from `action` and
       `hint`, whose words the schema fixes. The same goes for its outcome, the flags, the proposals and the summary,
       in the digest and in what code prints. This keeps the old promise that no reviewer text holds a task value,
       since the report puts that text before Claude. A reply is refused whole only when it breaks `REVIEW_SCHEMA`.
     - **The cost, accepted:** P16 makes common words task values, such as "search" and "date", so a note decision
       that needs one is refused, and its recovery is not queued again. The digest and the report show each refusal
       and its reason.
     - **Tests,** each changed so it fails on the code before the fix, with the file still at 19 tests:
       - **Summaries:** in `test_summaries_hold_no_typed_values_page_text_or_query_values`, a value typed in one run
         shows as `<value>` in another run's goal and in a seed note's detail;
       - **Replies:** in `test_apply_applies_checked_note_decisions_and_writes_the_digest`, a reply holding a value
         typed in a queued run, in one add's detail, another decision's note, a flag, a proposal and the summary,
         applies its other decisions. The hint `scroll_first` stays when "first" is a task value, a decision's `runs`
         lose theirs, and the value reaches neither the digest, the notes file nor what code prints;
       - **Refusals:** in `test_apply_refuses_bad_replies`, the task-value case becomes a note detail holding one,
         refused on its own;
       - **Chains, a pin for what the fix keeps** (it passes on the code before the fix too): in
         `test_summaries_skip_excluded_and_reviewed_runs`, a retry's goal naming what its excluded earlier attempt typed
         shows `<value>`, so the one set takes each queued run's whole chain, excluded attempts included.
     - **Design, v4.4:** §7.2, §7.5 and §12 decision 1 say this; so does the integration design's §7.6.
  2. **Rerun Gates 4 and 6 as one review:** an independent review of the fix and its docs, and QA: both gates' checks,
     and 7.1, 7.2, 7.3 and 7.5 again. Its review ends `Open blockers: 0`.
  3. **Repeat 8.2,** capped at $0.50. It does its job when step 2's checks pass, which is "Solved when" 2. Whether the
     review's advice helps shows in the report, and is not a check.
     - **Before step 1:** the first attempt's records move to `attempt-1/`, so the repeat's step 1 keeps their names.
     - **Step 1, before paying:** its commands and check, and one more check, that no task value is left in the free
       text saved to send. It skips the lines code writes whole, from a site, a status, a failure code, a hint, dates,
       counters and IDs. There, the label "site" and the year in a date match task values: P16 makes each word of 4
       characters or more in a typed or quoted value one, and §6.5 each goal's run of 4 or more digits. This prints
       `0`:

       ```sh
       S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; uv run python -c "import sys; from scripts import review_runs as r; from jev_ultrafast import site_notes as s; q = r.build_queue('20260924'); v = s.task_value_pattern(q['values']); k = r.kept_names(q['names']); whole = ('run ', 'site ', 'note ', 'approved on ', 'unapproved', 'runs: ', 'notes shown: '); print(sum(r.holds_value(line, v, k, q['run_ids']) for line in open(sys.argv[1]) if not line.startswith(whole)))" "$S/queue-before-review.txt"
       ```

       On the first attempt's saved text, `attempt-1/queue-before-review.txt`, it prints `44`. A failed step 1 costs
       nothing: fix it as an offline check, and run step 1 again.
     - **The gate:** step 2 starts only when step 1's two checks print `0`, its text is not empty, and no Jev run is
       going: no run file changed in the last 10 minutes, since a run lasts at most 90 seconds. Otherwise nothing is
       paid.
     - **In one command,** so no run recorded and no note shown comes between the steps: `repeat-8.2.sh` in `$S` runs
       step 1, its checks, the gate, then step 2 and its checks. It exits 2, having paid nothing, when the gate holds,
       and 3 when the review wrote no new digest. It prints counts only: each check's diff goes to a file in `$S`, and
       shows as its size in bytes, which a passing check keeps at 0:
       `bash /Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation/repeat-8.2.sh`.
     - **Step 2:** its command and checks 1–5, and a sixth: the text sent is step 1's text, nonces aside, so step 1's
       check holds for it. This prints nothing:

       ```sh
       S=/Users/terry/projects/jev-ultrafast/artifacts/failure-review-implementation; diff <(sed -E 's/^(<\/?untrusted page content )[0-9a-f]{8}/\1NONCE/' "$S/queue-before-review.txt") <(uv run python -c "import json, pathlib; print(json.loads(max(pathlib.Path('artifacts/reviews').glob('2*.json')).read_text())['sent'], end='')" | sed -E 's/^(<\/?untrusted page content )[0-9a-f]{8}/\1NONCE/')
       ```

     - **Recorded, not checked:** the `<value>` marks in the text sent, against the first attempt's; and the decisions
       applied and refused.
     - **The attempt** is step 2's paid call. If any of its six checks fails, stop and report; there is no third.
     - **An automatic review is not an attempt.** None can start before `state.json`'s `next_due`,
       2026-09-30T06:31:30, and each needs 5 queued runs from the build date on.

- **8.3 Status lines:** the design's status says implemented, with the date, and every task in the task graph is
  marked done.
  - **Check:** `grep -c 'implemented on' docs/failure-review.md` → `1`, and this prints `0`:

    ```sh
    awk -F'|' '/^\| (Gate )?[0-9]/ && $6 !~ /^ Done/ {n++} END {print n+0}' docs/failure-review-plan.md
    ```

## Review of this plan (2026-09-26)

- **Independent review:** approve with fixes, with 12 should-fixes and 9 nits. All are applied.
- **Calvin:** 24 questions over the two halves. The plan's author answered all of them.
- **What the reviews changed:**
  - **The paid review comes last,** in Phase 8, after mutation testing and the independent review. Before paying,
    an offline copy of what it sends is checked for the private runs.
  - **The failure rules** read the status and the first note only, with fixed texts from the code. The census checks
    pin the 76 public runs of 2026-09-24, which still give the design's counts.
  - **New decisions P8–P11:**
    - P8: an unreadable notes file;
    - P9: a site whose notes are all approved;
    - P10: the instructions line's order, and `last_shown`, also added to the design (v4.2);
    - P11: trigger errors.
  - **Tests:** the lock and terminal tests are deterministic, and each variant in 7.3 names the test expected to kill
    it.
  - **Checks:** they import the code where source wrapping or comments could mislead a grep, and their allow-lists
    print nothing when all is well.
- **The breakdown into dependent tasks:**
  - **The task graph:** every task lists what must be done first. Lanes own their files, so the server, the review
    script and the report can be built at once.
  - **Gates:** each phase ends with an independent review and QA, which holds back the tasks that depend on it (P13).
  - **Checks run each task's own tests by name,** so they hold in any valid order.
  - **Found while tracing dependencies:**
    - 2.1's test of the notes file needed the store, so it moved to the store (2.4);
    - chains, possible false DONEs, exclusions and task values had three users and no owner, so they are now 2.2's run
      helpers, tested there;
    - nothing called the store's counters from the server, so 3.3 now does, with a test and a variant;
    - the report's review sections need Phase 4's digests, so they are 5.2, and the rest of Phase 5 runs alongside
      Phases 3 and 4;
    - the AGENTS.md line and experiments' switch moved to Phase 0 (P12).
- **The breakdown's independent review:** ready after fixes, with 1 blocker, 5 should-fixes and 7 nits. All are
  applied:
  - **The blocker:** the report's lane needed store and chain behaviour that Phase 2 left open. `load()` gains
    `create`, which the report sets false, and a run with neither link key is its own chain.
  - **Contracts between parallel lanes:**
    - the run-file keys, run IDs, the review state and paths are pinned under "Files and formats";
    - site notes owns the review state (2.6, P15);
    - Gate 2 checks every function's arguments;
    - no lane imports another's module.
  - **The trigger (3.6) waits for Gate 4,** so a restarted real server never starts a half-built review.
  - **Process:**
    - a closed lane can be reopened for a defect;
    - one person or agent edits the Status column;
    - 7.5 reruns 7.1–7.3.
  - **Docs:** 6.2 now also covers the integration doc's §6.1, §6.3, §6.4 and §7.1, which the build would make untrue.
  - **Chains (P14):** a chain ends where the site changes or after a pass. Possible false DONEs follow the link, which
    still flags the census's 3.
  - **Checks:**
    - the gates read the review's last non-blank line;
    - the diffs compare against the baseline copy, so they survive a commit;
    - 8.3 counts only rows not done.
- **Counts:** `tests/test_site_notes.py` 51, `tests/test_mcp_server.py` plus 21, `tests/test_review_runs.py` 19 and
  `tests/test_report_runs.py` plus 6: the baseline plus 97. There are 21 variants.
- **Records:** in `artifacts/experiments/2026-09-26/failure-review/`:
  - `plan-review.md` and `breakdown-review.md`;
  - `calvin-plan-a.md` and `calvin-plan-b.md`;
  - `calvin-plan-answers.md`;
  - `check_plan_graph.py`, which checks this graph.
