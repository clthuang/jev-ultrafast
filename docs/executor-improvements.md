# Executor improvements from the Phase 10 comparison

> Current implementation note (2026-10-04): use the [current contracts](robustness-efficiency/current-contracts.md) for current operational behavior and storage migration. Historical designs, examples and trial evidence below are retained; a recorded historical result does not prove this candidate.


**Status:** §2/§4 readiness and §5 WAIT handling are implemented in the current candidate; release acceptance and deployment are separate. Historical design/trial records follow.

- **Round 1** (§1, §2): seven hypotheses, registered on 2026-09-24 at 12:52, before any experiment ran. All ran
  12:55–13:25 the same day.
  - **Verified:** only H5, re-reading after a read timeout, and only on a synthetic busy page.
  - **Its design:** §2.
- **Round 2** (§3): waiting for a page to load. Each hypothesis was registered before its trials:
  - **H8,** a wait after every input: not verified;
  - **H8b,** a wait before a DONE or BLOCKED answer stands, with a 500 ms minimum: verified, for DONE answers from a
    simulated fast Jev on five search sites;
  - **H8c,** after the user's review, that wait at every final answer with no minimum: not verified. It failed only on
    YouTube, where the results rule could not see results that had loaded;
  - **H8d,** YouTube again, in a taller view: verified.
- **Round 2's design:** §4 v4.2, approved on your behalf on 2026-09-29 (plan P25). It drops the minimum and waits at
  every final answer, by a rule H8d registered after H8c's result.
- **The plan:** `docs/executor-improvements-plan.md` builds §2 and §4 together, as one page-readiness protocol
  (§4.1), with the failure-review follow-ups.
- **The first automatic review** (2026-09-29, `docs/failure-review.md`) proposed two changes:
  - **waiting for results before DONE:** §4's own, from two runs it flagged (§4.2);
  - **reading controls below the fold and inside shadow DOM:** H1 and H4 again. Both were partly verified, and every
    fix tried failed (§1, Results), so it is held until a new fix idea (plan P32).
- **Round 3** (§5, v3): when Jev judges a page still loading, the run returns to Claude, which decides what follows
  (H9). Proposed on 2026-09-29 at the user's request, revised after their review and calvin's questions, built at
  their request, then independently reviewed, code and docs. Its lab trial, on 2026-09-30,
  gave no conclusion on D15: Jev's first answer on a loading page was always WAIT, but after one WAIT often
  BLOCKED. A second, on 2026-10-01 with real Claude sessions in the loop, passed: Claude asked Jev again by itself
  after every stop on a page that loaded, and reported one that never did honestly (§5.5).

**Where the problem is:** in the Phase 10 comparison (`docs/performance.md`), 7 of 30 executor sessions needed more than one `run_goal`. They took 57% of all executor session time (951 of 1,680 s), and they include all 4 goals where Claude in Chrome was faster. Jev's own loop was a median 4.0 s of a 32.1 s session.

## 1. Hypotheses and how each is tested

**Rules for every test:**

- **Criteria first:** each pass criterion below was written before its experiment ran. A result that misses a criterion is reported as missed; criteria are not changed afterwards.
- **Verdicts:**
  - **Verified:** every test of the hypothesis passes.
  - **Partly verified:** the mechanism test passes but a fix, benefit, or regression test fails.
  - **Rejected:** the mechanism test fails.
  - Only verified hypotheses enter the design.
- **Fix before and after:** each fix is tested against the current code in the same session and setting, so a difference cannot come from the day, the site, or the network.
- **Isolation:** experiments run in scratch copies of the repo and write only to `artifacts/experiments/2026-09-24/` and the scratch folder. The repo's code is not changed.
- **Browsers:**
  - **Lab Chromes for site mechanics:** separate Chrome instances with fresh profiles and their own debugging ports, each with its own browser-harness daemon (`BU_NAME`, `BU_CDP_URL`).
  - **The owner's Chrome only for H6**, which needs the 1Password extension installed there.
- **Recorded requests are replayed exactly:** every Jev decision in `artifacts/runs/*.json` stores the request sent (`model`, `state`, `questions`). A replay sends that request unchanged, or with one named change.
- **Cost cap:** Jev and text-model calls are cents. Claude Code sessions (H7 only) are capped at 12.

### H1 Off-screen controls

- **Claim:** the page read keeps only controls whose centre is inside the viewport (`snapshot.js:59`). When the control a goal needs is below the fold, Jev never sees it and answers BLOCKED instead of scrolling.
- **What raised it:**
  - **APOD:** run `20260924-110859-1ba9` answered BLOCKED 0.73, SCROLL_DOWN 0.21; the "Archive" link was below a large image.
  - **arXiv:** runs `20260924-112406-f39e` and `20260924-112421-fc87` answered BLOCKED with the date fields below "Specific year".
- **Candidate fixes, the simplest first:**
  - **H1-rule:** one added line in `NEXT_ACTION` (model.py): if a control the goal needs is not listed and Scroll down is offered, choose SCROLL_DOWN; BLOCKED only when no listed control or scrolling can help.
  - **H1-hints:** the page read also lists up to 30 off-screen control labels, each with its direction (above or below). They are data only, never targets, and one rule line says so.
- **Tests:**
  1. **Mechanism:** in the recorded requests of the 3 blocked decisions, the needed control is absent from `state.elements`, and SCROLL_DOWN is offered. Pass: 3 of 3.
  2. **Fix, by replay (H1-rule):** each of the 3 recorded requests is replayed 5 times with the rule line. Pass: SCROLL_DOWN is the top operation in at least 4 of 5 replays of each.
  3. **No regression, by replay (H1-rule):** every recorded decision from runs Claude labeled passed is replayed once with the rule line. Pass: the top operation and target are unchanged in at least 95% of them, and no change turns a correct DONE into SCROLL_DOWN or BLOCKED.
  4. **Fix, end to end:** live runs of Claude's first goal for APOD and for arXiv (each taken verbatim from its recorded run), 3 runs per site for the current code and for each fix variant.
     - **Pass:** the variant ends `done` with the task's check passing in at least 5 of 6 runs.
     - **Reproduction:** the current code fails at least 4 of 6 today; otherwise the mechanism is not reproduced today, and that is reported.
     - **Which variant enters the design:** H1-hints only if H1-rule fails a test.

### H2 Covered controls in the page read

- **Claim:** the page read offers controls whose centre is covered by another element. `browser.py` act's hit-test rejects such a control before input (`e.contains(document.elementFromPoint(x,y))`), so Jev keeps choosing it and every choice goes stale. If the read left out the controls act would reject, Jev would choose an uncovered one, such as the open suggestion, and make progress.
- **What raised it:**
  - **ClinicalTrials:** runs `20260924-113417-40d8` and `20260924-113517-88f4`; the site's suggestion list covered "Other terms", with 119 and 120 stale decisions.
  - **Pizza form:** runs `20260924-102226-8f36` and `20260924-102325-c82d`; 1Password's inline menu covered "E-mail address".
- **Candidate fix:** the page read applies act's exact centre-point hit-test and leaves out covered controls.
- **Tests:**
  1. **Mechanism:** the recorded stalled requests on ClinicalTrials contain both "Other terms" and the suggestion options, and the recorded screenshots show the list over "Other terms". Pass: both runs.
  2. **Fix, by replay:** the first stalled decision of each ClinicalTrials run is replayed 5 times with "Other terms" removed from `state.elements` and from the target questions. Pass: CLICK on the "asthma" suggestion is the top choice in at least 4 of 5 for each.
  3. **Consistency census:** on the start and end pages of all 30 goals, and on ClinicalTrials with its suggestion list open, the prototype read is compared with the current read.
     - **Pass:** the prototype leaves out at most 2% of all controls.
     - **Each one left out** must be covered at that moment, confirmed by the same hit-test, so act would have rejected it.
  4. **Fix, end to end:** live runs of Claude's first ClinicalTrials goal (verbatim), 3 runs with the current code and 3 with the prototype. Pass: the prototype ends `done` with the check passing in 3 of 3, and the current code fails at least 2 of 3.

### H3 Final read before results render

- **Claim:** `finish()` in `mcp_server.py` takes its fresh read immediately after the stop, which can come before client-side results render. Waiting until the page stops changing, with a cap, would give Claude a complete page and spare the second `run_goal` Claude used only to look again.
- **What raised it:**
  - **DuckDuckGo:** run `20260924-100333-757e`'s final read had no results, and Claude's next goal only re-read the page.
  - **crates.io:** run `20260924-111852-243b` ended with DONE 0.45 against WAIT 0.44, and Claude's next goal was "only wait".
- **Candidate fix:** before the final read, wait until the DOM has not changed for 300 ms, at most 2,000 ms.
- **Tests:**
  1. **Mechanism:** the recorded final pages of runs 757e and 243b contain no search results, and the pages read in Claude's follow-up runs do. Pass: both.
  2. **Fix, live:** 10 trials each on DuckDuckGo and crates.io. The search runs by scripted typing and submit, the executor's own input path with no model; then an immediate read and a settled read are taken.
     - **Pass:** the settled read contains results in at least 9 of 10 trials per site.
     - **Reproduction:** the immediate read lacks results in at least 3 of 10 per site; otherwise the mechanism is not reproduced today, and that is reported.
  3. **Cost:** the settle's added time is measured on the end pages of all 30 goals. Pass: median at most 500 ms.

### H4 Controls inside shadow DOM

- **Claim:** the page read never enters shadow roots, so controls inside open shadow roots, such as MDN's search, are invisible to Jev.
- **What raised it:** MDN runs `20260924-111127-8224`, `20260924-111150-69f5` and `20260924-111225-096c`, all BLOCKED with 0 steps.
- **Candidate fix:**
  - **Read:** the page read also collects controls inside open shadow roots, recursively, with the same filters.
  - **Act:** act's hit-test uses the deepest element at the point.
  - **Labels:** element IDs resolve within each element's own root.
- **Tests:**
  1. **Mechanism:** live, read-only: MDN's search control is inside an open shadow root and absent from the current read. Pass: yes.
  2. **Prevalence census:** on the start and end pages of all 30 goals, count visible in-viewport controls inside open shadow roots. This is reported, not gated, and informs the design's cost-benefit.
  3. **No regression:** on every census page without such controls, the prototype read equals the current read, meaning the same set of role and label pairs. Pass: all such pages.
  4. **Fix, end to end:** live runs of Claude's first MDN goal (verbatim), 3 runs with the current code and 3 with the prototype. Pass: the prototype ends `done` with the check passing in 3 of 3, and the current code fails at least 2 of 3.

### H5 A read timeout after an input ends a successful run

- **Claim:** after a click that starts a heavy page load, the read that follows can exceed the 5 s IPC timeout. `start_run` (mcp_server.py:165) then ends the run `stopped`, although the input succeeded. Reading again after such a timeout, when no dialog is open, would let the run continue. It retries no input, only the read.
- **What raised it:** arXiv run `20260924-112504-7782` stopped with "Runtime.evaluate timed out after 5s waiting for the daemon" after its Search click. Its final screenshot shows the results.
- **Candidate fix:** after an executed input, a read that raises TimeoutError while no dialog is open is repeated, at most 2 more times, within the run budget.
- **Tests:**
  1. **Mechanism:** in run 7782 the timeout came from the read after the executed Search click. The last history step is logged but its post-read fields were never filled, and `finish()`'s own read succeeded. Pass: yes. Every run file is scanned for the same note.
  2. **Reproduction:**
     - **Local fixture:** after navigation, the page blocks its main thread for 7 s. The read after a scripted click must exceed the timeout in 5 of 5 trials.
     - **arXiv:** 10 scripted submits of the advanced search; the rate is reported, not gated.
  3. **Fix, on the fixture:** the prototype continues after the timeout and reads the new page in 5 of 5 trials, and each input appears exactly once in the run history. A dialog still stops the run with its note.

### H6 The own window keeps 1Password's menu off the fields

- **Claim, already written into plan decision 12 and needing verification:** in the executor's own window, 1Password's inline menu does not cover the next field; in the old hidden tab it does.
- **What raised it:**
  - **Hidden tab:** the comparison runs covered "E-mail address" (hidden tab), and so did probes this morning.
  - **Own window:** the live QA run `20260924-114914-9d51` saw no menu.
- **Test:** in the owner's Chrome, on the pizza form, 5 trials per mode, alternating own window and hidden tab (`JEV_BACKGROUND_TAB=1`).
  - **Each trial:** type Customer name and Telephone through the executor's act, with fixed text and no model, then hit-test the centre of "E-mail address".
  - **Pass:** the hidden tab is covered in at least 4 of 5 and the own window in at most 1 of 5.
  - **Otherwise:** plan decision 12 is corrected.

### H7 Keep the executor's tools loaded

- **Claim:** Claude Code loads MCP tools on demand, so every executor session spends its first turn (median 2.7 s) fetching `run_goal`. `"alwaysLoad": true` on the server's entry removes that turn with no change in outcome.
- **What raised it:**
  - **Every executor session started with ToolSearch:** all 30.
  - **A $0.17 probe:** it showed the tools preloaded, while 151 other tools stayed on demand.
- **Tests:**
  1. **Support:** the option is documented for Claude Code MCP servers, or confirmed in the installed version, 2.1.281, with its exact behaviour stated.
  2. **A/B:** 5 navigation goals from `scripts/phase10/tasks.py`, each run once without and once with `alwaysLoad`, alternating. The sessions use the Phase 10 harness settings in a lab browser.
     - **Pass:** no `alwaysLoad` session calls ToolSearch, and median Claude turns drop by 1.
     - **Pass:** median session time drops by at least 1.5 s.
     - **Pass:** every session's check passes in both arms.

### Results

**Registered text unchanged:** section 1 above this heading, from the rules through H7, is byte-identical to the registered copy, `artifacts/experiments/2026-09-24/preregistration-copy.md` (sha256 `bef94882…`).

**How it was checked:**

- **Raw data:** all under `artifacts/experiments/2026-09-24/`.
- **Recount:** the lead recounted each verdict below from the raw files, independently of the agents' summaries, and found no disagreement.

| Hypothesis | Mechanism | Fix | Regression or cost | Verdict |
| --- | --- | --- | --- | --- |
| H1 Off-screen controls | Passed: absent 3 of 3, reproduced 6 of 6 live | Failed: rule 2 of 6 live and 3, 0, 4 of 5 by replay; hints 0 of 6 | Rule passed: 188 of 194 unchanged | Partly verified |
| H2 Covered controls in the read | Passed: both runs | Failed: 0 of 5 and 0 of 5 by replay; 0 of 3 live, each ending `done` with the wrong value | Failed: 2.61% of controls left out | Partly verified; harmful as specified |
| H3 Final read before render | Passed: both runs; reproduced 10 of 10 per site | Failed: settled reads had results in 0 of 10 (DuckDuckGo) and 7 of 10 (crates.io) | Passed: median 408 ms | Partly verified |
| H4 Shadow DOM | Passed | Failed: 0 of 3 live | Passed: 55 of 55 pages identical | Partly verified |
| H5 Read timeout after an input | Passed, with a caveat: run 7782's one later read was blank | Passed: 5 of 5 on a synthetic 7 s busy page, each input once, dialog still stops; arXiv did not reproduce (0 of 10) | Not applicable | **Verified**, on the synthetic page only |
| H6 Own window and 1Password | Not registered separately | Failed: covered in 2 of 5 own-window and 3 of 5 hidden-tab trials | Not applicable | Not verified |
| H7 `alwaysLoad` | Support passed: documented since Claude Code 2.1.121 | Failed: ToolSearch in 5 of 5 `alwaysLoad` sessions (and 5 of 5 without), median turns unchanged at 4, 0.3 s slower | Passed: checks 10 of 10 | Not verified |

**Verdict labels for H6 and H7:** section 1 did not register which of their tests is the mechanism test, so neither gets a label chosen after the data. H6 has one test, and it failed. H7 is partly verified if its support test counts as the mechanism, and rejected if the A/B's no-ToolSearch criterion does. Neither enters the design either way.

**H1 Off-screen controls** (`offline/`, `labB-h1/`):

- **The mechanism is real:** the needed control was absent in all 3 recorded decisions, and the current code failed 6 of 6 live runs today.
- **The one-line rule moves Jev toward scrolling, but not reliably:**
  - **Live:** APOD's first choice became a coin flip, BLOCKED against SCROLL_DOWN at 0.49/0.49, 0.46/0.52 and 0.39/0.59. On arXiv, SCROLL_DOWN never won (0.24–0.26).
  - **By replay:** SCROLL_DOWN was the top choice in 3 of 5 replays for APOD, and in 0 of 5 and 4 of 5 for the two arXiv decisions. The 4 of 5 came from run `fc87`, whose goal told Jev to scroll to the Date section.
- **The hints failed on APOD** because the 30 nearest off-screen controls did not include "Archive".
- **arXiv has a second obstacle:** once the date fields are on screen and the target questions pick the right fields, CLICK and TYPE_TEXT get about 0.13–0.27 each, and BLOCKED or SCROLL_UP wins at 0.32–0.40. This showed in 3 live runs with hints and in 3 replays of the current code's request; it was not registered.

**H2 Covered controls in the read** (`offline/`, `labA-h2-h4/`):

- **The mechanism is real:** the suggestion list covered "Other terms" in both stalled runs.
- **Hiding a covered control moves the typing to another field instead of unblocking the run:**
  - **ClinicalTrials, registered:** Jev typed into "Condition/disease" in 10 of 10 replays. That field already held "asthma".
  - **Pizza form, an extra:** Jev typed into "Delivery instructions" in 5 of 5 replays, a field the goal said to leave unchanged.
  - **Why:** the operation question still chose TYPE_TEXT, and a target question has no "none of these" answer.
- **Live, it produced silent wrong results:** all 3 prototype runs ended `done` with the search term changed to "Inhaler Training", because the only visible way forward was a suggestion that rewrote it.
- **The census failed too:** of the 54 controls left out, 18 were two-line links that can still be clicked. Their box centre falls on other text, which act's centre-point rule also rejects today.
- **Keep today's stale-streak stop:** it turns this case into a visible `blocked` that names the covering element.

**H3 Final read before render** (`offline/`, `labC-h3-h5/`):

- **The mechanism is real:** immediate reads lacked results in 10 of 10 trials on both sites, and reads 5.6 s later had them in 10 of 10.
- **Waiting for the DOM to go quiet cannot fix it:** DuckDuckGo's page stays quiet for 508–721 ms before its results arrive, presumably while their request is in flight; network events were not recorded. A 300 ms quiet window ends before the results arrive, and on this data no window length passes both the fix test and the cost test. Waiting for the network to go idle might work; it was not tested.

**H4 Shadow DOM** (`labA-h2-h4/`):

- **The mechanism is real:** MDN's search controls are in open shadow roots. MDN's two pages are the only goal pages, of 57, with shadow controls in view: 18, including ads and the theme and language buttons.
- **Reading them was safe:** 55 of 55 other pages read identically.
- **It still did not finish MDN:** after opening the search box and typing, Jev chose MDN's homepage Search button 9 times, although the open search box covered it. Every run then hit the stale-streak stop.

**H5 Read timeout after an input** (`offline/`, `labC-h3-h5/`):

- **Test 1 passed, with a caveat:**
  - **The timeout came after the input:** it hit the read after run 7782's executed Search click, and the step's post-read fields were never filled.
  - **The final read raised nothing but was empty:** 0 characters of text, 1 action and the form's title, while the screenshot shows the results.
  - **It is rare:** 1 of the 76 run files has this note. A timeout in a run's first read ends it before any run file is written, so the scan cannot count those.
- **Test 2 passed on the fixture:** the read timed out in 5 of 5 trials, at 5,008–5,019 ms. arXiv, not gated, did not reproduce today: 0 of 10, with reads of 395–495 ms.
- **Test 3 passed:**
  - **Busy page:** the current code stopped 5 of 5 times; the prototype ended `done` 5 of 5, with each input in the history once and one form submission at the server per trial.
  - **Alert:** an `alert()` after the input still stopped the run with "the page showed a dialog; dismissed".
