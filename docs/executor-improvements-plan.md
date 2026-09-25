# Implementation plan: repeat a read that times out after a step (H5)

**Source design:** `docs/executor-improvements.md` §2, "the design" below. Its review history is at the top of §2.

**Review of this plan:**
- **Cycle 3's reviewer** dry-ran every offline check against a build of the design, and found one blocker: the lab shutdown could kill your apps when a shell variable was empty. It is fixed, with the other findings.
- **Calvin,** in report mode, asked 24 questions. All are answered in "Calvin's ledger" at the end, and the answers are applied.

**How to use this plan:**
- Execute the phases in order. Each phase lists what to read first, so it can run in a fresh context.
- Every subtask ends with a **Check**: a command or a file condition, and its expected result. A subtask is done only when its check passes.
- **Test names** are the design's (§2.5). `test_new_goal_resets_every_counter` and `test_report_counts_false_and_missed_done` already exist and are extended; the others are new.
- **Every command runs from the repo root,** `/Users/terry/projects/jev-ultrafast`.
- **Shell variables do not persist between commands.** Every command that uses `$S` starts with `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation;`. That folder is made in 0.2; git ignores it, and it survives a reboot. Every Phase 5 command sets `A` to the literal folder that 5.1 makes.
- **Never kill by a pattern built from a variable that could be empty.** 5.4 kills the lab by recorded process IDs, and refuses to run when none was recorded.

## The problem, and how we will know it is solved

- **Today:** when a page stays busy for more than 5 s after a step, the read that follows times out, and the run ends `stopped` although its input worked. Claude then has to check the page and call `run_goal` again. Run `20260924-112504-7782` is the one recorded case: its arXiv search ran, and its final screenshot shows the results.
- **After this plan:** that read is repeated up to 2 times, and the run carries on.
- **How we will know:**
  - **On the test page:** 5.2's acceptance, where 5 of 5 busy trials end `done`, each input once.
  - **In real use:** `scripts/report_runs.py` counts "repeated reads". A run that repeated a read and went on is the fix working. A read-timeout stop after a step, with "repeated reads" 0, would mean it did not fire.
  - **What cannot be known yet:** how often this matters. It happened in 1 of 76 run files, and arXiv did not reproduce it in 10 tries (design §1, Results).

## When a check fails

- **Never loosen a check or its expected value to make it pass.**
- **Phases 0–3 and 6:** if the cause is inside the subtask's own change and the fix stays within the design, fix it and run the check again. Otherwise stop, and report the check's command and output.
- **Phases 4–5:**
  - **First, shut the lab down** with 5.4's commands. They are safe to run at any point after 4.1, and they refuse to run when 4.1 recorded nothing.
  - **Then stop,** and report the failing command and its output.
  - **Never re-run a trial or a check to get a pass,** except where a step says so.
- **Your Chrome (4.4):** if something fails there, stop and report. If your daemon's dialog record looks stuck, ask the owner to run `uv run browser-harness --reload`; the plan never restarts your daemon itself.

## Status (2026-09-24)

Not started. None of this plan's changes is committed.

| Phase | Status |
| --- | --- |
| 0 Read first, baseline | Not started |
| 1 `browser.py` | Not started |
| 2 `agent.py` | Not started |
| 3 MCP path, run report, comments | Not started |
| 4 Lab Chrome and live checks | Not started |
| 5 Acceptance | Not started |
| 6 Docs | Not started |
| 7 Review and QA | Not started |

## Decisions made on your behalf

- **The design's D1–D5** (the table at the top of design §2): the repeat cap, failing closed, the private `_send`, every executed step, and the `repeated_reads` counter. Each has a comment in the code naming the design section.
- **P1 Live checks run in a lab Chrome first.**
  - **The risk:** check 11 tests whether a tab closed with its dialog open leaves browser-harness's single dialog record set. If it does, the repeat is off for every run until that daemon restarts.
  - **Why the lab first:** the check resets the record itself, but the reset needs the check to reach its `finally` and Chrome to send the close event. If either fails the first time, the stuck record lands on a throwaway daemon, not on the one your real runs use.
  - **Your Chrome:** it runs the checks only after the lab run passes. Change this in 4.2 and 4.4.
- **P2 The fallback if a closed tab leaves the record set** (4.3): `Browser.close()` dismisses any dialog before closing its tab. It never accepts a dialog and adds one CDP call per close. Applied only if check 11 fails in the lab. Change it in 4.3.
- **P3 The acceptance run reuses the lab name `labC` and port 9335,** which the copied harness already checks, so the copy needs no guard edit. Change it in 4.1 and 5.1.

## Global rules

- **Repo rules:** follow `AGENTS.md`.
  - Never retry a browser mutation, and log execution before observing its result.
  - Tests must not call paid APIs.
  - Keep README claims, evidence, and model-call counts consistent.
  - Do not commit or push unless the user asks.
- **Repo checks:** run these at the end of every phase that changes code. All must pass.
  - `uv run ruff check .` → `All checks passed!`
  - `uv run pytest -q` → no failures
  - `node --check jev_ultrafast/static/app.js` and `node --check jev_ultrafast/snapshot.js` → exit 0
  - `uv build` → a wheel is built
- **Cost:** Phases 0–3 and 6 are offline. Phases 4 and 5 need Chrome but make no model calls. No phase calls a paid API.
- **Files this plan may change**, and no others:
  - `jev_ultrafast/agent.py`, `jev_ultrafast/browser.py`, `jev_ultrafast/mcp_server.py` (two comments only)
  - `scripts/report_runs.py`, `scripts/check_guards.py`
  - `tests/test_agent.py`, `tests/test_mcp_server.py`, `tests/test_report_runs.py`
  - `docs/claude-code-integration.md`, `docs/performance.md`, this plan
  - `docs/executor-improvements.md`: the status line, and, only if 4.3 runs, §2.3 "One record for every tab" and the §2.4 table
  - new files under `artifacts/experiments/`, which git ignores

