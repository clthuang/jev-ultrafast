# Implementation plan: page readiness (H5 and the loading wait), and the failure-review follow-ups

> Current implementation note (2026-10-04): the robustness/efficiency candidate implements the policy, execution limits, versioned review storage, bounded snapshots and readiness contracts. See the [current contracts](robustness-efficiency/current-contracts.md) and its evidence/activation links. The design, planning statuses, trial counts and performance observations below are historical; they are not current release or production-activation proof.


**Sources:**
- **The design:** `docs/executor-improvements.md`:
  - **§2 v2** (H5): a read that times out after a step is repeated. v2 cut v1's dialog check;
  - **§4 v4.2:** a final answer waits for loading.

  §4.1 joins them into one page-readiness protocol.
- **The follow-ups:** eleven small defects and test gaps left open when `docs/failure-review.md` v4.4 was built. Each
  task below states its issue in full. The notes they came from stay in the ignored
  `artifacts/failure-review-implementation/followups.md`.
  - **Why they ride in this plan:** you asked for them with it; they share its files (`scripts/report_runs.py`,
    `tests/test_report_runs.py`, `tests/test_mcp_server.py` and `docs/failure-review.md`); and their own lanes keep
    them separable, each reviewed at its own gate.
  - **Where each is fixed:**

    | Follow-up | Issue | Task |
    | --- | --- | --- |
    | F1 | a note check reads a field its action never uses | 3.1 |
    | F2 | a decision the notes file refused marks its runs reviewed | 3.3 |
    | F3 | `docs/failure-review.md` gives `failure_code()` an old signature | 7.4 |
    | F4 | the report counts a running review as failed | 4.1 |
    | F5 | `auto` logs a traceback for an unreadable exclude file | 3.4 |
    | F6 | replacing values in an outcome breaks code's own words | 3.2 |
    | F7 | a failure's text can quote a task value | 3.5 |
    | F8 | overlapping task values are not replaced together | 3.6 |
    | F9 | `start_review()`'s arguments are untested | 4.3 |
    | F10 | the lesson walk's loop guard is untested | 4.4 |
    | F11 | the hyphenated look-alike is untested | 4.2 |

**Status:** superseded for scheduling on 2026-10-03 by `docs/robustness-efficiency-implementation-plan.md`, which runs
this plan's follow-ups F1–F11 (stages PRIVACY-1 and REVIEWS-1…7) and its §2/§4 readiness work (READINESS-1…3) against
the newer interfaces. The task details, checks and lab safety rules below remain that plan's reference. Before then:
not started (2026-09-29); this plan replaced the H5-only plan of 2026-09-24.

**How to use this plan:**

- **Order:** the task graph below is the source of truth.
  - **When a task may start:** once every task in its "Depends on" column is done.
  - **When it is done:** when its check passes.
  - **The listed order** is one valid order.
- **Status:** one of `Not started`, `In progress` or `Done`. Only the person or agent running the plan edits the
  Status column; lanes report their tasks done to them.
- **Lanes:** each task belongs to one lane, and each lane owns its files. No task edits another lane's files.
  - **At once:** tasks in different lanes may run at the same time.
  - **In order:** within a lane, each task depends on the one before it. The setup and QA lanes are the exceptions:
    their tasks touch different files, or none.

  | Lane | Files it owns | Test files its tasks run |
  | --- | --- | --- |
  | setup | nothing tracked; `$S`'s baseline: `before.sha`, `before/`, `baseline.txt`, `reviews-before.txt` | all, at Gate 0 |
  | executor | `jev_ultrafast/agent.py`, `jev_ultrafast/browser.py`, `jev_ultrafast/mcp_server.py`, `scripts/report_runs.py`, `tests/test_agent.py`, `tests/test_mcp_server.py`, `tests/test_report_runs.py`, until Gate 2 | those three test files |
  | review | `$S/review-lane`, a copy of the baseline, until 3.7 lands its `scripts/review_runs.py` and `tests/test_review_runs.py` in the repo | `tests/test_review_runs.py`, `tests/test_site_notes.py` |
  | follow-ups | after Gate 2: `scripts/report_runs.py`, `tests/test_report_runs.py`, `tests/test_mcp_server.py` | `tests/test_report_runs.py`, `tests/test_mcp_server.py` |
  | live | `scripts/check_guards.py`; the lab Chromes; new files under `artifacts/experiments/`; its records in `$S`: `lab*.pid`, `lab*.profile`, `lab*-version.json`, `h5_dir`, `loading_dir`, `registered.sha`, `default_pid` | none: its checks are live |
  | docs | `README.md`, `docs/claude-code-integration.md`, `docs/performance.md`, `docs/executor-improvements.md`, `docs/failure-review.md` | all, at Gate 7 |
  | QA | nothing tracked | all |

  - **After Gate 2:** `scripts/report_runs.py`, `tests/test_report_runs.py` and `tests/test_mcp_server.py` pass to the
    follow-ups lane. The executor lane's other files stay closed: a defect found in them reopens that lane
    (§"When a check fails").
  - **The review lane's copy:** Phase 3 edits the copy, so its half-done edits never run in the repo. 3.7 lands both
    files at once, after Gate 2; Phase 3's opening says why.
  - **Other files in `$S`:** each belongs to the lane whose task writes it. Gate reviewers write only their
    `review-phase-<n>.md`.

- **Checks:** every task ends with a **Check**: a command or file condition, with its expected result.
  - **Also part of every check, where they apply:** the lane's test files pass, with no failure; and
    `uv run ruff check <the files the task changed>` → `All checks passed!`.
  - **A task's tests run by name,** so its check holds in any valid order.
  - **`→ 3 passed`** means the last line starts with `3 passed` and holds no `failed` or `error`. The deselected count
    does not matter.
  - **Cases:** a test listed "with N cases" is parametrized into N. Any other test is one function.
  - **Raw output:** where a hook rewrites commands, as RTK does in this environment, put `rtk proxy` directly before
    each `uv run pytest`, `uv run ruff` and `diff` that starts a command or follows `;`, `&&` or `||`, after any
    variable assignment: `S=…; rtk proxy uv run pytest …`.
    - **Why those three:** rtk rewrites them so that pytest and ruff print its summaries, and a `diff` with no
      difference prints `[ok] Files are identical`. The other commands the checks use print the same either way.
    - **What rtk leaves alone:** a command after `rtk proxy`, and commands inside `$(…)`. After a `|`, it rewrote
      only `grep` in every form probed, and `rtk grep` printed the same in each form the checks use.
    - **`rtk proxy S=…` fails:** rtk would run the assignment as a command.