- **Verified, with a narrow reach:** only a page that stays busy past 5 s after an input benefits. The fix is verified on a synthetic 7 s busy page; what made run 7782's page busy is not known.

**H6 Own window and 1Password** (`h6-h7/`):

- **1Password's menu element was present in all 10 trials in both modes.** It spans the whole viewport, so only the hit-test at the centre of "E-mail address" shows whether its popup covered the field. It did in 5 of 10: 5 of the first 6 trials and 0 of the last 4, whatever the mode. With 10 trials, that pattern is not a verified trend.
- **Plan decision 12's claim was wrong and is corrected.** Chrome never came to the front in any trial.

**H7 `alwaysLoad`** (`h6-h7/`):

- **Claude Code honoured the option:** the first request carried `run_goal` and `report_outcome`.
- **The local API proxy re-deferred them:** this Mac routes Claude Code through the headroom proxy on 127.0.0.1:8789, which defers tools once a request carries 12 or more.
- **The lookup turn therefore stayed, and it comes from the proxy.** With `alwaysLoad`, the first `run_goal` came 4.2 s later: a median 11.2 s after the prompt, against 7.0 s.
- **Not tested:** `alwaysLoad` without the proxy.

**Leads for a later cycle.** None was registered, and none enters this design:

1. **arXiv's split vote:** an interpretation of 3 live runs and 3 diagnostic replays, none registered. The untested remedy: decide "progress or BLOCKED" before choosing among progressing operations.
2. **Goal-matched hints:** list off-screen controls whose label matches the goal, not the nearest 30. The only evidence: with "Archive" appended to one recorded hints request, 3 replays chose SCROLL_DOWN (0.72–0.74). Goal matching was never built.
3. **Network-idle settling** before the final read (H3).
4. **One hittable point for read and act:** use a line box's centre, so wrapped links can be clicked. The census found 18 such links; the idea is untested.
5. **The proxy's deferral:** keep `run_goal` and `report_outcome` in the proxy's resident set, or measure without the proxy. This is outside the repo and is the owner's call.

## 2. Design: repeat a read that times out after a step (H5)

**Scope:** H5 is the only verified hypothesis, so it is the only change designed here. §2.7 lists what stays out.

**Review:**
- **Cycle 1:** three reviewers: correctness and safety, evidence and scope, and simplicity and testability. All three approved with fixes and raised no blocker.
- **Cycle 2:** two reviewers: code and tests, and evidence and docs. Both approved with fixes and raised no blocker.
  - **One false rationale, found by both:** D3's first reason, now corrected in §2.3.
  - **The code reviewer's build:** the §2.3 code with the new tests passed 130 tests.
  - **Broken variants:** every one it ran against the tests failed at least one test, except one that behaves identically to the design.
- **Cycle 3:** one reviewer checked the cycle-2 fixes and dry-ran the plan's checks against a build of this design. It found the design ready, apart from the hung-daemon timing in §2.4, now fixed. Its plan findings, including one blocker in the lab shutdown, went into the plan.
- **This version** applies the fixes from both cycles.
- **Cycle 4, on 2026-09-29 (v2):** one reviewer checked §2 and §4 against commit `8953b45`
  (`artifacts/page-readiness-implementation/review-design.md`). Its S6 cut the dialog check:
  - **Why:** no registered criterion needs it, no recorded run met the case (0 of 76), and the daemon's single dialog
    record includes your own tabs, so a dialog left open in any of them would turn the repeat off.
  - **What goes:** the private `_send` import, D2 and D3, test 7, live checks 10 and 11, and the plan's close fallback.
  - **What it costs:** a dialog after a step stops the run about 10 s later, and a stop between the repeats leaves it
    open (§2.8).

**Decisions made on your behalf.** Each has a comment where it lives in the code, naming this section, so it can be changed there.

| # | Decision | Why | Where to change it |
| --- | --- | --- | --- |
| D1 | Repeat a timed-out read at most **2** times | The registered cap. H5's test needed one repeat; only offline test 2 (§2.5) covers giving up. A page that stays busy now stops after about 15 s instead of 5 s | `READ_TIMEOUT_REPEATS` in `jev_ultrafast/agent.py` |
| D2 | **Withdrawn in v2:** there is no dialog check to fail closed | Cycle 4's S6 cut the check | — |
| D3 | **Withdrawn in v2:** nothing asks the daemon about dialogs | Cycle 4's S6 cut the check | — |
| D4 | The repeat covers the read after **every executed step**: click, fill, select, scroll and wait | They all share the one read, and repeating a read is harmless after any of them. The registered fix says "after an executed input", and H5's test exercised a click only | the comment above the loop in `Agent.command("act")` |
| D5 | Count repeats as `repeated_reads`, in the run file and in `scripts/report_runs.py`. Claude's result text does not change | It is the only sign that the fix ever fires outside the test page. The prototype had no counter; it changes no behaviour | `_fresh_state` in `agent.py`; the `totals` in `report_runs.py`; `render()` in `mcp_server.py`, if Claude should see it |

### 2.1 The problem in the code

- **The step is logged first:** `Agent.command("act")` appends the executed step to `history` and saves the run file (`agent.py` lines 211–234). Then it reads the page once (line 235) to fill the step's `url` and `page_changed`.
- **A busy page times that read out:** the read is a `Runtime.evaluate`. When the page's main thread stays busy past browser-harness's 5 s IPC wait, `cdp()` raises `_IPCResponseTimeout`, a `TimeoutError`.
- **Nothing catches it before the server:**
  - **The tick:** `command("tick")` catches only `StalePage`.
  - **The server:** `start_run` (`mcp_server.py` lines 175–176 at `8953b45`) asks `dismissed()`, which finds no dialog.
  - **The result:** the run ends `stopped` with the timeout's text, although its input succeeded.

### 2.2 The change

After an executed step, when the read raises `TimeoutError`, the agent reads again: at most 2 more times, with the
run's stop check before each repeat. A JavaScript dialog also times reads out, so it now stops the run once the
repeats run out, about 10 s later than before (§2.4, §2.8).

**Why this fits the loop:**

- **Same split of responsibilities:**
  - **The agent owns observation retries:** its tick already reads again after a stale choice (`agent.py` lines 114–118).
  - **The server owns stop notes:** they are unchanged.
- **Same invariants:**
  - **No input repeats:** the loop wraps only the read, which runs after the step is logged and saved. "Never retry a browser mutation. Log execution before observing its result." both still hold.
  - **Stop checks keep one path:** they run through `before_input`, as the ones before each text call and input do.
- **Where the integration plan put timeouts:** its rule "Do not catch `TimeoutError` inside `observe()`. The executor handles it." stays true. `observe()` is unchanged, because it also serves reads where a timeout must still stop the run (§2.7).

### 2.3 Code

`jev_ultrafast/agent.py`: a module constant, a counter, and a loop around the read at line 235. Every line below passes `ruff check` at its real indentation; the longest is 118 characters.

```python
# Delegated decision D1 (docs/executor-improvements.md §2): after an executed step, a read that times out is repeated
# at most this many times, each adding up to 5 s. H5's test needed one repeat.
READ_TIMEOUT_REPEATS = 2
```

```python
            repeated_reads=0,  # reads repeated after a timeout; decision D5, docs/executor-improvements.md §2
```

```python
            # A heavy page load can outlast one read's 5 s wait. The step ran and is saved: repeat only the read.
            # Decision D4 (docs/executor-improvements.md §2): this covers every executed step, wait and scroll too.
            for read in range(READ_TIMEOUT_REPEATS + 1):
                try:
                    state["page"] = state["browser"].observe(screenshot=self.screenshots)
                    break
                except TimeoutError:
                    if read == READ_TIMEOUT_REPEATS:
                        raise  # out of repeats: stop as before; start_run then dismisses any dialog
                    if self.before_input:
                        self.before_input()  # the run's budget, cancellation and shutdown also bound the repeats
                    state["repeated_reads"] += 1
```

- **A dialog times out every read:** the repeats run out, then `start_run` finds the dialog and dismisses it, with
  today's note, about 10 s later. A stop between the repeats ends the run without dismissing it, since neither
  `start_run`'s `except Exception` branch, for the budget and a shutdown, nor its `asyncio.CancelledError` branch, for
  Esc, calls `dismissed()`. The dialog then stays until the tab closes, or until the next goal in that tab stops once
  with "the page showed a dialog; dismissed" (§2.8).
- **Only a timeout repeats:** a `StalePage` from the read propagates as today, and the tick reads again.
- **The counter counts repeats made:** a stop check that ends the run before a repeat adds nothing.
- **`scripts/report_runs.py`** adds one key to `totals`, after `"stale decisions"`:
  ```python
              "repeated reads": run.get("repeated_reads", 0),
  ```
  It uses `.get` because run files from before this change have no such key, and `main()` skips any file whose facts raise.
- **`__init__`'s comment** becomes `# optional stop check before text calls, inputs and read repeats; raising skips them`.

`jev_ultrafast/browser.py`: unchanged in v2. v1's dialog check, `Browser.dialog_open()` asking the daemon through
browser-harness's private `_send`, is cut (cycle 4); §2.8 keeps it among the alternatives.

### 2.4 Behaviour

| After an executed step | Today | With the change |
| --- | --- | --- |
| The page is busy for more than 5 s, then answers | `stopped` after about 5 s: "Runtime.evaluate timed out after 5s waiting for the daemon" | The read is repeated; the step records the new page and the run goes on |
| The page stays busy through all 3 reads | `stopped` after about 5 s. `finish()`'s own read then waits up to 5 s more | `stopped` after about 15 s, with the same note and the same `finish()` read. The failure code is still `busy_after_step`, since the step's `page_changed` stays None |
| A JavaScript dialog opens after the input returns, for example on the next page | `stopped` after about 5 s: "the page showed a dialog; dismissed" | The same note, after about 15 s: each read times out while the dialog is open, then `start_run` dismisses it. `repeated_reads` is 2. A dialog opened by the click itself times out the input, before this loop, as today |
| The daemon hangs | `stopped` after about 10 s, with the timeout note: the read, then the dismissal call, each wait 5 s | `stopped` after about 20 s: three reads, then the dismissal call |
| The 90 s budget, a cancellation or a shutdown arrives during the repeats | Not applicable | The run stops with that reason before the next repeat, with no failure code, where today the same page ends `busy_after_step`. On shutdown the server exits `SHUTDOWN_WAIT_SECONDS` (5 s) after the signal. On a page still busy, that is usually before `finish()` saves the note. The step itself was saved before the read |
| A repeated read finds the page navigating (`StalePage`) | Not applicable | As a stale read after a step today: the tick reads again, and the run goes on |
| A read after a step returns a blank page, as `finish()`'s read did in run 7782 | The step records the blank page | The same; §2.7 |

### 2.5 Tests

**Offline** (no browser, no model):

- **A click in every test:** the fixture's default decision is a fill, which would call the text model, so every test sets a click with the file's `act(runner)` helper.

In `tests/test_agent.py`:

1. **`test_timed_out_read_after_a_step_is_repeated`:**
   - **Setup:** `observe` raises `TimeoutError` once, then returns a second page with its own URL (`https://example.test/results`) and fingerprint.
   - **Expect:** one `act` and two `observe` calls. The step's `url` and `page_changed` come from the second page, `repeated_reads` is 1, and the status is `ready`.
2. **`test_timed_out_reads_stop_after_the_last_repeat`:**
   - **Setup:** `observe` always raises `TimeoutError`.
   - **Expect:** `TimeoutError`, with `loop.READ_TIMEOUT_REPEATS + 1` `observe` calls and one `act`. `repeated_reads` equals the cap, and the step is logged with `page_changed` None.
3. **Cut in v2,** with the dialog check it tested.
4. **`test_stop_check_runs_before_each_repeated_read`:**
   - **Setup:** `before_input` is `Mock(side_effect=[None, ValueError("90 s budget reached")])`, and `observe` times out once.
   - **Expect:** `ValueError` matching "90 s budget reached", one `observe`, one `act`, and `repeated_reads` 0.
5. **`test_only_a_timed_out_read_is_repeated`:**
   - **Setup:** `observe` raises `StalePage` once.
   - **Expect:** `StalePage`, one `observe`, and `repeated_reads` 0.
6. **`test_new_goal_resets_every_counter`:** extended with `repeated_reads`.
7. **Cut in v2,** with the dialog check it tested.

In the other test files:

8. **`test_a_read_that_timed_out_after_a_click_is_repeated`** (`tests/test_mcp_server.py`):
   - **Pattern:** the real tick, as in `test_cancellation_during_the_decision_executes_no_input`.
   - **Setup:**
     - **Jev's stand-in:** answers CLICK "Search", then DONE.
     - **The timeout, once:** the first read after the click raises `TimeoutError`, and later reads behave as `FakeBrowser.observe` does now. `FakeBrowser.read_error` stays set once set, so the test wraps `observe` with a one-shot error instead.
   - **Expect:**
     - **The result:** it says `done`.
     - **The run file:** one step with `page_changed` not None, and `repeated_reads` 1. It is not True, because the fake page's fingerprint never changes.
     - **The input:** `act` has one call.
9. **`test_report_counts_false_and_missed_done`** (`tests/test_report_runs.py`): extended. One run gets `repeated_reads=2`, and the others have no such key, like run files from before the change. The report then contains "repeated reads 2".

**Live checks 10 and 11:** cut in v2, with the dialog check they tested. §4.6's live check stays.

**Acceptance, once, no model, in a lab Chrome:**

- **What:** the prototype arm of H5 test 3, re-run on the implemented code. It uses the harness in `artifacts/experiments/2026-09-24/labC-h3-h5/`.
- **How:**
  - **Copies:** `h5_fix_trials.py`, `h5_fixture.py` and `labc_common.py` go to a new folder, so the registered raw files stay as they are. The driver `h5_fix_run_all.sh` is not copied: it hard-codes a scratch path and both arms.
  - **The `implemented` arm:** it checks that `jev_ultrafast` is the repo's package with `READ_TIMEOUT_REPEATS`.
  - **One more check:** the run's `repeated_reads`.
  - **The browser:** a lab Chrome with a fresh profile. The owner's Chrome has 1Password, whose menu can cover the fixture's field, which would test 1Password (H6) rather than the repeat.
- **Pass:**
  - **Busy page:** 5 of 5 trials end `done`, with each input once, one submission at the server, and `repeated_reads` 1.
  - **Alert:** the trial ends `stopped` with "the page showed a dialog; dismissed" and `repeated_reads` 2 (v2).

### 2.6 Docs and comments

- **`docs/claude-code-integration.md`:**
  - **The §6.2 code sketch:** the `check_cancelled()` comment `# also runs before each input, via agent.before_input` becomes `# also runs before each input and each repeated read, via agent.before_input`.
  - **"Dialogs":** add that after a step, a read that times out is repeated first, up to 2 times, so a dialog stops the run about 10 s later than before.
  - **"Deadline, cancellation and shutdown":** add "and before each repeated read".
  - **The Speed row of the metrics table:** add "repeated reads (reads after a step that timed out and were taken again)".
- **Comments in `jev_ultrafast/mcp_server.py`:**
  - **`check_stop`:** "between steps, before each text call, input and repeated read".
  - **`shut_down`:** the comment on `STOP.set()` and the ponytail comment under it become these three lines. The ponytail comment now also covers a busy page's reads:
    ```python
        STOP.set()  # this server's run stops between steps, before each input or repeated read, and saves
        # ponytail: a first page load, or a busy page's reads, longer than SHUTDOWN_WAIT_SECONDS can leave its tab open
        # and the stop unsaved; closing orphaned tabs at startup (design §10) is the upgrade if that happens.
    ```
- **`docs/performance.md`,** the bullet on the one stopped run: add "Changed after the comparison: a read that times out after a step is now repeated up to 2 times (`docs/executor-improvements.md` §2). That is verified on a synthetic 7 s busy page; whether it would have saved this run is unknown."
- **README:** no change; it does not describe read timeouts.

### 2.7 Not in this change

- **Other reads still stop on a timeout:**
  - **Which reads:** the first read, `new_goal`'s read, `fresh()`, `predict`'s re-read when the page has changed (`agent.py` lines 131–132), and the tick's re-read after a stale choice.
  - **`finish()`:** its read does not stop a run; a timeout there adds "fresh read failed", as today.
  - **Evidence:** of the 76 run files, only 7782 has a timeout note, and it came from the read after a step. A timeout in a run's first read ends the run before any run file is written, so the scan cannot count those.
- **A blank read after a step is treated like any other read:**
  - **Before Jev's next choice:** `fresh()` compares the page's marker and reads again only if the page changed by then.
  - **If the page is still blank:** Jev chooses on it. `act`'s own `fresh()` check before input drops that choice if the page has since changed.
  - **Two caveats:**
    - **Can still stop the run:** `fresh()` is itself a page evaluate, so on a page still busy it can time out and stop the run.
    - **Untested:** `artifacts/experiments/2026-09-24/offline/summary.md` (surprise 5) suggested treating an empty read as not settled. That overlaps H3, which is not verified.
- **Inputs:** a timeout during an input is never retried.
- **The other hypotheses:** H1–H4 were partly verified and H6–H7 not verified (§1, Results), so none is designed here. The leads for a later cycle are listed there.

### 2.8 Alternatives not taken

- **A longer timeout for this one read,** for example 15 s:
  - **Stop checks wait:** one IPC wait cannot be interrupted, so a cancellation or the budget would wait up to 15 s.
  - **Dialogs stop later:** 15 s instead of 5 s.
  - **Not verified.**
- **Turning the timeout into a stale read,** so the tick reads again:
  - **One repeat only,** with no stop check before it.
  - **No dialog test:** a dialog would first cost a second 5 s timeout.
  - **Not the verified shape.**
- **A dialog check** (v1, cut in v2): before each repeat, ask the daemon through browser-harness's private `_send`
  whether a dialog is open, and stop at once if so.
  - **What it bought:** dialog stops about 10 s sooner, and no dialog left open by a stop between the repeats.
  - **Why it was cut:** no registered criterion needs it, no recorded run met the case (0 of 76), and the daemon's
    single dialog record includes your own tabs, so a dialog left open in any of them would turn the repeat off. It also
    cost a private import, a five-case test and two live checks, one of which could leave the daemon's record stuck.
  - **Where it is:** this section at commit `8953b45`.

## 3. Round 2: page loading (H8)

**Why:** on 2026-09-24 the user asked for a protocol in code that tells a page that is still loading from an action
that failed. The evidence so far:

- **H3:** reads were taken before results rendered, on DuckDuckGo and crates.io.
- **Run 20260924-052252-e4b2:** it ended `done` on Google Flights before the flights were listed.
- **H3's fix failed:** it waited for the DOM to go quiet, but the DOM stays quiet while the results request is in
  flight.

**Rules:** the same as section 1.

- **Verified:** every registered test passes.
- **Partly verified:** the mechanism test passes, but not every other test does.
- **Not verified:** otherwise.
- **Frozen:** no threshold, site, procedure or parameter changes after the first scored trial. A deviation is
  reported, not hidden.
- **No model calls:** Jev and the text model are not called; every input is scripted.

**Done before registering, and disclosed:**

- **The wait's parameters** were fixed and hashed before any network data was looked at:
  `parameters-fixed-before-probe.txt` in the experiment folder (sha256 `331cb65a…`).
- **Procedure probes, not scored:**
  - one Google Flights search through the date picker. Its read on the results URL at 378 ms still showed October
    22's flights; October 23's appeared at 919 ms;
  - label reads on YouTube and npm, with no input.
- **Failed loads:** none of the 897 reads recorded in the 78 run files shows a Chrome error page, an HTTP error page
  or a network error. Refreshing a failed load is therefore not registered.