## Phase 0: Read first, and record the baseline

Read first:
- **The design:** §2 in full, and §1 "Results" for H5.
- **Code:** `agent.py` 16–37, 48–73 and 95–254; `browser.py` 13–15 and 50–177; `mcp_server.py` 143–203 and 314–318; `scripts/report_runs.py` 60–90; `scripts/check_guards.py` in full.
- **Tests:** `tests/test_agent.py` 1–48 (`page`, `decision`), 227–241 (`runner`), 446–456 (`test_dismiss_dialog_never_accepts`, the pattern for test 7), 618–640 (`act`, `test_new_goal_resets_every_counter`); `tests/test_mcp_server.py` 47–75 (`FakeBrowser`, `FakeAgent`) and 288–311 (the real-tick pattern); `tests/test_report_runs.py` 20–85.
- **browser-harness 0.1.13** in `.venv/lib/python3.13/site-packages/browser_harness/`: `helpers.py` (`_send`, `page_info`) and `daemon.py` 628–631 and 739.

### Allowed APIs

| API | Behaviour | Source |
| --- | --- | --- |
| `browser_harness.helpers._send(req, response_timeout=5.0)` | Sends one IPC request to the daemon and returns its reply as a dict. Raises `_IPCResponseTimeout`, a `TimeoutError`, after 5 s; `RuntimeError` when the reply has an `error` key. Returns `{}` when the daemon closes without replying | `helpers.py`, `_ipc.py` `request()` |
| `_send({"meta": "pending_dialog"})` | `{"dialog": None}` or `{"dialog": {...}}`, from the daemon's memory; touches no tab | `daemon.py` 739 |
| `Browser.observe`, `Browser.act`, `Browser.dismiss_dialog`, `Browser.close` | Unchanged, except `close()` in 4.3's fallback | `browser.py` |

### Anti-patterns

- **The dialog check through `page_info()`:** when no dialog is recorded, it evaluates with no session, so the daemon runs code in its own default tab. In your Chrome, that is one of your tabs (design §2.3).
- **Catching `TimeoutError` inside `observe()`:** the other reads must still stop on a timeout (design §2.7).
- **`act()` or the history append inside the loop:** the loop wraps the read alone.
- **`.get("dialog")`:** a daemon that closes without replying would then read as "no dialog".
- **Any network or model call in a test.**
- **Editing the registered part of the design doc:** everything above "### Results" in §1.

### Subtasks

- **0.1 The daemon's reply is as the design says.**
  - **Check:** `grep -n '"pending_dialog"' .venv/lib/python3.13/site-packages/browser_harness/daemon.py` prints one line containing `return {"dialog": self.dialog}`.
- **0.2 Baseline.**
  - Make the scratch folder. Save a manifest of every file git tracks or would add, and a copy of those files for 7.1's diffs. `.env` is ignored by git, so it is not copied.
    ```
    S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; [ -e "$S/before.sha" ] && { echo "baseline exists; not overwritten"; exit 1; }; mkdir -p "$S"
    git ls-files -co --exclude-standard -z | xargs -0 shasum -a 256 > "$S/before.sha"
    git ls-files -co --exclude-standard -z | rsync -a --from0 --files-from=- ./ "$S/before/"
    ```
  - **A baseline is taken once, on unchanged files.** The command refuses to overwrite one. To start over, delete that folder by hand first, and only while the repo is back at the baseline.
  - **Check 1:** `uv run pytest -q` → `120 passed`.
  - **Check 2:** `uv run ruff check .` → `All checks passed!`.
  - **Check 3:** `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; wc -l < "$S/before.sha" | tr -d ' '` prints a number above 50 (55 on 2026-09-24), and `test -f "$S/before/jev_ultrafast/agent.py" && echo copied` prints `copied`.

## Phase 1: `browser.py` (offline)

Read first: design §2.3, "`jev_ultrafast/browser.py`" and "Why a dialog check, and why `_send`"; `browser.py` 13–15 and 165–177; `tests/test_agent.py` 446–456; `helpers.py` `_send`, `page_info`, `_runtime_evaluate` and `cdp`.

- **1.1 `Browser.dialog_open()` and the `_send` import (design §2.3, D2, D3).**
  - Change the import to `from browser_harness.helpers import _send, cdp`. Put the three-line comment from the design above the whole `browser_harness` import group, not between its lines, which fails ruff's I001.
  - Add `dialog_open()` after `dismiss_dialog()`, verbatim from the design.
  - Add test 7, `test_dialog_open_asks_only_the_daemon`, beside `test_dismiss_dialog_never_accepts`.
    - **Cases:** parametrized over five: `{"dialog": {"type": "alert"}}` gives True, `{"dialog": None}` False, `{}` True, a raised `RuntimeError` True, and a raised `TimeoutError` True, which is what `_send` raises when the daemon does not answer.
    - **Patches:** `_send` and `cdp` in `jev_ultrafast.browser`, and `_send` and `cdp` in `browser_harness.helpers`, each a `Mock`. `page_info()` reaches the daemon only through `helpers._send`: directly for `pending_dialog`, and through `_runtime_evaluate` → `cdp` → `_send` for the URL and title. So a regression to `page_info()` cannot reach the live daemon.
    - **Asserts:** the result; `jev_ultrafast.browser._send.assert_called_once_with({"meta": "pending_dialog"})`; the other three mocks not called.
  - **Check 1:** `uv run pytest -q -k test_dialog_open_asks_only_the_daemon` → `5 passed`.
  - **Check 2:** outside comments, `browser.py` neither calls `page_info` nor uses `.get("dialog")`: `grep -v -E '^\s*#' jev_ultrafast/browser.py | grep -c -E 'page_info|\.get\("dialog"\)'` → `0`. The D3 comment names `page_info()` on purpose.
  - **Check 3:** `grep -c 'is decision D3' jev_ultrafast/browser.py` → `1`, and `grep -c '(D2, docs/executor-improvements.md §2)' jev_ultrafast/browser.py` → `1`.
  - **Check 4:** the comment sits right above the import group: `grep -A1 'Recheck both on any browser-harness upgrade' jev_ultrafast/browser.py | tail -1` → `from browser_harness import _ipc as ipc`.