- **Test counts are relative to 0.2's baseline,** per test file, since other work may land first.
  - **"`tests/test_agent.py` at baseline plus K":** its last line has no `failed` or `error`, and its passed count
    minus the baseline's is K. This prints the difference:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; F=tests/test_agent.py; now=$(uv run pytest -q $F | tail -1); echo "$now"; echo "added: $(( ${now%% passed*} - $(grep -F "$F " "$S/baseline.txt" | cut -d' ' -f2) ))"
    ```

- **Gates:** Phases 0–5 and 7 each end with a gate. No task that depends on a gate starts before it closes.
  1. **Independent review:** a reviewer who did not write the phase's changes reads its diff against the design
     sections in the phase's "Read first" and this plan. It writes `$S/review-phase-<n>.md`, ending with the line
     `Open blockers: <count>`. The Codex reviewer is disabled in your settings, so reviewers are Claude's own.
  2. **Fixes:** the lane fixes each blocker and should-fix, and the reviewer updates the file.
  3. **QA:** every check of the phase runs again, after the fixes, then the gate's own checks.
  - **Lane checks, at Gates 1–5:** the lane's test files pass, with no failure, and `uv run ruff check <the lane's
    files>` → `All checks passed!`. The repo checks run only at Gate 0, Gate 7 and 8.5: while lanes overlap, a
    whole-suite run would also test another lane's half-done task.
  - **Reading the verdict:** `awk 'NF{l=$0} END{print l}' <file>` prints its last non-blank line.
  - **Diffs to review:** `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; diff -u "$S/before/<file>" <file>`
    for each file the phase changed. `git diff` would miss new files, and the working tree may hold other uncommitted
    work.
- **Where commands run:** from the repo root, `/Users/terry/projects/jev-ultrafast`, except 3.1–3.6's checks, which run
  inside the review lane's copy (Phase 3).
- **One command is one shell call, and shell variables do not persist between calls:**
  - each fenced block runs as one call;
  - every command that uses `$S` starts with `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation;`,
    and every one that uses `$E` with `E=artifacts/experiments/2026-09-24/h8-network-settle/design-check/v4;`;
  - git ignores both folders.
- **Line numbers** are for commit `8953b45`. `browser.py` and `scripts/check_guards.py` have not changed since
  `523ede7`, where the design's line numbers come from. Design §5 (H9), built on 2026-09-29, changed `agent.py`,
  `tests/test_agent.py`, `scripts/report_runs.py` and `tests/test_report_runs.py` outside the saved §4 diff's hunks,
  which still apply. Each "Read first" also names the function, which survives edits.
- **Decision numbers** continue from `docs/failure-review-plan.md`'s P1–P22, so each P-number names one decision in
  the repo. The design's own are D1–D20; D15–D20 are §5's, built outside this plan.
- **Never kill by a pattern built from a variable that could be empty.** 6.5 kills the labs by recorded process IDs,
  and refuses to touch a lab with no record.

## The problem, and how we will know it is solved

- **Today:**
  - **A busy page after a step:** the read that follows times out, and the run ends `stopped` although its input
    worked. Run `20260924-112504-7782` is the one recorded case (design §2.1).
  - **A final answer before the results load:** Jev can answer DONE on a page that is still loading, and the freshness
    check accepts it, since the page has not changed yet (§4.2).
    - Of the 76 public runs of 2026-09-24, 3 ended DONE before their results rendered: `20260924-052252-e4b2`,
      DuckDuckGo `20260924-100333-757e` and crates.io `20260924-111852-243b`.
    - The first automatic review flagged the last two on 2026-09-29.
  - **The follow-ups:** eleven defects and test gaps in the failure review, none blocking (Phases 3–4).
- **Solved when:**
  1. every offline check in Phases 0–4, 7 and 8 passes;
  2. the live checks pass in a lab Chrome, then in your Chrome: `PASS: 29 browser guard checks; no model calls`;
  3. **H5's acceptance:** 5 of 5 busy trials end `done`, each input once, and the alert trial stops with its note;
  4. **§4's acceptance:** on Google Flights, DuckDuckGo, crates.io and YouTube, the gate trials pass P33's rule:
     - the accepted read has results in at least 9 of 10 per site;
     - no wait records `lost`;
     - each site has at most one capped trial.
- **In real use:**
  - `scripts/report_runs.py` counts "repeated reads", "loading wait ms", "loading caps" and "loading event losses";
  - its "possible false DONEs" line, from the failure review, should stop growing. To compare: once at least 76 runs
    have started after the build lands, `scripts/report_runs.py --since <n>h`, with n the hours since it landed,
    counts them among those runs, against 3 of 76 before;
  - later automatic reviews should stop flagging DONEs given before results rendered.

## When a check fails

- **Never loosen a check or its expected value to make it pass.**
- **Offline phases (0–4, 7, 8):** if the cause is inside the task's own change, and the fix stays within the design,
  fix it and run the check again. Otherwise stop, and report the check's command and its output.
- **Live phases (5–6):**
  - **First, shut the labs down** with 6.5's command. It is safe at any point after 5.1, and it refuses to touch a lab
    with no record.
  - **Then stop,** and report the failing command and its output.
  - **Never re-run a trial or a check to get a pass,** except where a step says so.
- **Your Chrome (5.3):** if something fails there, stop and report. The plan never restarts your daemon.
- **A gate's blockers** are fixed, never waived. A blocker that needs a design change stops the plan, for you.
- **A defect in a closed lane,** found by a later task or gate:
  1. pause every task that depends on that lane's gate;
  2. reopen the lane to fix it, recorded in the Status column of the task that found it;
  3. rerun the lane's gate;
  4. resume.

## Decisions made on your behalf

The design's own decisions are in its tables: D1–D5 at the top of §2, with D2 and D3 withdrawn in v2, and D6–D14 at
the top of §4. Each has a comment in the code naming it. This plan adds these; each names where to change it.

| # | Decision | Why | Where to change it |
| --- | --- | --- | --- |
| P23 | Live checks run in a lab Chrome first, and in your Chrome only after the lab run passes | The new loading check starts a local server and a cross-site iframe; a failure there lands on a throwaway daemon, not the one your runs use | 5.2 and 5.3 |
| P24 | Two labs: `labC` on port 9335 for the live checks and H5's acceptance, `labE` on 9337 for §4's | Each copied harness already refuses any other lab name and port, so neither copy needs a guard edit | 5.1, 6.2 and 6.3 |
| P25 | §2 v2 and §4 v4.2 are approved on 2026-09-29, with the fixes from their review against `8953b45` and calvin's answers folded in. §2's dialog check is cut (the review's S6) | You asked to proceed with the recommendation to review §4 next. The review found no blocker; the dialog check guarded a case no recorded run met, and a dialog in another of your tabs would have turned the repeat off | the status lines of design §2 and §4 |
| P26 | §4 goes in first, as its saved diff; §2 goes in by hand after it | The diff is the exact code whose 24 tests and 34 broken variants passed, and at `8953b45` it applies to 5 of its 6 files unchanged. §2 is a few lines, written verbatim in its design | Phases 1–2 |
| P27 | §4's acceptance runs the H8c harness's gate arm only | The pass rule is about the gate arm; the today arm was H8c's comparison, and dropping it halves the live time | 6.3 |
| P28 | Eleven follow-ups are fixed here; four stay accepted as they are | The eleven are small, and each gets a test. The four cost more than they are worth today; §"Not in this plan" lists them with their reasons | Phases 3–4 |
| P29 | A note decision is refused only for a task value in a field its action uses: an add's `detail`, a flag's or a retire's `note` (F1) | An add never stores its `note`, yet a value there refused both adds of the first review. Their `detail`s held values too, so this alone would not have saved them. Every field is still replaced in the digest | `USED_FIELDS` in `scripts/review_runs.py` |
| P30 | A decision's `outcome` is kept whole, as `action` and `hint` are (F6) | It is code's own text. After P29 and 3.2's one change, every slot it fills is a kept name or a checked field. Replacing it turned "a value from a task" into "a value <value> a task" | `without_values()` in `scripts/review_runs.py` |
| P31 | P16's cost is judged after 5 successful reviews since 3.7 lands P29: if more than half of their proposed adds were refused for common words, narrow P16 | The first review lost both its adds to values in their `note`s and `detail`s, before P29. Five reviews give about ten adds, enough to tell a pattern from chance | §"After the plan: the P16 check" |
| P32 | The first review's second proposal, reading controls below the fold and inside shadow DOM, is held | It is H1 and H4 again: both were partly verified, and every fix tried failed (design §1, Results). It waits for a new fix idea | §"Not in this plan" |
| P33 | §4.6's "each has at most one cap" is read per site: at most one capped trial among a site's 10 | A cap is a trial's wait reaching 5 s after its input; the design counted caps per site in its replays | 6.4 |
| P34 | A decision refused because the notes file cannot be read also leaves its runs queued, as one refused by a failed write does (F2) | An unreadable file refuses every decision, as a failed write does; marking their runs reviewed would lose those recoveries for good. `site_notes.update()` raises `ValueError` for it, the same as for a refused change, so `scripts/review_runs.py` marks it by its own `NotesFileError` | `NotesFileError` in `scripts/review_runs.py` |

## Global rules

- **Repo rules:** follow `AGENTS.md`:
  - never retry a browser mutation, and log execution before observing its result;
  - tests must not call paid APIs;
  - keep README claims, evidence, and model-call counts consistent;
  - do not commit or push unless the user asks.
- **Repo checks,** at Gate 0, Gate 7 and 8.5; Gates 1–5 run their lane checks instead:
  - `uv run ruff check .` → `All checks passed!`;
  - `uv run pytest -q` → no failures;
  - `node --check jev_ultrafast/static/app.js` and `node --check jev_ultrafast/snapshot.js` → exit 0;
  - `uv build --out-dir "$(mktemp -d)"` → a wheel is built.
- **Cost:** no phase calls a paid API or a model. Phases 5 and 6 need Chrome; 6.3's trials also load Google Flights,
  DuckDuckGo, crates.io and YouTube, as H8c's did, with a simulated Jev.
- **Automatic reviews during the build:** a real Jev session that reports an outcome can start
  `scripts/review_runs.py auto` from the working tree.
  - **Why that is safe:** Phase 3 edits a copy, and 3.7 lands its two files in one step, so a review runs the old
    script or the new one, never a half-edited one.
  - **What limits it:** at most one review a day, capped at $0.50; the next may start after 2026-09-30 11:49.
  - **To rule it out anyway:** set `JEV_AUTO_REVIEW=0` in the server entry's `env`. The plan never changes your
    configuration. 8.4 lists any review that ran.
- **New Jev sessions during Phases 1–2:** don't start one until Gate 2 closes. A new session's server loads
  `jev_ultrafast/` from the working tree, where the executor lane's edits may be half done. Sessions already running
  keep the code they loaded.
- **Privacy:** never open the private runs, the two run IDs that `artifacts/review-exclude.txt` lists; never read or
  print `.env`.
- **Files this plan may change,** and no others:
  - `jev_ultrafast/agent.py`, `jev_ultrafast/browser.py`, `jev_ultrafast/mcp_server.py` (comments only);
  - `scripts/report_runs.py`, `scripts/review_runs.py`, `scripts/check_guards.py`;
  - `tests/test_agent.py`, `tests/test_mcp_server.py`, `tests/test_report_runs.py`, `tests/test_review_runs.py`;
  - `README.md`, `docs/claude-code-integration.md`, `docs/performance.md`, `docs/failure-review.md`, and
    `docs/executor-improvements.md` (its status lines), and this plan;
  - new files under `artifacts/`, which git ignores.

## Task graph

**At a glance:**

```
Phase 0, setup:
  0.1, 0.2, 0.3, 0.4 ─▶ Gate 0

Phases 1-2, the executor lane, and Phase 3, the review lane, at once after Gate 0:
  executor:  1.1 ─▶ 1.2 ─▶ 1.3 ─▶ Gate 1 ─▶ 2.1 ─▶ 2.2 ─▶ 2.3 ─▶ 2.4 ─▶ 2.5 ─▶ 2.6 ─▶ 2.7 ─▶ Gate 2
  review:    3.1 ─▶ 3.2 ─▶ 3.3 ─▶ 3.4 ─▶ 3.5 ─▶ 3.6 ─▶ 3.7, also after Gate 2 ─▶ Gate 3

After Gate 2, at once:
  follow-ups: 4.1 ─▶ 4.2 ─▶ 4.3 ─▶ 4.4 ─▶ Gate 4
  live:       5.1 ─▶ 5.2 ─▶ Gate 5 ─▶ 5.3 ─▶ 6.1 ─▶ 6.2 ─▶ 6.3 ─▶ 6.4 ─▶ 6.5

Phase 7, docs, after Gates 3 and 4 and 6.5:
  7.1 ─▶ 7.2 ─▶ 7.3 ─▶ 7.4 ─▶ 7.5 ─▶ Gate 7

Phase 8, QA:
  Gate 7 ─▶ 8.1, 8.2, 8.3, 8.4 ─▶ 8.5