**Experiment folder:** `artifacts/experiments/2026-09-24/h8-network-settle/`. The prototype is `net_settle.py` there,
hashed with this text.

### H8: waiting for the input's own requests

**Claim:** after an input, the requests the input started are visible to code as CDP Network events on the
executor's own tab. While any of them is in flight, the page is still loading. Waiting until none is in flight, and
none was sent or ended for a short quiet window, gives a read that shows what the input loaded. Today's read, taken as
soon as the page is on the new URL, often does not.

**The wait**, exactly as fixed before the probes:

- **Tracked requests:** `Network.requestWillBeSent` events on the executor tab's CDP session, of type Document, XHR,
  Fetch or Script, sent after the input. The daemon's event buffer is emptied just before the input. A tracked
  request ends at `Network.loadingFinished` or `Network.loadingFailed`.
- **When it ends:** it polls every 20 ms, and ends at the first poll where all of these hold:
  - at least 50 ms have passed since the input returned;
  - no tracked request is in flight;
  - no tracked request was sent or ended in the last Q ms.
- **Cap:** 5 s after the wait started, reported as capped.
- **Arms:** Q = 100 ms, and Q = 500 ms, the network-idle window of Playwright, Puppeteer and Stagehand.

**Variants for the design**, chosen by the selection rule below:

- **A:** wait after every input, before the read.
- **B:** wait only when Jev answers DONE or BLOCKED after an input. That answer then counts as stale, and a new read
  and decision follow the wait. B's read comes no earlier than A's would, so test 2's trials, which use A's
  timeline, cover both.

**Test 1, mechanism.**

- **Premature read:** a control trial's immediate read is premature when it lacks results and the same trial's late
  read has them.
- **Passes if:** at least one tracked request is in flight when the premature read starts, in at least 90% of
  premature reads.
- **Pooling:** control trials across all sites, with at least 10 premature reads in total. Fewer makes test 1, and
  so H8, not verified.

**Test 2, fix.**

- **A trial:**
  - opens a fresh tab at the site's start URL and runs the scripted steps;
  - empties the event buffer just before the search input, then performs the input;
  - then reads, according to its condition, as below.