- **1.2 Repo checks.** All pass; `uv run pytest -q` → `125 passed`.

## Phase 2: `agent.py` (offline)

Read first: design §2.3, "`jev_ultrafast/agent.py`", and §2.5 tests 1–6; `agent.py` 16–37, 48–73 and 149–254; `tests/test_agent.py` 1–48, 227–241 and 618–640.

- **Fixture rule:**
  - **State:** the `runner` fixture builds its state with the real `_fresh_state`, so the new key needs no fixture change.
  - **Browser:** the fixture's browser gains `dialog_open=Mock(return_value=False)`. It is a `Mock`, whose unset methods return a truthy `Mock`.
  - **A click in every new test:** each uses the file's `act(runner)` helper. The fixture's default decision is a fill, which would call the text model.

- **2.1 The constant (D1).**
  - Add `READ_TIMEOUT_REPEATS = 2` after the imports, with the D1 comment verbatim from the design.
  - **Check:** `uv run python -c "from jev_ultrafast import agent; print(agent.READ_TIMEOUT_REPEATS)"` → `2`, and `grep -c 'Delegated decision D1' jev_ultrafast/agent.py` → `1`.
- **2.2 The counter (D5).**
  - Add `repeated_reads=0` to `_fresh_state` after `stale_streak=0`, with its comment verbatim from the design.
  - Extend `test_new_goal_resets_every_counter` (design test 6): set `repeated_reads=2` in its `state.update`, and assert it is `0` after `new_goal`.
  - **Check:** `uv run pytest -q -k test_new_goal_resets_every_counter` → `1 passed`, and `grep -c 'decision D5' jev_ultrafast/agent.py` → `1`.
- **2.3 The loop (design §2.3, D4).**
  - Replace the read after a step with the loop, verbatim from the design, including its two comment lines.
    - **Which read:** `agent.py` has three identical `state["page"] = state["browser"].observe(screenshot=self.screenshots)` lines. The one to replace is in `command("act")`, right after the `self.save()` that follows `state["stale_streak"] = 0  # a step ran` (line 235 before this plan). The other two, in `tick` and `predict`, stay as they are.
  - Change the `before_input` comment in `__init__` to the design's wording.
  - Add tests 1–5 from design §2.5, with the setups it specifies. Test 1's second page has its own URL, `https://example.test/results`, and fingerprint.
  - **Check 1:** `uv run pytest -q -k "test_timed_out_read_after_a_step_is_repeated or test_timed_out_reads_stop_after_the_last_repeat or test_open_dialog_stops_a_timed_out_read_at_once or test_stop_check_runs_before_each_repeated_read or test_only_a_timed_out_read_is_repeated"` → `5 passed`.
  - **Check 2:** `grep -c READ_TIMEOUT_REPEATS jev_ultrafast/agent.py` → `3`: the definition, the range, and the last-read test.
  - **Check 3:** the loop wraps only the read. `awk '/for read in range/,/repeated_reads"\] \+= 1/' jev_ultrafast/agent.py | grep -c -E 'act\(|history'` → `0`, and the same `awk` range is 10 lines: `… | wc -l` → `10`.
  - **Check 4:** `grep -c 'Decision D4' jev_ultrafast/agent.py` → `1`, and it sits right above the loop: `grep -A1 'Decision D4' jev_ultrafast/agent.py | tail -1 | sed 's/^ *//'` → `for read in range(READ_TIMEOUT_REPEATS + 1):`.
  - **Check 5:** `grep -c 'before text calls, inputs and read repeats' jev_ultrafast/agent.py` → `1`.
  - **Check 6:** the right read was replaced: `grep -B4 'for read in range' jev_ultrafast/agent.py | head -1 | sed 's/^ *//'` → `state["stale_streak"] = 0  # a step ran`.
- **2.4 Repo checks.** All pass; `uv run pytest -q` → `130 passed`.

## Phase 3: The MCP path, the run report, and comments (offline)

Read first: design §2.3 (the `report_runs.py` line), §2.5 tests 8–9 and §2.6; `tests/test_mcp_server.py` 47–75 and 288–311; `scripts/report_runs.py` 60–90; `tests/test_report_runs.py` 20–85; `mcp_server.py` 143–152 and 314–321.

- **3.1 Test 8 through the server.**
  - Add `def dialog_open(self): return self.dialog` to `FakeBrowser` in `tests/test_mcp_server.py`.
  - Add `test_a_read_that_timed_out_after_a_click_is_repeated`, following `test_cancellation_during_the_decision_executes_no_input`:
    - **The real tick:** `monkeypatch.setattr(FakeAgent, "command", Agent.command)`, `FakeBrowser.fresh` returning True, and `FakeBrowser.act` a `Mock`.
    - **Jev's stand-in:** `jev_ultrafast.agent.choose` answers CLICK `e2` ("Search"), then DONE.
    - **The timeout, once:** the first `observe(screenshot=False)` after the click raises `TimeoutError("Runtime.evaluate timed out after 5s waiting for the daemon")`; every other read behaves as `FakeBrowser.observe` does now. `FakeBrowser.read_error` stays set once set, so wrap `observe` with a one-shot error instead.
    - **Expect:** the result text contains ` · done · `. `run_file()` has one step with `page_changed` not None, which is False here because the fake page's fingerprint never changes, and `repeated_reads` 1. `act` has one call.
  - **Check:** `uv run pytest -q -k test_a_read_that_timed_out_after_a_click_is_repeated` → `1 passed`.