```

**Parallel work, with up to 6 agents:**
- **After Gate 0:** the executor and review lanes run at once, the review lane in its copy.
- **After Gate 2:** the follow-ups and live lanes run at once.
- **Reviewers:** one takes each gate as its lane reaches it. So there are at most two implementers and two reviewers
  at a time, and two reviewers at 8.1.

| ID | Task | Depends on | Lane | Status |
| --- | --- | --- | --- | --- |
| 0.1 | browser-harness is as the design says | — | setup | Not started |
| 0.2 | Baseline | — | setup | Not started |
| 0.3 | The saved §4 diff applies | — | setup | Not started |
| 0.4 | Record the review digests | — | setup | Not started |
| Gate 0 | Setup checks | 0.1, 0.2, 0.3, 0.4 | setup | Not started |
| 1.1 | Apply §4's saved diff | Gate 0 | executor | Not started |
| 1.2 | No test reaches the daemon's buffer | 1.1 | executor | Not started |
| 1.3 | D14, tests 25–27, and a rename | 1.2 | executor | Not started |
| Gate 1 | Review of Phase 1 | 1.3 | executor | Not started |
| 2.1 | The repeat constant (D1) | Gate 1 | executor | Not started |
| 2.2 | The `repeated_reads` counter (D5) | 2.1 | executor | Not started |
| 2.3 | The repeat loop (D4) | 2.2 | executor | Not started |
| 2.4 | Test 8 through the server | 2.3 | executor | Not started |
| 2.5 | The report counts repeats | 2.4 | executor | Not started |
| 2.6 | Comments in `mcp_server.py` | 2.5 | executor | Not started |
| 2.7 | No test reaches the daemon | 2.6 | executor | Not started |
| Gate 2 | Review of Phase 2 | 2.7 | executor | Not started |
| 3.1 | F1: check only the fields a decision uses | Gate 0 | review | Not started |
| 3.2 | F6: keep a decision's outcome whole | 3.1 | review | Not started |
| 3.3 | F2: a write failure leaves its runs queued | 3.2 | review | Not started |
| 3.4 | F5: `auto` stops quietly on an unreadable exclude file | 3.3 | review | Not started |
| 3.5 | F7: a failure's text never quotes a task value | 3.4 | review | Not started |
| 3.6 | F8: overlapping task values are replaced together | 3.5 | review | Not started |
| 3.7 | Land the review lane's two files | 3.6, Gate 2 | review | Not started |
| Gate 3 | Review of Phase 3 | 3.7 | review | Not started |
| 4.1 | F4: the report shows a running review as running | Gate 2 | follow-ups | Not started |
| 4.2 | F11: pin the hyphenated look-alike | 4.1 | follow-ups | Not started |
| 4.3 | F9: pin `start_review()`'s arguments | 4.2 | follow-ups | Not started |
| 4.4 | F10: pin the lesson walk's loop guard | 4.3 | follow-ups | Not started |
| Gate 4 | Review of Phase 4 | 4.4 | follow-ups | Not started |
| 5.1 | Start the two lab Chromes | Gate 2 | live | Not started |
| 5.2 | §4's loading check, in the lab | 5.1 | live | Not started |
| Gate 5 | Review of the live check | 5.2 | live | Not started |
| 5.3 | The live checks in your Chrome | Gate 5 | live | Not started |
| 6.1 | Copy H5's harness | 5.3 | live | Not started |
| 6.2 | H5's acceptance | 6.1 | live | Not started |
| 6.3 | §4's acceptance trials | 6.2 | live | Not started |
| 6.4 | Score §4's acceptance | 6.3 | live | Not started |
| 6.5 | Shut the labs down | 6.4 | live | Not started |
| 7.1 | `README.md` | Gate 3, Gate 4, 6.5 | docs | Not started |
| 7.2 | `docs/claude-code-integration.md` | 7.1 | docs | Not started |
| 7.3 | `docs/performance.md` | 7.2 | docs | Not started |
| 7.4 | `docs/failure-review.md` | 7.3 | docs | Not started |
| 7.5 | The design's status lines | 7.4 | docs | Not started |
| Gate 7 | Review of the docs | 7.5 | docs | Not started |
| 8.1 | Independent review of the whole change | Gate 7 | QA | Not started |
| 8.2 | Mutation check | Gate 7 | QA | Not started |
| 8.3 | Scope | Gate 7 | QA | Not started |
| 8.4 | List the reviews that ran during the build | Gate 7 | QA | Not started |
| 8.5 | Final checks | 8.1, 8.2, 8.3, 8.4 | QA | Not started |

## Phase 0: Read first, and record the baseline

Read first:
- **The design:** §2 and §4 in full, and §1 "Results" for H5.
- **`artifacts/experiments/2026-09-24/h8-network-settle/design-check/v4/README.md`:** what the saved diff holds.
- **browser-harness 0.1.13** in `.venv/lib/python3.13/site-packages/browser_harness/`: `helpers.py` (`drain_events`,
  `cdp`, `_send`), `daemon.py` (its event buffer, `BUF`), `admin.py` (`ensure_daemon`, `restart_daemon`) and `_ipc.py`
  (`connect`, `request`).

### Allowed APIs

| API | Behaviour | Source |
| --- | --- | --- |
| `browser_harness.helpers.drain_events()` | `_send({"meta": "drain_events"})["events"]`: returns and empties the daemon's buffer of CDP events, its last 500, for every client. Raises `TimeoutError` after 5 s, and `KeyError` when the daemon closes without replying | `helpers.py`, `daemon.py` |
| `Browser.observe`, `Browser.act` | As §4.4 changes them | `browser.py` |

### Anti-patterns

- **A dialog check:** §2 v2 cut it (P25). A dialog times out the repeated reads, and the server dismisses it after.
- **Catching `TimeoutError` inside `observe()`:** the other reads must still stop on a timeout (design §2.7).
- **`act()` or the history append inside the repeat loop:** the loop wraps the read alone.
- **Retyping §4's code:** it goes in as the saved, tested diff (P26).
- **A minimum wait, or a wait on anything but a DONE or BLOCKED answer:** §4.7 and §4.8 say why not.
- **Any network or model call in a test.**
- **Editing the registered part of the design doc:** everything above "### Results" in §1.

### Tasks

- **0.1 browser-harness is as the design says.**
  - **Check:** `grep -c '^def drain_events' .venv/lib/python3.13/site-packages/browser_harness/helpers.py` → `1`,
    `grep -c -E '^BUF = 500$' .venv/lib/python3.13/site-packages/browser_harness/daemon.py` → `1`, and the seven routes
    to the daemon that 2.7 replaces exist:
    `uv run python -c "import browser_harness._ipc as i, browser_harness.admin as a, browser_harness.helpers as h; print(all(callable(getattr(m, n, None)) for m, n in [(h, 'drain_events'), (h, '_send'), (h, 'cdp'), (a, 'ensure_daemon'), (a, 'restart_daemon'), (i, 'connect'), (i, 'request')]))"`
    → `True`.
- **0.2 Baseline.**
  - Make the folder, save a manifest of every file git tracks or would add, a copy of those files for the gates'
    diffs, and each test file's count. `.env` is ignored by git, so it is not copied:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; [ -e "$S/before.sha" ] && { echo "baseline exists; not overwritten"; exit 1; }; mkdir -p "$S"
    git ls-files -co --exclude-standard -z | xargs -0 shasum -a 256 > "$S/before.sha"
    git ls-files -co --exclude-standard -z | rsync -a --from0 --files-from=- ./ "$S/before/"
    for f in tests/test_*.py; do echo "$f $(uv run pytest -q "$f" | tail -1 | cut -d' ' -f1)"; done > "$S/baseline.txt"
    echo "tests $(uv run pytest -q | tail -1 | cut -d' ' -f1)" >> "$S/baseline.txt"
    ```

  - **A baseline is taken once, on unchanged files.** The command refuses to overwrite one. To start over, delete
    `$S/before.sha` and `$S/before/` by hand first, and only while the repo is back at the baseline.
  - **Check 1:** `uv run pytest -q` has no `failed` or `error`, and `uv run ruff check .` → `All checks passed!`.
  - **Check 2:** `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; grep -c -E '^tests(/test_[a-z0-9_]+\.py)? [0-9]+$' "$S/baseline.txt"`
    prints the number of `tests/test_*.py` files plus 1, `7` at `8953b45`, and
    `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; test -f "$S/before/jev_ultrafast/agent.py" && echo copied`
    → `copied`.
- **0.3 The saved §4 diff applies.** Five of its six files apply unchanged at `8953b45`. The sixth,
  `tests/test_mcp_server.py`, gained an import since, so 1.1 applies its two small hunks by hand.
  - **Check:** this prints `exit 0`:

    ```sh
    E=artifacts/experiments/2026-09-24/h8-network-settle/design-check/v4; git apply --check --include=jev_ultrafast/browser.py --include=jev_ultrafast/agent.py --include=scripts/report_runs.py --include=tests/test_agent.py --include=tests/test_report_runs.py "$E/design-v41.diff"; echo "exit $?"
    ```

- **0.4 Record the review digests,** for 8.4:
  `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; ls artifacts/reviews/2*.json > "$S/reviews-before.txt"`.
  - **Check:** `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; test -s "$S/reviews-before.txt" && echo recorded` → `recorded`.
- **Gate 0:** the repo checks pass. No review: nothing changed yet.

## Phase 1: §4's loading wait, from its saved diff (executor lane, offline)

Read first: design §4.3–§4.6; `browser.py` `__init__`, `observe`, `act` and `close`; `agent.py` `__init__`,
`_fresh_state`, `command("predict")` and `command("act")`; `scripts/report_runs.py` `facts()`; the `runner` fixture in
`tests/test_agent.py`; `FakeBrowser` in `tests/test_mcp_server.py`.

- **1.1 Apply §4's saved diff (P26).**
  - Apply it to its five clean files:

    ```sh
    E=artifacts/experiments/2026-09-24/h8-network-settle/design-check/v4; git apply --include=jev_ultrafast/browser.py --include=jev_ultrafast/agent.py --include=scripts/report_runs.py --include=tests/test_agent.py --include=tests/test_report_runs.py "$E/design-v41.diff"
    ```

  - **By hand, in `tests/test_mcp_server.py`:** the diff's two hunks for it. Add `import contextlib` in its
    alphabetical place among the imports, after `import builtins`, and add to `FakeBrowser`, after `dismiss_dialog()`:

    ```python
        def draining(self):
            return contextlib.nullcontext()

        def wait_for_loading(self, stop=None):
            return None
    ```

  - **Check 1:** the applied lines are the tested ones. This prints six lines ending in `same`, and keeps them in
    `$S/check-1.1.txt` for Gate 1:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; E=artifacts/experiments/2026-09-24/h8-network-settle/design-check/v4; for f in jev_ultrafast/browser.py jev_ultrafast/agent.py scripts/report_runs.py tests/test_agent.py tests/test_report_runs.py tests/test_mcp_server.py; do a=$(awk -v f="a/$f" '/^--- /{on=($2==f)} on && /^[+-]/ && !/^(\+\+\+|---) /' "$E/design-v41.diff" | sort | shasum); b=$(diff -U0 "$S/before/$f" "$f" | awk '/^[+-]/ && !/^(\+\+\+|---) /' | sort | shasum); [ "$a" = "$b" ] && echo "$f same" || echo "$f DIFFERS"; done | tee "$S/check-1.1.txt"
    ```

  - **Check 2:** `tests/test_agent.py` at baseline plus 24, and its 24 new tests, named in design §4.6 and read from
    the diff, pass by name. A keyword filter would also catch the existing
    `test_loading_waits_do_not_trigger_no_progress_stop`:

    ```sh
    E=artifacts/experiments/2026-09-24/h8-network-settle/design-check/v4; uv run pytest -q tests/test_agent.py -k "$(awk '/^--- /{on=($2=="a/tests/test_agent.py")} on && /^\+def test_/' "$E/design-v41.diff" | sed -E 's/^\+def (test_[a-z0-9_]+).*/\1/' | paste -sd'|' - | sed 's/|/ or /g')" | tail -1
    ```

    → `24 passed`.
  - **Check 3:** the extended tests pass:
    `uv run pytest -q -k "test_new_goal_resets_every_counter or test_report_counts_false_and_missed_done"` → `2 passed`.
  - **Check 4:** `tests/test_mcp_server.py` and `tests/test_report_runs.py` are at baseline plus 0, with no failure.
- **1.2 No test reaches the daemon's buffer.** With browser-harness's real `drain_events` replaced by one that fails,
  the executor lane's tests still pass (design §4.6). The whole suite runs so at 8.5, once no lane is mid-task:

  ```sh
  uv run python -c "import sys, pytest, browser_harness.helpers as h; h.drain_events = lambda *a, **k: (_ for _ in ()).throw(AssertionError('a test reached the daemon')); sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', 'tests/test_agent.py', 'tests/test_mcp_server.py', 'tests/test_report_runs.py']))" | tail -1
  ```

  - **Check:** its last line has no `failed` or `error`, and the same passed count as
    `uv run pytest -q tests/test_agent.py tests/test_mcp_server.py tests/test_report_runs.py`.
- **1.3 D14, tests 25–27, and a rename (design §4.6, v4.2).** Two rows of §4.5 had no test, so two broken variants of
  v4.1 survived every test. The new tests use the diff's `tab` fixture.
  - **D14:** in `Browser.observe()`, the drain after a read runs only once tracking has started, verbatim from design
    §4.4: `if self.network:` above `self._track()`, with the D14 comment.
  - **25. `test_the_next_goals_first_answer_waits_for_the_last_goals_loading`:** from the plan review's dry run, where
    it passed, and was the only test its variant failed:

    ```python
    def test_the_next_goals_first_answer_waits_for_the_last_goals_loading(runner, tab):
        runner.browser = tab.browser
        tab.operation.return_value = page()  # new_goal() reads a page
        click(tab)
        tab.at(0, sent("results"))
        tab.at(800, ended("results"))
        runner.new_goal("Open the first result")  # within 5 s of the click
        runner.state["started_at"] = time.perf_counter()  # new_goal() clears it; predict would set it
        act(runner, "DONE")
        assert runner.state["status"] == "done" and runner.state["loading_waits"] == [[920, False, False]]
    ```

    It tests §4.5's next-goal row (D9). The variant it kills: a new goal clearing the browser's `input_done`.
  - **26. `test_a_done_with_nothing_loading_stands_while_a_stop_is_pending`:** from the design review's S4:

    ```python
    def test_a_done_with_nothing_loading_stands_while_a_stop_is_pending(tab):
        click(tab)
        stop = Mock(side_effect=ValueError("90 s budget reached"))
        assert tab.browser.wait_for_loading(stop=stop) == [0, False, False]
        stop.assert_not_called()
    ```

    The variant it kills: the stop checked before the loaded test. Since `8953b45`, that variant would end a finished
    run `stopped`, and the review would queue it.
  - **27. `test_a_read_before_the_first_input_leaves_the_buffer_alone`:** before any input, `observe()` does not call
    `drain_events`, and the fake daemon's buffer keeps its events; after a click, the next `observe()` drains it.
  - **The rename:** `test_loading_waits_do_not_trigger_no_progress_stop`, which is about WAIT steps, becomes
    `test_wait_steps_do_not_trigger_no_progress_stop`, since `loading_waits` now names §4's waits.
  - **Check 1:** `uv run pytest -q tests/test_agent.py -k "test_the_next_goals_first_answer_waits_for_the_last_goals_loading or test_a_done_with_nothing_loading_stands_while_a_stop_is_pending or test_a_read_before_the_first_input_leaves_the_buffer_alone or test_wait_steps_do_not_trigger_no_progress_stop"`
    → `4 passed`, and `tests/test_agent.py` at baseline plus 27.
  - **Check 2:** `grep -c 'test_loading_waits_do_not_trigger_no_progress_stop' tests/test_agent.py` → `0`, and
    `grep -c '# D14:' jev_ultrafast/browser.py` → `1`.
- **Gate 1:** reviewed against design §4.4–§4.6. Its checks, in this order:
  1. **1.1's record:** `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; grep -c ' same$' "$S/check-1.1.txt"`
     → `6`. 1.1's Check 1 is not run again: 1.3 changes `browser.py` and `tests/test_agent.py` after it.
  2. **1.1's Checks 2–4:** Check 2's 24 names → `24 passed`, and Checks 3 and 4 as written. Check 2's count is now
     1.3's.
  3. **1.2's and 1.3's checks,** with `tests/test_agent.py` at baseline plus 27.
  4. **The lane checks.**

## Phase 2: §2's repeated read, by hand (executor lane, offline)

Read first: design §2.3, §2.5 and §2.6; `agent.py` `__init__`, `_fresh_state` and `command("act")`;
`tests/test_agent.py` `runner` and `act`; `tests/test_mcp_server.py` `FakeBrowser` and
`test_cancellation_during_the_decision_executes_no_input`; `mcp_server.py` `check_stop` and `shut_down`.

- **Fixture rule:** the `runner` fixture builds its state with the real `_fresh_state`, so new keys need no fixture
  change. Every new test sets a click with the file's `act(runner)` helper: the fixture's default decision is a fill,
  which would call the text model.

- **2.1 The constant (D1).** Add `READ_TIMEOUT_REPEATS = 2` after the imports, with the D1 comment verbatim.
  - **Check:** `uv run python -c "from jev_ultrafast import agent; print(agent.READ_TIMEOUT_REPEATS)"` → `2`, and
    `grep -c 'Delegated decision D1' jev_ultrafast/agent.py` → `1`.
- **2.2 The counter (D5).** Add `repeated_reads=0` to `_fresh_state` after `stale_streak=0` and before §4's
  `loading_waits=[]`, with its comment verbatim. Extend `test_new_goal_resets_every_counter` (design test 6): set
  `repeated_reads=2` in its `state.update`, and assert it is `0` after `new_goal`.
  - **Check:** `uv run pytest -q tests/test_agent.py -k test_new_goal_resets_every_counter` → `1 passed`, and
    `grep -c 'decision D5' jev_ultrafast/agent.py` → `1`.
- **2.3 The loop (design §2.3, D4).**
  - Replace the read after a step with the loop, verbatim from design §2.3 v2, with its two comment lines.
    - **Which read:** `agent.py` has three identical
      `state["page"] = state["browser"].observe(screenshot=self.screenshots)` lines.
    - **The one to replace:** in `command("act")`, right after the `self.save()` that follows
      `state["stale_streak"] = 0  # a step ran`.
  - **The `before_input` comment** in `__init__`, for §2 and §4 at once, within ruff's 120 characters:
    `# optional stop check before text calls, inputs and read repeats, and during a loading wait; raising stops them`.
  - Add design §2.5's tests 1, 2, 4 and 5, with its setups. Tests 3 and 7 were cut with the dialog check. Test 1's
    second page has its own URL, `https://example.test/results`, and fingerprint.
  - **Check 1:** `uv run pytest -q tests/test_agent.py -k "test_timed_out_read_after_a_step_is_repeated or test_timed_out_reads_stop_after_the_last_repeat or test_stop_check_runs_before_each_repeated_read or test_only_a_timed_out_read_is_repeated"`
    → `4 passed`.
  - **Check 2:** `grep -c READ_TIMEOUT_REPEATS jev_ultrafast/agent.py` → `3`: the definition, the range, and the
    last-read test.
  - **Check 3:** the loop wraps only the read.
    `awk '/for read in range/,/repeated_reads"\] \+= 1/' jev_ultrafast/agent.py | grep -c -E 'act\(|history|dialog_open'`
    → `0`, and the same `awk` range is 10 lines: `… | wc -l | tr -d ' '` → `10`. The pattern names `dialog_open`, the
    cut check, since the loop's own comment says "start_run then dismisses any dialog".
  - **Check 4:** `grep -A1 'Decision D4' jev_ultrafast/agent.py | tail -1 | sed 's/^ *//'` →
    `for read in range(READ_TIMEOUT_REPEATS + 1):`.
  - **Check 5:** `grep -c 'before text calls, inputs and read repeats, and during a loading wait' jev_ultrafast/agent.py` → `1`.
  - **Check 6:** the right read was replaced: `grep -B4 'for read in range' jev_ultrafast/agent.py | head -1 | sed 's/^ *//'`
    → `state["stale_streak"] = 0  # a step ran`.
  - **Check 7:** `tests/test_agent.py` at baseline plus 31: §4's 27, and tests 1, 2, 4 and 5.