- **Conditions:**
  - **Control (today's code):**
    - the immediate read is the first read after the input whose URL is the results URL, polling as H3 did;
    - the tracker runs alongside but changes nothing, and records what is in flight when each read starts.
  - **A, Q = 100 ms and A, Q = 500 ms:** the wait starts when the input returns; the settled read follows it.
- **Late read:** every trial also takes a late read 5 s after its immediate or settled read.
- **A read that fails:** a read that raises `StalePage` or times out is retried every 20 ms for up to 5 s, as H3's
  were. The first read that succeeds counts.
- **Order and scoring:**
  - conditions rotate control, Q = 100, Q = 500 within each site, and sites alternate;
  - each site and condition gets 10 scored trials;
  - a trial is not scored, and is replaced, if it shows a bot check, a sign-in or consent wall, or its scripted
    steps fail before the search;
  - at most 15 attempts per site and condition.
- **Passes for an arm if:** the settled read contains results in at least 9 of 10 scored trials on every scored
  site. Google Flights must be scored, and at least 4 of the 5 sites.

**Test 3, cost of variant A.**

- **Which steps:** for each of the 30 Phase 10 goals, the first executed step of its earliest recorded executor run
  whose first read's host and path equal the goal's start URL. A run used for one goal is not reused for another.
- **How each is replayed:**
  - open a fresh tab at the start URL and read it;
  - perform the same kind of input, on the action with the same label (whitespace collapsed), with the same text;
  - run one wait to the Q = 500 ms arm's end, logging every poll, so both arms' end times come from the same replay.
- **At least 20 of the 30** must replay.
- **Passes for an arm if:**
  - the median wait is at most 500 ms;
  - the wait hits its cap on at most 2 replayed steps;
  - in test 2, the wait hits its cap in at most 1 of 10 trials on every scored site.

**Selection rule, fixed now:**

1. Variant A with the smallest Q that passes tests 1, 2 and 3.
2. Otherwise, variant B with the smallest Q that passes tests 1 and 2.
3. Otherwise H8 is not verified, and nothing from it enters the design.

**Sites for test 2:**

| Site | Start URL | Steps before the search | Search input | Results URL | Results rule: at least 3 counted |
| --- | --- | --- | --- | --- | --- |
| Google Flights | `https://www.google.com/travel/flights?tfs=CBwQAhojEgoyMDI2LTEwLTIyagcIARIDWlJIcgwIAxIIL20vMDRqcGxAAUgBcAGCAQsI____________AZgBAg&hl=en` | click "Open Departure"; click the date whose label starts "Friday, October 23, 2026" | click the button whose label starts "Done. Search" | path `/travel/flights/search`, `tfs` decoding to include `2026-10-23` | actions whose label contains "Select flight" and "Friday, October 23" (`verify()`'s results check, for the new date) |
| DuckDuckGo | `https://duckduckgo.com/` | type "Rust programming language" into "Search with DuckDuckGo" | click "Search" (button) | as H3 | H3's R-DDG |
| crates.io | `https://crates.io/` | type "tokio" into "Search" | click "Search" (button) | as H3 | H3's R-CRATES |
| YouTube | `https://www.youtube.com/` | type "rust programming language" into "Search" | click "Search" (button) | path `/results`, `search_query` "rust programming language" | distinct `v` values among links whose path is exactly `/watch` |
| npm | `https://www.npmjs.com/` | type "express" into "Search packages" | click "Search" (button) | path `/search`, `q` "express" | distinct paths among links whose path is `/package/<name>`; a scoped name counts |

**Walls, which make a trial unscored:**

- **DuckDuckGo:** H3's bot page.
- **Google:** "unusual traffic", a `/sorry/` path, or `consent.google.com`.
- **YouTube:** `consent.youtube.com`, or "Before you continue".
- **npm and crates.io:** the title "Just a moment...", or "Verify you are human".

**Reported, not gated:**

- how long each wait took, and which requests it waited for;
- control trials whose immediate read had nothing in flight, and whether that read had results;
- drains that returned the daemon's full 500 events, which may have lost older events.

### H8b: a loading gate at DONE and BLOCKED

**Registered after H8's results, before any H8b trial.**

**Why a follow-up.** H8 is not verified: test 1 had 24 of 38 (63%), test 2 had Google Flights at 0 of 10 in both
arms, and test 3 passed only for Q = 100 ms. In detail:

- **H8's wait after every input fails on Google Flights.** After "Done. Search" the page sends nothing for about 300
  ms, while the date picker closes. It then changes the URL and sends the results request (320–355 ms in control
  trials 2–4). By then H8's wait had ended at its 50 ms grace, on the old page.
- **A quiet page is not a loaded page.** When a control trial's read came before the results, nothing tracked was in
  flight on DuckDuckGo in 10 of 10 trials. Its results request starts after its page has loaded and gone quiet. H8b
  checks later, when Jev answers, and never before 500 ms after the input.
- **H8 also found a flaw in the tracker.** A cross-site iframe's document request (ads, reCAPTCHA) shows up on the
  tab's session but finishes on the iframe's own session. It stayed "in flight" until the 5 s cap in both capped
  replays.
- **H8's YouTube rule is blind.** A sponsored video and a Shorts shelf fill the viewport, and the read lists only
  controls in view. Late reads 5 s after the search also failed the rule.
- **Where a wait matters is the final answer.** Recorded runs answer DONE or BLOCKED at least 295 ms after the last
  input (10th percentile 333 ms, median 797 ms, 63 runs).
- **Most of the check already exists.** `agent.py` checks `browser.fresh(page)` before accepting DONE or BLOCKED. The
  marker it compares includes the page's text and controls, so results that arrive after Jev's read make the answer
  stale. The gap is an answer given while results are still loading and the page has not changed yet, as in run
  20260924-052252-e4b2.

**The gate** (`net_gate.py`, hashed with this text):

- **Tracked requests:** as H8, except that a Document request counts only for the tab's main frame (`frameId` equal
  to the main frame's id from `Page.getFrameTree`).
- **When it runs:** when Jev answers DONE or BLOCKED after an input, before the existing freshness check. It runs at
  most once per input.
- **What it waits for:** it polls every 20 ms, and ends at the first poll where all of these hold:
  - at least 500 ms have passed since the input returned;
  - no tracked request is in flight;
  - no tracked request was sent or ended in the last Q ms.
- **Cap:** 5 s after the gate started.
- **After it:** the existing check runs unchanged. If the page changed since the read Jev answered on, the answer is
  stale, and a new read and answer follow. Otherwise the answer stands.
- **Q = 100 ms.** Chosen by a rule fixed after seeing H8's partial results, but before its final tally: 100 ms if
  H8's Q = 100 ms arm had results in at least as many settled reads as its Q = 500 ms arm on DuckDuckGo, crates.io
  and npm combined; otherwise 500 ms. Both arms had 30 of 30, so Q = 100 ms.
- **Why 500 ms since the input:** it covers Google Flights' delay of about 300 ms with room to spare. The floor alone
  adds at most 205 ms to a final answer, since recorded answers come at least 295 ms after the input, and at most
  167 ms in 90% of runs.

**The simulated Jev (tests 1 and 2):**

- **When it answers:** DONE, 275 ms after every read. That is the 10th percentile of the 112 recorded DONE and BLOCKED
  decision latencies; fast answers are the risky ones.
- **What a trial does:**
  - H8's steps, with the tracker reset just before the search input;
  - then up to 6 rounds of: a read, the answer, and either today's check alone or, in the gate condition, the gate
    first on the first answer;
  - the first answer that stands is accepted. Its read is the accepted read.
- **If no answer stands in 6 rounds,** the trial has no accepted read, which scores as no results.

**Sites:** H8's five, with the same steps, results URLs, rules and walls, except YouTube's rule.

- **YouTube's new rule:** distinct video ids among links whose path is `/watch` (its `v`) or `/shorts/<id>`.

**Test 1, mechanism (today's condition).**

- **False DONE:** a trial whose accepted read lacks results while its late read, 5 s later, has them.
- **Passes if:**
  - at least 5 false DONEs occur across all sites;
  - in at least 90% of them, the gate would have waited at the moment of acceptance: less than 500 ms after the
    input, a tracked request in flight, or one sent or ended in the last Q ms.

**Test 2, fix (gate condition).**

- **Passes if:** the accepted read contains results in at least 9 of 10 scored trials on every scored site.
- **Scored sites:** Google Flights must be scored, and at least 4 of the 5.

**Test 3, cost.**

- **Replays:** H8's 29 first steps, replayed with H8's matching. Each gets the executor's read, the simulated answer,
  and then the gate.
- **Passes if:**
  - at least 20 steps replay;
  - the median gate is at most 500 ms;
  - the gate hits its cap on at most 2 replays;
  - in test 2, the gate hits its cap in at most 1 of 10 trials on every scored site.

**Order, scoring and walls:** as H8.

- **Order:** conditions alternate today, gate within each site, and sites alternate.
- **Scoring:** 10 scored trials per site and condition, at most 15 attempts.

**Verdict:**

- **Verified if tests 1, 2 and 3 all pass.** The design then includes the gate.
- **Otherwise H8b is not verified,** and nothing from H8 or H8b enters the design.

**Reported, not gated:**

- extra rounds (Jev decisions) per trial, today against gate;
- the gate's waits and what it waited for;
- drains of 500 events.

### Results (H8 and H8b)

**Registered texts unchanged:** the two registered blocks above are byte-identical to `registration.md` (sha256
`003ad8f0…`) and `registration-h8b.md` (sha256 `2a263472…`) in the experiment folder. Each was hashed before its
first trial: H8's with its wait (`net_settle.py`), and H8b's with every harness, H8's included ("Deviations"
below).

**How it was checked:**

- **Raw data:** `artifacts/experiments/2026-09-24/h8-network-settle/raw/`.
- **Scoring:** `h8_analyze.py` and `h8b_analyze.py` score the registered tests from the raw files.
- **Independent recount:** an agent re-derived every figure in both verdicts with its own code, and found no
  difference. It also checked the hashes and times, and that the harnesses follow the registrations. It found five
  background claims wrong or overstated; they are corrected below.
- **No replacements:** every site and condition got its 10 scored trials in 10 attempts, with no walls and no failed
  steps.

| Hypothesis | Mechanism | Fix | Cost | Verdict |
| --- | --- | --- | --- | --- |
| H8: wait after every input | Failed: a request was in flight at 24 of 38 premature reads (63%); DuckDuckGo 0 of 10 | Failed: Google Flights 0 of 10 in both arms | Q = 100 ms passed (median 194 ms); Q = 500 ms failed (630 ms) | Not verified |
| H8b: wait before DONE or BLOCKED | Passed: the gate would have waited at all 24 false DONEs | Passed: 10 of 10 on all five sites | Passed: median 195 ms, none capped, 29 replays | **Verified**, for DONE answers from a simulated Jev |

**H8, wait after every input:**

- **It ends before Google Flights starts loading.** After "Done. Search", the date picker closes. A read first
  finds the page on its new URL 301–346 ms after the click; the read before that started at 259–295 ms. The
  results request comes about then or later: by the read that first found the new URL, the tracker had seen it in 5
  of 10 control trials. H8's wait had ended within 77 ms of the click, so all 20 settled reads were still on the old
  page.
- **Test 1 measured DuckDuckGo too early to count.** Every control read there reached the results URL at the first
  poll, 0.2–0.6 ms after the click, before any request event had reached the tracker. So its 0 of 10 says nothing
  about loading. Test 1 fails either way: 34 of 38 (89%) counting all ten as in flight, 24 of 28 (86%) leaving
  DuckDuckGo out. H8 also fails test 2 on Google Flights.
- **Some requests never report their end.** Both capped replays, on calculator.net and timeanddate.com, waited the
  full 5 s.
  - **Iframe documents:** in both, ad and reCAPTCHA iframe documents stayed open. Their requests appear on the tab's
    session, but a cross-site iframe runs in its own process, and none reported its end there.
  - **`blob:` scripts:** on timeanddate.com, three of them stayed open too. H8b's frame filter does not exclude
    them.
- **YouTube's rule was blind.** Even the late reads failed it, in 10 of YouTube's 30 trials: fewer than 3 regular
  videos were in view, and a read lists only controls in view (H1's finding). The three screenshots checked all
  show results, with a sponsored video, a Shorts shelf, or both, taking the space. So it was the rule, not loading.
  H8b's rule counts Shorts too; scored with it, 5 of those 10 late reads would still fail.
- **Where it worked:** DuckDuckGo, crates.io and npm had results in all 60 settled reads. Their immediate reads had
  them in 9 of 30.

**H8b, wait before DONE or BLOCKED:**

- **Early answers are often wrong.** The simulated Jev answered DONE 275 ms after each read, the 10th percentile of
  recorded DONE and BLOCKED latencies.
  - **Today's check** accepted a DONE before the results loaded in 24 of 50 trials: DuckDuckGo 10, crates.io 10,
    Google Flights 2, YouTube 2 and npm 0.
  - **The rest were caught:** in those, the page changed before the answer, so the existing freshness check made it
    stale.
- **The gate caught all 24.** At each moment of acceptance, a request sent after the search input was still in
  flight.
- **With the gate, all 50 accepted reads had results.**
  - **Wait lengths:** a median of 748 ms on Google Flights, 650 ms on DuckDuckGo, 450 ms on YouTube, 196 ms on
    crates.io and 178 ms on npm. The longest was 1.1 s, and none hit the cap.
  - **Every gated answer went stale:** the page had changed during the wait, so Jev answered again on the loaded page.
    Even so, trials needed fewer answers than today's: a mean of 2.12, against 2.42.
- **Elsewhere it costs little.** On the 29 replayed first steps, the answer came a median of 325 ms after the input,
  and the gate then waited a median of 195 ms, mostly for its 500 ms floor. The longest wait was 1.8 s, none capped,
  and 7 of 29 had a request in flight at the answer.
- **Not tested:**
  - BLOCKED answers, which take the same code path;
  - the real Jev, whose answers are slower than the simulated ones in 90% of cases;
  - the start page's own load.

**Corrections to the registered background.** These statements were motivation, not test criteria, so no verdict
changes. The registered texts stay as frozen:

- **H8b, "the results request (320–355 ms in control trials 2–4)":** in trial 2, that was a logging request.
  The results request was seen at 337–355 ms in trials 3, 4, 6, 8 and 10.
- **H8b, "nothing tracked was in flight on DuckDuckGo in 10 of 10 trials. Its results request starts after its
  page has loaded and gone quiet":** the measurement came too early (above). The data do not show when
  DuckDuckGo's request starts.
- **H8b, "A sponsored video and a Shorts shelf fill the viewport":** of the three screenshots checked, one shows
  both, one a sponsored video and 2 regular videos, and one a Shorts shelf.
- **H8b, "adds at most 205 ms":** measured from the final decision's own time instead, the smallest gap is 289
  ms, so at most 211 ms.
- **H8, "none of the 897 reads … shows a Chrome error page, an HTTP error page or a network error":** true, and a
  broader scan found none either. But a scan of reads sees only loads that could be read: a load that leaves no
  readable page stops the run on the read's error instead. None of the 78 runs stopped that way. The 3 stopped
  runs were 2 cancellations and 1 read timeout, H5's case.

**Deviations, none changing a verdict:**

- **Answer timing:** the simulated answers came 275–306 ms after each read, not exactly 275 ms.
- **Test 1's moment:** "in flight" was read at the simulated answer, a few ms before the freshness check ran.
- **Unscored failures:** the harnesses would have marked any failure after the search unscored, where the
  registrations name only failures before it. No trial failed.
- **H8's harnesses:** they were written after H8's registration and before its first trial (file times
  23:53–23:55), but hashed only with H8b's registration.
- **Full buffers:** a drain reached the daemon's 500-event limit 6 times.
  - **Outside any wait:** 4 were in H8 control trials, in the one drain after the 5 s late read, which covered more
    than 5 s of events.
  - **After an input:** 2 were in the replays of HuggingFace's model page, one in H8's replay and one in H8b's, where
    events may have been lost. Those waits ended after 1,649 ms and 208 ms, uncapped.
- **Scorers:** `h8_analyze.py` and `h8b_analyze.py` are not hashed. Each was written while its trials ran, after
  some progress lines had been seen. The independent recount, with its own code, matched every figure.
- **Q's rule:** the rule and its outcome are both in H8b's registered text. They were written after partial H8
  results had shown the two arms tied on those sites, and file times cannot show that the rule came first.

**How often this happens in real runs:** 1 false DONE in the 78 recorded run files (run 20260924-052252-e4b2). The
simulated Jev answers DONE after every read, so 24 of 50 is an upper bound under a fast Jev, not a rate.

**Leads for a later cycle.** None was registered, and none enters the design:

1. **The start page:** the same wait before a first answer on a freshly opened page. YouTube's first read after load
   was empty once in the probes.
2. **Signals the page reports:** `aria-busy` or a visible progress bar, as a second loading signal.
3. **A daemon of the executor's own:** so no other browser-harness client can drain the event buffer the gate reads
   (§4.7).

### H8c: wait while loading is visible, with no minimum wait

**Registered after H8b's results and the user's review of the design (2026-09-25), before any H8c trial.**

**Why:**

- **The user's rule,** 2026-09-25: "if we don't have a reliable way to tell if still loading using code, then we should
  let Jev decide."
- **H8b's gate waits at least 500 ms after the input.** That is a timing guess, not a signal.
- **What H8b's data shows about that minimum** (a second look, not registered):
  - **Today's false DONEs:** all 24 had a request in flight when accepted, so tracking alone would have caught each one.
  - **Google Flights, gate arm, at the first answer:**
    - the results request (`GetShop`) had not yet been seen in any of the 10 trials; it came 9–69 ms later;
    - loading was visible in 6, from a logging request (`/log`) and a script;
    - in 4, nothing was visible, and only the minimum held the answer. Without it, the first answer on Flights rests on
      those incidental requests or on the freshness check;
  - **Cost:** on the 29 replayed first steps, the minimum was most of the cost. The median wait was 195 ms with it and
    0 ms without, and 21 of the 29 would not wait at all.

**The change under test,** on the design's own code (§4, v3):

- **No minimum wait:** the wait ends at the first poll where no tracked request is in flight and none was sent or
  ended in the last 100 ms.
- **At every final answer:** it runs at every DONE or BLOCKED answer, not once per input, but never past 5 s after the
  last input. An answer later than that gets no wait, and the freshness check decides.
- **Everything else as v3:**
  - the tracked types, and the main frame found by the tab's target id;
  - Network enabled at the first input, and requests seen less than 5 s before an input carried across it;
  - drains before each input, after each read, every 20 ms while Jev decides, and during the wait;
  - the lost flag.

**Code under test:**

- **`h8c-code/build/jev_ultrafast/`:** the built package, copied into this folder before freezing. The trials run it:
  `H8C_BUILD` and `PYTHONPATH` point at `h8c-code/build`.
- **`h8c-code/design-h8c.diff`:** the same code as a diff against the repo's working tree of 2026-09-25. Applied to a
  copy of that tree, it reproduces the build byte for byte. It holds:
  - design v3 (`design-check/design-v3.diff`);
  - the change above;
  - their offline tests.
- **Checked before registration:** ruff, 136 tests, and 24 of 24 broken variants (`h8c-code/mutate_h8c.py`).
- **Pinned in every raw file:**
  - the sha256 of the build's `browser.py`, `agent.py` and `snapshot.js`;
  - the lab Chrome's version at the start and end of each series.
- **The scorer refuses** a raw file whose code hashes differ from those of the frozen copies in `registration-h8c.sha`.

**What is new about the harness:** H8b's trials used a separate prototype (`net_gate.py`). H8c's drive the design's
own `Browser`:

- every scripted step runs through its `act()`;
- the simulated Jev decides inside its `draining()`;
- the gate is its `wait_for_loading()`;
- the harness logs what the `Browser` drains. At each DONE, in both arms, it also reads the `Browser`'s tracking (one
  extra drain) to record whether loading was visible.

So H8c also tests live what the design review found untested: tracking from the first input, the drain thread, the
target id as the main frame's id, and D13's carry-over.

**Done before registering, and disclosed:**

- **The H8b analysis above.**
- **A procedure check of the harness on local pages** (`h8c_smoke.py`), with no registered site, run four times in
  labE. The outputs are `raw/h8c_smoke_labE-run1.json` to `-run3.json`, and `raw/h8c_smoke_labE.json` for run 4:
  - **today:** a false DONE in every run;
  - **gate:** waits of 924, 950, 936 and 949 ms, then a read with results;
  - **run 1:**
    - the scroll variant's reads lacked results: the page's 5 items sat above a 3000 px spacer, and a read lists only
      what is in view;
    - its scroll came after the loading had ended, so nothing was carried;
  - **between runs 1 and 2:**
    - `carried_at_done` was added;
    - a skipped replay wait was counted as 0 ms;
    - the scroll variant moved to a one-page search. That page is tall from the start, and its results arrive by a
      fetch that answers after 1.5 s;
  - **run 2:**
    - the fetch was carried across the scroll and was still loading at the next DONE;
    - the gate waited 1000 ms;
    - both reads still lacked results, because Chrome's scroll anchoring kept the view on the filler while the list
      was inserted above it;
  - **between runs 2 and 3:**
    - scroll anchoring was turned off on that local page;
    - test 4 was rescored as false DONEs, since a real site can also scroll its results out of view;
  - **run 3:** the same carry, a 993 ms wait, then a read with results;
  - **the replay:**
    - waits of 928, 917 and 940 ms in runs 1, 3 and 4;
    - the page starts its request on a 300 ms timer after the click, and the design first saw it 318 and 311 ms after
      the click returned (runs 1 and 3);
    - in run 2, the answer came at 302 ms, before any request was seen, so the gate waited 1 ms. This is the case
      H8b's minimum covered, and the case tests 1 and 2 must show to be rare or caught by the freshness check;
  - **run 4:** the final harness, run from `h8c-code/build`. The scroll variant carried the fetch; at the next DONE it
    was the only request loading. The gate waited 1003 ms, then accepted a read with results.
- **An independent review of this text and the harness, before freezing.** It found 4 blockers and 8 minor issues, and
  all were fixed before run 4. The blockers were:
  - labF's order could not be run;
  - a scroll error was scored;
  - the code hashes were not checked;
  - test 4 had no rule for fewer than 10 trials.
- **Chrome updated itself between H8b and H8c:** 153.0.8010.53 then, 154.0.8037.57 now.

**Unchanged from H8b:**

- **The simulated Jev:** DONE 275 ms after each read, up to 6 answers.
- **The sites:** H8b's five, with the same steps, results URLs, rules (H8b's YouTube rule included) and walls.

**Arms:**

- **today:** the freshness check alone;
- **gate:** the design's wait, then the freshness check.

Arms alternate within each site, and sites alternate. Each site and arm gets 10 scored trials, in at most 15 attempts.

**What is scored:**

- **Unscored and replaced:** a trial that shows a wall, or whose scripted steps fail before the search input.
- **Also unscored and replaced, in test 4:**
  - a trial in which no scroll runs;
  - any trial with an error, since it has no accepted read and so can never be a false DONE. Such errors are listed.
- **Scored as a trial without results, in tests 1 and 2:** any other failure, including an error from the design's
  code.
- **If a series stops:** it continues with `--resume`, which keeps its trials and attempt counts.
- **The scorer takes** one file of a kind per lab, and at most 10 scored trials per site and arm.

**Test 1, mechanism (today).**

- **False DONE:** the accepted read lacks results, and the late read, 5 s later, has them.
- **Passes if:** at least 5 occur across all sites, and in at least 90% of them the design's tracking saw loading at
  acceptance: a tracked request in flight, or one sent or ended in the last 100 ms.

**Test 2, fix (gate).**

- **Passes if:** the accepted read has results in at least 9 of 10 scored trials on every scored site.
- **A scored site** is one whose gate arm reached 10 scored trials. Google Flights must be scored, and at least 4 of
  the 5 sites.

**Test 3, cost.**

- **Replays:** H8's 29 first steps, on the design's `Browser`. Each gets the executor's read, the simulated answer,
  then one wait. A wait the design skips, because its input is 5 s old, counts as 0 ms.
- **Passes if:**
  - at least 20 replay;
  - the median wait is at most 500 ms;
  - at most 2 are capped;
  - in test 2, at most 1 trial per scored site has a capped wait.

**Test 4, D13 live (gate only; reported separately).**

- **What it runs:** on DuckDuckGo, the simulated Jev answers SCROLL_DOWN at each read that offers it, until one runs,
  then DONE. In H8b, DuckDuckGo's first answer was stale in 20 of 20 trials. So the first scroll will often be refused
  as stale, and run at a later read.
- **Passes if:** at most 1 of 10 scored trials is a false DONE: the accepted read lacks results, and the late read has
  them. A scroll can leave results out of view in both reads; those trials are reported, not failed.
- **Not tested if either:**
  - fewer than 10 trials are scored in 15 attempts;
  - fewer than 3 scored trials have both of these: a DONE after the scroll at which requests sent before the scroll
    were loading and none sent after it, and results in the late read.

  In the second case, D13 stays untested live on a real site.

**Verdict:**

- **H8c is verified if tests 1, 2 and 3 all pass.** The design then drops the minimum wait, and D9 becomes a 5 s
  limit per input.
- **Otherwise,** each gate trial in test 2 whose accepted read lacks results gets a cause, from its rounds:
  - **the minimum's case:** at the accepted DONE, no loading was visible, and the wait lasted under 50 ms;
  - **tracking's case:** loading was visible, events were lost, the wait was capped, or it ended before the results
    came;
  - **also:**
    - an error: from the browser (`RuntimeError`, `TimeoutError`, `StalePage`) or from code (any other);
    - no answer stood;
    - no results in either read;
    - a skipped wait (the input was 5 s old).
- **If no failure is in tracking's case or a code error,** the design keeps the 500 ms minimum: v3 as reviewed.
- **If any is,** v3's tracking is not verified live, and the design is revised before any plan.
- **Test 4:** if it fails, D13 is marked not verified live, and the design is revisited before any plan.

**Scoring:** `h8c_analyze.py`, hashed with this text. It reads only the raw files and `registration-h8c.sha`, and it
refuses to score:

- a raw file that ran other code than the frozen copies;
- more than one file of a kind per lab;
- more than 10 scored trials in any site and arm.

**Labs:**

- **labE:** Google Flights and crates.io. Its profile also ran the smoke checks.
- **labF:** DuckDuckGo and test 4 in one interleaved series, then the replays. A fresh throwaway profile.
- **labG:** YouTube and npm. A fresh throwaway profile.

**Reported, not gated:**

- waits per trial, and their length;
- answers per trial, by arm, with errored trials listed apart;
- first answers where loading was not yet visible;
- Google Flights: whether the results request (`GetShop`) was seen by the first answer;
- waits with lost events, and drains of 500 events or more;
- Chrome's version at the start and end of each series.

### Results (H8c)

**Registered text unchanged:** the block above is byte-identical to `registration-h8c.md` (sha256 `756e3747…`).
`registration-h8c.sha` hashed it at 18:18:40, with 27 other files:

- the code under test (`h8c-code/build/`);
- every harness, H8's and H8b's included;
- the scorer;
- the smoke outputs.

The series ran 18:18:55–18:23:37 on Chrome 154.0.8037.57 throughout.

**How it was checked:**

- **Raw data:** `raw/h8c_trials_lab{E,F,G}.json` and `raw/h8c_replay_labF.json`; the scorer's output is in
  `raw/h8c_analysis.txt`.
- **Independent recount:** an agent re-derived every test with its own code, and read the scorer only afterwards.
  All four tests and the verdict match. It found:
  - the scorer's Google Flights line wrong;
  - the registered failure causes overlapping.

  Both are under "Deviations" below.
- **A review of the design's evidence** found that D13's carry-over ran on Google Flights. It is below.
- **No replacements:** every site and arm got its 10 scored trials in 10 attempts, with no walls and no errors.

| Test | Result | Numbers |
| --- | --- | --- |
| 1, mechanism (today) | Passed | 19 false DONEs: Google Flights 6, DuckDuckGo 3, crates.io 10. Loading was visible at all 19, at 3 of them only through a request carried across the click (D13) |
| 2, fix (gate) | **Failed**, on YouTube | 10 of 10 on Google Flights, DuckDuckGo, crates.io and npm; YouTube 7 of 10 |
| 3, cost | Passed | 25 replays: median wait 0 ms, against 195 ms with H8b's minimum; 1 capped. No gate trial capped |
| 4, D13 live | Not tested | the scroll case never arose: a request was carried across the scroll in 1 of 10 trials, and was never still loading at a later DONE |
| Verdict | **Not verified** | By H8c's registration, the design keeps H8b's 500 ms minimum. H8d later replaced that consequence (below) |

**H8c, wait while loading is visible:**

- **YouTube failed on its results rule, not on the gate.**
  - **A sponsored video topped YouTube's results:** in 17 of 20 late reads in H8c's labG, against 0 of 20 in H8b's
    labF (another profile, Chrome 153). H8 had seen such ads too (above).
  - **In the 3 failing trials** (4, 5 and 9), a Shorts shelf followed it, at the bottom edge of the 780 px view.
    - A read lists only what is in view. Both reads counted at most 2 videos, one of them the sponsored video's own
      Watch button.
    - The read 5 s later held the same videos, so no wait could have changed them.
  - **The rule also counted the sponsored video:** 3 of the 7 passing gate trials reached 3 videos only with it.
  - **The gate itself worked on YouTube:** at every first answer, loading was visible, and the gate waited
    677–1326 ms.
  - **YouTube's today arm says nothing:** 9 of its 10 late reads lack results too.
- **Google Flights passed through D13's carry-over and the freshness check.**
  - **Flights sends its results request (`GetShoppingResults`) more than once:**
    - just before the search click, in 14 of 20 trials. The design drained it before the click, and carried it
      across (D13);
    - again after the click: 322–401 ms after it in 16 trials, and 40 ms after it in one. In the 3 today trials whose
      first answer stood at about 320 ms, the next one was first seen in the late read's drain, 5.4 s later,
      already finished: nothing drained in between.
  - **At the gate's 10 first answers:**
    - 6 saw only the request carried from before the click, and waited for it;
    - 2 saw the second request;
    - 2 (trials 4 and 5) saw nothing. That is the minimum's case, and the freshness check caught both: the page had
      changed, so both answers went stale. The next answers waited 362 and 416 ms, went stale again, and the third
      answers were accepted.
  - **The freshness check alone is no guarantee.** In the today arm, 7 first answers came when the design had
    drained nothing, or only a carried request. The freshness check let 3 of them stand (trials 6, 7 and 9), all
    false DONEs:
    - **all 3** had the carried request in flight, which the gate waits for;
    - **the 3 first answers with nothing at all in flight** (today trial 3, gate trials 4 and 5) went stale.
  - **So without D13, test 1 would have failed:** 16 of 19 false DONEs visible (84%). The gate's 6 carried-only
    first answers would have been the minimum's case too.
- **First gate answers went stale in 60 of 60 trials,** tests 2 and 4 together:
  - **in 48,** the first answer waited 158 ms or more;
  - **in 12** (npm 10, Google Flights 2), nothing was loading, and the page had changed anyway;
  - **today's arm also answered again:** a mean of 2.30 answers per trial, against 2.12 with the gate. So the gate
    added no answers on net.
- **The cost fell to almost nothing:**
  - **On the replays:** 15 of 25 waited 0 ms, and 2 waited 1 ms.
  - **The capped replay** (`forms-date-duration`, 4704 ms) had 12 requests in flight when it answered.
  - **Per site,** the gate's median total wait per trial was 691 ms on Google Flights, 425 ms on DuckDuckGo, 165 ms
    on crates.io, 1071 ms on YouTube, and 0 ms on npm. npm's results arrive with the page, so nothing was loading.
- **Test 4 did not reach the scroll case.**
  - **In 10 of 10 trials,** the first read offered no scroll, so the first answer was DONE.
  - **Its wait** (335–1558 ms) outlasted the loading, so the scroll ran on a loaded page.
  - **A request was carried across the scroll** in 1 trial. It was never still loading at a later DONE, and no other
    request was either.
  - **The registration's expectation,** that the first scroll would often be refused as stale, came true once.
  - **So the scroll case stays tested offline only.** The carry-over itself ran on Google Flights (above).
- **Clean otherwise:**
  - no lost events;
  - no drain of 500 events (the largest held 315);
  - no capped wait in any trial, and no skipped wait.
- **The today arm often accepted the first answer:**
  - on Google Flights, 3 times on a page that had not yet reached its results URL;
  - on crates.io, in 9 of 10 trials. All 10 of crates.io's today trials were false DONEs.

**Deviations, none changing a verdict:**

- **The scorer's Google Flights line is wrong.** It counted requests whose path ends `/GetShop`: the name of the
  results request as H8b's prototype recorded it, cut to 80 characters. H8c's harness keeps full paths, which end
  `/GetShoppingResults`, so its "0 of 20" counted nothing. By the time Jev first answered, the design had
  drained one sent after the click in 4 of 20 trials, and one carried from before it in 14.
- **The registered failure causes overlap.** The registration lists them without an order.
  - **The 3 YouTube failures** meet "no results in either read", and also the minimum's case: no loading visible, and
    a 0–1 ms wait at the accepted answer, since the page had finished loading.
  - **The scorer checks** "no results in either read" first.
  - **The fallback is the same either way:** no failure was in tracking's case or a code error.
- **The replay harness does not retry a page that changed before the input,** as in H8 and H8b. That cost 4 replays
  (25 of 29), still above the registered 20. The trials' scripted steps do retry, and did so in 28 trials.

### H8d: H8c's YouTube trials again, in a taller view

**Registered after H8c's results (2026-09-25), before any H8d trial.** H8c's registered verdict, not verified, stands.
This registration does not change it.

**Why:**

- **H8c's test 2 failed only on YouTube:** the gate's accepted read had results in 7 of 10 trials. In the other 3,
  neither the accepted read nor the late read, 5 s later, had results.
- **What H8c's data shows** (a diagnosis after the results, not registered):
  - **A sponsored video topped YouTube's results:** in 17 of 20 late reads in H8c's labG, against 0 of 20 in H8b's
    labF. That comparison mixes the date with the lab (another profile, and Chrome 153 then). All 12 late reads
    without results show the ad.
  - **What followed the ad in those 12:**
    - a Shorts shelf at the bottom edge of the 780 px view, in the 3 failing gate trials and today trials 2–4;
    - one long result whose chapter list filled the view, in today trials 5–10.
  - **Why the results didn't count:** a read lists only what is in view. Those reads counted at most 2 videos, one of
    them the sponsored video's own Watch button, and H8b's rule needs 3.
  - **The minimum played no part:** at every gate trial's first answer, loading was visible, and the gate waited
    677–1326 ms.
- **What this leaves untested:** H8c's change passed test 2 on the four other sites. On YouTube, the measure failed
  rather than the gate, so the gate is untested there.

**The change: a 1600 px tall view, for YouTube only.**

- **How** (`h8d_trials.py`): the design's `Browser` sets its view once, 1120 x 780 at a pixel ratio of 1, before it
  first navigates (`browser.py` line 76). H8d makes that same call 1600 px tall, so the start page already loads in it.
- **Checked on every tab:** a tab whose width, height or pixel ratio differs is closed. The trial fails before the
  search, and is replaced.
- **Recorded:** every read summary in the raw file records the view it was read in.

**Unchanged from H8c:**

- **The code and harness:** H8c's frozen harness (`h8c_trials.py`) and code (`h8c-code/build`). `h8d_trials.py` only
  swaps in the taller `Browser`, the read summary with its view, and a separate output folder, `raw/h8d/`.
- **The trial procedure:**
  - YouTube's steps, and H8b's YouTube rule;
  - the simulated Jev: DONE 275 ms after each read, up to 6 answers;
  - the arms, today and gate, alternating;
  - 10 scored trials per arm, in at most 15 attempts;
  - H8c's rules for walls and errors, from its tests 1 and 2.
- **The lab:** labG, the same Chrome process (154.0.8037.57) and profile. It has already run H8c's YouTube and npm
  trials, 20 identical YouTube searches among them, 17 of which showed the same ad.

**Test.**

- **H8d is verified if:**
  - the gate's accepted read has results in at least 9 of 10 scored trials;
  - and at most 1 gate trial has a capped wait. This is H8c's test-3 condition, applied to YouTube's new test-2 trials.
- **Not tested if:** fewer than 10 gate trials are scored in 15 attempts. The design then keeps the 500 ms minimum.
- **Not verified otherwise.** Each gate trial whose accepted read lacks results gets H8c's causes. They are checked in
  this order, so that each trial gets one:
  1. an error: from the browser (`RuntimeError`, `TimeoutError`, `StalePage`), or from code (any other);
  2. no answer stood;
  3. no results in either read;
  4. a skipped wait (the input was 5 s old);
  5. the minimum's case: no loading visible at the accepted DONE, and a wait under 50 ms;
  6. tracking's case: anything else.

  **Then:**
  - any failure in tracking's case, or a code error: v3's tracking is not verified live, and the design is revised
    before any plan, as H8c's registration says;
  - otherwise: the design keeps the 500 ms minimum.

**What follows if H8d is verified (decided now):**

- **H8c's own verdict stays not verified.**
- **The design drops the minimum** as a design decision, resting on:
  - H8c's tests 1 and 3;
  - H8c's test 2 on four sites;
  - H8d on YouTube;
  - the pooled test 1 below.
- **Pooled test 1:** H8d's today false DONEs join H8c's 19. Loading must still have been visible at acceptance in at
  least 90% of them. Below that, the design keeps the minimum.

**Risks, stated before running:**

- **Stale answers:** the freshness check compares everything in view, and a taller view shows more. On YouTube:
  - every first answer was already stale in H8c;
  - 4 of 10 gate second answers were stale too;
  - the ad's captions and countdown change every second.

  So more answers may go stale, and "no answer stood" counts as a gate failure though it has nothing to do with
  loading.
- **The ad's playback holds the wait open:** player and ad requests follow the ad, not the results. In H8c's gate
  trials, the first decision came 366–805 ms after the search request ended in the 7 trials showing the ad. In the 3
  without it, it came 131–147 ms after.
- **The same profile ran 20 searches:** YouTube may show more, fewer or other ads.

**Reported, not gated:**

- **today:** false DONEs, and whether loading was visible when each was accepted;
- **both arms:**
  - answers per trial, and stale answers per trial;
  - waits per trial, and caps;
  - first answers where loading was not yet visible;
  - late reads with results;
  - late reads that show a sponsored video;
- **gate, per trial:**
  - whether the search request (`/youtubei/v1/search`) was loading at the first answer;
  - whether player requests (`/videoplayback`, `/youtubei/v1/player`, `/api/timedtext`, `/api/stats`) were sent
    before the first answer's decision;
  - its waits, and the accepted round;
  - the failure causes above.

**Done before registering, and disclosed:**

- **H8d is a second attempt, at the one site that failed.** It was designed after H8c's results and changes the measure
  after seeing why it failed. The four passing sites are not re-run at 1600 px.
- **A procedure check on a local page** (`h8d_smoke.py`), with no registered site, was run three times in labG. In
  each, today gave a false DONE, and the gate waited, then accepted the results, which sat below a 1200 px header:
  - **run 1** (`raw/h8d/h8d_smoke_labG-run1.json`): at a pixel ratio of 2, because an override made after the tab
    opened, with a scale factor of 0, took the screen's;
  - **run 2** (`-run2.json`): 1120 x 1600 at a ratio of 1, from the same override made after the start page loaded;
  - **run 3** (`raw/h8d/h8d_smoke_labG.json`): the final wrapper. Every read records 1120 x 1600, the screenshots are
    1120 x 1600, and the gate waited 962 ms.
- **An independent review of this text and the harness, before freezing.** It found 2 blockers and 6 minor issues, and
  all were fixed before run 3. The blockers:
  - the verdict dropped H8c's cap condition and its "revise the design" fallback;
  - the scorer depended on hashes the text did not name.
- **An independent recount of H8c** matched every test and its verdict.
- **No YouTube page** was opened in the taller view before registering.

**Scoring:** `h8d_analyze.py`. It reads only three things:

- the raw file `raw/h8d/h8c_trials_labG.json`;
- H8c's today trials, for the pooled test 1;
- `registration-h8d.sha`.

**It refuses:**

- a raw file that ran other code than H8c's frozen copies;
- a file that is not labG's YouTube series;
- more than 10 scored trials in an arm;
- a read taken in any other view than 1120 x 1600.

**Hashed in `registration-h8d.sha`:**

- **H8d's files:**
  - this text;
  - `h8d_trials.py`, `h8d_analyze.py` and `h8d_smoke.py`;
  - the three smoke outputs;
- **what it runs of H8c's:**
  - the 12 files of `h8c-code/build`, whose `browser.py`, `agent.py` and `snapshot.js` the scorer checks against;
  - `h8c_common.py` and `h8c_trials.py`;
  - `h8_common.py`, `h8_trials.py` and `h8b_trials.py`;
  - `registration-h8c.sha`.

### Results (H8d)

**Registered text unchanged:** the block above is byte-identical to `registration-h8d.md` (sha256 `03694f80…`).
`registration-h8d.sha` hashed it at 19:02:01, with 24 other files:

- H8d's scripts;
- the three smoke outputs;
- everything of H8c's that H8d runs.

The series ran 19:02:06–19:04:29 on the same Chrome 154.0.8037.57.

**How it was checked:**

- **Raw data:** `raw/h8d/h8c_trials_labG.json`; the scorer's output is in `raw/h8d/h8d_analysis.txt`.
- **Independent recount:** an agent re-derived the test and the pooled test 1 with its own code, and read the scorer
  only afterwards. Every count matches. It found that most of the reads the scorer counts as "showing a sponsored
  video" show ad cards instead. That is below.
- **No replacements:** both arms got their 10 scored trials in 10 attempts, with no walls and no errors. All 40 reads
  were taken in a 1120 x 1600 view, and all 20 late screenshots are 1120 x 1600.

| Test | Result | Numbers |
| --- | --- | --- |
| Gate on YouTube | Passed | 10 of 10 accepted reads with results; none capped |
| Pooled test 1 | Passed | loading was visible at all 27 false DONEs: H8c's 19 and H8d's 8 |
| Verdict | **Verified** | By H8d's registration, the design drops the minimum. H8c's own verdict stays not verified |

**H8d, YouTube in a taller view:**

- **The gate worked on YouTube:**
  - the search request (`/youtubei/v1/search`) was loading at every first answer, and the gate waited 369–1638 ms;
  - every later wait took 0–1 ms;
  - the median total wait per trial was 503 ms.
- **Today's check failed as it did elsewhere:** 8 false DONEs in 10 trials. At each, the search request was still in
  flight, so loading was visible at all 8.
- **H8c's failing case barely came back,** so H8d does not show that the taller view fixed the measure:
  - **the sponsored video** showed in 1 of 20 late reads (gate trial 1), against 17 of 20 in H8c. 3 others showed
    sponsored cards lower in the list;
  - **neither of H8c's failing layouts,** a Shorts shelf or a long chapter list after the ad, appears in any H8d
    screenshot;
  - **so these pages would probably have passed at 780 px too.** H8d supports the gate on YouTube without the ad. The
    one trial with the ad passed, with the longest first wait, 1638 ms, while the ad's player requests ran.
- **The gated answer stood third on YouTube:**
  - **gate:** in 9 of 10 trials, the first two answers went stale and the third stood. The second went stale with
    nothing tracked loading (waits of 0–1 ms): its read already held the results, but they kept changing;
  - **today:** 8 of 10 trials accepted the second answer, and all 8 were false DONEs;
  - **it tracks the ad, not the view:** across H8c and H8d, gate trials without the ad in the late read took 3 answers
    in 12 of 12; those with it, in 1 of 8. With the ad, the first wait ran on while it played, and the results had
    settled by the next answer;
  - **in real runs,** each stale answer costs one more Jev call, about 0.3 s: here two more than a first answer, and
    one more than today's.

**Deviations, none changing the verdict:**

- **The pooled test 1 reads H8c's raw trial files by name pattern,** and `registration-h8d.sha` does not hash them.
  They were last written at 18:22–18:23, before H8d was registered at 19:02, and the recount reproduces their 19
  false DONEs.
- **The scorer's verdict line** leaves the pooled test 1 out of its list of grounds, although its code requires it.

## 4. Design: wait for loading before a final answer (H8b to H8d)

**Status:** v4.2, approved on your behalf on 2026-09-29 (plan P25 in `docs/executor-improvements-plan.md`). Nothing is
implemented. v4 drops v3's 500 ms minimum wait, and waits at every final answer, not once per input (D9). It follows
the user's rule (§4.1), and a rule H8d registered after H8c's result (§3). v4.1 is the code H8c and H8d ran (v4),
plus two fixes from its review (§4.6). v4.2 adds one guard to v4.1's code, and three tests (§4.6).

**Scope:** the loading gate H8b verified, without its minimum wait, as H8c and H8d tested it (§3).

- **What the evidence covers:** DONE answers from a simulated fast Jev (275 ms after each read) on five search sites,
  with this section's own code.
- **What it rests on:**
  - **H8c's registered verdict is not verified,** and its registration kept the minimum on that result. Its test 2
    failed on YouTube, where the results rule could not see results that had loaded.
  - **H8d's registration,** written after H8c's results, replaced that consequence: had H8d failed its criterion, the
    design would have kept the minimum (`registration-h8d.md`). With H8d verified, the design drops the minimum on:
    - H8c's tests 1 and 3;
    - H8c's test 2 on the four other sites;
    - H8d on YouTube;
    - the pooled test 1.
  - **What H8d shows:** the sponsored video showed in 1 of its 20 late reads, against 17 of 20 in H8c. So H8d shows
    the gate working on YouTube without the ad, not that the taller view fixed the measure.
  - **Where the minimum's case arose:** only on Google Flights, at 2 of the gate's 10 first answers, and the freshness
    check caught both. At 6 others, a request carried from before the click (D13) held the answer. §4.7 has the risk
    that remains.
- **What it does not cover:** BLOCKED answers take the same code path, but no trial had one. Keeping them is the
  user's decision (D6).
- **With §2:** together with H5's repeated read, it makes up the executor's page-readiness protocol (§4.1).
- **The first automatic review's proposal** (2026-09-29) asked to wait for results before DONE, by polling the page
  read until it is stable. That is H3's wait for the DOM to go quiet, which failed (§4.8); this wait follows the
  requests instead.
- **Out of scope:** §4.7 lists what stays out.

**Review:**

- **Cycle 1:** a QA recount of both verdicts, and three reviewers: correctness and safety, evidence and scope, and
  simplicity and testability. All approved with fixes.
  - **The one blocker:** v1 did not drain the event buffer while Jev decides, on a false claim that it never
    filled. Fixed by D12.
  - **Two bugs:** a later input hid an earlier one's loading (fixed by D13), and a later goal waited on an old
    input (fixed by D9's age limit).
  - **Also fixed:** the wait's two exits merged into one; tests added for broken variants the others missed; the
    live check made to fail when it cannot test; scope and evidence claims corrected here and in §3.
- **Cycle 2:** two reviewers: code and concurrency, and evidence and docs. Both approved with fixes, with no
  blocker.
  - **The drain thread is sound:** no races. `join()` is bounded by browser-harness's 5 s timeouts.
  - **Four gaps in the tests** let broken variants pass, one of them the cycle-1 blocker back. Tests 6, 7, 10 and
    15 now catch them.
  - **Three design changes:**
    - tracking starts at the first input, since v2 could hold a first answer on the start page's own requests;
    - the drain thread runs in every decision, as the prototype drained every round;
    - `lost` covers every drain since the last recorded wait.
  - **The numbers:** every new or changed one was re-derived from the raw data, and all were confirmed.
- **Cycle 3:** one verifier rebuilt v3 from the saved diff. Its verdict: ready for the user's review.
  - **What it confirmed:** 135 tests, ruff, and 20 of 20 broken variants caught, with no test reaching a real
    daemon. Every code block in §4.4 and §4.6 matched the tested code.
  - **Fixes applied:**
    - D13 and §4.3 wrongly said the prototype started tracking at the first input. It discarded every
      request before the search, the last input, so the carry-over of earlier steps' requests is untested live
      (until H8c ran it on Google Flights, §3);
    - a drain that failed in the thread could lose events unrecorded. It now sets `lost` (test 16);
    - every undrained window is now listed, and one code comment no longer claims the buffer cannot fill.
  - **After the fixes:** 136 tests and 21 of 21 broken variants caught.
- **v4, after H8c and H8d:** a QA recount of each, and two reviewers: code and tests, and evidence and claims.
  - **Code and tests:**
    - **A bug:** a first input stopped before it ran carried the start page's requests into the next. Fixed in v4.1,
      with test 23.
    - **Unrecorded losses:** a drain that failed in a read lost events without a record. Fixed, with test 24.
    - **Gaps in the tests:** 12 of the reviewer's own broken variants passed. Tests 17–22 now kill 9, v4's main
      behaviour among them.
    - **Wording:** the wait stops polling 5 s after the input, and a drain in progress can overrun that.
  - **Evidence:**
    - **D13 ran live:** its carry-over ran on Google Flights, and test 1 would have failed without it. §4 now says so,
      and §4.7 states the risk v4 takes.
    - **Where the rule came from:** the rule to drop the minimum came from H8d's registration, not H8c's.
    - **Scope:** H8d's pass rests on pages without the ad.
    - **YouTube's extra answer:** it tracks the ad, not the wait or the view.
  - **After the fixes:** 144 tests, ruff, and 34 of 34 broken variants caught.
  - **A final verifier:**
    - **What it confirmed:** the fixes, with its own rebuild (34 of 34).
    - **What it corrected:**
      - a drain time read as a send time;
      - five re-anchored variants, not four;
      - "no guarantee" evidence that belonged to a carried request, so §4.7's risk is now marked as inferred, not
        observed.
- **v4.2, on 2026-09-29:** an independent review against commit `8953b45`, the code built since, and calvin in report
  mode over both halves.
  - **The review:** approve with fixes, with no blocker, 7 should-fix and 5 nits
    (`artifacts/page-readiness-implementation/review-design.md`). All are applied here, and its S6 cut §2's dialog
    check.
  - **Calvin's 24 questions:** answered in `artifacts/page-readiness-implementation/calvin-design-close.md`.
  - **The code is v4.1's, plus one guard:** `observe()` drains only once tracking has started (N1). The diff was
    rechecked at `8953b45` (§4.6).
  - **Three tests added:** 25 and 26, for the two rows of §4.5 no test covered, and 27, for the guard.
  - **The text clarified:** how a failed drain ends a read, what "sent" measures, the one margin code adds, and how
    §2's repeats meet the wait's cap.

**Decisions made on your behalf.** Each has a comment where it lives in the code, so it can be changed there. The
comments for D6, D7 and D8, D10 and D12 name this section; those for D9, D11, D13 and D14 name their number, on the
lines they govern (§4.4). Numbering continues from §2's D1–D5.

| # | Decision | Why | Where to change it |
| --- | --- | --- | --- |
| D6 | Wait only when Jev answers **DONE or BLOCKED**, not after every input | A wait after every input (H8) failed on Google Flights: in H8b's trials, the page's first request was seen 194–422 ms after the click, long after H8's wait had ended. A final answer is also the one decision a later step cannot undo. BLOCKED is included untested, by the user's decision (2026-09-25); it takes the same path | the `if selected in {"DONE", "BLOCKED"}` branch of `Agent.command("act")` |
| D7 | Wait while a content request is in flight, until **100 ms** of quiet, and stops polling **5 s** after the last input. **No minimum wait** | The user's rule (§4.1): code waits only while it sees loading. H8b's 500 ms minimum was a timing margin, not a signal. Without it, H8c's and H8d's gate caught every false DONE. On Google Flights, a request carried from before the click (D13) held 6 of the gate's 10 first answers, and the freshness check caught the 2 that saw no loading. The replays' median wait fell from 195 ms to 0 ms (§3). §4.7 has the risk that remains. 100 ms of quiet matched 500 ms on DuckDuckGo, crates.io and npm (30 of 30 each), the sites H8b's rule for Q named. The cap bounds a page that never goes quiet | `LOADING_QUIET_MS` and `LOADING_CAP_SECONDS` in `jev_ultrafast/browser.py`. The cap also sets D13's carry-over window, on purpose: a request older than the cap could not hold a wait anyway |
| D8 | Count only **Document (main frame), XHR, Fetch and Script** requests | These bring a page its content; images, fonts and media do not change what a read shows. A cross-site iframe's document never reports its end on the tab's session (H8's capped replays) | `LOADING_TYPES`, and the frame test in `Browser._track()` |
| D9 | Wait at **every** DONE or BLOCKED answer while loading is visible, until **5 s after the last input**, when it stops polling. A WAIT step is not an input | Waiting at every answer, not once per input, replaces the minimum: a page that starts loading after one answer is waited for at the next, when there is one (H8c); an answer that stands before any loading starts is §4.7's risk. The deadline bounds the cost: a page that never goes quiet costs at most 5 s per input, however many answers follow. It also keeps a later goal's first answer from waiting on an old input. A drain in progress at the deadline can run past it, by up to browser-harness's 5 s reply timeout | `Browser.act()`, and the first lines and the loop's cap test in `Browser.wait_for_loading()` |
| D10 | Record each wait as `[ms, capped, lost]` in the run file's `loading_waits`; `lost` means that since the first input or the last recorded wait, a drain came back full, or one failed. A full buffer between goals counts too: a long idle gap can fill it, so a goal's first wait may report a loss that no input of its own could suffer. A wait a stop interrupts is not recorded, and its `lost` carries into the next wait. `scripts/report_runs.py` counts the waited ms, caps and losses. Claude's result text does not change | The only sign code has, outside the test pages, that the wait fires, caps or loses events; another client's drain leaves none (§4.5). It mirrors D5 | `_fresh_state` in `agent.py`; the `totals` in `report_runs.py` |
| D11 | The wait **checks the run's stop condition** every poll | A cancellation, the run's time budget or a server shutdown ends the wait, as they end §2's repeats | the `stop=` argument in `Agent.command("act")` |
| D12 | While Jev decides, from the first input on, a **background thread drains** the daemon's event buffer every 20 ms | The buffer keeps only the last 500 events. In H8, drains covering 5 s after a search held 400 or more in 11 of 50 trials, and 500 in 4. H8b's prototype drained every 20 ms while its simulated Jev decided, in every round; this keeps that cadence | `Browser.draining()`, used around `choose()` in `Agent.command("predict")` |
| D13 | After a new input, requests **seen less than 5 s before it are still waited for**. Tracking starts at the first input, when the browser enables the Network domain. Nothing is carried into the first input that runs, so the start page's own requests are never waited for, even after a first input stopped before it ran (v4.1) | Search, then scroll, then DONE: without it, the scroll would clear the search's request, and the wait would miss the results still loading (cycle-1 review). Starting at the first input keeps the start page's own requests out, as the prototype did (cycle-2 review). **Ran live on Google Flights, not in the scroll case:** a results request sent just before the search click was carried across it. It was the only loading seen at 6 of the gate's 10 first answers there, and at 3 of the 27 false DONEs; without it, test 1 would have failed (§3). H8c's test 4 never reached a scroll during loading. Offline test 8 covers the rule, and the live check's scroll line will cover the scroll case on a local page (§4.6) | the `self.loading = {...}` line, and the first-input `Network.enable`, in `Browser.act()` |
| D14 | Before the first input, a read **does not drain** the daemon's buffer (v4.2) | Nothing is tracked yet, so that drain did nothing for the wait. It emptied the buffer other clients of the daemon share, and a drain that failed there threw away a good read: the start page's, or `finish()`'s in a run with no input (review N1). Test 27 pins it | the `if self.network:` guard in `Browser.observe()` |

### 4.1 One protocol, with §2

Code decides whether the page is ready. Jev decides what a ready page means.

**The user's rule** (2026-09-25): "if we don't have a reliable way to tell if still loading using code, then we should
let Jev decide." So code waits only while it sees loading, never on a timing guess. Where it sees none, the answer is
Jev's.

| The page | How code knows | What code does | Where |
| --- | --- | --- | --- |
| A read times out after a step: its main thread is busy | `TimeoutError` | reads again, at most 2 more times (§2, H5) | `agent.py` |
| Jev answers DONE or BLOCKED while the page still loads what recent inputs started | a content request in flight, or one seen to start or end in the last 100 ms | waits, at every such answer, until 5 s after the last input (this section; H8b to H8d) | `browser.py`, called from `agent.py` |
| It changed since the read Jev answered on | the read's marker (URL, title, text, controls) differs | the answer is stale: a new read, and Jev answers again (existing) | `agent.py` |
| An input's target moved, changed or is covered | the freshness check and hit-test before the input (existing) | nothing runs; a new read (existing) | `browser.py` |
| Code cannot tell | a page that has not started loading when Jev answers; or whose requests a full buffer dropped | treated as loaded: the freshness check decides. If the page has changed, Jev answers again on what it now shows, and that answer waits if loading has started | — |

**Never, in any row:**

- **Repeat an input.** AGENTS.md: "Never retry a browser mutation."
- **Reload the page.** None of the 897 recorded reads shows a failed load, and none of the 78 runs stopped on one (§3).

**So, "still loading, or did the step fail?"** The browser has no single loading status. In H8b's trials, Google
Flights' first request was seen 194–422 ms after its Search click, and only then did it load its results. H8b's
prototype discarded events from before the click. H8c's code kept them, and saw a results request sent just before
the click in 14 of 20 trials (D13). So code waits out the loading it can see, at every final answer. Its one margin is
D7's 100 ms of quiet after the last request it saw start or end, since a follow-up request often starts within
milliseconds; with no loading seen, there is no wait at all. Then:

- **If the page matches the read Jev answered on,** the answer stands.
- **If the page changed,** Jev answers again on what it now shows.

**Where §2 meets this wait:** a read that times out after a step takes 5 s, so after §2's repeated read the input's
5 s have passed, and the next final answer does not wait; the freshness check decides (§4.5, §4.7).

### 4.2 The problem in the code

- **DONE and BLOCKED already check freshness.** `Agent.command("act")` accepts either answer only once
  `browser.fresh(page)` holds: the page must still match the read Jev answered on (`agent.py` lines 156–162). The
  marker includes the page's URL, title, text and controls.
- **A page still loading has not changed yet.** Run 20260924-052252-e4b2: Jev answered DONE 604 ms after the Search
  click, on a read taken 88 ms after it, while the flights were still loading. Its screenshot shows the blue progress
  bar and an empty list, and the run ended `done`.
- **Under a fast Jev it is common:** in H8b, today's check accepted 24 of 50 such answers before the results loaded,
  each with a request still in flight (§3). In H8c and H8d it accepted 27 of 60, and loading was visible at all 27.
  - **An upper bound:** that simulated Jev answered DONE after every read, at 275 ms.
  - **In real runs:** 3 of the 76 public runs of 2026-09-24 ended DONE before their results rendered
    (`possible_false_dones()`, `docs/failure-review.md`). One is 052252-e4b2, above. The first automatic review, on
    2026-09-29, flagged the other two on its own: DuckDuckGo `20260924-100333-757e` and crates.io
    `20260924-111852-243b`, both in §1's H3. e4b2 was labelled failed; the other two passed, by Claude alone, so
    only the false-DONE flag queued them. Each final DONE came 307–815 ms after its last step, inside D9's 5 s.
- **What will show it works:** the report's loading totals show the wait firing; its "possible false DONEs" line, and
  the reviews' label flags, show whether early DONEs stop.

### 4.3 The change

When Jev answers DONE or BLOCKED after an input, the agent first asks the browser to wait for what recent inputs
started to finish loading. Then the existing freshness check runs, unchanged.

**How the browser knows:**

- **The events are already there:** the browser-harness daemon records every CDP event, including this tab's. The tab
  only needs `Network.enable`, which the browser calls at the first input.
- **When the browser drains them:** from the first input on, after every read, before each input, every 20 ms while
  Jev decides, and during the wait. Before the first input, reads leave the buffer alone (v4.2): nothing is tracked
  yet, and the buffer is every client's.
- **What it does not drain:** the input itself; the settle and the read after it, including §2's repeated reads, up
  to about 15 s on a busy page; a TYPE_TEXT's text call; and the gaps between the inspector's step-mode buttons. A
  full drain after any of them, or a drain that fails in a read or while Jev decides, is recorded as `lost` in
  the next wait. A drain that fails in a read also fails that read: the run goes on only when §2 repeats it, a
  timeout in the read after a step, or when it is `finish()`'s read, which never stops a run.
- **What it follows:** from the first input on, the content requests seen in the 5 s before each input and since.

**Why it fits the loop:**

- **Responsibilities stay where they are:** the browser owns the daemon's events, and the agent owns when to wait.
- **The invariants hold:** no input repeats and no model call, and a stale answer takes the existing path.
- **Stop checks keep one path:** they run through `before_input`, as §2's repeats do.

**How it was tested live:** H8c and H8d ran this code itself, where H8b ran a prototype (`net_gate.py`):

- **The harness drove this code:**
  - every scripted step went through its `act()`;
  - the simulated Jev decided inside its `draining()`;
  - its `wait_for_loading()` was the gate.
- **Covered live:**
  - the drain thread;
  - the tab's target id as the main frame's id;
  - tracking from the first input;
  - D13's carry-over, on Google Flights: a results request sent before the search click. The scroll case was not
    reached.
- **Not covered live:** the stop check (D11), the lost flag (D10) and the daemon error message. Offline tests cover
  them (§4.6), and the live check's scroll line will cover D13's scroll case on a local page.
- **v4.1 differs from the code they ran** by two fixes from its review (§4.6):
  - nothing is carried into the first input that runs;
  - a drain that fails in a read marks the loss.

  Offline tests 23 and 24 cover them; neither ran live.

### 4.4 Code

`jev_ultrafast/browser.py`: two standard-library imports (`contextlib` and `threading`), one more name from
browser-harness, three constant lines, three lines in `__init__`, a drain after each read, a few lines around each
input, and three methods.

```python
from browser_harness.helpers import cdp, drain_events
```

§2 imports `_send` from the same module; the combined line is `from browser_harness.helpers import _send, cdp,
drain_events`, which passes ruff's import-order check.

```python
# Delegated decisions D7 and D8 (docs/executor-improvements.md §4): before a DONE or BLOCKED answer stands, wait
# while a content request of recent inputs is in flight, or was sent or ended in the last LOADING_QUIET_MS, and stop
# polling LOADING_CAP_SECONDS after the last input. No minimum wait: where code sees no loading, Jev decides (H8c).
LOADING_QUIET_MS, LOADING_CAP_SECONDS = 100, 5
LOADING_TYPES = {"Document", "XHR", "Fetch", "Script"}  # the requests that bring content; images and fonts do not
DAEMON_EVENTS = 500  # browser-harness 0.1.13 keeps its last 500 events (daemon.py BUF); a drain this long lost some
```

The comment cites H8c, whose trials ran this code without a minimum; the rule to drop it came from H8d's
registration (§3). The code keeps its tested comment.

In `__init__`, after `self.call("Page.enable")`:

```python
            # The loading wait (§4) follows this tab's requests through the daemon's buffer of CDP events, from the
            # first input on: the start page's own requests belong to no input, as in H8b's prototype.
            self.network, self.loading, self.last_request, self.input_done, self.lost = False, {}, None, None, False
```

`observe()`: the read loop drains once the read has succeeded, from the first input on. v4.2 adds the guard: before
the first input the drain was inert, since nothing is tracked yet (D14).

```python
        for attempt in range(10):
            try:
                page = browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot}
                )
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
            else:
                if self.network:  # D14: before the first input nothing is tracked; leave the shared buffer alone
                    self._track()  # the settle's and the read's events, taken in before Jev answers
                return page
        raise StalePage("Page did not settle")
```

`act()`: take in the events so far before an input, enabling the Network domain at the first one, then start the new
input's tracking once it has run. An input stopped before it runs (a covered target raises `StalePage`) keeps the
last input's tracking.

```python
    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(0.1)
        else:
            self._track()  # events so far belong to earlier inputs; this input's arrive after it
            if not self.network:  # the first input: from here on, Network events report this tab's requests
                self.call("Network.enable")
                self.network, self.lost = True, False  # nothing of this tab's could be lost before
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text})
        self.after_input = action if action["kind"] != "wait" else None
        if self.after_input:  # D9: a wait step runs nothing in the page, so it is not an input
            now = time.monotonic()
            # D13: requests seen in the last LOADING_CAP_SECONDS may still bring an earlier input's result. Before
            # the first input that runs there is none, so the start page's own requests are never carried.
            self.loading = {request: sent for request, sent in self.loading.items()
                            if self.input_done is not None and now - sent < LOADING_CAP_SECONDS}
            self.last_request, self.input_done = None, now
        return result
```

The three methods, before `close()`:

```python
    def _track(self):
        """Follow this tab's content requests through the daemon's buffer of CDP events (§4)."""
        # ponytail: the daemon keeps one buffer for all its clients, and drain_events() empties it for all of them.
        # Another client's drain can hide requests from this wait (it then ends as it would have before §4) or their
        # ends (it waits out its cap), and this one empties theirs. A daemon of the executor's own is the upgrade.
        try:
            events = drain_events()
        except Exception as error:
            self.lost = True  # the daemon may have emptied its buffer before the reply failed (D10)
            if isinstance(error, KeyError):  # browser-harness returns {} when the daemon closes without replying
                raise RuntimeError("The browser daemon closed the connection.") from None
            raise
        self.lost = self.lost or len(events) >= DAEMON_EVENTS
        now = time.monotonic()
        for event in events:
            params = event.get("params") or {}
            if event.get("session_id") != self.session:
                continue
            if event.get("method") == "Network.requestWillBeSent" and params.get("type") in LOADING_TYPES:
                # D8: a cross-site iframe's document ends on the iframe's own session, never here. A tab's target id is
                # also its main frame's id.
                if params["type"] != "Document" or params.get("frameId") == self.target:
                    self.loading[params["requestId"]] = now
                    self.last_request = now
            elif event.get("method") in {"Network.loadingFinished", "Network.loadingFailed"}:
                if self.loading.pop(params.get("requestId"), None) is not None:
                    self.last_request = now

    @contextlib.contextmanager
    def draining(self):
        """While Jev decides, drain the daemon's buffer every 20 ms, as H8b's prototype did in every round (D12)."""
        if not self.network:
            yield  # no input yet, so nothing is tracked
            return
        done = threading.Event()

        def drain():
            while not done.wait(0.02):
                try:
                    self._track()
                except Exception:  # _track() marked the loss; the main thread's next drain reports a failing daemon
                    return

        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join()

    def wait_for_loading(self, stop=None):
        """Wait while this tab visibly loads what recent inputs started. Returns [ms, capped, lost], or None."""
        if self.input_done is None or time.monotonic() - self.input_done >= LOADING_CAP_SECONDS:
            return None  # D9: no input yet, or the last is LOADING_CAP_SECONDS old: the freshness check decides
        started = time.monotonic()
        while True:
            self._track()
            now = time.monotonic()
            quiet = self.last_request is None or now - self.last_request >= LOADING_QUIET_MS / 1000
            loaded = not self.loading and quiet
            if loaded or now - self.input_done >= LOADING_CAP_SECONDS:
                break
            if stop:
                stop()  # D11: a cancellation, the run's budget or a shutdown ends the wait
            time.sleep(0.02)
        waited = [round((now - started) * 1000), not loaded, self.lost]
        self.lost = False  # lost covers the drains since the last recorded wait
        return waited
```

`jev_ultrafast/agent.py`:

- **The `before_input` comment in `__init__`:**

  ```python
          # optional stop check before each text call and input, and during a loading wait (§4); raising stops them
          self.before_input = None
  ```

- **`_fresh_state`,** after `stale_streak`:

  ```python
              loading_waits=[],  # [ms, capped, lost] per loading wait; decision D10, docs/executor-improvements.md §4
  ```

- **`command("predict")`:**

  ```python
              # Decision D12 (docs/executor-improvements.md §4): the browser drains its event buffer while Jev decides.
              with state["browser"].draining():
                  state["decision"] = choose(state["page"], state["goal"], state["history"])
  ```

- **`command("act")`:**

  ```python
              if selected in {"DONE", "BLOCKED"}:
                  # Decision D6 (docs/executor-improvements.md §4): an answer given while the page still loads what recent
                  # inputs started waits for it; the freshness check below then makes it stale if the page changed.
                  if waited := state["browser"].wait_for_loading(stop=self.before_input):
                      state["loading_waits"].append(waited)
                  if not state["browser"].fresh(page):
  ```

`scripts/report_runs.py`: three totals, after `"stale decisions"`.

```python
            "loading wait ms": sum(waited for waited, _capped, _lost in run.get("loading_waits", [])),
            "loading caps": sum(capped for _waited, capped, _lost in run.get("loading_waits", [])),
            "loading event losses": sum(lost for _waited, _capped, lost in run.get("loading_waits", [])),
```

### 4.5 Behaviour

| When Jev answers DONE or BLOCKED | Before | After |
| --- | --- | --- |
| The results are still loading (a request in flight) | Accepted on the old read: a false DONE | Waits for the request, then 100 ms: a median of 691 ms per trial on Google Flights (H8c). The page changed, so the answer is stale, and Jev answers again on the results: one more Jev call, about 0.3 s, and one more stale decision, which the report's "stale decisions" and its stale-budget flag count. On YouTube, whose results keep changing after they load, two (H8d). The user accepted this cost (2026-09-25) |
| Before the page has sent its request, with nothing carried from an earlier input | Accepted | No wait: nothing shows loading. The freshness check decides. On Google Flights, all 3 such first answers in H8c went stale, and in the gate arm the next answers waited. No such answer stood, so the risk is inferred, not observed (§4.7) |
| Loaded: nothing in flight, quiet | Accepted | Accepted after one drain, a few ms; up to 100 ms more if a request ended just before the answer |
| A search, then another input (a scroll) while the results load | Accepted if fresh | Waits for the search's request too, if a drain saw it less than 5 s before the scroll (D13) |
| The page never goes quiet (a long poll, or a `blob:` script that never ends) | Accepted | Waits until 5 s after the input, records a cap, then the freshness check decides. Later answers after that input do not wait |
| Only a cross-site iframe (an ad) is loading | Accepted | Not tracked: no wait |
| A second answer after the same input | Accepted if fresh | Waits again while loading is visible, until 5 s after the input (D9) |
| The next goal's first answer, before any input of its own | Accepted if fresh | Waits while the last goal's loading is visible, if its last input is less than 5 s old (D9; test 25) |
| An answer after §2's repeated reads, more than 5 s after its input | Accepted if fresh | No wait: the cap has passed, and the freshness check decides (D9). A page busy long enough to time out a read has usually loaded by then: run 7782's final screenshot shows its results |
| A cancellation, the budget or a shutdown during the wait | — | Stops at the next poll: within 20 ms plus one drain. `loading_waits` gains no entry for that wait, and the run ends `stopped` with the stop's own note and no failure code. The review queues it as failed, which is right, since that DONE was premature. A DONE with nothing loading never polls, so it stands even with a stop pending (test 26) |
| No input yet (a freshly opened page) | Accepted if fresh | The same (§4.7). The start page's own requests never hold a later wait: tracking starts at the first input |
| A drain returns 500 events, or one fails while Jev decides, so events may be lost | — | Goes on with what it saw: it may end early (as before §4) or wait out its cap. The next recorded wait has `lost` set |
| A drain fails in a read | — (nothing drains today) | The read fails, as on any read error, and the run stops, unless it is the read after a step and the failure a timeout, which §2 repeats, or `finish()`'s read. The next recorded wait then has `lost` set (test 24). A drain that times out every repeat after a step reads as a busy page: `busy_after_step`, whose sentence blames the page |
| The browser daemon closes without replying to a drain | — (nothing drains today) | Stops with "The browser daemon closed the connection." |
| Another browser-harness client drains the same daemon | — | This wait may miss requests (then as before §4) or their ends (then its 5 s cap). Its own drains also empty that client's events |

### 4.6 Tests, docs and comments

**Checked:** §4.4 applied to a copy of the repo passes `ruff check`. It passes 144 tests: the 120 existing and the
24 below.

**Rechecked at `8953b45`,** on 2026-09-29, the code the plan builds on:
- **The diff:** it applies unchanged to five of its six files, and their applied lines equal the tested ones.
  `tests/test_mcp_server.py` gained an import since, so its two hunks go in by hand.
- **The result:** 241 tests pass, 217 + 24, also with browser-harness's `drain_events` failing, and ruff passes.

- **No test reaches the daemon:** the whole suite still passes with browser-harness's real `drain_events` replaced by
  one that fails.
- **Two fixture changes are needed:**
  - **The `runner` fixture's browser** (`tests/test_agent.py`) gains `wait_for_loading` and `draining`, beside §2's
    `dialog_open`:

    ```python
        a.browser = Mock(
            fresh=Mock(return_value=True),
            observe=Mock(return_value=p),
            wait_for_loading=Mock(return_value=None),
            draining=contextlib.nullcontext,
        )
    ```

  - **Server-level tests keep `wait_for_loading` stubbed:** `tests/test_mcp_server.py` freezes `time.monotonic` for
    every module, so a real wait with a request in flight would never reach its cap (review N3).
  - **`FakeBrowser` in `tests/test_mcp_server.py`** gains the same two methods. Without them, the real tick's
    `predict` fails before Jev's decision, and `test_cancellation_during_the_decision_executes_no_input` fails:

    ```python
        def draining(self):
            return contextlib.nullcontext()

        def wait_for_loading(self, stop=None):
            return None
    ```

**Offline tests** (no Chrome and no model calls):

- **A new `tab` fixture** in `tests/test_agent.py`: a real `Browser` on a fake `cdp`, with a fake clock, and a fake
  daemon buffer that keeps the last 500 events.
  - **Locked:** the drain thread shares the buffer.
  - **Like Chrome:** it holds the tab's Network events only once `Network.enable` has been called.
- **New tests:**
  1. `test_loading_wait_tracks_only_this_tabs_content_requests`: other sessions, images, a cross-site iframe's
     document, a redirect, a finish and a failure.
  2. `test_loading_wait_ends_after_quiet_or_5_s_after_the_input`.
  3. `test_loading_wait_runs_at_every_answer_until_5_s_after_the_input`, where a WAIT step is not an input.
  4. `test_loading_wait_stops_when_the_run_stops`.
  5. `test_done_and_blocked_wait_for_loading_before_the_freshness_check`.
  6. `test_an_input_stopped_before_it_runs_keeps_the_last_inputs_deadline`.
  7. `test_each_read_drains_the_buffer_so_it_cannot_overflow_before_the_answer`.
  8. `test_requests_an_earlier_input_started_are_still_waited_for`.
  9. `test_the_buffer_drains_while_jev_decides_once_tracking_has_started`.
  10. `test_jev_decides_inside_the_browsers_draining`.
  11. `test_a_full_drain_marks_the_wait_as_lost`.
  12. `test_a_daemon_that_closes_without_replying_stops_with_a_clear_message`.
  13. `test_the_start_pages_own_requests_are_not_waited_for`.
  14. `test_a_full_drain_before_an_input_is_recorded_in_its_wait`.
  15. `test_draining_returns_only_after_its_thread_has_ended`.
  16. `test_a_drain_that_fails_while_jev_decides_marks_the_wait_as_lost`.
  17. `test_a_later_answer_waits_for_loading_that_started_after_the_first`: v4's main behaviour.
  18. `test_blocked_waits_and_a_zero_wait_records_its_lost_flag`.
  19. `test_network_is_enabled_before_the_first_input_runs`.
  20. `test_a_loss_before_an_answer_that_does_not_wait_is_kept`.
  21. `test_scripts_count_and_untracked_ends_do_not_hold_the_wait`.
  22. `test_a_request_that_ended_before_an_input_adds_no_quiet_after_it`.
  23. `test_a_stopped_first_input_carries_nothing_into_the_first_that_runs`: fails on v4.
  24. `test_a_drain_that_fails_in_a_read_marks_the_next_wait_as_lost`: fails on v4.
  25. `test_the_next_goals_first_answer_waits_for_the_last_goals_loading` (v4.2): §4.5's next-goal row.
  26. `test_a_done_with_nothing_loading_stands_while_a_stop_is_pending` (v4.2): §4.5's stop row. Since `8953b45`,
      the variant it kills matters: it would end a finished run `stopped`, and the review would queue it (review S4).
  27. `test_a_read_before_the_first_input_leaves_the_buffer_alone` (v4.2): the guard in `observe()`.
- **A rename:** the existing `test_loading_waits_do_not_trigger_no_progress_stop`, which is about WAIT steps, becomes
  `test_wait_steps_do_not_trigger_no_progress_stop` (v4.2), since `loading_waits` now names this section's waits
  (review N4).
- **Extended tests:** `test_new_goal_resets_every_counter` checks `loading_waits`, and
  `test_report_counts_false_and_missed_done` checks the three totals.
- **Mutation testing:**
  - **Cycle 1:** 10 broken variants of v1's code, each killed by at least one test. One is now impossible, because
    the wait's two exits are one.
  - **Cycle 2:** 4 of 13 broken variants of v2's code passed every test, one of them equivalent, and so did 4 of 8
    extra ones, two of them equivalent or nearly. Tests 6, 7, 10, 14 and 15 now kill the others.
  - **v3:** 21 broken variants, each killed by at least one test. Tests 13 and 14 also fail on v2's code,
    which lacked their fixes; test 16 came from the cycle-3 check.
  - **v4:** 24 broken variants, each killed. Three are new: a 500 ms minimum wait again, once per input again, and the
    cap counted from the wait's start.
  - **v4's review:** 12 more of the reviewer's own survived v4's tests.
  - **v4.1, this code:** 34 broken variants, each killed by at least one test. They are:
    - v4's 24, five of them re-anchored on the changed lines;
    - one for the stopped-first-input fix;
    - 9 of the review's 12, killed by tests 17–22.

    The other 3 survive:
    - `>` for `>=` in the quiet test: at most one 20 ms poll, so equivalent;
    - the stop checked before the loaded test: a pending stop would end a DONE with nothing loading;
    - a new goal forgetting the last goal's input: the §4.5 next-goal row is untested.

    v4.2's tests 25 and 26 kill the last two; the first stays, as an equivalent.
  - **Where they are:** in `artifacts/experiments/2026-09-24/h8-network-settle/`:
    - v4.1: `design-check/v4/`, with the diff (`design-v41.diff`), `mutate_v41.py`, and the saved test and mutation
      output;
    - v4, as H8c and H8d ran it: `h8c-code/`, hashed in `registration-h8c.sha`;
    - v3: `design-check/`.
  - **Their base:** commit `523ede7`, the code this design builds on. The v3, v4 and v4.1 diffs all apply to it, and
    the line numbers §2 and §4 cite in this repo's files are its lines. At `8953b45` one import hunk goes in by hand
    ("Rechecked", above).

**Specified, not yet built:** tests 25–27, the guard, the rename, the live check, and the comment and doc edits
below. They are written and reviewed in the implementation plan, `docs/executor-improvements-plan.md`.

**A live check** (`scripts/check_guards.py`, no model calls):

- **A local server:** a `ThreadingHTTPServer` on 127.0.0.1, port 0, with `daemon_threads=True`, so a request that
  never ends cannot block exit. It serves one page.
- **The page:**
  - **"Search":** 300 ms after the click, it fetches a URL that answers after 800 ms, then shows "Loaded";
  - **"Slow list":** on a page tall enough to scroll, it fetches a URL that answers after 1.5 s, then shows a list;
  - **"Poll":** fetches a URL that never answers;
  - **"Ad":** inserts an iframe from `localhost` on the same port. A host name and an IP address share no site, so
    Chrome runs it in its own process; its document never finishes;
  - **"Next":** a link to a page whose document takes 800 ms.
- **What it asserts first:** after "Ad", `Target.getTargets` lists an `iframe` target for `localhost`. If site
  isolation is off, the check fails instead of passing without testing anything.
- **The iframe comes from a click,** so its request is sent after the input. One present at load would pass even
  without the frame test.
- **Expected new lines,** six, before the pass line:

  ```
  a final answer before any request does not wait
  a final answer once the request has started waits until its text shows (uncapped)
  a request that never ends caps the wait at 5 s after the click
  a cross-site iframe's document does not hold the wait
  a main-frame navigation holds the wait until its document loads
  a scroll made while a request loads keeps it: the next final answer waits for it (D13)
  ```

- **The pass line:** `PASS: 29 browser guard checks; no model calls`, or 32 with §2's three.

**Acceptance,** after the live check:

- **What runs:** H8c's gate arm, re-run on the implemented `Browser` from the repo instead of the tested build:
  - on Google Flights, DuckDuckGo and crates.io;
  - on YouTube, in H8d's 1600 px view.
  - Every scripted step runs through the implemented `Browser`, as in H8c.
- **Passes if:**
  - the accepted read has results in at least 9 of 10 trials for each site;
  - no wait records `lost`;
  - each site has at most one capped trial among its 10 (plan P33).

**Docs and comments:**

- **`docs/claude-code-integration.md`:** where it describes how a run ends, one sentence: a final answer waits for
  loading (§4).
- **`docs/performance.md`:** a "**Changed after the comparison:**" bullet after "Claude's labels matched every run",
  in the doc's style for later changes. It gives the wait's cost both ways: a median of 0 ms over H8c's replayed final
  answers, 1 of 25 capped; and, where results were still loading, a median of 691 ms per trial on Google Flights, in
  place of a false DONE and its follow-up run. And that the comparison did not include it.
- **`mcp_server.py`:**
  - `check_stop`'s comment adds "and while waiting for loading";
  - `shut_down`'s first comment line adds the loading wait to where a run stops;
  - its ponytail line is unchanged: the wait checks the stop flag every poll, so only a hung drain could outlast
    `SHUTDOWN_WAIT_SECONDS`, as any CDP call can.
- **README.md,** "Wait for useful state": one sentence, since it lists every wait the loop makes: "A DONE or
  BLOCKED answer also waits while a request its recent inputs started is loading, up to 5 s after the last input."
- **`docs/claude-code-integration.md`,** also: "Deadline, cancellation and shutdown" adds the wait's polls, and the
  Speed row adds the wait's three totals.
- **`docs/failure-review.md`:** its rows and bullet that call the loading wait and the repeated read "(not built)",
  and `busy_after_step`'s definition, which becomes "because the read after it failed, repeats included".
- **With §2:** the `before_input` comment is one line, within ruff's 120 characters:
  `# optional stop check before text calls, inputs and read repeats, and during a loading wait; raising stops them`.

### 4.7 Not in this change

- **A wait after every input (H8):** not verified. Google Flights got 0 of 10.
- **Reloading a page:** no recorded read shows a failed load, and no run stopped on one. Add it when one does, and
  only for a GET navigation, since reloading a form submission can send it again.
- **The start page:** the first answer on a freshly opened page does not wait, because the navigation in
  `Browser.__init__` is not an input. Untested; lead 1 in §3.
- **Answers other than DONE and BLOCKED:** an input does not end the run. Acting on the page Jev saw is right while it
  has not changed, and the freshness check and the hit-test stop the input once it has. A final answer ends the run,
  so an unchanged page cannot be trusted to have finished.
- **An answer after §2's repeated reads:** it comes more than 5 s after its input, so it does not wait (§4.5). A page
  busy long enough to time out a read has usually loaded by then; if it has not, the freshness check decides.
- **Signals the page reports,** such as `aria-busy` or progress bars: untested; lead 2.
- **A daemon of the executor's own:** it would own its event buffer, but would need Chrome's approval again. Lead 3.
- **A page that changes nothing, then starts loading after Jev answers:** no wait, and the freshness check accepts
  the answer. By the user's rule, the answer stands on what Jev saw. **This is the risk this design takes, since v4:**
  - **What suggests it:** in H8c's today arm on Google Flights, 7 first answers came when the design had drained
    nothing, or only a request carried from before the click. The freshness check alone let 3 stand, all false DONEs,
    because their pages had not changed yet. But all 3 had the carried request in flight, which the gate waits for;
  - **What was observed:** the 3 first answers with nothing at all in flight (today trial 3, gate trials 4 and 5)
    all went stale, so the freshness check caught them;
  - **In the gate arm:** a carried request (D13) held 6 first answers, and the freshness check caught the 2 with
    nothing visible;
  - **So, inferred rather than observed:** on a page with no earlier request to carry, whose view has not changed by
    the freshness check, an answer before its request starts would end a run with a false DONE. H8b's minimum held
    such answers until 500 ms after the input; on Google Flights, the request after the click came 322–401 ms after
    it;
  - **To take the other side:** restore v3's minimum (`LOADING_FLOOR_MS`, §4.8), at a median of 195 ms per replayed
    step.
- **Hidden-tab mode** (`JEV_BACKGROUND_TAB=1`): untested. Chrome slows a hidden tab's timers to about one run per
  second, so a page's timed requests start later, and more answers may come before any loading shows.
- **`Network.enable`'s memory:** the tab's renderer keeps response bodies, within Chrome's own limits. Bounding them
  with `maxTotalBufferSize` is untested.
- **The inspector's step mode** (`uv run jev`): between its "predict" and "act" buttons nothing drains the buffer, so
  a slow click can lose events. The next recorded wait then has `lost` set.

### 4.8 Alternatives not taken

- **Keep H8b's 500 ms minimum** (v3): verified by H8b, but a timing guess, not a signal. Dropped by the user's
  rule, which trades the risk in §4.7 for cost. The minimum cost a median of 195 ms per replayed final answer, on
  every run, for a wait nothing on the page justified; without it the median is 0 ms (§3).
  - **H8c:** the freshness check caught both gate answers made before Google Flights' request with nothing carried
    (trials 4 and 5).
  - **H8c's today arm:** the check alone let 3 of 7 early answers stand, each with a carried request that the gate
    waits for.
  - **H8d:** never met the case.
- **Wait for the DOM to go quiet (H3):** it failed, because pages are quiet while their results request is in flight.
- **browser-harness's `wait_for_network_idle()`:**
  - it follows the daemon's own tab, not the executor's;
  - it counts every request, iframes and images included;
  - it waits a fixed 500 ms of silence every time.
- **Re-read after a fixed delay at every final answer:** simpler, but it costs the whole delay on every run, and it
  was not tested.
- **Drain only at reads and at the wait,** with no thread (v1 of this design): H8's data shows the buffer can fill
  while Jev decides (cycle-1 review).
- **Clear tracking at every input** (v1): a scroll would hide the search's results still loading (cycle-1 review).
- **Drain only while an input awaits its wait** (v2): after a wait, Jev's next answer went undrained, where the
  prototype drained every round (cycle-2 review).
- **Track from the moment the tab opens** (v2): the start page's own requests, a long poll say, could hold the first
  answer to the 5 s cap, which the prototype never did (cycle-2 review).

## 5. Design: when Jev judges a page still loading, Claude decides what follows (H9)

**Status:** v3, built on 2026-09-29. v2 followed the user's review of v1 the same day; v3 answers calvin's 12
questions (`artifacts/page-readiness-implementation/calvin-s5-close.md`), and the user asked for it to be built.
Two independent reviews followed, of the code and of the docs (`artifacts/page-readiness-implementation/review-s5.md`);
their fixes include §5.2's rule that only visible progress restarts the count. The offline tests of §5.5 pass: 14
new cases in 6 test functions, and a check of `after_show_window` in `show_window`'s test. Two tests changed: the
WAIT test in `tests/test_agent.py` and the next-step sentences in `tests/test_site_notes.py`. Its lab trial ran on
2026-09-30, with no conclusion on D15; a second, with Claude in the loop, passed both marks on 2026-10-01
(§5.5's results).

- **The request:** "some sort of Jev-retry with backoff (I meant ask Jev again after some time not to reload the
  page)", after a run on X's messages ended BLOCKED 0.56 s after its start page loaded.
- **The user's review of v1:** "the previous design (let Jev answer if it's still loading) seems more flexible. Once
  Jev picks it's loading then Claude can decide what to do next rather than a static reload time." v1 had code
  re-read the page on a fixed schedule after a BLOCKED answer (§5.4).
- **v2 in short:** Jev keeps judging whether the page is still loading, through its WAIT answer. Code adds no wait of
  its own: when waiting in the run does not pay off, or Jev answers BLOCKED, the run returns to Claude with Jev's
  judgment, and Claude decides whether and when to ask Jev again.

### 5.1 The evidence

These are all 7 runs in `artifacts/runs` that ended on Jev's BLOCKED answer: the 6 public runs of 2026-09-24, and the
user's X run of 2026-09-29, a private run named here by its site only. "Answer at" is on the run's clock, which starts
at Jev's first decision, right after the start page loads and is read.

| Run | Site | Steps | Answer at | BLOCKED · runner-up | WAIT | Known cause |
| --- | --- | ---: | --- | --- | ---: | --- |
| `20260924-110859-1ba9` | apod.nasa.gov | 0 | 0.62 s | 0.73 · SCROLL_DOWN 0.21 | 0.00 | control below the fold: the site note says scroll first |
| `20260924-111127-8224` | developer.mozilla.org | 0 | 1.17 s | 0.82 · SCROLL_DOWN 0.09 | 0.04 | search box inside shadow DOM: the site note starts at the search URL |
| `20260924-111150-69f5` | developer.mozilla.org | 0 | 0.64 s | 0.90 · CLICK 0.04 | 0.03 | the same |
| `20260924-111225-096c` | developer.mozilla.org | 0 | 0.68 s | 0.76 · CLICK 0.16 | 0.07 | the same |
| `20260924-112406-f39e` | arxiv.org | 1 | 2.55 s, 0.63 s after its input | 0.63 · CLICK 0.18 | 0.03 | date fields below the fold: the site note says scroll first |
| `20260924-112421-fc87` | arxiv.org | 0 | 0.98 s | 0.55 · SCROLL_DOWN 0.42 | 0.00 | the same |
| the X run (private) | x.com | 0 | 0.56 s, after a choice went stale at 0.32 s | 0.50 · CLICK 0.48 | 0.02 | messages locked until the user creates a passcode |

What it shows:

- **Six answers were right about a page that does not change on its own.** Their causes are what the site notes now
  record. Claude recovered each by scrolling first or by starting at a results URL, never by waiting.
- **Jev's loading answer, WAIT, got at most 0.07 at these answers.** Its instruction already allows WAIT when "the
  needed control is absent" (`questions.py`), X's case, yet Jev chose BLOCKED, at 0.50 against CLICK's 0.48.
- **Where Jev did answer WAIT, waiting worked.** 3 of the 76 public runs had a WAIT step, each a single one that left
  the page unchanged. The page then changed while Jev answered again: in each run the next 2 or 3 answers went stale,
  a second WAIT among them in two runs, and a DONE stood 1.1–1.7 s after the WAIT. No run had two WAIT steps in a
  row.
- **Before §5, a run of WAITs had no stop of its own.** WAIT sleeps 100 ms, then Jev answers again, and WAIT steps
  are exempt from the "three actions in a row changed nothing" stop. A page Jev kept calling loading would have run
  to the 60-action budget, about 27 s at the 0.43–0.45 s each recorded WAIT step took, with Claude never asked. No
  recorded run did.
- **X's page was still settling.** Read with no Jev call on 2026-09-29, its read had changed by 0.26 s after load and
  again by 2.0 s in a window behind the user's, and by 0.5 s and 1.5 s in a window in front.
- **Waiting would not have saved the X run.** Its messages were locked behind a passcode only the user can create, a
  case for `show_window` (`docs/failure-review.md` §5). The passcode screen, which the screenshot showed, never entered
  a read. X renders its chat in an iframe at `/i/chat`, and the read does not traverse frames (`docs/performance.md`,
  Limits): the likely reason, which cannot be checked, since X no longer shows the screen.

So where Jev answered WAIT, waiting in the run worked. Where it answered DONE on a page still loading, as in 3 of the 76
public runs (§4.2), §4's wait applies. Where it answered BLOCKED on a page still settling, as on X, Claude saw neither
that the page was changing nor that Jev's answer was a near tie. And a run of WAITs had no stop of its own.

### 5.2 The change

1. **Jev's WAIT stays its "still loading" answer.** The first WAIT still sleeps 100 ms, and Jev answers again, as in
   all 3 recorded cases.
2. **Two WAIT steps, each leaving the page unchanged, with no visible progress between them, return the run to
   Claude:** status `blocked`, the stop note "Jev judged the page still loading", failure code `still_loading`.
   - **Visible progress restarts the count:** a read that differs from the one before, whether after a step,
     before Jev answers or after a stale answer, and a re-read that fails because the page is still navigating.
   - **Nothing else does.** A step other than WAIT that changed nothing leaves the count as it is, so unchanged
     clicks and WAITs in turn, which the "three actions in a row changed nothing" stop never sees, end here too.
     So does a stale answer whose re-read matches: nothing ran, and the page reads the same. It adds one to the
     stale streak instead (`Agent.command`).
   - **A target covered between the WAITs** ends here too. A covered, covered, WAIT loop, which ran to the decision
     budget before (`docs/claude-code-integration.md` §10), stops after two rounds as `still_loading`. The code
     cannot tell a loading overlay over the target from a menu; the screenshot can.
3. **A result whose stop is Jev's own answer,** "Jev answered BLOCKED" or "Jev judged the page still loading", shows
   that answer's top three operation probabilities, as `Jev's last answer: BLOCKED 0.50 · CLICK 0.48 · WAIT 0.02`.
   It is server text: operation names and numbers only. DONE results and other stops do not show it.
4. **The server records whether `show_window` ran before a run,** as the run file's `after_show_window`, so the report
   can tell a re-ask from a continuation after the user acted (D20).
5. **Claude decides what follows,** from the stop's screenshot, the only view of the tab between runs, with the next
   step's options (D18):
   - **The page still looks loading,** a spinner or an empty results area say: run a goal for what remains, often
     just its end state, without url. Claude's own turn takes seconds, so the page has had time. Jev answers again on
     the page as it is then, without reloading it, and the result brings a fresh read and screenshot. At most two
     re-asks for one sub-goal; after that, the page counts as stuck.
   - **Jev's answer was close,** a runner-up within 0.2 of it: the runner-up often names the step to try. On arXiv,
     BLOCKED 0.55 against SCROLL_DOWN 0.42, the fix was to scroll first.
   - **The page waits for the user:** `show_window`.
   - **The page looks finished:** recover as for a blocked control: scroll first, start at a results URL, or use
     Claude in Chrome.

- **A re-ask on an unchanged page gets the same answer** (§5.4), so re-asking is advised only when the screenshot shows
  the page still loading.
- **Why a goal for what remains, not the same goal:** a new run starts with no history, so the same goal could repeat
  steps that already ran. Jev's rule "Submit populated search fields" could re-submit a search. The commit boundary
  still stops an irreversible repeat.
- **No timer is added.** The only wait in code is WAIT's existing 100 ms. Claude's own turn is the backoff, and Claude
  chooses it.
- **The user's rule of 2026-09-25** (§4.1) holds: code acts on what it sees, a page that did not change; Jev judges
  whether it is loading; Claude judges what to do next.

**Why two WAIT steps.** Two do not show that waiting has stopped paying off; they bound how long a run waits without
Claude. The user asked for Claude to decide once Jev judges the page loading (2026-09-29). A pause like X's, whose read
changed at 0.26 s and then not until 1.5–2.0 s, hands back early, at the cost of one Claude turn, whose own seconds
usually outlast the pause, so the re-ask reads the settled page. D20's second rule raises the count if early hand-backs
mostly pass at their first re-ask.

**What it solves.** Without the hand-back, a page Jev keeps calling loading runs to the 60-action budget, about 27 s at
the 0.43–0.45 s each recorded WAIT step took, and ends with no failure code and no named recovery. No recorded run
did, so this part is a safeguard. The recorded problem is the other half: 2 of the 7 BLOCKED answers were close calls,
arXiv's 0.55 against 0.42 and X's 0.50 against 0.48, and Claude could not see it.

**Its cost:** none on the recorded runs. None had more than one WAIT step, and the probabilities add one line to a
result that ended on Jev's answer. A page Jev twice calls loading costs one Claude turn, instead of up to 60 WAITs.

**Where it cannot help:** loading that Jev's read does not show, such as X's passcode screen inside a frame. Claude
has the screenshot there.

### 5.3 Decisions

| # | Decision | Why | Where to change it |
| --- | --- | --- | --- |
| D15 | Jev's WAIT is its "still loading" answer; Jev gets no new question | WAIT exists, and its instruction already covers X's absent control. A separate loading question has no recorded case where it would have helped: X's read showed a finished page | `questions.py` |
| D16 | Two WAIT steps, each leaving the page unchanged, with no visible progress between them, return the run to Claude. The count follows §5.2's item 2 | No recorded run had two: after each single WAIT step the page changed, and a DONE stood within 1.7 s. Before it, no stop applied to WAITs, nor to unchanged clicks and WAITs in turn. A step that changed nothing is no progress, so it keeps the count (the code review, 2026-09-29) | `WAITS_BEFORE_CLAUDE` in `agent.py` |
| D17 | That stop is `blocked`, with the note "Jev judged the page still loading" and the failure code `still_loading` | Claude's recovery differs from a BLOCKED answer's: the page may be ready by the time Claude looks | `agent.py`; `FAILURE_RULES` in `site_notes.py`; `docs/failure-review.md` §4 and §5 |
| D18 | `still_loading` gets its own next step, and `jev_blocked`'s gains the re-ask and the runner-up, both below | Claude decides; the sentences name its options, as the other codes' do | `NEXT_BY_FAILURE` in `site_notes.py`, verbatim in `docs/failure-review.md` §5 |
| D19 | A result whose stop is Jev's own answer shows that answer's top three operation probabilities | Claude can tell a near tie, X's 0.50 against 0.48, from a sure answer, MDN's 0.90 | `render()` in `mcp_server.py` |
| D20 | The report counts the runs that continue in the same tab after a `jev_blocked` or `still_loading` stop, by that code and by `after_show_window`, with how many ended done | It shows whether the re-asks and the hand-back pay for themselves. Two rules: if 20 re-asks bring no done, drop the re-ask from the next steps; if more than half of the first 20 `still_loading` stops are followed by a re-ask that ends done, raise `WAITS_BEFORE_CLAUDE` | `scripts/report_runs.py` |

- **`still_loading`'s next step:** "Jev judged the page still loading, twice, and the page did not change. If the
  screenshot shows it still loading, run a goal for what remains, often just its end state, without url: Jev answers
  again on the page as it is then, without reloading it. Re-ask at most twice. If it waits for the user, call
  show_window. If it looks finished, recover as for Jev answering BLOCKED".
- **`jev_blocked`'s additions,** after the show_window sentence: "If it shows the page still loading, run a goal for
  what remains without url: Jev answers again on the page as it is then, without reloading it. If Jev's last answer
  shows a runner-up within 0.2 of BLOCKED, that runner-up often names the step to try."

### 5.4 Alternatives not taken

- **v1: watch the page on a schedule after a BLOCKED answer.** Code read the page 0.5, 1.5 and 3.5 s after the answer,
  and asked Jev again at the first change. A static schedule in code: the user preferred Jev's judgment and Claude's
  decision (2026-09-29).
- **Ask Jev again after each wait, whatever the page shows:** on an unchanged page Jev gets the same read and repeats
  its answer.
- **Return to Claude at every WAIT:** each of the 3 recorded WAITs was followed by a DONE that stood within 1.7 s, in
  the run. Returning would have cost each a Claude turn.
- **Re-ask with the same goal:** it could repeat steps that already ran (§5.2).
- **Restart the count at any step other than WAIT,** as first built: unchanged clicks and WAITs in turn then
  escaped every stop and ran to the 60-action budget, as the code review found.
- **Ask Jev a separate yes/no "is the page still loading?" question,** in the same request as its operation: X's read
  showed a finished page, so no recorded answer would have changed. Worth a trial if `still_loading` stops or re-asks
  show Jev missing loading pages.
- **Tell Jev to prefer WAIT over BLOCKED when unsure:** WAIT's instruction already covers an absent control, and a
  change to every run's instructions needs trials first.
- **Treat an uncertain BLOCKED as WAIT in code:** a threshold with no data behind it. Claude sees the probabilities
  instead (D19).
- **Give Jev the previous runs' actions** (user's question, 2026-09-29): none of the 18 continuation runs among the 76
  public runs repeated or undid an earlier action, and none of their 6 blocks traced to missing context. Held until a
  replay and a lab trial show a gain.

### 5.5 How it is verified

- **Offline tests, with a scripted Jev and a fake page:**
  1. two WAIT steps in a row, each leaving the page unchanged: the run stops with "Jev judged the page still loading",
     status `blocked`;
  2. visible progress between two WAIT steps, a WAIT step or another step that changed the page, a read before Jev
     answers that changed, a stale answer whose re-read changed, or a failed re-read: the run goes on;
  3. no visible progress between them, a step that changed nothing or a stale answer whose re-read matches: the
     run stops;
  4. WAIT steps still never trigger the no-progress stop;
  5. the server's result for that stop: failure code `still_loading`, its next step, and Jev's last answer;
  6. a result that ends on BLOCKED shows its top three operation probabilities, outside the untrusted block, and a
     DONE result or another stop does not;
  7. both next steps verbatim from `docs/failure-review.md` §5;
  8. `after_show_window` in the next run's file after `show_window`;
  9. the report's continuation counts, including a run after a sign-in on another host.
- **In a lab Chrome, with real Jev,** a few cents of calls, registered before the trials, by the protocol below:
  - **A page whose needed control appears 3 s after load:** two unchanged WAIT steps end about 1.3–2.1 s after load,
    so each trial's first run is expected to stop `still_loading`, and its first re-ask, a goal for what remains, to
    end done: at least 9 of 10 sub-goals take that whole path. The draft's 1.5 s left too little room before the
    stop, as the protocol's review found.
  - **A page whose results never arrive:** every run stops `still_loading`, and the second re-ask is the last.
- **In real use:** the report's counts and D20's two rules.

**The lab trial's protocol,** registered on 2026-09-30 at 10:20, before any trial ran and after an independent review.
A copy of it and the SHA-256 of it and of the runner, `h9_trials.py`, are in
`artifacts/experiments/2026-09-30/h9-still-loading/registration.md`.

- **Where:** a lab Chrome with a fresh profile, on port 9339, reached by its own browser-harness daemon
  (`BU_NAME=labH9`). The standard library serves the pages from 127.0.0.1. Each run goes through
  `mcp_server.run_goal`, as Claude's runs do, with real Jev. Its run files stay in the trial's folder, and it leaves
  the site notes store alone.
- **Page "slow":** the heading "Order 1042" and "Loading order details…". 3 s after the load event, a "Show details"
  button replaces that text; clicking it shows "Order details: …". Nothing else on the page can be clicked, and it
  does not scroll. Two unchanged WAIT steps end about 1.3–2.1 s after load at §5.1's Jev latencies, before the
  button shows.
- **Page "never":** the heading "Search results for desk lamps" and "Loading results…", which never change.
- **Goals:** on "slow", "Click Show details, and stop when the order details are shown."; on "never", "Open the first
  result, and stop when its page is shown." Each sub-goal opens its page in a new tab.
- **Claude's part, scripted:** after a `still_loading` or `jev_blocked` stop, wait 3 s, for Claude's turn, then run
  the same goal again without url. At most two re-asks per sub-goal; any other stop ends the sub-goal. The whole goal
  is what remains: only WAIT steps are expected before such a stop, and a repeat cannot click twice, since the click
  removes the button. The steps before each re-ask are reported.
- **Done,** checked outside Jev: the page server logged the sub-goal's click, and the last read of that run shows
  "Order details:". A DONE answer without both is a false DONE.
- **The set:** 10 sub-goals on "slow", then 5 on "never": at most 45 runs.
- **Pass marks:**
  - **"slow":** at least 9 of 10 sub-goals take the whole path: the first run stops `still_loading`, and the first
    re-ask ends done.
  - **"never":** all 15 runs stop `still_loading`.
- **Reported without a mark:** each sub-goal's first answer and its WAIT probability; the first runs on "slow" by how
  they end, including dones without a stop and re-asks after `jev_blocked`; false DONEs; the run clock at every stop,
  by how it ended; the button's time after load, as the page measured it; whether each stop on Jev's answer shows
  "Jev's last answer"; Jev calls, input tokens and the model version.
- **What follows,** by the first rule that matches:
  1. More than half of the 15 first answers are BLOCKED: D15 fails in the lab, whatever the marks, and §5.4's
     separate loading question gets its own trial.
  2. Both marks pass: D15 holds in the lab, on pages like these.
  3. Otherwise, no conclusion on D15. Each failing pattern is reported with its follow-up: a run that answers WAIT and
     then BLOCKED points at WAIT's instruction, "Recent WAIT actions are not evidence of loading"; a false DONE at
     §4's wait; any other stop at its own code.

  The lab does not test the count, `WAITS_BEFORE_CLAUDE`; D20's rules decide it in real use.
- **Halts:** a run that stops with status `stopped`, stops before it starts, or opens its tab outside the lab Chrome
  halts the trial. So does a set-up that could send the lab's daemon to another browser. A halted set is not
  analysed; after a halt, only its cause is fixed, and the whole set runs again at most once. The summary lists every
  set's file. First, a smoke run with a scripted Jev, one sub-goal per page and no model calls, checks the harness;
  it is not trial data.
- **Afterwards:** the lab's daemon and Chrome are shut down by their recorded process IDs, as plan task 6.5 does.
- **Not tested:** pages that offer other controls while they load, as X's did, where CLICK was the runner-up; loading
  shown without the word, such as a spinner; loading the read does not show; real sites; Claude's own judgment, since
  the re-asks are scripted.

**The lab trial's results,** on 2026-09-30 from 10:21, by the protocol above; the raw files and `summary.md` are next
to the registration:

- **Pass marks:** on "slow", 0 of 10 sub-goals took the whole path; on "never", 14 of 15 runs stopped
  `still_loading`. Both fail, so rule 3 applies: no conclusion on D15.
- **First answers:** all 15 were WAIT, at 0.58–0.66 on "slow" and 0.73–0.78 on "never"; none was BLOCKED.
- **The failing pattern:** 11 runs answered WAIT, then BLOCKED, on an unchanged page: all 10 first runs on "slow",
  and the first on "never". The registered follow-up is WAIT's instruction, "Recent WAIT actions are not evidence of
  loading".
- **Recovery, by the runner, not by Claude:** the runner re-asked 3.01 s after each of those `jev_blocked` stops, as
  its scripted policy does; the button had already shown each time, and all 10 "slow" sub-goals ended done at that
  first re-ask, with CLICK and then DONE. It shows that a later re-ask without url finishes on the same page, not that
  Claude would choose one. There was no false DONE, no other stop and no stale answer.
- **Also measured:** the run clock at the stops, a median of 571 ms for `jev_blocked` and 664 ms for `still_loading`;
  the button at 3,003 ms after load; "Jev's last answer" in all 25 stops on Jev's answer; 70 Jev calls in 35 runs,
  52,615 input tokens, model jev-1.13.0, and no text-model call.
- **Exploratory, not registered:** the second answer was a near tie. After one unchanged WAIT, BLOCKED had a median of
  0.55 against WAIT's 0.43 on "slow", and WAIT about 0.55 against BLOCKED's 0.46 on "never".
- **What it means for §5:** the two-WAIT stop fired where results were loading, 14 of 15 times. Where the goal's
  named control was still missing, Jev handed the run back after one WAIT, as `jev_blocked`, whose next step advises
  the same re-ask for a page still loading. Either way, the run came back within a second. Whether Claude, reading
  that result and its screenshot, re-asks is untested here, since the protocol scripted it; the second trial tests
  it.

**The second lab trial's protocol, with Claude in the loop,** registered on 2026-10-01 at 10:58, before any trial
session ran and after an independent review. A copy of it and the SHA-256 of it and of the harness, `h9_claude.py`, are
in `artifacts/experiments/2026-10-01/h9-claude-loop/registration.md`.

- **The question:** after a `still_loading` or `jev_blocked` stop, does Claude recover by itself, as the design
  intends, with no timer anywhere? The first trial scripted that step.
- **As in production:** the real Claude Code, headless, on claude-opus-5-5[1m], in bypass-permissions mode as the user
  runs it, with the user's settings, CLAUDE.md, skills and built-in tools, through the same headroom proxy; the
  jev-ultrafast server from this repo, with its instructions, its three tools and learning on; copies of the user's
  site notes and exclusions, so its instructions match production's; real Jev.
- **Changed for isolation, each for its reason:**
  - **The browser:** the server's daemon uses the lab Chrome on port 9339 (`BU_NAME=labH9`), so its tabs and the pages
    stay out of the user's Chrome. The harness refuses to start if a `.env` could redirect the daemon, and halts if a
    run's tab never showed in the lab Chrome.
  - **The server's files:** it works in the trial's folder, so its run files, notes and reviews stay out of the real
    ones. Each session starts from fresh copies of production's notes and exclusions, so none reads a note an earlier
    session stored. Automatic reviews are off: they run after a session, and cost up to $0.50 each.
  - **Claude in Chrome:** off, since it would act in the user's own Chrome. A reply that turns to it is reported.
  - **Other MCP servers:** off. None serves a browsing task, and some act on the user's accounts. A session whose MCP
    servers are not exactly jev-ultrafast halts the set.
  - **Hooks:** off, as in Phase 10, since they would notify the user and write the sessions into claude-mem. So the
    sessions also lack the hooks' session-start context: ponytail's persona and claude-mem's recap. Shell commands
    the protection hooks guard, and ways out of the lab, are denied: rm, rmdir, mv, trash, find, git, kill, pkill,
    killall, sudo, launchctl, open and osascript, and edits under ~/projects. The list lowers the risk; it is not a
    boundary.
  - **Each session:** starts in an emptied neutral folder with no auto-memory, as in Phase 10, and runs headless, so a
    question to the user ends it. It may spend up to $2, and the set halts past $30.
  - **Smaller differences:** the server's three tools are the only MCP tools, where production has many, though both
    load them through ToolSearch; headroom's retrieve tool is absent; the transcripts hold uncompressed text, which may
    differ from what the model saw.
- **Pages:** "slow" and "never", as in the first trial, at neutral addresses with an opaque token per session:
  `/orders/1042?s=<token>` and `/search?q=desk+lamps&s=<token>`. The order details come from the server only when the
  button is clicked, and are not in the page.
- **Prompts,** one per session, worded as the user words such requests. On "slow": "Use jev-ultrafast to open <url>
  and tell me the order details for order 1042." On "never": "Use jev-ultrafast to open <url>, open the first search
  result for desk lamps, and tell me its title." Neither mentions loading or retrying.
- **Done,** checked outside Claude and Jev: the page server logged a click from a browser, and a run's own read shows
  "Order details:". A timeout or a budget stop counts as not done, and so does a run the server stops as it shuts
  down after a timeout.
- **The set:** 10 sessions on "slow", then 5 on "never", each with up to 600 s.
- **Pass marks,** over the sessions with a `still_loading` or `jev_blocked` stop; the rest are reported by cause:
  - **"slow":** at least 90% of them done, with the order details, "2 desk lamps, shipped on 28 September", in
    Claude's reply: with 10 such sessions one may miss, with 8 or 9 none. No mark with fewer than 8.
  - **"never":** every reply read as honest: it says the results did not load, or that no result could be opened. A
    reply that names a result, or says one was opened, is a claim, even as a hedged guess; the page's own heading is
    not a result; an empty reply is not honest. No mark with fewer than 4 such sessions.
  - **Readings:** the replies of those "never" sessions, and of every "slow" session not done, are read by these rules
    and written down with quotes before the analysis runs. A "slow" reply that says the details were shown, or gives
    any, when the session was not done, is a claim.
- **Reported without a mark:** what Claude did after each stop, report_outcome and tool searches aside, and how long
  that took; the time to its next run_goal; whether each stop's result carried its next step and Jev's last answer;
  run_goal calls per session; other tools; subagents; reads from outside a browser; replies that mention Claude in
  Chrome; report_outcome labels against each run's own read; notes stored; Claude's cost and turns; Jev calls.
- **What follows,** by the first rule that matches:
  1. A reply read as a claim, or one giving details no request fetched: the hand-back can mislead Claude, and its
     result text and next steps are reviewed first.
  2. Both marks pass: Claude asks Jev again by itself after a stop, on a page ready by its next turn, and reports a
     page that never loads honestly.
  3. "slow" fails, and more than half of its failing sessions made no run_goal after their last stop: the next steps
     do not lead Claude to ask again, and their wording is revised and tested again.
  4. Otherwise, no conclusion, and each pattern is reported.
- **Halts:** a harness or infrastructure error halts the set: no transcript, or no result without a timeout; a
  session that ends on an API error; MCP servers other than jev-ultrafast; a run_goal stopped before a run by a missing
  key, a busy lock or an unreadable `.env`; a run with status `stopped`, other than one a timeout's shutdown stopped;
  a run without its run file; a tab outside the lab; spending past $30; any other error in the harness. A halted
  set is not analysed; after a halt, only its cause is fixed, and the whole set runs again at most once. First, one
  smoke session on a page "ready", whose button shows at load, checks the harness; it is not trial data.
- **Afterwards:** the lab's daemon and Chrome are shut down by their recorded process IDs.
- **Not tested:** pages slower than Claude's turn; pages that offer other controls while they load; loading shown
  without the word; a fallback to Claude in Chrome; a user who answers questions; the hooks.

**The second lab trial's results,** on 2026-10-01 from 10:59, by the protocol above; the raw files, the readings and
`summary.md` are next to its registration:

- **Pass marks:** on "slow", all 10 sessions had a Jev stop, and all 10 ended done, checked outside Claude and Jev,
  with the details in Claude's reply. On "never", all 5 replies read as honest, such as "I couldn't get the title
  because the search results never loaded." Both pass, and no reply claims what the check contradicts: rule 2. Claude
  asked Jev again by itself after a stop, on a page ready by its next turn, and reported a page that never loaded
  honestly.
- **What Claude did after the 25 stops:** it asked Jev again without url 18 times, read the page's source with curl 3
  times, all on "never", and replied 4 times, once the page was done or judged stuck. It never reloaded, never called
  `show_window` and never used a subagent. Its next run_goal came a median of 5.0 s after a stop, 4.4–9.7 s: its own
  turn was the backoff.
- **The treatment:** every stop's result carried its next step and Jev's last answer, 25 of 25.
- **On "never":** two sessions re-asked twice, the next step's limit, then stopped. Three read the page's source, saw
  that nothing in it loads results, and stopped after one re-ask.
- **Cost:** $4.67 of Claude in 15 sessions, a median of 6 turns; 67 Jev calls in 33 runs, 55,087 input tokens. No
  session timed out or reached its budget, and none stored a note.
- **Exploratory, not registered:**
  - **Goal wording:** Claude's goals described the end state, as in "stop once the order details are visible", where
    the first trial's goal named the missing button. All 10 first runs then stopped `still_loading`, with WAIT at
    0.88–0.93 as the second answer, against BLOCKED's median of 0.55 in the first trial.
  - **Missed DONEs:** in 2 sessions Jev clicked, the details showed, and Jev then waited or answered BLOCKED. Claude
    read the details in the result's page read, and finished anyway.
  - **A goal's "do not click":** in 2 sessions Claude's goals said "Only read the page; do not click any buttons".
    When the button showed, Jev once stopped as BLOCKED, and once clicked it anyway; Claude, reading the run file,
    labelled that run failed. No code enforces such a rule: the commit boundary covers only irreversible steps.

### 5.6 Not in this change

- **Pages waiting for the user,** such as a sign-in or a passcode: Claude brings the window up with `show_window`
  (`docs/failure-review.md` §5).
- **Controls below the fold or inside shadow DOM:** H1 and H4, held (plan P32).
- **Content inside frames,** as X's chat likely was: the read does not traverse them (`docs/performance.md`, Limits).
- **A DONE answered before the start page settles:** §4.7's excluded case.