- **3.2 The run report counts repeats (D5).**
  - In `scripts/report_runs.py` `facts()`, add `"repeated reads": run.get("repeated_reads", 0),` to `totals`, after `"stale decisions"`. It uses `.get` because run files from before this change have no such key.
  - Extend `test_report_counts_false_and_missed_done` (design test 9): give run 2 `repeated_reads=2`, and assert `"repeated reads 2"` is in the report line.
  - **Check 1:** `uv run pytest -q -k test_report_counts_false_and_missed_done` → `1 passed`.
  - **Check 2:** `uv run python scripts/report_runs.py 2>/dev/null | head -1 | grep -o 'repeated reads [0-9]*'` → `repeated reads 0`. No existing run file has the key, and none is skipped for lacking it.
- **3.3 Comments in `mcp_server.py` (design §2.6).**
  - **`check_stop`:** its comment becomes `# between steps, before each text call, input and repeated read`.
  - **`shut_down`:** the comment on `STOP.set()` and the two-line ponytail comment under it become the three lines in design §2.6, verbatim.
  - **Check:** `grep -c "repeated read" jev_ultrafast/mcp_server.py` → `2`, `grep -c "a busy page's reads" jev_ultrafast/mcp_server.py` → `1`, and `grep -c 'design §10' jev_ultrafast/mcp_server.py` → `1`, so the old ponytail lines are gone.
- **3.4 Repo checks.** All pass; `uv run pytest -q` → `131 passed`.

## Phase 4: Lab Chrome and live checks (Chrome, no model calls)

Read first: `scripts/check_guards.py`. It loads `data:` pages, drives `Browser` directly, collects `passed` lines, and ends with a `PASS:` line. Today it ends `PASS: 23 browser guard checks; no model calls`.

- **4.1 Start a lab Chrome with a fresh profile (P3).**
  - **Before:** nothing listens on the port: `lsof -nP -iTCP:9335 -sTCP:LISTEN -t | wc -l | tr -d ' '` → `0`. If something does, it is not the plan's: stop, kill nothing, and report what listens there.
  - Run:
    ```
    S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; profile=$(mktemp -d /tmp/jev-h5-chrome.XXXXXX); echo "$profile" > "$S/profile"
    nohup "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir="$profile" \
      --remote-debugging-port=9335 --no-first-run --no-default-browser-check --window-size=1240,960 about:blank \
      > "$profile.log" 2>&1 &
    echo $! > "$S/chrome.pid"; disown
    ```
  - **Check:** `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; curl -s --retry 10 --retry-delay 1 --retry-connrefused --max-time 20 http://127.0.0.1:9335/json/version | tee "$S/lab_chrome_version.json" | grep -c '"Browser"'` → `1`, and `test -s "$S/chrome.pid" && echo recorded` → `recorded`.
  - **If the version check fails:** run 5.4's shutdown, which stops the Chrome that 4.1 started, then stop and report `$profile.log`.
- **4.2 Checks 10 and 11 (design §2.5), run in the lab Chrome (P1).**
  - **Check 10:** its three asserts go inside the existing dialog check. Its line is appended right after `dialog dismissed without accepting`.
  - **Check 11:** goes last, after the pop-up check, with the clean-ups the design lists: its own `try/finally` for the second `Browser`, the reset through a dismissed `confirm()`, and `dismiss_dialog()` before `close()` in `main()`'s `finally`.
  - **If any line differs, other than the closed-tab line:** run 5.4's shutdown, then stop and report. Only the closed-tab line leads to 4.3.
  - **Check:** `BU_NAME=labC BU_CDP_URL=http://127.0.0.1:9335 uv run python scripts/check_guards.py | tail -6` prints exactly these six lines:
    ```
    dialog dismissed without accepting
    dialog check sees a dialog and leaves it open
    pop-up tab closed and reported
    a busy page's read times out; the dialog check answers without the page
    a tab closed with its dialog open leaves no dialog record
    PASS: 26 browser guard checks; no model calls
    ```
- **4.3 Only if the closed-tab line failed (P2).**
  - In `Browser.close()`, inside `if self.target:` and before `Target.closeTarget`, add these two lines, and `import contextlib`:
    ```python
                with contextlib.suppress(Exception):  # e.g. no session yet when setup failed; the tab still closes
                    self.dismiss_dialog()  # a closed tab must not leave the daemon's dialog record set
    ```
    - **Why the guard:** `close()` also runs when `Browser.__init__` fails before `self.session` exists. `dismiss_dialog()` catches only `RuntimeError`, so without the guard an `AttributeError` or a `TimeoutError` would hide the setup error and leave the tab open.
  - Add `test_close_dismisses_a_dialog_first` beside `test_dismiss_dialog_never_accepts`, parametrized over two cases:
    - **With a session:** `close()` sends `Page.handleJavaScriptDialog` with `accept=False`, then `Target.closeTarget`, in that order.
    - **Without a session:** it still sends `Target.closeTarget`, and raises nothing.
  - Record the finding in design §2.3 under "One record for every tab", and in the §2.4 table.
  - **Check 1:** `uv run pytest -q -k test_close_dismisses_a_dialog_first` → `2 passed`, and the existing `uv run pytest -q -k test_constructor_failure_closes_target` → `1 passed`.
  - **Check 2:** 4.2's command again → the same six lines. If it still fails, run 5.4's shutdown, then stop and bring the finding back to design review.