- **2.4 Test 8 through the server.**
  - Add `test_a_read_that_timed_out_after_a_click_is_repeated`, following
    `test_cancellation_during_the_decision_executes_no_input`:
    - **The real tick:** `monkeypatch.setattr(FakeAgent, "command", Agent.command)`, `FakeBrowser.fresh` returning
      True, and `FakeBrowser.act` a `Mock`.
    - **Jev's stand-in:** `jev_ultrafast.agent.choose` answers CLICK `e2` ("Search"), then DONE.
    - **The timeout, once:** the first `observe(screenshot=False)` after the click raises
      `TimeoutError("Runtime.evaluate timed out after 5s waiting for the daemon")`; every other read behaves as
      `FakeBrowser.observe` does. `FakeBrowser.read_error` stays set once set, so wrap `observe` with a one-shot
      error.
    - **Expect:**
      - the result text contains ` · done · `;
      - `run_file()` has one step with `page_changed` not None, `repeated_reads` 1, and `loading_waits` `[]`, since
        the fake's wait returns None;
      - `act` has one call.
    - **The clock:** `FakeBrowser.wait_for_loading` stays stubbed. This file freezes `time.monotonic` for every
      module, so a real wait would never reach its cap (design §4.6).
  - **Check:** `uv run pytest -q tests/test_mcp_server.py -k test_a_read_that_timed_out_after_a_click_is_repeated` →
    `1 passed`, and `tests/test_mcp_server.py` at baseline plus 1.
- **2.5 The report counts repeats (D5).**
  - In `scripts/report_runs.py` `facts()`, add `"repeated reads": run.get("repeated_reads", 0),` to `totals`. It goes
    after `"stale decisions"` and before §4's `"loading wait ms"`, and uses `.get` because older run files lack the key.
  - Extend `test_report_counts_false_and_missed_done` (design test 9): give run 2 `repeated_reads=2`, and assert
    `"repeated reads 2"` is in the report's line.
  - **Check 1:** `uv run pytest -q tests/test_report_runs.py -k test_report_counts_false_and_missed_done` → `1 passed`.
  - **Check 2:** on the real runs, no file is skipped for lacking the new keys. The two counts this prints are equal.
    The baseline's copy of the script finds its runs from its own folder, so both get the paths:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; echo "now $(uv run python scripts/report_runs.py --runs artifacts/runs --artifacts artifacts 2>&1 >/dev/null | grep -c '^skipped')"; echo "before $(uv run python "$S/before/scripts/report_runs.py" --runs artifacts/runs --artifacts artifacts 2>&1 >/dev/null | grep -c '^skipped')"
    ```

  - **Check 3:** `uv run python scripts/report_runs.py 2>/dev/null | head -1 | grep -o -E 'repeated reads 0|loading wait ms 0|loading caps 0|loading event losses 0' | wc -l | tr -d ' '`
    → `4`.
- **2.6 Comments in `mcp_server.py` (design §2.6 and §4.6),** each within ruff's 120 characters:
  - **`check_stop`:** its comment becomes
    `# between steps, before each text call, input and repeated read, and while waiting for loading`.
  - **`shut_down`:** the comment on `STOP.set()` and the ponytail lines under it become:

    ```python
        STOP.set()  # the run stops between steps, before each input or repeated read, or in a loading wait, and saves
        # ponytail: a first page load, or a busy page's reads, longer than SHUTDOWN_WAIT_SECONDS can leave its tab open
        # and the stop unsaved; closing orphaned tabs at startup (design §10) is the upgrade if that happens.
    ```

  - **Check:** each prints the count shown:
    - `grep -c "repeated read" jev_ultrafast/mcp_server.py` → `2`;
    - `grep -c "while waiting for loading" jev_ultrafast/mcp_server.py` → `1`;
    - `grep -c "in a loading wait" jev_ultrafast/mcp_server.py` → `1`;
    - `grep -c "a busy page's reads" jev_ultrafast/mcp_server.py` → `1`;
    - `grep -c 'design §10' jev_ultrafast/mcp_server.py` → `1`.
- **2.7 No test reaches the daemon.** 1.2's command, with every route to the daemon replaced by one that fails:
  browser-harness's `drain_events`, `_send` and `cdp`, `admin.ensure_daemon` and `admin.restart_daemon`, and the
  socket calls `_ipc.connect` and `_ipc.request`:

  ```sh
  uv run python -c "import sys, pytest, browser_harness._ipc as i, browser_harness.admin as a, browser_harness.helpers as h; fail = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('a test reached the daemon')); h.drain_events = h._send = h.cdp = fail; a.ensure_daemon = a.restart_daemon = fail; i.connect = i.request = fail; sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider', 'tests/test_agent.py', 'tests/test_mcp_server.py', 'tests/test_report_runs.py']))" | tail -1
  ```

  - **Check:** its last line has no `failed` or `error`, and the same passed count as
    `uv run pytest -q tests/test_agent.py tests/test_mcp_server.py tests/test_report_runs.py`.
- **Gate 2:** reviewed against design §2.3, §2.5 and §2.6, and §4.6's comments. Its checks: 2.1–2.7's, and the lane
  checks. Three of the executor lane's files then pass to the follow-ups lane (§"How to use this plan").

## Phase 3: The review script's follow-ups (review lane, offline)

Read first: `docs/failure-review.md` §6.5 and §7.5; in `scripts/review_runs.py`:
- `record_review()`, `apply_decision()`, `add_from_recovery()` and `unapproved()`;
- `without_values()`, `holds_value()`, `scrub()` and `schema_errors()`;
- `result_failure()`, `once_command()` and `auto_command()`.

Also `tests/test_review_runs.py`'s `test_apply_applies_checked_note_decisions_and_writes_the_digest` and
`test_apply_refuses_bad_replies`.

Every fix keeps `docs/failure-review.md`'s rule (§7.5) that no task value reaches the digest, the notes file,
`state.json` or what code prints.

- **Where the lane works:** in `$S/review-lane`, a copy of the baseline, until 3.7.
  - **Why:** a real Jev session can start `scripts/review_runs.py auto` from the repo at any time, and
    `jev_ultrafast/__init__.py` imports `agent` and `browser`, which the executor lane is editing. In the copy,
    neither half-done lane affects the other.
  - **Make it once,** before 3.1:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; [ -e "$S/review-lane" ] && { echo "copy exists; not overwritten"; exit 1; }; cp -R "$S/before" "$S/review-lane"
    ```

  - **Edit only** its `scripts/review_runs.py` and `tests/test_review_runs.py`.
  - **Run 3.1–3.6's checks from inside the copy:** start each with
    `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; cd "$S/review-lane" &&`, and in
    it, run `uv run pytest` as
    `PYTHONPATH="$S/review-lane" PYTHONDONTWRITEBYTECODE=1 /Users/terry/projects/jev-ultrafast/.venv/bin/python -m pytest -p no:cacheprovider`
    and `uv run ruff` as `/Users/terry/projects/jev-ultrafast/.venv/bin/ruff`. The tests then import the copy's
    code, and write no bytecode into it; `uv run` would build a second environment from the copy's `pyproject.toml`.

- **3.1 F1: check only the fields a decision uses (P29).** Today `record_review()` refuses a note decision whose `note`
  or `detail` holds a task value. An add never stores its `note`, yet a value there refused both adds of the first
  review. A flag and a retire read only `note`, the note they name.
  - **The change:** `USED_FIELDS = {"add": ("detail",), "flag": ("note",), "retire": ("note",)}`, with a P29 comment
    naming this plan, and `held` reads only those fields. `without_values()` still replaces values in every field.
  - **Test:** `test_note_checks_read_only_the_fields_each_action_uses`, with 3 cases:
    - an add with a task value in its `note` alone is applied;
    - a flag with one in its `detail` alone is applied;
    - a flag with one in its `note` is refused with `its note holds a value from a task`.

    In each, the value reaches neither the digest nor what code prints.
  - **Check:** `uv run pytest -q tests/test_review_runs.py -k test_note_checks_read_only_the_fields_each_action_uses`
    → `3 passed`, and `grep -c 'Delegated decision P29 (docs/executor-improvements-plan.md)' scripts/review_runs.py`
    → `1`.
- **3.2 F6: keep a decision's outcome whole (P30).** Replacing values in `outcome` also replaced code's own words: the
  first review's refusals read "a value <value> a task", since "from" was a task value.
  - **The change:** `without_values()` keeps `outcome` whole, as it keeps `action` and `hint`, with a P30 comment.
    - **An outcome is code's own text with a few slots:**
      - run IDs and note IDs, which are kept names;
      - a flag's or a retire's `note`, which 3.1 checks before the action runs;
      - `check_note()`'s reasons, which are fixed text.
    - **The one other slot:** `retire`'s refusal "it cites no queued run on <site>" quotes the note's site from the
      notes file, which another queued run may have typed. It becomes `it cites no queued run on <note ID>'s site`.
      The ID is the decision's `note`, which 3.1 checks, so no slot can hold a task value.
      `test_apply_refuses_bad_replies` still passes: its "cites no queued run on example.com" is part of "…on
      example.com-1's site".
  - **Test:** `test_a_decisions_outcome_is_kept_whole`, with 2 cases:
    - with "from" a task value, a refused add's outcome is `its detail holds a value from a task`;
    - a retire citing no queued run on its note's site, a site another queued run typed, names the note's ID.

    In both, the outcome is whole, and no task value reaches the digest or what code prints.
  - **Check:** `uv run pytest -q tests/test_review_runs.py -k test_a_decisions_outcome_is_kept_whole` → `2 passed`, and
    `grep -c 'Delegated decision P30 (docs/executor-improvements-plan.md)' scripts/review_runs.py` → `1`.
- **3.3 F2: a notes-file failure leaves its runs queued (P34).** A decision refused because the notes file cannot be
  written (`OSError`), or cannot be read (P8), still puts its runs in the digest's queue. That marks them reviewed, so
  that recovery is never queued again.
  - **The change:** `record_review()` leaves out of the digest's `queue.runs` the queued runs cited by a decision
    that the notes file refused.
    - **How it knows:** a new `NotesFileError(OSError)` in `scripts/review_runs.py`, with a P34 comment. The add and
      flag branches raise it for `site_notes.load()`'s error, where they raise `ValueError` today, and a retire calls
      `site_notes.load()` before `site_notes.update()` to check the same. `record_review()` then keys on `OSError`,
      which covers both.
    - **Why not in `site_notes.py`:** `update()` raises `ValueError` both for an unreadable file and for a refused
      change, and this plan leaves that file alone.
    - **ponytail:** a file that turns unreadable between that `load()` and `update()` still counts as a refusal.
  - **Test:** `test_a_decision_the_notes_file_refused_leaves_its_runs_queued`, with 2 cases:
    - `site_notes.add_note` raises `OSError`;
    - the notes file holds text that is not JSON, so `site_notes.load()` returns an error. `build_queue()` also
      raises while the file cannot be read, so the test breaks the file after building the queue, and restores it
      before building the next.

    In each, the digest's queue lacks the add's runs, and the next `build_queue()` queues them again.
  - **Check:** `uv run pytest -q tests/test_review_runs.py -k test_a_decision_the_notes_file_refused_leaves_its_runs_queued`
    → `2 passed`, and `grep -c 'Delegated decision P34 (docs/executor-improvements-plan.md)' scripts/review_runs.py`
    → `1`.
- **3.4 F5: `auto` stops quietly on an unreadable exclude file.** `read_exclude()` raises `OSError` for an exclude
  file it cannot read, and `auto_command()` catches only `ValueError`. So each label starts an `auto` that logs a
  traceback. Nothing is paid.
  - **The change:** `auto_command()` catches `OSError` there too, and prints `<time> auto: <error>; no review started.`
  - **Test:** `test_auto_stops_quietly_on_an_unreadable_exclude_file`. The exclude path is a directory; `auto`
    returns 0, prints that line, starts no review, and leaves `state.json` unchanged.
  - **Check:** `uv run pytest -q tests/test_review_runs.py -k test_auto_stops_quietly_on_an_unreadable_exclude_file` → `1 passed`.
- **3.5 F7: a failure's text never quotes a task value.** A failure can quote the model in two ways:
  - a reply's unknown key, through `schema_errors()`;
  - `LABEL_CHARACTERS` of a failed result's text, through `result_failure()`.

  Since v4.4 no task value is sent, so such a match can only be a common word. But it reaches the digest and what code
  prints; `state.json` keeps only a count of failures.
  - **The change:** `schema_errors()` and `result_failure()` take a `quote` function, and pass only the model's text
    through it: the unknown key, and the result's text. `record_review()` and `launch_review()` pass one that clips to
    `LABEL_CHARACTERS` and replaces the queue's task values, as `without_values()` does. Code's own words around a
    quote stay whole, for P30's reason.
  - **Test:** `test_a_failure_never_quotes_a_task_value`, with 2 cases: an unknown key equal to a task value, and a
    failed result whose text holds one. In each, a second task value is one of code's own words in that failure,
    `reply` or `ended`, and stays whole. The quoted value reaches neither the digest nor what code prints.
  - **Check:** `uv run pytest -q tests/test_review_runs.py -k test_a_failure_never_quotes_a_task_value` → `2 passed`.
- **3.6 F8: overlapping task values are replaced together.** A value whose start another match took is not matched.
  With "jane smith" and "smith bo lee" typed in two runs, "jane smith bo lee" keeps "bo lee". `scrub()` and
  `holds_value()` share the gap. The real queue has no such pair today.
  - **The change:** find every value's match at each position, with a lookahead, and replace the union of their spans,
    so overlapping matches become one `<value>`. A match inside a kept name still stays, as today.
  - **Test:** `test_overlapping_task_values_are_replaced_together`, on that pair:
    - through `scrub()` and `without_values()`, which give `<value> bo lee` today, and `<value>` after the fix;
    - through `holds_value()`, with a kept name covering "jane smith". Today its one match is kept, so it returns
      False; after the fix it also finds "smith bo lee", and returns True. Without that kept name it returns True
      either way, and would prove nothing.
  - **Check:** `uv run pytest -q tests/test_review_runs.py -k test_overlapping_task_values_are_replaced_together` →
    `1 passed`, and `tests/test_review_runs.py` at baseline plus 11.
- **3.7 Land the review lane's two files, after Gate 2.** By then `jev_ultrafast/` is final, and the repo's review
  tests import it. The command refuses if either repo file changed since the baseline, and lands
  `scripts/review_runs.py` by a rename, so a review starting meanwhile reads the old file or the new one, never part
  of one:

  ```sh
  S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; L="$S/review-lane"; cmp -s scripts/review_runs.py "$S/before/scripts/review_runs.py" && cmp -s tests/test_review_runs.py "$S/before/tests/test_review_runs.py" || { echo "a repo file changed; nothing landed"; exit 1; }; cp "$L/tests/test_review_runs.py" tests/test_review_runs.py && cp "$L/scripts/review_runs.py" scripts/review_runs.py.landing && mv scripts/review_runs.py.landing scripts/review_runs.py && date +%Y%m%d-%H%M%S > "$S/review-landed.txt"
  ```

  - **Check:** `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; cmp scripts/review_runs.py "$S/review-lane/scripts/review_runs.py" && cmp tests/test_review_runs.py "$S/review-lane/tests/test_review_runs.py" && echo landed`
    → `landed`, and in the repo, `tests/test_review_runs.py` at baseline plus 11 and `tests/test_site_notes.py` at
    baseline plus 0.
- **Gate 3:** reviewed against `docs/failure-review.md` §6.5 and §7.5, and P29, P30 and P34, in the repo. Its checks: 3.1–3.7's, run in the
  repo now, and the lane checks.

## Phase 4: The report's and the server tests' follow-ups (follow-ups lane, offline)

Read first:
- `scripts/report_runs.py` `review_lines()`;
- `scripts/review_runs.py` `begin()`, `finish()` and `launch_review()`, which writes the placeholder digest;
- `tests/test_report_runs.py` `test_report_prints_reviewer_text_only_inside_a_marked_block`;
- `jev_ultrafast/mcp_server.py` `start_review()` and `store_lesson()`, and `tests/test_mcp_server.py`'s trigger tests.

- **4.1 F4: the report shows a running review as running.** A review writes a placeholder digest with a `failure` when
  it starts, so a crash leaves a record. While it runs, up to `REVIEW_TIMEOUT_MINUTES` (15), the report counts that
  digest as failed.
  - **The change:** `review_lines()` reads `state.json`'s `running`, the start in ISO form, which names the digest as
    `%Y%m%d-%H%M%S`. That digest shows `<path>: running`, and is left out of the failed count and the cost, only
    while its start is less than `REVIEW_TIMEOUT_MINUTES` ago, imported from `scripts.review_runs`.
  - **Why the limit:** a review killed before its end leaves `running` set until a later start settles it, and with
    `JEV_AUTO_REVIEW=0` none may come. Past the limit, its digest counts as failed, as today.
  - **Test:** `test_report_shows_a_running_review_as_running`, with 2 cases: a start 1 minute ago shows `running`
    and is not counted; a start `REVIEW_TIMEOUT_MINUTES` + 1 minutes ago shows `failed` and is counted.
  - **Check:** `uv run pytest -q tests/test_report_runs.py -k test_report_shows_a_running_review_as_running` →
    `2 passed`.
- **4.2 F11: pin the hyphenated look-alike.** The rule that a hyphenated tail holding a dot stays whole is untested.
  - **The change:** in `test_report_prints_reviewer_text_only_inside_a_marked_block`, the look-alike flag's reason also
    names `private.example-cdn.net`, and the test asserts that its line keeps it.
  - **Check:** `uv run pytest -q tests/test_report_runs.py -k test_report_prints_reviewer_text_only_inside_a_marked_block`
    → `1 passed`, `grep -c 'private.example-cdn.net' tests/test_report_runs.py` → at least `1`, and
    `tests/test_report_runs.py` at baseline plus 2.
- **4.3 F9: pin `start_review()`'s arguments.** Its `Popen` call has no test: the trigger tests replace
  `start_review()`.
  - **Test:** `test_start_review_runs_auto_in_its_own_session`. The autouse `server` fixture replaces
    `start_review()` with a `Mock`, so the test calls the real one, saved at import:
    `REAL_START_REVIEW = mcp_server.start_review` at the top of the file. `AUTO_LOG` is relative, and the fixture's
    `chdir` puts it under `tmp_path`. With `subprocess.Popen` recorded, the real `start_review()` passes:
    - `[sys.executable, str(REVIEW_SCRIPT), "auto"]`;
    - `stdin=subprocess.DEVNULL`;
    - the same open `auto.log` for `stdout` and `stderr`;
    - `start_new_session=True`.
  - **Check:** `uv run pytest -q tests/test_mcp_server.py -k test_start_review_runs_auto_in_its_own_session` → `1 passed`.