- **4.4 The owner's Chrome, after 4.2 passes.**
  - **Why your Chrome as well:** `scripts/check_guards.py` is the repo's standing live check, and it normally runs against your daemon. That daemon is attached to one of your tabs and runs with your extensions, which the lab has neither of.
  - **Before:** no tab in your Chrome shows a JavaScript dialog. The daemon keeps one dialog record for all tabs, so an open dialog anywhere fails checks 10–11.
  - **If it fails here after passing in the lab:** stop and report; do not apply 4.3 on this evidence alone. If a dialog was open in one of your tabs, close it and run 4.4 once more.
  - **Check:** `uv run python scripts/check_guards.py | tail -6` → the same six lines.
  - **What you see:** its windows open and close in your Chrome. Check 11 opens a second window while the first is still open. Nothing else in your Chrome is touched.

## Phase 5: Acceptance (lab Chrome, no model calls)

Read first: `artifacts/experiments/2026-09-24/labC-h3-h5/h5_fix_trials.py`, `h5_fixture.py`, `labc_common.py`, and `summary.md` §3 "Test 3".

- **5.1 Copy the harness to a new folder, so the registered raw files stay unchanged.**
  - Run `A=artifacts/experiments/$(date +%F)/h5-acceptance; echo "$A" > /Users/terry/projects/jev-ultrafast/artifacts/h5-implementation/acceptance_dir; mkdir -p "$A"; cp artifacts/experiments/2026-09-24/labC-h3-h5/{labc_common.py,h5_fixture.py,h5_fix_trials.py} "$A/"`.
  - **Every later Phase 5 command** starts with `A=$(cat /Users/terry/projects/jev-ultrafast/artifacts/h5-implementation/acceptance_dir);`, so the date in the path is fixed at 5.1.
  - **Where the copy writes:** `labc_common.py` sets `RAW = OUT / "raw"` with `OUT = Path(__file__).resolve().parent`, and `h5_fix_trials.py` points `mcp_server.RUNS` inside `RAW`. So the copy writes only under its own folder.
  - **Record the registered H5 folder,** the one the harness was copied from and could overwrite, to show in 5.2 that it did not change: `find artifacts/experiments/2026-09-24/labC-h3-h5 -type f -print0 | sort -z | xargs -0 shasum -a 256 > /Users/terry/projects/jev-ultrafast/artifacts/h5-implementation/registered.sha`.
  - Edit only `$A/h5_fix_trials.py`:
    - **The package map:** add `"implemented": "/jev-ultrafast/jev_ultrafast/"`.
    - **After the package assert:** `assert ARM != "implemented" or hasattr(loop, "READ_TIMEOUT_REPEATS")`.
    - **The record:** add `repeated_reads=state.get("repeated_reads")` to `record.update(...)`, and `"repeated_reads": record.get("repeated_reads")` to `record["checks"]`.
  - **Check 1:** only the package-map line changed and three lines were added. With `A` set to the folder above:
    - `diff artifacts/experiments/2026-09-24/labC-h3-h5/h5_fix_trials.py $A/h5_fix_trials.py | grep -c '^<'` → `1`
    - the same `diff … | grep -c '^>'` → `4`
    - `grep -c repeated_reads $A/h5_fix_trials.py` → `2`
  - **Check 2:** `uv run python $A/h5_fixture.py` → `fixture self-check passed on port …`.
- **5.2 Run 5 busy trials and 1 alert trial.**
  - Run from the repo root, with no `PYTHONPATH`:
    ```
    A=$(cat /Users/terry/projects/jev-ultrafast/artifacts/h5-implementation/acceptance_dir)
    for t in 1 2 3 4 5; do BU_NAME=labC BU_CDP_URL=http://127.0.0.1:9335 uv run python $A/h5_fix_trials.py implemented busy $t; done
    BU_NAME=labC BU_CDP_URL=http://127.0.0.1:9335 uv run python $A/h5_fix_trials.py implemented alert 1
    ```
  - **Why exactly one repeat per busy trial:** the fixture blocks the page for 7 s. The first read times out at about 5 s, and the block ends inside the second read's 5 s wait. In H5's test, the repeated reads returned after 2,001–2,002 ms.
  - **A trial that prints anything else fails the acceptance.** It is not re-run. Keep every raw file, run 5.4's shutdown, and bring the result back to design review.
  - **Check 2:** the registered folder is unchanged: `find artifacts/experiments/2026-09-24/labC-h3-h5 -type f -print0 | sort -z | xargs -0 shasum -a 256 | diff /Users/terry/projects/jev-ultrafast/artifacts/h5-implementation/registered.sha -` prints nothing.
  - **Check:** `A=$(cat /Users/terry/projects/jev-ultrafast/artifacts/h5-implementation/acceptance_dir); uv run python -c "import json,glob; [print(f.rsplit('/',1)[1], (c:=(r:=json.load(open(f)))['checks'])['status'], c['each_input_once'], c['one_submission_at_server'], c['repeated_reads'], r['notes']) for f in sorted(glob.glob('$A/raw/h5_fix/implemented-*.json'))]"` prints:
    - `implemented-alert-1.json stopped True True 0 ['the page showed a dialog; dismissed']`
    - `implemented-busy-N.json done True True 1 []`, once for each N from 1 to 5
- **5.3 Record the result.**
  - Write `$A/summary.md`: the date, the source hash from any run file's `source`, the six lines above, and the lab Chrome's version from `/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation/lab_chrome_version.json`.
  - **Check:** `$A/summary.md` exists and contains `5 of 5` and `stopped`.