- **4.4 F10: pin the lesson walk's loop guard.** Without `previous not in runs` in `store_lesson()`'s walk, two
  hand-edited runs that name each other as `previous_run` hang `report_outcome`: the chain never grows, so
  `MAX_CHAIN_RUNS` never ends it.
  - **Test:** `test_a_looping_chain_ends_the_lesson_walk`. With two such run files, `store_lesson()` returns within
    5 s:
    - **The limit:** a `SIGALRM` handler that raises `AssertionError("the lesson walk did not end")`, then
      `signal.alarm(5)`. Not `TimeoutError`: it is an `OSError`, which the walk catches, so the walk would just end,
      and the test would pass with the guard removed;
    - **In a `finally`:** `signal.alarm(0)`, and the old handler restored.

    A bare alarm would end pytest with exit code 142 and no `FAILED` line, and 8.2 reads those lines.
  - **Check:** `uv run pytest -q tests/test_mcp_server.py -k test_a_looping_chain_ends_the_lesson_walk` → `1 passed`,
    and `tests/test_mcp_server.py` at baseline plus 3.
- **Gate 4:** reviewed against the follow-ups above. Its checks: 4.1–4.4's, and the lane checks.

## Phase 5: The live check (live lane, Chrome, no model calls)

Read first: `scripts/check_guards.py` in full, and design §4.6 "A live check". The script loads `data:` pages, drives
`Browser` directly, collects `passed` lines, and ends with a `PASS:` line; today
`PASS: 23 browser guard checks; no model calls`, after `pop-up tab closed and reported`.