- **5.4 Shut the lab down.**
  - **First, record your own daemon's process ID:** `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; uv run python -c "from browser_harness import _ipc as ipc; print(ipc.identify('default'))" > "$S/default_pid"`.
  - Then run the shutdown. It names the lab daemon literally, and kills Chrome by its recorded process ID. It refuses to run when either record is missing:
    ```
    S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; profile=$(cat "$S/profile" 2>/dev/null); chrome=$(cat "$S/chrome.pid" 2>/dev/null)
    [ -n "$profile" ] && [ -n "$chrome" ] || { echo "lab not recorded; nothing killed"; exit 1; }
    pid=$(uv run python -c "from browser_harness import _ipc as ipc; print(ipc.identify('labC') or '')" | tail -1)
    [ -n "$pid" ] && kill "$pid"
    ps -p "$chrome" -o command= | grep -q -F -- "--user-data-dir=$profile" && kill "$chrome"
    pkill -f -- "--user-data-dir=$profile"
    ```
  - **Why the `ps` check:** a recorded process ID can be reused after its process exits. Chrome is killed by ID only while that ID's command line still names the lab profile. The last line matches only processes whose command line names the lab's unique temporary profile.
  - **Check 1:** `curl -s --max-time 2 http://127.0.0.1:9335/json/version; echo "exit $?"` prints a non-zero exit code.
  - **Check 2,** as its own command, repeated once if Chrome is still exiting: `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; pgrep -f -- "--user-data-dir=$(cat "$S/profile")" | wc -l | tr -d ' '` → `0`.
    - **If still not 0:** run `pkill -9 -f -- "--user-data-dir=$(cat "$S/profile")"` once. It matches only the lab profile. Then run Check 2 again, and if it still fails, stop and report.
  - **Check 3:** your daemon is untouched: `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; uv run python -c "from browser_harness import _ipc as ipc; print(ipc.identify('default'))" | diff - "$S/default_pid"` prints nothing.
    - **If it prints a difference:** your daemon's process changed during the shutdown. The plan did not do that on purpose. Stop, report both IDs, and change nothing on your daemon.

## Phase 6: Docs (offline)

- **6.0 README needs no change.** Design §2.6 says so: the README does not describe read timeouts.
  - **Check:** `grep -c -i -E 'timed out|timeout' README.md` → `0`, both before and after Phase 6.

- **6.1 `docs/claude-code-integration.md` (design §2.6).** Five edits, each with the exact text below:
  1. **The §6.2 sketch:** the comment `# also runs before each input, via agent.before_input` becomes `# also runs before each input and each repeated read, via agent.before_input`.
  2. **"Dialogs":** append "After a step, a read that times out while no dialog is recorded is read again first, up to 2 times (`docs/executor-improvements.md` §2)."
  3. **"Shared daemon side effects":** append "The reverse holds too: a dialog open in another tab of the same daemon makes `Browser.dialog_open()` true, so the executor does not repeat a timed-out read."
  4. **"Deadline, cancellation and shutdown":** "are checked between steps and again right before each input (`Agent.before_input`)" becomes "are checked between steps, right before each input, and before each repeated read (`Agent.before_input`)".
  5. **The Speed row:** append " · repeated reads per run (reads after a step that timed out and were taken again)".
  - **Check:** each of these five phrases occurs exactly once, `grep -c -F '<phrase>' docs/claude-code-integration.md` → `1`:
    - `each repeated read, via agent.before_input`
    - `is read again first, up to 2 times`
    - `does not repeat a timed-out read`
    - `and before each repeated read (`
    - `repeated reads per run`
  - **Check 2:** the replaced text is gone. Both `grep -c -F '# also runs before each input, via agent.before_input' docs/claude-code-integration.md` and `grep -c -F 'are checked between steps and again right before each input' docs/claude-code-integration.md` → `0`.
- **6.2 `docs/performance.md`.** Append the design's sentence to the bullet on the one stopped run.
  - **Check:** `grep -c "whether it would have saved this run is unknown" docs/performance.md` → `1`.
- **6.3 The design's status line.**
  - Replace "Nothing is implemented." with "Implemented on <date>; acceptance 5 of 5 busy trials `done`, and the alert trial `stopped` with its note (`artifacts/experiments/<date>/h5-acceptance/summary.md`)."
  - **Check:** `grep -c "h5-acceptance/summary.md" docs/executor-improvements.md` → `1`, and the registered text is unchanged:
    `python3 -c "from pathlib import Path; r=Path('artifacts/experiments/2026-09-24/preregistration-copy.md').read_text(); print(r[r.index('## 1. Hypotheses and how each is tested'):] in Path('docs/executor-improvements.md').read_text())"` → `True`.

## Phase 7: Review and QA

- **7.1 Independent review of the change.**
  - Two reviewer agents, read-only: one for correctness and safety, one for tests and docs. The Codex reviewer is disabled in your settings, so these are Claude's own reviewers.
  - **What they read:** `diff -u /Users/terry/projects/jev-ultrafast/artifacts/h5-implementation/before/<file> <file>` for each file 7.3 lists. `git diff` would miss the files the change adds until they are staged.
  - Apply every blocker and should-fix, then run the repo checks again.
  - **If a fix changes any file under `jev_ultrafast/`, or `scripts/check_guards.py`:** run 4.1, 4.2 and Phase 5 again on the final code, into a new acceptance folder. Update 5.3's summary and the design's status line to point at it.
  - **Check 2:** the acceptance ran on the final code. `uv run python -c "from jev_ultrafast import mcp_server; print(mcp_server.SOURCE[:12])"` prints the source hash recorded in the acceptance summary that the design's status line cites.
  - **Check:** both final verdicts are "approve", or "approve with fixes" with each fix applied and listed in the Status table.