- **5.1 Start the two lab Chromes, each with a fresh profile (P24).**
  - **Before:** nothing listens on either port. For each of 9335 and 9337,
    `lsof -nP -iTCP:<port> -sTCP:LISTEN -t | wc -l | tr -d ' '` → `0`. If something does, it is not the plan's: stop,
    kill nothing, and report what listens there.
  - Run:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation
    for lab in labC:9335 labE:9337; do name=${lab%:*}; port=${lab#*:}; profile=$(mktemp -d /tmp/jev-$name-chrome.XXXXXX); echo "$profile" > "$S/$name.profile"
      nohup "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir="$profile" \
        --remote-debugging-port=$port --no-first-run --no-default-browser-check --window-size=1240,960 about:blank \
        > "$profile.log" 2>&1 &
      echo $! > "$S/$name.pid"; disown; done
    ```

  - **Check:** for each lab and its port,
    `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; curl -s --retry 10 --retry-delay 1 --retry-connrefused --max-time 20 http://127.0.0.1:<port>/json/version | tee "$S/<lab>-version.json" | grep -c '"Browser"'`
    → `1`, and `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; test -s "$S/<lab>.pid" && echo recorded`
    → `recorded`.
  - **If a version check fails:** run 6.5's shutdown, then stop and report that lab's Chrome log: the path in
    `$S/<lab>.profile`, plus `.log`.
- **5.2 §4's loading check, run in `labC` (P23).** Build it as design §4.6 "A live check" specifies:
  - a `ThreadingHTTPServer` on 127.0.0.1, port 0, `daemon_threads=True`;
  - serving the one page, with its "Search", "Slow list", "Poll", "Ad" and "Next" controls;
  - the `Target.getTargets` assert after "Ad".

  Its six lines go after the pop-up check.
  - **Check:** `BU_NAME=labC BU_CDP_URL=http://127.0.0.1:9335 uv run python scripts/check_guards.py | tail -8` prints
    exactly:

    ```
    pop-up tab closed and reported
    a final answer before any request does not wait
    a final answer once the request has started waits until its text shows (uncapped)
    a request that never ends caps the wait at 5 s after the click
    a cross-site iframe's document does not hold the wait
    a main-frame navigation holds the wait until its document loads
    a scroll made while a request loads keeps it: the next final answer waits for it (D13)
    PASS: 29 browser guard checks; no model calls
    ```

  - **If it fails:** run 6.5's shutdown, then stop and report. A failing assert here is a finding for design review,
    not something to tune.
- **Gate 5:** reviewed against design §4.6: `scripts/check_guards.py`. Its checks: 5.2's, and the lane check,
  `uv run ruff check scripts/check_guards.py`. It closes before the check runs in your Chrome.
- **5.3 The live checks in your Chrome.**
  - **Why your Chrome as well:** `scripts/check_guards.py` is the repo's standing live check, and it normally runs
    against your daemon. That daemon is attached to one of your tabs and runs your extensions; the labs have neither.
  - **Before:** no tab in your Chrome shows a JavaScript dialog, since the existing dialog check shares the daemon's
    one dialog record.
  - **Check:** `uv run python scripts/check_guards.py | tail -8` → the same eight lines.
  - **If it fails here after passing in the lab:** stop and report. If a dialog was open in one of your tabs, close it
    and run 5.3 once more.
  - **What you see:** its windows open and close in your Chrome. Nothing else in your Chrome is touched.

## Phase 6: Acceptance (live lane, lab Chromes, no model calls)

Read first:
- `artifacts/experiments/2026-09-24/labC-h3-h5/`: `h5_fix_trials.py`, `h5_fixture.py`, `labc_common.py` and
  `summary.md` §3 "Test 3";
- `artifacts/experiments/2026-09-24/h8-network-settle/`: `h8c_trials.py`, `h8c_common.py`, `h8d_trials.py`,
  `h8c_analyze.py` and `h8d_analyze.py`;
- design §3, "Results (H8c)" and "Results (H8d)".

- **6.1 Copy H5's harness to a new folder,** so the registered raw files stay unchanged.
  - Run `A=artifacts/experiments/$(date +%F-%H%M)/h5-acceptance; [ -e "$A" ] && { echo "$A exists; not overwritten"; exit 1; }; echo "$A" > /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/h5_dir; mkdir -p "$A"; cp artifacts/experiments/2026-09-24/labC-h3-h5/{labc_common.py,h5_fixture.py,h5_fix_trials.py} "$A/"`.
  - **The folder's name carries the minute,** so 8.1's re-run gets a new one.
  - **Every later H5 command** starts with `A=$(cat /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/h5_dir);`.
  - **Where the copy writes:** `labc_common.py` sets `RAW = OUT / "raw"` from its own folder, and `h5_fix_trials.py`
    points `mcp_server.RUNS` inside `RAW`. Its `log_calls()` skips a `Browser` method that does not exist, so the cut
    `dialog_open` needs no edit.
  - **Record the registered folders,** to show in 6.4 that they did not change:
    `find artifacts/experiments/2026-09-24/labC-h3-h5 artifacts/experiments/2026-09-24/h8-network-settle -type f -print0 | sort -z | xargs -0 shasum -a 256 > /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/registered.sha`.
  - **Edit only `$A/h5_fix_trials.py`:**
    - add `"implemented": "/jev-ultrafast/jev_ultrafast/"` to the package map;
    - after the package assert, add `assert ARM != "implemented" or hasattr(loop, "READ_TIMEOUT_REPEATS")`;
    - add `repeated_reads=state.get("repeated_reads")` to `record.update(...)`;
    - add `"repeated_reads": record.get("repeated_reads")` to `record["checks"]`.
  - **Check 1:** with `A` set as above:
    - `diff artifacts/experiments/2026-09-24/labC-h3-h5/h5_fix_trials.py $A/h5_fix_trials.py | grep -c '^<'` → `1`;
    - the same `| grep -c '^>'` → `4`;
    - `grep -c repeated_reads $A/h5_fix_trials.py` → `2`.
  - **Check 2:** `uv run python $A/h5_fixture.py` → `fixture self-check passed on port …`.
- **6.2 H5's acceptance: 5 busy trials and 1 alert trial, in `labC`.**
  - Run from the repo root, with no `PYTHONPATH`:

    ```sh
    A=$(cat /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/h5_dir)
    for t in 1 2 3 4 5; do BU_NAME=labC BU_CDP_URL=http://127.0.0.1:9335 uv run python $A/h5_fix_trials.py implemented busy $t; done
    BU_NAME=labC BU_CDP_URL=http://127.0.0.1:9335 uv run python $A/h5_fix_trials.py implemented alert 1
    ```

  - **Why exactly one repeat per busy trial:** the fixture blocks the page for 7 s. The first read times out at about
    5 s, and the block ends inside the second read's 5 s wait; in H5's test the repeats returned after 2,001–2,002 ms.
  - **Why two in the alert trial:** page 2 opens `alert()` as it loads, after the click returned. Each read times out
    while it is open, until the repeats run out; then the server dismisses it (design §2.4).
  - **Check:** this prints `implemented-alert-1.json stopped True True 2 ['the page showed a dialog; dismissed']`,
    then `implemented-busy-N.json done True True 1 []` for each N from 1 to 5:

    ```sh
    A=$(cat /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/h5_dir); uv run python -c "import json,glob; [print(f.rsplit('/',1)[1], (c:=(r:=json.load(open(f)))['checks'])['status'], c['each_input_once'], c['one_submission_at_server'], c['repeated_reads'], r['notes']) for f in sorted(glob.glob('$A/raw/h5_fix/implemented-*.json'))]"
    ```
  - **A trial that prints anything else fails the acceptance.** It is not re-run: keep every raw file, run 6.5's
    shutdown, and bring the result back to design review.
- **6.3 §4's acceptance trials, gate arm only, in `labE` (P24, P27).**
  - **The copy:** `h8_common.py` sets `RAW` from its own folder, so the copy writes only under `$B`. The originals are
    read-only, and `cp` keeps that, so the command makes the copies writable:

    ```sh
    B=artifacts/experiments/$(date +%F-%H%M)/loading-acceptance; [ -e "$B" ] && { echo "$B exists; not overwritten"; exit 1; }; echo "$B" > /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/loading_dir; mkdir -p "$B"; cp artifacts/experiments/2026-09-24/h8-network-settle/{h8_common.py,h8_trials.py,h8b_trials.py,h8c_common.py,h8c_trials.py,h8d_trials.py,net_settle.py,net_gate.py} "$B/"; chmod u+w "$B"/*.py
    ```

  - **The one edit,** in `$B/h8c_trials.py`: `CONDITIONS` gives every site `("gate",)` instead of `("today", "gate")`.
    - **Check:** `B=$(cat /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/loading_dir); diff artifacts/experiments/2026-09-24/h8-network-settle/h8c_trials.py $B/h8c_trials.py | grep -c '^[<>]'`
      → `2`.
  - **The code under test is the repo's:** `h8c_common.py` refuses any `jev_ultrafast` but the one in `H8C_BUILD`, so
    `H8C_BUILD` and `PYTHONPATH` name the repo root. Run:

    ```sh
    B=$(cat /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/loading_dir); R=/Users/terry/projects/jev-ultrafast
    BU_NAME=labE BU_CDP_URL=http://127.0.0.1:9337 H8C_BUILD=$R PYTHONPATH=$R uv run python -u $B/h8c_trials.py google_flights duckduckgo crates.io
    BU_NAME=labE BU_CDP_URL=http://127.0.0.1:9337 H8C_BUILD=$R PYTHONPATH=$R uv run python -u $B/h8d_trials.py
    ```

  - **A series that stops early** continues with the same command plus `--resume`, which keeps its trials and attempt
    counts. That is the harness's own rule, not a re-run for a pass.
  - **Check:** both raw files ran the repo's code. Each records it once, as `code_sha256`, and `--resume` refuses a
    file whose code differs. This prints `[True, True]`:

    ```sh
    B=$(cat /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/loading_dir); uv run python -c "import hashlib, json; code = {name: hashlib.sha256(open(name, 'rb').read()).hexdigest() for name in ('jev_ultrafast/browser.py', 'jev_ultrafast/agent.py', 'jev_ultrafast/snapshot.js')}; print([json.load(open(path))['code_sha256'] == code for path in ('$B/raw/h8c_trials_labE.json', '$B/raw/h8d/h8c_trials_labE.json')])"
    ```
- **6.4 Score §4's acceptance (P33).** Two scorers, each copied into `$B`, so it reads only `$B/raw`, the
  acceptance's trials, and made writable, as 6.3's copies are:

  ```sh
  B=$(cat /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/loading_dir); H=artifacts/experiments/2026-09-24/h8-network-settle; cp "$H/h8c_analyze.py" "$B/acceptance_score.py"; cp "$H/h8d_analyze.py" "$B/acceptance_score_youtube.py"; chmod u+w "$B/acceptance_score.py" "$B/acceptance_score_youtube.py"
  ```

  - **In each copy:** replace `FROZEN` and `CODE` with the sha256 of `jev_ultrafast/browser.py`, `agent.py` and
    `snapshot.js`, read from `/Users/terry/projects/jev-ultrafast` and keyed by those paths as `CODE` is today, and
    add `import hashlib`. Nothing else changes, apart from the next bullet.
  - **`$B/acceptance_score.py`,** from `h8c_analyze.py`: the three sites, in `$B/raw/h8c_trials_labE.json`.
  - **`$B/acceptance_score_youtube.py`,** from `h8d_analyze.py`: YouTube, in `$B/raw/h8d/h8c_trials_labE.json`. Every
    `labG` in it also becomes `labE`, since it opens `labG`'s file and refuses any other lab.
  - **What else they print:** with no today arm, no replays and no scroll variant, H8c's tests 1, 3 and 4 print `FAIL`
    or `NOT TESTED`, and its test 2 wants four sites in one file. The acceptance reads only the lines below.
  - **Check 1:** each command starts with
    `B=$(cat /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/loading_dir);`, and each part
    must hold:
    - `uv run python "$B/acceptance_score.py"`: under "Test 2", the lines for `google_flights`, `duckduckgo` and
      `crates.io` each show `N/10` with N at least 9, and `capped trials 0` or `capped trials 1`; and it prints
      `Reported: waits with lost events 0`;
    - `uv run python "$B/acceptance_score_youtube.py"`: its line `Test: gate, accepted reads with results …` ends
      `-> H8d verified`, which needs 10 scored trials, at least 9 with results, and at most 1 capped;
    - YouTube records no lost events:
      `uv run python -c "import json; d = json.load(open('$B/raw/h8d/h8c_trials_labE.json')); print(sum(r['wait'][2] for t in d['trials'] for r in t.get('rounds', []) if r.get('wait')))"`
      → `0`.
  - **Check 2:** the registered folders are unchanged. This prints nothing:

    ```sh
    find artifacts/experiments/2026-09-24/labC-h3-h5 artifacts/experiments/2026-09-24/h8-network-settle -type f -print0 | sort -z | xargs -0 shasum -a 256 | diff /Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation/registered.sha -
    ```
  - **Record:** `$A/summary.md` and `$B/summary.md` each hold the date, the lab Chrome's version from
    `$S/<lab>-version.json`, the result lines, and the code the trials ran:
    - **`$A/summary.md`:** the `source` its run files record, one hash over `jev_ultrafast/`;
    - **`$B/summary.md`:** the `code_sha256` its raw files record, a hash for each of `browser.py`, `agent.py` and
      `snapshot.js`: those trials drive `Browser` directly and write no run file.
  - **If Check 1 fails:** keep every raw file, run 6.5's shutdown, and bring the result back to design review.
- **6.5 Shut the labs down.**
  - **First, record your own daemon's process ID:**
    `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; uv run python -c "from browser_harness import _ipc as ipc; print(ipc.identify('default'))" > "$S/default_pid"`.
  - Then run the shutdown. It names each lab's daemon literally, kills each Chrome by its recorded process ID, and
    refuses to touch a lab with a missing record:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation
    for name in labC labE; do profile=$(cat "$S/$name.profile" 2>/dev/null); chrome=$(cat "$S/$name.pid" 2>/dev/null)
      if [ -z "$profile" ] || [ -z "$chrome" ]; then echo "$name not recorded; nothing killed"; continue; fi
      pid=$(uv run python -c "from browser_harness import _ipc as ipc; print(ipc.identify('$name') or '')" | tail -1)
      [ -n "$pid" ] && kill "$pid"
      ps -p "$chrome" -o command= | grep -q -F -- "--user-data-dir=$profile" && kill "$chrome"
      pkill -f -- "--user-data-dir=$profile"; done
    ```

  - **Why the `ps` check:** a recorded process ID can be reused after its process exits, so Chrome is killed by ID only
    while that ID's command line still names the lab profile. `pkill` matches only the unique temporary profile path.
  - **Check 1:** for each of 9335 and 9337, `curl -s --max-time 2 http://127.0.0.1:<port>/json/version; echo "exit $?"`
    prints a non-zero exit code.
  - **Check 2,** as its own command, repeated once if Chrome is still exiting. This prints `0` for each lab 5.1
    recorded, and `<lab> not recorded` for any other:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; for name in labC labE; do profile=$(cat "$S/$name.profile" 2>/dev/null); [ -n "$profile" ] || { echo "$name not recorded"; continue; }; pgrep -f -- "--user-data-dir=$profile" | wc -l | tr -d ' '; done
    ```

    - **Why the guard:** with no record, the pattern would be `--user-data-dir=` alone. That matches every process
      started with that flag, your own Chrome among them: 58 on this Mac on 2026-09-29.
    - **If a count is not `0`:** run this once for that lab, with `<lab>` replaced by its name, then check again. It
      kills nothing without a recorded profile. If the check still fails, stop and report:

      ```sh
      S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; profile=$(cat "$S/<lab>.profile" 2>/dev/null); [ -n "$profile" ] && pkill -9 -f -- "--user-data-dir=$profile"
      ```
  - **Check 3:** your daemon is untouched:
    `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; uv run python -c "from browser_harness import _ipc as ipc; print(ipc.identify('default'))" | diff - "$S/default_pid"`
    prints nothing. If it prints a difference, stop, report both IDs, and change nothing on your daemon.

## Phase 7: Docs (docs lane, offline)

Read first: design §2.6 and §4.6 "Docs and comments"; `docs/failure-review.md` §4, §7.5, its status list, and the rows
and bullet that call the two executor fixes "(not built)".

- **7.1 `README.md`,** "Wait for useful state", which lists every wait the loop makes: append "A DONE or BLOCKED answer
  also waits while a request its recent inputs started is loading, up to 5 s after the last input."
  - **Check:** `grep -c 'also waits while a request its recent inputs started is loading' README.md` → `1`.
- **7.2 `docs/claude-code-integration.md`,** five edits:
  1. **The §6.2 sketch:** the comment `# also runs before each input, via agent.before_input` becomes
     `# also runs before each input and each repeated read, and in a loading wait, via agent.before_input`.
  2. **"Dialogs":** append "After a step, a read that times out is repeated first, up to 2 times
     (`docs/executor-improvements.md` §2), so a dialog stops the run about 10 s later."
  3. **"Deadline, cancellation and shutdown":** "are checked between steps and again right before each input
     (`Agent.before_input`)" becomes "are checked between steps, right before each input, before each repeated read,
     and at every poll of a loading wait (`Agent.before_input`)".
  4. **The Speed row:** append " · repeated reads per run (reads after a step that timed out and were taken again) ·
     loading wait ms, caps and event losses per run (a final answer's wait for loading)".
  5. **The "Continue or stop" row:** "Applies Jev's DONE or BLOCKED answer and its own rules (§6.2)" becomes "Applies
     Jev's DONE or BLOCKED answer, after waiting while the page visibly loads what recent inputs started
     (`docs/executor-improvements.md` §4), and its own rules (§6.2)".
  - **Check:** each of these occurs exactly once, `grep -c -F '<phrase>' docs/claude-code-integration.md` → `1`:
    - `each repeated read, and in a loading wait, via agent.before_input`
    - `is repeated first, up to 2 times`
    - `and at every poll of a loading wait (`
    - `loading wait ms, caps and event losses per run`
    - `after waiting while the page visibly loads`
  - **Check 2:** the replaced text is gone. `grep -c -F '# also runs before each input, via agent.before_input' docs/claude-code-integration.md`
    and `grep -c -F 'are checked between steps and again right before each input' docs/claude-code-integration.md` → `0`.
- **7.3 `docs/performance.md`.** It marks later changes with bullets such as "**Fixed after the comparison**".
  - **§2:** append design §2.6's sentence to the bullet on the 48 runs, which names the one stopped run.
  - **§4:** add a new bullet after "**Claude's labels matched every run**":
    > **Changed after the comparison:** a DONE or BLOCKED answer now waits for visible loading
    > (`docs/executor-improvements.md` §4). Over H8c's replayed final answers the median wait is 0 ms, with 1 of 25
    > capped. Where results were still loading, as on Google Flights, it is a median of 691 ms per trial, in place of
    > a false DONE and the follow-up run it cost. The comparison's times do not include it.
  - **Check:** `grep -c "whether it would have saved this run is unknown" docs/performance.md` → `1`, and
    `grep -c "now waits for visible loading" docs/performance.md` → `1`.
- **7.4 `docs/failure-review.md`,** v4.5:
  - **§4 (F3):** `failure_code(state, notes)` becomes `failure_code(status, notes, history)`, the code's signature.
  - **`busy_after_step`'s definition:** "because the read after it failed" becomes "because the read after it failed,
    repeats included".
  - **The two executor fixes:** the rows and bullet that call the loading wait and the repeated read "(not built)" now
    say "(built on <date>)".
  - **§7.5:**
    - a note decision is refused only for a task value in a field its action uses (P29);
    - `outcome` is kept whole with `action` and `hint`, and a retire's refusal names its note by ID (P30);
    - a decision the notes file refused, by a failed write or an unreadable file, leaves its runs queued (F2, P34).
  - **The report:** a running review shows as running, for up to `REVIEW_TIMEOUT_MINUTES` (F4).
  - **v4.5:** the Status line's "design v4.4" becomes "design v4.5", and a v4.5 bullet in the status list names this
    plan and says its changes were made on your behalf. The `v4.5` count below needs both.
  - **Check:** each prints the count shown:
    - `grep -c 'failure_code(state, notes)' docs/failure-review.md` → `0`;
    - `grep -c 'failure_code(status, notes, history)' docs/failure-review.md` → at least `1`;
    - `grep -c '(not built)' docs/failure-review.md` → `0`;
    - `grep -c 'v4.5' docs/failure-review.md` → at least `2`.
- **7.5 The design's status lines.** In `docs/executor-improvements.md`, the top status and §2's and §4's become
  "Implemented on <date>", with the acceptance results and the paths of `$A/summary.md` and `$B/summary.md`.
  - **Check 1:** `grep -c -E 'h5-acceptance/summary.md|loading-acceptance/summary.md' docs/executor-improvements.md` →
    at least `2`.
  - **Check 2:** the registered text is unchanged. This prints `True`:

    ```sh
    python3 -c "from pathlib import Path; r=Path('artifacts/experiments/2026-09-24/preregistration-copy.md').read_text(); print(r[r.index('## 1. Hypotheses and how each is tested'):] in Path('docs/executor-improvements.md').read_text())"
    ```
- **Gate 7:** reviewed against the phases' changes: every doc says what was built. Its checks: 7.1–7.5's, and the repo
  checks.

## Phase 8: Review and QA

- **8.1 Independent review of the whole change.** Two reviewers, read-only: one for correctness and safety, one for
  tests and docs. Each reads the diff of every file 8.3 lists, made as "Diffs to review" says.
  - Apply every blocker and should-fix, then run the repo checks again.
  - **If a fix changes a file under `jev_ultrafast/`, or `scripts/check_guards.py`:** run 5.1, 5.2, 5.3 and Phase 6
    again on the final code, into new acceptance folders, and point 7.5's status lines at them.
  - **Check 1:** both final verdicts are "approve", or "approve with fixes" with each fix applied and listed in the
    Status column.
  - **Check 2:** the acceptances ran on the final code:
    - `uv run python -c "from jev_ultrafast import mcp_server; print(mcp_server.SOURCE)"` prints the `source`
      `$A/summary.md` records;
    - `shasum -a 256 jev_ultrafast/browser.py jev_ultrafast/agent.py jev_ultrafast/snapshot.js` prints the three
      hashes `$B/summary.md` records.
- **8.2 Mutation check, in a scratch copy.**
  - **The copy:** mutants go only into copies of `$S/mut`, never into the repo:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; rm -rf "$S/mut"; git ls-files -co --exclude-standard -z | rsync -a --from0 --files-from=- ./ "$S/mut/"
    ```

  - **§4's 34:** this prints `34 of 34 mutants killed`:

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; E=artifacts/experiments/2026-09-24/h8-network-settle/design-check/v4; uv run python "$E/mutate_v41.py" "$S/mut" | tail -1
    ```

    - **Anchors that move:** D14 moves mutant 6's anchor (the drain in `observe()`), and §2's edits may move others.
    - **What to do then:** copy the script to `$S`, re-anchor the mutant on the same code, and list the change in the
      Status column.
  - **The rest:** apply each to a fresh copy of `$S/mut`, and run it with `PYTHONPATH=<copy>` from inside that copy.
    Each must fail at least one of its named tests:

    | Mutant | Must fail |
    | --- | --- |
    | No repeat: the loop replaced by the old single read | test 1 or 8 |
    | `range(READ_TIMEOUT_REPEATS)`: one read too few | test 2 |
    | No stop check | test 4 |
    | `except Exception` instead of `except TimeoutError` | test 5 |
    | Counter incremented before the stop check | test 4 |
    | `run["repeated_reads"]` instead of `run.get(...)` in `report_runs.py` | test 9 |
    | A new goal clears the browser's `input_done` | test 25 |
    | The wait checks the stop before its loaded test | test 26 |
    | D14's guard removed: reads drain before the first input | test 27 |
    | F1: `held` reads `note` and `detail` for every action | `test_note_checks_read_only_the_fields_each_action_uses` |
    | F6: `outcome` replaced again | `test_a_decisions_outcome_is_kept_whole` |
    | F6: a retire's refusal names the site again | `test_a_decisions_outcome_is_kept_whole` |
    | F2: every queued run recorded, refused or not | `test_a_decision_the_notes_file_refused_leaves_its_runs_queued` |
    | P34: an unreadable notes file raises `ValueError` again | `test_a_decision_the_notes_file_refused_leaves_its_runs_queued` |
    | F5: `auto` catches `ValueError` alone | `test_auto_stops_quietly_on_an_unreadable_exclude_file` |
    | F7: the quote passes the model's text unchanged | `test_a_failure_never_quotes_a_task_value` |
    | F7: the whole failure text replaced, code's words included | `test_a_failure_never_quotes_a_task_value` |
    | F8: matches found without the lookahead | `test_overlapping_task_values_are_replaced_together` |
    | F4: a running review's digest counted as failed | `test_report_shows_a_running_review_as_running` |
    | F4: a review shown as running past `REVIEW_TIMEOUT_MINUTES` | `test_report_shows_a_running_review_as_running` |
    | F9: `start_new_session=False` | `test_start_review_runs_auto_in_its_own_session` |
    | F10: the walk's `previous not in runs` removed | `test_a_looping_chain_ends_the_lesson_walk` |
    | F11: a hyphenated tail with a dot masked as the excluded host | `test_report_prints_reviewer_text_only_inside_a_marked_block` |

  - **Check:** `$S/mutation.txt` lists every mutant with the tests that failed on it, and none survives.
- **8.3 Scope.**
  - **Check:** this lists only files from "Files this plan may change":

    ```sh
    S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; git ls-files -co --exclude-standard -z | xargs -0 shasum -a 256 | diff "$S/before.sha" - | grep '^[<>]' | awk '{print $3}' | sort -u
    ```
- **8.4 List the reviews that ran during the build.** Informational, not a failure: Phase 3 worked in a copy, so a
  review that ran meanwhile used the old script, or after 3.7 the new one.
  - **Check:** this writes the list, empty if none ran, and prints `listed`:
    `S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; ls artifacts/reviews/2*.json | diff "$S/reviews-before.txt" - | sed -n 's/^> //p' > "$S/reviews-during-build.txt"; echo listed`.
  - **The final report** names each digest listed, and whether it ran before or after 3.7, from its name and
    `$S/review-landed.txt`.
- **8.5 Final checks.** The repo checks pass, with the counts in "Final verification". Then 2.7's command runs on
  the whole suite, `'tests'` in place of its three files: its last line has no `failed` or `error`, and the same
  passed count as `uv run pytest -q`.

## Final verification

1. **Repo checks** pass, and each test file is at its baseline plus:
   - `tests/test_agent.py` 31: §4's 24 and tests 25–27, and §2's tests 1, 2, 4 and 5;
   - `tests/test_mcp_server.py` 3: test 8, F9 and F10;
   - `tests/test_report_runs.py` 2: F4's 2 cases. Test 9 and F11 extend existing tests;
   - `tests/test_review_runs.py` 11: F1's 3 cases, F6's 2, F2's 2, F5, F7's 2 and F8;
   - every other test file 0.
2. **Anti-pattern greps,** each with no output:
   - `grep -n -E 'dialog_open|\b_send\b|page_info' jev_ultrafast/*.py | grep -v -E ':[0-9]+:\s*#'`, which drops
     comments: with several files, each line starts `<file>:<line>:`;
   - `grep -n "except TimeoutError" jev_ultrafast/browser.py`
   - `grep -n -E 'LOADING_FLOOR|minimum wait' jev_ultrafast/browser.py | grep -v -E '^[0-9]+:\s*#'`, which drops
     comments: with one file, each line starts `<line>:`;
   - `grep -rn "api.typesafe.ai\|openrouter.ai\|api.deepseek.com" tests/`
3. **Coverage:** every item maps to a task whose check has passed.

| Item | Tasks |
| --- | --- |
| §4.4 code, D14, and §4.6 offline tests 1–27 | 1.1–1.3 |
| §2.3 `agent.py`: constant, counter, loop, comment | 2.1–2.3 |
| §2.5 tests 1, 2, 4–6, 8 and 9 | 2.2–2.5 |
| §2.6 and §4.6 comments | 2.3, 2.6 |
| §4.6 live check | 5.2, 5.3 |
| §2.5 and §4.6 acceptances | 6.1–6.4 |
| §2.6 and §4.6 docs | 7.1–7.3 |
| Follow-ups F1–F11 | 3.1–3.7, 4.1–4.4, 7.4 |
| Design status | 7.5 |

## After the plan: the P16 check

Design v4.4 made common words task values (P16). The first review lost both its proposed notes to task values, in
their `note`s and their `detail`s. P29 stops checking an add's `note`, so only reviews after 3.7 show P16's cost. P31
decides when to judge it.

- **When:** once 5 successful reviews have run since 3.7 landed P29. This counts them and their adds, from the landing
  time 3.7 recorded:

  ```sh
  S=/Users/terry/projects/jev-ultrafast/artifacts/page-readiness-implementation; uv run python -c "import json, pathlib; since = pathlib.Path('$S/review-landed.txt').read_text().strip(); ds = [json.loads(p.read_text()) for p in sorted(pathlib.Path('artifacts/reviews').glob('2*.json')) if p.stem >= since]; ok = [d for d in ds if 'failure' not in d]; adds = [x for d in ok for x in d['decisions'] if x['action'] == 'add']; lost = sum('a value' in x['outcome'] and 'a task' in x['outcome'] for x in adds); print(f'reviews {len(ok)}, adds {len(adds)}, applied {sum(x[\"applied\"] for x in adds)}, refused for a task value {lost}')"
  ```

- **Then read each refused add's `detail`** in its digest, where each value shows as `<value>`. The words around it
  tell a common word, such as a label or a verb, from a value the task really typed. Only the first are P16's cost.
- **If more than half of the adds were refused for common words:** narrow P16. There are two levers; both change
  `docs/failure-review.md` §6.5, and so every note check:
  - count only words of 6 characters or more, instead of 4;
  - stop treating a goal's quoted field labels as values.
- **Otherwise:** P16 stays; check again after 5 more reviews.
- **Optional, and paid:** the first review's proposal also asked to re-run its three goals after the fix. That needs
  Jev calls, so it stays outside the tests; run it once after the merge only if you want it.

## Not in this plan

- **Held (P32):** the first review's proposal to read controls below the fold and inside shadow DOM. It is H1 and H4:
  both partly verified, and every fix tried failed (design §1, Results).
- **Follow-ups accepted as they are (P28):**
  - **`run_arm.py` lacks `--strict-mcp-config`:** the free check is the next Phase 10 session. Its run files should
    hold an empty `notes_shown`, and no result "site notes from earlier runs". Add the flag if one does.
  - **Two notes for one recovery:** a lesson stored while a review applies an add for the same recovery, or a repeated
    lesson. The cost is one wasted unapproved slot. The fix, refusing in `add_note()` under the lock, would change the
    shared `stored()` fixture that about 40 tests use.
  - **A run cut off by the server's 5 s shutdown wait** never gets a result, so the review never queues it. No public
    run lacks one. The optional fix: queue a run with no result once its ID's time is more than `RUN_SECONDS` plus a
    margin in the past.
  - **Runs from before the failure-review build** link by `pid` in ID order, since they have no `previous_run`. The
    census holds no same-second pair.
- **The design's own exclusions:** §2.7 and §4.7, among them a wait after every input (H8), reloading a page, the
  start page's first answer, and hidden-tab mode.

## Review of this plan

- **Calvin, 2026-09-29:** two report-mode runs, one for each half of the plan, asked 24 questions, 15 of them
  blockers. Every answer is applied above. The ledgers and answers are in `$S/calvin-plan-a.md`, `$S/calvin-plan-b.md`
  and `$S/calvin-plan-close.md`.
- **Independent review, 2026-09-29:** `$S/review-plan.md`, against the plan after calvin's answers. It dry-ran Phases
  0–2 in a scratch copy, ending at 249 tests, and killed §4's 34 mutants and §2's 6. It found 5 blockers, 4
  should-fix and 15 nits; each is applied above.
  - **Blockers:** four checks that failed as written (0.2's regex, 2.3's Check 3, and two anti-pattern greps), and
    6.5's Check 2, whose empty-profile pattern could have led its fallback to kill every process started with
    `--user-data-dir`.
  - **Should-fix:** the raw-output rule under rtk; the read-only harness copies in 6.3 and 6.4; F10's alarm, which
    would have killed pytest instead of failing the test; and 3.2's missing wording for the retire refusal.
  - **A new decision, from nit N5:** P34, an unreadable notes file leaves its runs queued too.
  - **The reviewer's re-check of the fixes, 2026-09-29:** `Open blockers: 0`. It found three more, each applied
    above, and confirmed on the final plan, with nothing left open:
    - **R1:** F10's handler raises `AssertionError`. The `TimeoutError` the review first suggested is an `OSError`,
      which the walk catches, so the mutant without the loop guard survived 3 of 3 runs; `AssertionError` failed it
      3 of 3;
    - **R2:** F2's unreadable-file case breaks the file only after building the queue;
    - **R3:** the rtk rule says a `grep` after a `|` is rewritten too, and prints the same.

The H5 plan of 2026-09-24 had cycle 3's dry run and 24 calvin questions, all answered. Their answers live on in the
tasks above:
- the problem statement, and "When a check fails";
- the lab's safety rules, in 5.1 and 6.5;
- the anchor of the read to replace, in 2.3;
- the refusal to overwrite a baseline, in 0.2.

Its dialog-check answers (A4, A8, A10, A12, B2, B4, B5) went with the dialog check, cut in design §2 v2.