- **7.2 Mutation check, in a scratch copy.**
  - Copy the package and the scripts: `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; rsync -a jev_ultrafast/ "$S/mut/jev_ultrafast/"; rsync -a scripts/ "$S/mut/scripts/"`. Every 7.2 command starts with `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation;`.
  - Apply each mutant from the table below to the copy, one at a time. Mutants go only into `$S/mut`, never into the repo. That is why the final `page_info` grep over `jev_ultrafast/*.py` stays empty.
  - Run the named tests with `PYTHONPATH=$S/mut uv run pytest -q -k "<names>"`. First confirm the copy is the one imported. `-P` keeps the current folder off the import path: `PYTHONPATH=$S/mut uv run python -P -c "import jev_ultrafast, scripts.report_runs as r; print(jev_ultrafast.__file__, r.__file__)"` prints two paths under `$S/mut`.
  - **Check:** every mutant fails at least one of its named tests.

  | Mutant | Must fail |
  | --- | --- |
  | No repeat: the loop replaced by the old single read | test 1 or 8 |
  | `range(READ_TIMEOUT_REPEATS)`: one read too few | test 2 |
  | No dialog check | test 3 |
  | Stop check before the dialog check | test 3 |
  | No stop check | test 4 |
  | `except Exception` instead of `except TimeoutError` | test 5 |
  | Counter incremented before the stop check | test 4 |
  | `.get("dialog")` instead of `["dialog"]` | test 7 |
  | `page_info()` instead of `_send` | test 7 |
  | `run["repeated_reads"]` instead of `run.get(...)` in `report_runs.py` | test 9 |
  | Only if 4.3 was applied: `self.dismiss_dialog()` without its `contextlib.suppress` guard | `test_constructor_failure_closes_target` or `test_close_dismisses_a_dialog_first` |

- **7.3 Scope.**
  - **Check:** `S=/Users/terry/projects/jev-ultrafast/artifacts/h5-implementation; git ls-files -co --exclude-standard -z | xargs -0 shasum -a 256 | diff "$S/before.sha" - | grep '^[<>]' | awk '{print $3}' | sort -u` lists only files from "Files this plan may change".
- **7.4 Final repo checks.** All pass; `uv run pytest -q` → `131 passed`, or `133 passed` if 4.3 was applied.

## Final verification

1. **Repo checks:** all pass, with `131 passed`: the 120 of the baseline, 5 cases of test 7, 5 new agent tests, and test 8. Tests 6 and 9 extend existing tests. With 4.3's fallback it is `133 passed`.
2. **Anti-pattern greps, each with no output:**
   - `grep -n -E 'page_info|get\("dialog"\)' jev_ultrafast/*.py | grep -v -E ':[0-9]+:\s*#'`: no use outside full-line comments
   - `grep -n "except TimeoutError" jev_ultrafast/browser.py`
   - `grep -rn "api.typesafe.ai\|openrouter.ai\|api.deepseek.com" tests/`
3. **Coverage of the design:** every design item maps to a subtask whose check has passed.

| Design item | Subtasks |
| --- | --- |
| §2.3 `agent.py`: constant, counter, loop, comment | 2.1–2.3 |
| §2.3 `browser.py`: import, `dialog_open()` | 1.1 |
| §2.5 tests 1–7 | 1.1, 2.2, 2.3 |
| §2.5 tests 8–9 | 3.1, 3.2 |
| §2.5 live checks 10–11 | 4.2–4.4 |
| §2.5 acceptance | 5.1–5.3 |
| §2.6 docs and comments | 3.3, 6.1, 6.2 |
| D5 in `report_runs.py` | 3.2 |
| Design status | 6.3 |

## Calvin's ledger

- **Questions:** asked in report mode by two calvin runs, one per half of the plan. Line numbers refer to the version they read, sha256 prefix `edd32a9c62a7be37`, before the answers were applied.
- **Answers:** the author's, Claude's; each is applied in the plan.

## Calvin's Ledger — executor-improvements-plan.md (close)
| # | Line | Quote | Category | Question | Status | Author's answer |
|---|------|-------|----------|----------|--------|-----------------|
| A1 | doc | (absent) problem statement and success measure | completeness · blocker | Why repeat the read at all, and how would anyone know H5 is solved, beyond checks passing? | RESOLVED | Today a busy page after a step ends the run `stopped` though its input worked (run 7782). Solved means 5.2's acceptance on the test page, and in real use `report_runs.py`'s "repeated reads" with the runs going on. How often it matters is unknown: 1 of 76 run files. Added "The problem, and how we will know it is solved". |
| A2 | L6 | "Each phase lists what to read first" | inconsistency · blocker | Phases 1–3 list nothing to read first; what does their executor read? | RESOLVED | Added "Read first" lines to Phases 1, 2 and 3. |
| A3 | L7 | "A subtask is done only when its check passes." | completeness · blocker | When a check doesn't pass, what does the executor do next? | RESOLVED | Added "When a check fails": never loosen a check; fix only inside the subtask and the design, else stop and report; in Phases 4–5, shut the lab down first. |
| A4 | L33–L34 | "Applied only if check 11 fails in the lab." | completeness · blocker | If check 11 passes in the lab but fails in your Chrome, what then? | RESOLVED | Stop and report; 4.3 is not applied on that evidence alone. If a dialog was open in one of your tabs, close it and run 4.4 once more. Added to 4.4. |
| A5 | L42+L50 | "Keep README claims, evidence, and model-call counts consistent." | inconsistency · blocker | How is README kept consistent when it isn't in the files this plan may change? | RESOLVED | README describes no read timeouts, so nothing in it goes stale. Added 6.0, whose check shows `grep -c -i -E 'timed out|timeout' README.md` → `0`. |
| A6 | L77+L127 | "Replace the read at `agent.py` 235" | ambiguity · blocker | Once lines are added, how does the executor find that read and tell it from the others? | RESOLVED | By its surroundings: the read in `command("act")` right after the `self.save()` that follows `state["stale_streak"] = 0  # a step ran`. Added to 2.3, with Check 6. |
| A7 | L9+L90 | "a fixed scratch folder outside the repo, made in 0.2" | completeness · minor | What happens to the baseline if 0.2 runs again after later phases changed files? | RESOLVED | 0.2 now refuses to overwrite a baseline. The folder moved to `artifacts/h5-implementation`, which git ignores and a reboot keeps. |
| A8 | L32 | "resets the record itself, and the lab run finds out safely" | reasoning · minor | If the check resets the record itself, what does running it first in the lab avoid? | RESOLVED | The reset needs the check to reach its `finally` and Chrome to send the close event. If either fails the first time, the stuck record lands on a throwaway daemon, not the one real runs use. P1 now says so. |
| A9 | L44+L98 | "run these at the end of every phase that changes code" | inconsistency · minor | Phase 1 changes code but has no repo-checks subtask; what closes it? | RESOLVED | Added 1.2: repo checks, `125 passed`. |
| A10 | L70+L104 | "Raises `_IPCResponseTimeout`, a `TimeoutError`, after 5 s" | completeness · minor | What does `dialog_open()` do when `_send` times out? Test 7 doesn't cover it. | RESOLVED | A `TimeoutError` is an `Exception`, so it counts as a dialog. Test 7 gains that fifth case; the counts became 125, 130 and 131, or 133 with 4.3. |
| A11 | L103+L129+L139 | "Add tests 1–5 from design §2.5" | completeness · minor | Where is test 6, and which phase adds it? | RESOLVED | Test 6 is the extension of `test_new_goal_resets_every_counter` in 2.2, and test 9 the extension in 3.2. Both are now labelled. |
| A12 | L105 | "A regression to `page_info()` then cannot reach the live daemon." | reasoning · minor | How do you know patching both modules closes every path `page_info()` could take? | RESOLVED | `page_info()` reaches the daemon only through `helpers._send`: directly for `pending_dialog`, and through `_runtime_evaluate` → `cdp` → `_send`. The reason is now in 1.1. |
| B1 | L163+L172 | "nothing listens on the port" | completeness · blocker | What if something already listens on 9335, or the version check never answers? | RESOLVED | Port taken: stop, kill nothing, report what listens. Version check fails: 5.4's shutdown, then stop and report the Chrome log. Both added to 4.1. |
| B2 | L176+L185 | "Only if the closed-tab line failed" | completeness · blocker | If 4.2 fails on another line, what next? | RESOLVED | 5.4's shutdown, then stop and report; only the closed-tab line leads to 4.3. Added to 4.2. |
| B3 | L197 | "stop and bring the finding back to design review" | completeness · blocker | When the plan stops at a Phase 4–5 failure, what happens to the running lab? | RESOLVED | Every Phase 4–5 failure runs 5.4's shutdown first ("When a check fails"). 5.4 is safe at any point after 4.1. |
| B4 | L198 | "The owner's Chrome, after 4.2 passes." | assumption · blocker | Why run checks 10–11 in your Chrome at all? | RESOLVED | `check_guards.py` is the repo's standing live check and normally runs against your daemon, which is attached to one of your tabs and runs your extensions. The lab has neither. Added to 4.4. |
| B5 | L200 | "→ the same six lines." | completeness · blocker | If 4.4 fails after 4.2 passed, what next? | RESOLVED | Stop and report; 4.3 is not applied on that alone. If a dialog was open in one of your tabs, close it and run 4.4 once more. |
| B6 | L207 | "so the registered raw files stay unchanged" | assumption · blocker | How do you know the copy writes under `$A`? | RESOLVED | `labc_common.py` sets `RAW = OUT / "raw"` from the copy's own folder, and `h5_fix_trials.py` puts `mcp_server.RUNS` inside it. 5.1 now records the registered H5 folder's hashes, and 5.2's Check 2 shows them unchanged. |
| B7 | L219+L226 | "Run 5 busy trials and 1 alert trial." | completeness · blocker | If a trial prints something unexpected, what happens to it? | RESOLVED | It fails the acceptance and is not re-run. Keep every raw file, shut the lab down, and bring it back to design review. Added to 5.2. |
| B8 | L228 | "implemented-busy-N.json done True True 1 []" | reasoning · blocker | What fixes the repeat count at 1? | RESOLVED | The fixture blocks the page for 7 s. The first read times out at about 5 s, and the block ends inside the second read's 5 s wait; H5's repeats returned after 2,001–2,002 ms. Added to 5.2. |
| B9 | L234+L239 | "kills Chrome by its recorded process ID" | assumption · blocker | How does the shutdown know the ID still belongs to the lab Chrome? | RESOLVED | It checks: Chrome is killed by ID only while `ps` shows that ID's command line naming the lab profile. The final `pkill` matches only the unique temporary profile path. |
| B10 | L242–L243 | "repeated once if Chrome is still exiting" | completeness · blocker | If Check 2 or Check 3 still fails, what does the executor do? | RESOLVED | Check 2: `pkill -9` on the lab profile once, check again, then stop and report. Check 3: stop, report both IDs, and change nothing on your daemon. |
| B11 | L272 | "Apply every blocker and should-fix, then run the repo checks again." | reasoning · blocker | If a review fix changes code after the acceptance, what shows the final code still passes? | RESOLVED | If a 7.1 fix touches `jev_ultrafast/` or `check_guards.py`, 4.1, 4.2 and Phase 5 run again on the final code. 7.1's Check 2 compares `mcp_server.SOURCE` with the acceptance summary's hash. |
| B12 | L290+L302 | "`page_info()` instead of `_send`" | inconsistency · minor | How can the final `page_info` grep come back empty if a mutant calls it? | RESOLVED | Mutants go only into `$S/mut`, never into the repo, and the grep reads the repo. 7.2 now says so. |
☑ 24 resolved · 0 open · 0 dismissed
