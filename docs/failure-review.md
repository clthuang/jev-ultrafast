# Failure log, review and site protocols

**Status:** design v4.4, approved by the user on 2026-09-26, with their decisions in §12 and v4.4's; implemented on
2026-09-29, as `docs/failure-review-plan.md` lays out. The first review ran that day, for $0.07.

- **The request** (2026-09-26): "we need to have a failure logs + review and improvement mechanism. For example, for
  particular domain we should use a particular workflow/protocols to handle certain website quirks. This should be
  automated where possible."
- **Review:** three cycles, each by independent reviewers:
  - **Cycle 1:** safety, evidence, simplicity and intent. Three of the four blocked.
  - **Cycle 2:** safety, evidence and intent. All three approved with fixes.
  - **Cycle 3:** one final verifier. Ready after three fixes, now applied.
  - **v4:** records your decisions (§12): automatic reviews on, with a $0.50 cap and a record of what was sent.
  - **v4.1:** details found while planning: the server is built in `main()`, the module is `site_notes.py`, notes sit
    before the result's fields, and `render()` reports the notes it placed.
  - **v4.2:** details from the plan's review: notes gain `last_shown`, for §6.4's order, and each digest is named by
    its start time, so two reviews on one day do not collide.
  - **v4.3:** from the plan's breakdown: where a chain of attempts ends (the plan's P14), and the false-DONE mark
    follows `previous_run` directly, which still marks the census's 3 early DONEs.
  - **v4.4, your decision after the first review (2026-09-29):** that review's reply was refused whole. Each run's
    summary hid only the values its own chain typed, while the reply check refused a value typed in any queued run.
    Now every summary hides every queued run's values (§7.2), and a task value in a reply refuses only a note
    decision holding it in its note or detail; anywhere else it becomes `<value>` (§7.5).
  - **After v4.4, at your request (2026-09-29):** `jev_blocked`'s next step (§5) also covers a page waiting for you,
    such as X's messages asking you to create a passcode: Claude calls the new `show_window` tool to bring the run's
    window up, asks you to finish there, then continues in the same tab. Only the screenshot showed X's passcode
    screen, neither page read did, so Claude judges this case too.
  - **Also after v4.4, at your request (2026-09-29):** a fourth code, `still_loading`: two unchanged WAIT steps
    with no change between them return the run to Claude (§4, §5). A result that stopped on Jev's own answer shows
    its top three operation probabilities, and `jev_blocked`'s next step gains a re-ask for a page still loading
    (`docs/executor-improvements.md` §5).
  - **Two findings not followed, with reasons:** the session-start list of approved notes stays, approved only at a
    terminal (§8.1), where a safety reviewer asked to defer it; and the summaries go to the reviewer on stdin, where a
    nit asked for none.
  - **Where they are:** the reviews and the research are listed under "Sources", at the end.
- **Related designs:**
  - **The integration design** (`docs/claude-code-integration.md` §7.5, "Improve"): this design replaces its item 4,
    review on request, and extends item 1, prompt changes. Its items 2, 3 and 5 stay as they are.
  - **The executor design** (`docs/executor-improvements.md`): its repeated read after a busy step (its §2) and its wait
    for visible loading before DONE (its §4) are the generic fixes this design relies on. They should ship first.

## The short version

**What the data says:** every recovery in the recorded runs came from Claude rewriting its goal after a failed run.
None needed the executor to act differently on one site. So the per-site "workflow" you asked for lives where the
recoveries happened: in the goals Claude writes.

**What gets built, all automatic, with no extra model calls, and nothing sent anywhere results don't already go:**

1. **A failure code:** at a stop whose cause code can read from the run file, one of four codes.
2. **A next step for each code:** the result tells Claude, in a fixed sentence, how that kind of failure was
   recovered.
3. **Site notes:** when a changed goal fixes a failed run, Claude records the site's quirk as one of four hints, plus a
   short detail, keyed by the site's host.
   - **In results:** every later run on that site shows its notes, in any session.
   - **At session start:** notes you approve are listed in the server's instructions, so they help a session's first
     run on a site at no extra turn.
4. **Upkeep by code:** notes expire. An unapproved note that did not stop its failure retires itself; an approved one is
   flagged for you.
5. **The report:** failures by site and code, runs per sub-goal, what each note changed, and the notes waiting for your
   approval.

**Your controls:**

- **Approve a note:** run `uv run python scripts/review_runs.py approve <id>` in your terminal. It shows the exact line
  it will add to the server's instructions, and asks you to confirm there, which Claude's ordinary tool calls cannot
  do (§8.1).
- **Retire or restore one:** ask Claude, or run the same script.
- **Keep a site or a run out:** list it in `artifacts/review-exclude.txt`, which starts with your two private runs.
- **See what a review sent and decided:** its digest, `artifacts/reviews/<start time>.json`, keeps the exact text sent
  to Anthropic, and the report lists every review's decisions at its end.
- **Turn automatic reviews off:** `JEV_AUTO_REVIEW=0` in `.env`.
- **Turn it all off for experiments:** `JEV_LEARNING=0` in `.env`.

**An automatic reviewer, on by your decision (§12).** A Claude with no tools reads short summaries of the runs
waiting for review, at most once a day and for at most $0.50, then:

- retires notes that don't help, and adds notes from recoveries Claude did not record;
- flags labels that look wrong;
- drafts code-change proposals for you.

It sends those summaries to Anthropic, which changes a promise in the integration design. The build rewrites that
design's line, and each digest keeps the exact text sent. "Review Jev runs" runs the same review on request, in
your session.

**Designed, built later: per-site executor settings,** such as a taller view on one site. No recorded failure needed
one (§1). The spec is ready (§8.3). The first failure that no generic fix covers triggers a lab trial, and the runner
it needs.

**Size:** about 950 lines, about 420 of them the plan's 49 offline tests.

**Your decisions (§12, 2026-09-26):** automatic reviews on, capped at $0.50 a review, with a record of what was sent;
the four seed notes approved; the AGENTS.md line added with the build; the paid test skipped.

## 1. What the recorded runs show

Sources: `r1-census.md`, recounted in `qa-census.md`. All counts are in-sample: the rules and notes below were written
from these same runs.

**Failures:**

- **15 of 78 runs failed:** 1 false DONE, 1 missed DONE, and 13 stops labelled failed.
- **Their cost came mostly from one mode, since fixed:**
  - they used 517 of 819 Jev calls;
  - 480 of those were four "stale storms", where a covered field made Jev choose again 120 times;
  - the stale-streak stop, added since, capped the same case at 7 calls, though that run still failed;
  - with storms at 7 calls, failures would have used about 65 of 367 calls (18%).
- **What remains is extra runs:** in Phase 10, 7 of 30 sessions needed more than one `run_goal`. They took 951 of
  1,680 s; the two storm sessions account for 532 s of that.

**Classifying them:** the census's rules named 14 of the 15 from run-file fields. Only the false DONE needed a verdict,
and only a verdict showed the missed DONE had succeeded.

**How Claude recovered, each seen in one session:**

| Site | What went wrong | Claude's fix |
| --- | --- | --- |
| ClinicalTrials.gov | a suggestion list covered the next field | choose the suggestion, then one action per goal |
| httpbin.org forms, in your Chrome | 1Password's menu covered the fields | one field per goal, "do not choose any entry from the 1Password menu" |
| APOD (apod.nasa.gov) | the Archive link sat below the view | "scroll to the bottom first", in the goal |
| arXiv | the date controls sat below the view | a goal that only scrolled; a scroll inside the full goal was answered BLOCKED again |
| MDN | the search box sits in a shadow DOM, which Jev cannot read | open the results URL, after two other rewrites failed |
| Google Flights, DuckDuckGo, crates.io | DONE before the results loaded | run again, to wait or re-read |

**Claude tried to learn, without a channel:**

- In 4 of the 7 multi-run sessions, it tried to read the failed run's file, and was denied.
- 2 sessions wrote lessons into Claude Code's auto-memory. One leaked into the next 6 sessions, which had to be run
  again (`docs/performance.md`, "Auto-memory leak").
- Both lessons worked later in the session that wrote them.

**Repeats:**

- **Within a session:** Claude's own failed rewrites, before its fix. They cost 243 Jev calls, 240 of them in storms.
  A next-step sentence targets these.
- **Across sessions, too few cases to say:**
  - ClinicalTrials.gov's suggestion list came back in a later, deliberate QA re-test: 1 of 1.
  - Google Flights' early DONE did not come back in 3 later runs, one of them the same task: 0 of 3.

**Why no per-site executor setting yet:**

| Quirk | Fixed by | Would a per-site executor setting have helped? |
| --- | --- | --- |
| Suggestion list, 1Password menu | one field per goal; the stale-streak stop caps the cost | no: 1Password belongs to the browser profile, and the rest was the goal |
| Controls below the view | a scroll-only goal | untested. A scroll rule for Jev passed 2 of 6 live trials, and listing off-screen controls 0 of 6 (`docs/executor-improvements.md` §1, H1); on arXiv, BLOCKED won even with the dates on screen. No trial tried a taller view there. The note costs one extra goal; a trial needs the runner in §8.3 |
| Search box in a shadow DOM | the results URL | no: Jev cannot read it on any site |
| Results that load late | the executor design's loading wait (not built) | no: it is generic. With a 500 ms minimum and a simulated Jev, it passed on five sites; without the minimum, 10 of 10 on four of them |
| A busy page after a step | the executor design's repeated read (not built) | no: it is generic |
| YouTube's changing results (lab only; no recorded run) | the same loading wait: 7 of 10 at the usual 780 px, and a pass in a 1600 px view | probably not: the failing layouts did not come back at 1600 px, so that trial "would probably have passed at 780 px" too |

## 2. The mechanism

```text
run ──▶ run file: + previous run, failure code, notes shown
  │
  ├─▶ result: the code's next step, and the site's notes
  │
  ├─▶ report_outcome: the verdict, plus an optional lesson ──▶ site note
  │
  ├─▶ code: counts what follows each note; retires notes that did not help
  │
  └─▶ review, on request or automatic: summaries of waiting runs
        ├─▶ note retirements and new notes, applied by code after its checks
        ├─▶ label flags, for you
        └─▶ code-change proposals ──▶ you ──▶ the usual test, design, review and plan
```

| Layer | What it changes | Who decides |
| --- | --- | --- |
| Next-step sentences | the result's advice after a failure | code, from fixed text reviewed like any code |
| Site notes | the advice for one site, which Claude reads | Claude writes; code checks, counts and retires; you approve |
| Per-site executor settings (later) | what the executor does on one site | a lab trial, then you, per setting |
| Code changes, Jev's questions included | anything | you, through the usual workflow |

**Why this split:**

- **The responsibility cut holds:** code decides what it can observe (the failure code), Claude decides what to do next
  (the goal), and Jev still judges one page at a time.
- **AGENTS.md holds, with §12's added line:** "Do not add site-specific plans or hardcoded field values." Site notes
  reach Claude, whose goals may already carry exact values and steps. The executor's input stays one goal.
- **Trust follows the author:**
  - fixed sentences are code;
  - anything a model wrote stays inside the result's untrusted block;
  - only notes you approve at a terminal reach the server's instructions, and only as host, fixed sentence and a URL
    code derived, capped at 100 characters.

## 3. The failure log

**The run file is already the log.** It records every decision with Jev's full probabilities and exact request, every
step, the verdicts, and the result text Claude received. It gains three fields:

| Field | Written | Why |
| --- | --- | --- |
| `previous_run` | at the start | the last run this server saved a run file for: a chain of attempts at one sub-goal, which ends where the site changes or after a pass (the plan's P14). A recovery can start at a new URL, which closes the tab, as MDN's did |
| `failure` | at the stop | the failure code, by §4's rules, or null |
| `notes_shown` | at the stop | the IDs of the notes the result showed, as `render()` placed them. Never parsed from the text, which a page could imitate |

- **Already recorded:** the site, as the host of the run's final page (`page.url`), and the start time, in the run ID.
- **Left out:**
  - **Stale-drop reasons:** only one of the seven stale messages names a cover. The integration design (its §10) adds
    them when the report shows a budget stop whose cause the run file cannot explain; §4 flags such stops.
  - **A file for runs that fail before their first save:** none were recorded, and such a result has no run ID to
    label.

## 4. Failure codes

`failure_code(status, notes, history)` runs in `finish()`. Each code reads only run-file fields, and each has a
next-step sentence (§5).

| Code | Rule | Recorded runs it fires on |
| --- | --- | --- |
| `covered_target` | the stale-streak stop, whose note contains "Target is covered by <…>" | 1: the re-test on ClinicalTrials.gov, naming `<mat-option>` |
| `jev_blocked` | the "Jev answered BLOCKED" stop | 6 |
| `busy_after_step` | a timeout, with the last step's `page_changed` still None, because the read after it failed | 1 |
| `still_loading` | the "Jev judged the page still loading" stop: two WAIT steps, each leaving the page unchanged, with no change between them (`docs/executor-improvements.md` §5) | 0: added on 2026-09-29 |

**The rest of the 15:**

- **The 4 stale storms** ended at the model-call budget, before the stale-streak stop existed. Today the same quirk
  ended at the stale-streak stop, naming its cover, in the one re-test: a forecast from one run.
- **The report flags** a budget stop with more than half of its decisions stale, which is the integration design's
  trigger for recording stale-drop reasons. It gets no code, because code cannot name its cause.
- **The 2 cancels** keep their stop note.
- **The false DONE** needs a verdict. A DONE has no code, since whether it is right is the verdict's job. The report
  marks a DONE followed, through `previous_run`, by a run on its site that took no step, as the census's 3 early
  DONEs were.

**The report** counts other stops by the fixed markers it uses today, and never prints stop-note text outside a marked
block, because stop notes can quote the page.

## 5. Next-step sentences

The result's `next:` line holds only server text, outside the untrusted block. With a failure code, it names a
recovery instead of the generic "try a narrower goal".

| Code | Next step shown |
| --- | --- |
| `covered_target` | a control kept covering the target, such as an open suggestion list or a password manager's menu. Give one field or click per goal, starting with controls it does not cover. A goal may choose the site's suggestion the task needs; never choose an entry from a password manager's menu |
| `jev_blocked` | Jev answered BLOCKED. If the screenshot shows the page waiting for the user, such as for a sign-in, a passcode, a verification code or a CAPTCHA, call show_window, ask them to finish it there, and then continue with run_goal without url. If it shows the page still loading, run a goal for what remains without url: Jev answers again on the page as it is then, without reloading it. If Jev's last answer shows a runner-up within 0.2 of BLOCKED, that runner-up often names the step to try. If the control may be further down, first run a goal that only scrolls until it shows, then the rest. If Jev cannot see it at all, as with a search box inside a shadow DOM or frame, open the results URL directly, or use Claude in Chrome |
| `busy_after_step` | the page stayed busy after the last step, which ran: check the page before running the goal again |
| `still_loading` | Jev judged the page still loading, twice, and the page did not change. If the screenshot shows it still loading, run a goal for what remains, often just its end state, without url: Jev answers again on the page as it is then, without reloading it. Re-ask at most twice. If it waits for the user, call show_window. If it looks finished, recover as for Jev answering BLOCKED |

- **One sentence for every BLOCKED answer:** the page offered a scroll at every decision of all 6 BLOCKED runs, so
  code cannot tell a control below the view from one it cannot read. Claude tells them apart from the screenshot.
- **Evidence, in-sample** (`qa-census.md` §5, scoring `tier0-hints-draft.md`):
  - **The first draft:** it named the fix in 3 of the 5 multi-run sessions not about loading, and part of it in the
    other 2. Its covered-field rule also counted the storms' budget stops.
  - **What v3's sentences fix:** the draft could have picked a 1Password entry, and it put the scroll inside the full
    goal, which failed on arXiv.
  - **Fit, not prediction:** the fixes come from the same sessions. The paid test in §10 would measure it.
- **Loading failures** mostly end DONE, so they get no code. The executor design's loading wait is their fix.
  A run whose WAIT steps twice leave the page unchanged stops with `still_loading` (§4).

## 6. Site notes

### 6.1 A note

Stored in `artifacts/site-notes.json`, which git ignores, because it shows which sites you use.

```json
{
  "id": "clinicaltrials.gov-1",
  "site": "clinicaltrials.gov",
  "hint": "one_action_per_goal",
  "detail": "The condition field's suggestion list covers the next field: choose the suggestion first.",
  "url": null,
  "failure": "covered_target",
  "runs": {"failed": ["20260924-113417-40d8", "20260924-113517-88f4"], "recovered": "20260924-113700-fc97"},
  "approved": null,
  "created": "<build date>",
  "shown": 0,
  "last_shown": null,
  "failed_after": 0
}
```

This is the ClinicalTrials.gov seed. Its two failures ended at the model-call budget, before the stale-streak stop
existed, so they have no code of their own (§4). The seed takes `covered_target` from the later re-test of the same
quirk.

- **Key:** the host without `www.`. The registrable domain would merge `apod.nasa.gov` into `nasa.gov`, and
  browser-harness's domain-skill key, the host's first label, turns `flights.google.com` into `flights`.
- **Hint:** one of a closed set, each with a fixed sentence for results, and a short form for the server's instructions:

  | Hint | Sentence in results | Short form, at session start | Seen |
  | --- | --- | --- | --- |
  | `one_action_per_goal` | give one field or click per goal on this site | one field or click per goal | ClinicalTrials.gov, 1 session |
  | `scroll_first` | a control here sits below the first view: scroll to it first, as a goal of its own if Jev still answers BLOCKED | scroll to the control first, in its own goal | APOD and arXiv, 1 session each |
  | `start_at_url` | start at this URL instead of using the page's controls: <url> | start at <url> | MDN, 1 session |
  | `use_claude_in_chrome` | Jev cannot operate a control this site needs: use Claude in Chrome for it | use Claude in Chrome for its controls | not yet: Phase 10 sessions could not call Claude in Chrome |

- **Detail:** at most 300 characters about the site's behaviour. No URLs, and no values from the task (§6.5).
- **URL:** only for `start_at_url`, derived by code (§6.3), never taken from free text, and at most 100 characters.
  Its path still comes from a page, so the approval shows it in full.
- **Counters:** `shown` counts results that showed the note. `failed_after` counts later runs on the site that failed
  with the note's code after it was shown. `last_shown` is the date a result last showed it.

### 6.2 Seed notes

The recorded recoveries give four notes, stored when the design is built and dated from then:

| Site | Hint | Detail |
| --- | --- | --- |
| `clinicaltrials.gov` | `one_action_per_goal` | The condition field's suggestion list covers the next field: choose the suggestion first. |
| `apod.nasa.gov` | `scroll_first` | The Archive link sits below the day's image. |
| `arxiv.org` | `scroll_first` | The advanced search's date fields sit below the first view. |
| `developer.mozilla.org` | `start_at_url` | The search box sits inside a shadow DOM that Jev cannot read. URL: `https://developer.mozilla.org/en-US/search?q=` |

- **Approved by you** (§12): the build stores them approved, so their line is in the server's instructions from the
  first session.
- **The MDN URL:** the recovered run's starting URL, with its query value removed.
- **Left out:**
  - httpbin.org's 1Password menu, which belongs to your browser profile. The `covered_target` sentence covers it;
  - the early DONEs, whose fix would be the executor design's loading wait (not built), and which did not come back on
    Google Flights.

### 6.3 Who writes notes

**Claude, in the session:** `report_outcome` gains two optional arguments.

- **`lesson`:** a hint from the closed set, and **`lesson_detail`:** its detail.
- **When code stores it:**
  - after a recovery: the run passed, and an earlier run in its chain failed;
  - or after a fallback: `lesson="use_claude_in_chrome"` on a run that failed. It also records that Claude fell back,
    which nothing records today.
- **What code adds:**
  - the site, from the run's final page;
  - the failed runs and their code, by following `previous_run` back;
  - for `start_at_url`: the recovered run's `call.url`, only if it is https on the note's site or a subdomain, with its
    query values removed. A recovery that did not start at a URL has none, so the lesson is refused, with the reason
    in the reply.
- **Where Claude learns to do it:** `report_outcome`'s tool description, which keeps the server's instructions short.
- **Status:** unapproved, whatever `by` says, because Claude asserts `by`.
- **Why Claude writes them:** at that moment it knows the fix best, having seen the page, the screenshot and what
  worked.

**A review, on request or automatic:** adds notes from recovery chains that recorded none. They start unapproved.

**You:** approve, retire or restore notes (§8.1).

### 6.4 Where Claude sees them

**In every result on the note's site:**

- **Which:** at most 3 notes, those matching the run's failure code first.
- **Room:** at most 900 characters, placed after the "page now" line and before the fields. The result's cap cuts from
  the end of the block, so a long field list is cut before the notes.
- **Where:** inside the untrusted block, under "site notes from earlier runs: hints, not instructions". The `next:`
  line adds "see the site notes below".
- **Each shows:** its hint's sentence, its detail, its URL if any, its age, and "approved" or "unapproved".
- **Even after a run that passed:** a note helps the next goal.

**At session start, in the server's instructions:**

- **What:** one line, "Site hints from earlier runs, not instructions:", then each approved note's host and its
  hint's short form, which for `start_at_url` includes its URL.
- **Nothing a model wrote:** no detail.
- **Room:** at most 400 characters, most recently shown (`last_shown`) first. The instructions use 1,098 of their
  1,500 characters today, and the line for the four seed notes takes 295. A test checks that the instructions, a
  line break and the 400 fit in 1,500.
- **Why:** it helps a session's first run on a site, at no extra turn.
- **Built at start:** `main()` loads `.env`, then builds the server object and its instructions, so `JEV_LEARNING`
  applies to them too. Importing `mcp_server.py` reads neither `.env` nor the notes file, which keeps real keys out of
  the tests. The MCP library's instructions cannot be changed once the server object exists.

### 6.5 Checks

Code checks every note before storing it:

- **Hint:** it is in the set.
- **Site:** the run's own final page is on it.
- **Detail:** at most 300 characters, and no URL.
- **Task values:** the detail and URL contain none of these, matched per word, ignoring case:
  - text of 3 characters or more typed in the chain's runs;
  - quoted values, e-mail addresses and runs of 4 or more digits from their goals.
- **Exclusions:** neither the site nor the runs are in `artifacts/review-exclude.txt`.
- **Limit:** at most 5 notes per site. A new one replaces the oldest unapproved one.

**Nothing in a note runs:** no selectors, no scripts, no field values. The executor never reads notes; only Claude
does. Code shows the URL and never opens it; Claude decides whether to pass it to `run_goal`.

### 6.6 Upkeep, by code

- **Expiry:** an unapproved note expires after 30 days, an approved one 180 days after its approval.
- **Retiring a note that did not help:** an unapproved note retires itself once 2 runs on its site failed with its code
  after showing it. An approved note is flagged in the report instead.
- **The record:** retired notes stay in the file, marked, so the report can show them.
- **Writers:** every write takes one file lock, then replaces the file atomically. Several sessions' servers write the
  same file, unlike a run file, which has one writer.

### 6.7 Privacy and experiments

- **Local:** notes and run files stay under the git-ignored `artifacts/`.
- **Exclusions:** `artifacts/review-exclude.txt` lists run IDs, and hosts with their subdomains.
  - **Matched against:** every URL a run visited: `call.url`, each decision request's page URL, each step's `url`, and
    the final `page.url`.
  - **Effect:** an excluded site gets no notes, and its runs never reach a review or the report's printed text. Notes
    are checked again when shown.
  - **Seeded:** with your two private runs.
- **One switch:** `JEV_LEARNING=0` turns off the next-step sentences, the notes and automatic reviews. Phase 10's
  auto-memory leak shows why comparisons need it.
  - **Where:** in `.env`, or in the server entry's `env`. A shell `export` does not reach the MCP server.
  - **Who sets it:** the tests' fixtures, and `scripts/phase10/run_arm.py`'s server entry.

## 7. Reviews

### 7.1 The queue, built by code

`scripts/review_runs.py queue` builds it from the run files, with no model call:

- runs that failed: not done, or labelled failed;
- possible false DONEs (§4);
- runs where your label differs from Claude's;
- notes new or changed since the last review, and recovery chains that recorded no lesson.

**It leaves out:**

- excluded runs and sites;
- runs already reviewed, which the digests list;
- for automatic reviews, runs from before the build. "Review Jev runs" covers older ones.

### 7.2 What a review sees

**Code writes one summary per queued item:**

- the site, the failure code, and the goal;
- the steps: operation, target label, whether the page changed, and Jev's probability. Typed values become their
  length;
- the stop notes, the verdicts and Claude's evidence;
- the final URL without its query values, the title, and the notes shown.

**Replaced by `<value>`,** in the goal, the stop notes and the evidence, matched as §6.5 matches them:

- any text of 3 characters or more typed in a queued run or another attempt in its chain. Claude often writes the
  values to type into its goal: in 14 of the 37 runs that typed text, the goal held a typed value that the other
  replacements missed;
- those runs' quoted values, and, by P18, every e-mail address and run of 4 or more digits.

**One set for every summary (v4.4):** every summary, a note's too, replaces all of these values, so a value typed in
one queued run never shows in another's summary. A value typed only in runs outside every queued run's chain is not
replaced.

**Left out:** visible page text, screenshots and Jev's full requests.

**Marked:** each summary sits inside a block marked with a random nonce, as `render()` does for results, because
titles, labels and stop notes are page text.

**Size, estimated:** 1–2 KB a summary, so a queue of 20 is about 5,000–10,000 tokens.

### 7.3 On request

"Review Jev runs": Claude in your session runs `review_runs.py queue`, reviews the summaries itself, and passes its
decisions to `review_runs.py apply --batch <id>`, naming the batch that `queue` printed. That is today's review on
request with code's checks added, and it sends less than today's version, which reads whole run files.

**Batches (2026-10-04, robustness plan REVIEWS-1…7).** `queue` saves an immutable batch: at most 25 runs, 5 notes and
65,536 bytes, oldest whole items first. It prints each item sent and each item deferred, with its reason, so a backlog
drains over several batches and an item too large for any batch is shown for a manual look instead of silently
waiting. Only a committed batch acknowledges exactly the item versions it sent; a later correction queues the run
again. Automatic reviews still consider only runs from `BUILD_DATE` on (`AUTO_FROM`), and their cadence, $0.50 cap,
15-minute limit and three-failure rule are unchanged. If a committed review's digest cannot be published, its receipt
in the notes file keeps the decisions and new work waits: `review_runs.py recover` publishes it. If a paid review's
process cannot be verified, dispatch stops rather than risk a second paid run; once no review runs,
`review_runs.py resolve <attempt ID>`, confirmed at a terminal, settles it once.

### 7.4 Automatic (on)

**When,** unless `JEV_AUTO_REVIEW=0` or `JEV_LEARNING=0` turns it off:

- after `report_outcome`, the server checks one stamp file. If the last review started more than 24 hours ago, it
  starts `review_runs.py auto` in the background;
- the server starts it with stdin from `/dev/null` and its output going to a log, so it never touches the MCP pipe.
  It skips the trigger when `scripts/review_runs.py` is missing, as in the built wheel;
- `review_runs.py` takes a lock, so only one review runs. It stamps the start, then exits at no cost unless 5 queued
  runs wait, or the oldest is 7 days old. Only runs count toward that;
- a failed review, or a start with no recorded end, counts as a failure and uses that day's review. After 3 failures
  in a row, automatic reviews stop, the report says so, and `review_runs.py enable` restarts them.

**How it runs:**

```sh
/Users/terry/.local/bin/claude -p --model sonnet \
  --tools "" --restricted --safe-mode --strict-mcp-config --no-chrome --permission-prompts none \
  --system-prompt "$REVIEW_INSTRUCTIONS" --output-format stream-json --verbose \
  --json-schema "$REVIEW_SCHEMA" --max-budget-usd 0.5 --no-session-persistence < summaries.txt
```

**What the flags do,** from the installed CLI's help (2.1.283, `claude-help.txt`):

- `--tools ""`: no tools, so page text in a summary cannot run a command, read a file or reach the network.
- `--restricted`: ignores your user, project and local settings files, so your global allow rules do not apply, and it
  refuses bypass mode.
- `--safe-mode`: disables CLAUDE.md, plugins, hooks and MCP servers. `--strict-mcp-config`, given no config, also
  loads no MCP server, and `--no-chrome` keeps Claude in Chrome off, which your global config enables.
- `--permission-prompts none`: anything that would prompt is denied.
- `--system-prompt`: the review's instructions, kept apart from the summaries on stdin.
- `--max-budget-usd 0.5`: caps one review at $0.50, as Claude Code estimates cost. On a subscription login, a review uses plan
  usage.

**How code starts it:**

- **The binary:** its absolute path, from an argument list, never through a shell. Your shell's `claude` alias adds
  `--dangerously-skip-permissions`.
- **Directory:** a fresh temporary one, never the repo, which holds `.env`.
- **Environment:** only HOME, PATH, USER, LOGNAME, TMPDIR and LANG. None of `.env`'s keys, and no `ANTHROPIC_*`
  variable that could redirect traffic or billing.
- **Checked at every start:** the stream's first event lists the session's tools and MCP servers. Code kills the review
  unless it shows no MCP server and no tool beyond the one that returns structured output.
- **Input and output:** the summaries on its stdin, its output to the log.
- **Lifetime:** its own process group, so it survives the server's exit. `review_runs.py` kills it after 15 minutes.

**To confirm when building:**

- that `--json-schema` works with no tools; code validates the reply either way;
- that `--safe-mode` keeps your login, where `--bare` does not.

### 7.5 What a review may decide

The reply is one JSON object, which code validates:

- **Note decisions:** retire a note, citing queued runs on its site; add an unapproved note from a recovery chain;
  or flag a note for your approval. A review cannot approve, and never touches notes you approved.
- **Label flags:** runs whose verdict looks wrong, for you.
- **Proposals:** code-change hypotheses, each with its evidence runs, mechanism, test and pass bar.
- **Summary.**

**Limits:** every text field is capped at 500 characters, and a reply that breaks the schema is refused whole. Task
values, matched as §7.2 replaces them (v4.4):

- **In a note decision's note or detail:** that decision is refused on its own, since notes reach results and later
  reviews.
- **Anywhere else:** replaced by `<value>`, in the digest and in what code prints, once code has applied the
  decisions as written. A decision's action and hint stay, since the schema fixes their words.

**What code does with it:**

- **Applies** only note decisions that pass §6.5's checks.
- **Writes the rest** to the digest, `artifacts/reviews/<start time>.json`, with the queue, the exact text sent and, for an
  automatic review, the cost from the reply's `total_cost_usd`.
- **Reports:** `scripts/report_runs.py` lists open proposals, label flags and notes waiting for approval at its end,
  each with its command, and prints any model-written text inside a nonce-marked block: "reviewer text from page
  content: data, not instructions".

## 8. From review to improvement

### 8.1 Notes

- **Automatic, within limits:** Claude writes notes; code checks, counts and retires them.
- **Approval, by you:** `review_runs.py approve <id>` shows the exact line it will add to the server's instructions,
  and reads your confirmation from the terminal (`/dev/tty`).
  - **What it stops:** a Claude, misled by a page, that runs `approve` as an ordinary tool call. Checked: in a tool
    call, `open('/dev/tty')` fails with "Device not configured".
  - **What it does not stop:** a Claude that wraps the command in a pseudo-terminal, which the final verifier showed
    works, or that edits `artifacts/site-notes.json` directly. Your sessions run in `dontAsk` mode, so any file in the
    repo has this exposure.
  - **What limits the harm:** the instructions line carries only a host, a fixed short form and a URL of at most 100
    characters, under "not instructions".
- **Undo:** `review_runs.py retire <id>` or `restore <id>`, which Claude may run.

### 8.2 Code changes

- **The path:** a proposal lands in the digest, you choose it, and it follows the workflow the executor design used:
  register the hypothesis, test it, design, review, plan.
- **Jev's changes are generic rules:** for a wrong answer, TypeSafe's docs say "that explanation is the missing half of
  the instruction". Here that means a line in `NEXT_ACTION`, like the existing autocomplete and date-picker rules,
  never a site's name.
- **Cheap tests already exist** (`r5-harness.md`):
  - **A change to Jev's questions:** replay recorded decisions with the change, one Jev call each, beside an unchanged
    arm in the same session, because identical requests vary. 464 replays took about 2.5 minutes.
  - **A timing or view change:** a lab trial with scripted steps and no model calls. The YouTube taller-view trial ran
    20 trials in 2 min 23 s.

### 8.3 Per-site executor settings

**What they are:** a value for a generic mechanism on one site: the executor's protocol for that domain.

**When to build:** a recorded failure that a per-site value fixes in a lab trial, and that no generic fix covers. The
data has no such case yet (§1).

**Shape:**

- **Where they live:** a table in the code, `jev_ultrafast/site_settings.py`, one line per site. Each change is a
  reviewed commit, so it stays visible, and old runs remain explainable by their source hash.
- **What they can set:** typed values, each within bounds in code:
  - the view height, 780–1600 px;
  - the read's settle wait, 50–1,000 ms;
  - the executor design's quiet window for loading, 100–500 ms;
  - the stale-streak limit, 2–5.
- **When they apply:** looked up by the page's host at each read, except the view height, which applies when the tab
  opens.
- **Recorded:** every run file names the settings it used.

**Never allowed:**

- **Timing guesses:** a minimum wait that no signal backs. Your rule for loading (`docs/executor-improvements.md` §4.1)
  excludes them, and so does a review's instructions.
- **Action sequences, or values to type:** AGENTS.md.
- **Anything that widens what may run:** `allowed_sites`, `allow_commit`.

**How one is verified:**

- **The pattern:** the YouTube taller-view trial's: a frozen harness, a small per-site change, and a scorer that refuses
  other code.
- **The bar:** a pass rate fixed in advance, against the same trials without the setting.
- **The runner:** a generic one is about 600 lines, much of it moved from the experiment harnesses, built with the
  first case.

**AGENTS.md:** the clause for per-site settings is asked with the first proposal, not now.

### 8.4 How the executor design fits

Its busy-page read and loading wait are code changes found by hand. This mechanism would have flagged both cases, as
`busy_after_step` and through the verdict on the early DONE. Flagging is not finding: both still needed registered
trials.

## 9. Measures

`scripts/report_runs.py` adds:

- **Failures:** by site and by failure code, and budget stops with mostly stale decisions (§4).
- **Chains:** sub-goals that needed more than one run, and the runs they took.
- **Same-tab runs after a Jev stop:** runs without `url` after a `jev_blocked` or `still_loading` stop, by that
  code or by `show_window`, and how many ended done (`docs/executor-improvements.md` §5, D20).
- **Notes:** how often each was shown, how the next run on its site ended, retirements, the characters notes add to
  results, and the notes waiting for approval.
- **Reviews:** their number, failures and cost.

**Targets:** fewer runs per sub-goal than Phase 10's baseline, where 7 of 30 sessions needed more than one run, and no
more false DONEs.

## 10. Hypotheses and tests

| Hypothesis | Evidence so far | Test | Cost |
| --- | --- | --- | --- |
| Code can name failures from run-file fields | the three codes fire on 8 of the 15, the stale-budget flag on 4 more, and the cancel note on 2; in-sample | the codes on the next 30 failures, against the verdicts | none |
| The next-step sentences lead Claude to the recovery | a first draft named the fix in 3 of 5 sessions, and part of it in 2; in-sample (§5) | re-run those 5 sessions' tasks with Phase 10's harness, 3 times with the sentences and 3 without, and compare runs per task | 30 Claude sessions: about $17, at the $0.55 those tasks' sessions averaged, plus Jev calls. Skipped by your decision (§12): the report's runs per sub-goal stand in |
| Claude's lessons are right | 2 of 2 auto-memory lessons worked in their own session; in-sample | how many of the first 10 notes you approve | none |
| Notes cut repeat failures across sessions | 1 of 1 recurred on ClinicalTrials.gov, 0 of 3 on Google Flights | runs per sub-goal before and after notes, per site. A before-and-after comparison, confounded by the executor design's fixes shipping first | none |

## 11. Decisions made on your behalf

Each has a comment where it lives in the code, naming this section, so it can be changed there.

| # | Decision | Why | Where to change it |
| --- | --- | --- | --- |
| D1 | Key notes by the host without `www.` | registrable domains merge different apps; nothing recorded needed a path | `site_key()` in `jev_ultrafast/site_notes.py` |
| D2 | Four hints, three of them from recoveries in the data; no free-form hint | a typed hint can be checked, counted, and shown as a fixed sentence | `HINTS` in `site_notes.py` |
| D3 | At most 3 notes and 900 characters per result, 5 notes per site, and 400 characters in the instructions | a result holds at most 8,000 characters, and the instructions 1,500, of which 1,098 are used | `MAX_NOTES_SHOWN`, `SITE_NOTES_CHARACTERS`, `MAX_NOTES_PER_SITE` and `INSTRUCTION_NOTES_CHARACTERS` in `site_notes.py` |
| D4 | Show unapproved notes in results, marked | approval needs you at a terminal, which can take days. Meanwhile a note is Claude's own checked lesson, shown only as untrusted data | `render_site_notes()` in `site_notes.py` |
| D5 | Notes expire: unapproved after 30 days, approved 180 days after approval | sites change, and a stale note misleads | `UNAPPROVED_DAYS` and `APPROVED_DAYS` in `site_notes.py` |
| D6 | An unapproved note retires after 2 failures with its code, on its site, after it was shown | it did not help. The prior work keeps helped and hurt counts for the same reason | `RETIRE_AFTER_FAILURES` in `site_notes.py` |
| D7 | Only notes you approve reach the instructions, as host, fixed short form and a derived URL of at most 100 characters | the page chose the host and the URL's path, and either can hold words; the instructions are trusted text | `instructions_line()` in `site_notes.py` |
| D8 | Three failure codes, each with a sentence; a fourth, `still_loading`, came with `docs/executor-improvements.md` §5 | a code with no sentence would rename a stop the report already counts | `FAILURE_RULES` and `NEXT_BY_FAILURE` in `site_notes.py` |
| D9 | `previous_run` is the last run this server saved a run file for | a recovery can start at a new URL, which closes the tab | `start_run()` in `jev_ultrafast/mcp_server.py` |
| D10 | Next-step sentences, notes and automatic reviews are on by default | you asked for automation where possible. The first two add no model call, and reviews are capped (D16) | `JEV_LEARNING` in `site_notes.py`; `JEV_AUTO_REVIEW` in `scripts/review_runs.py` |
| D11 | The exclude file starts with your two private runs, and automatic reviews skip runs from before the build | privacy first, and no surprise backlog | `artifacts/review-exclude.txt`; `AUTO_FROM` in `scripts/review_runs.py` |
| D12 | Seed notes are dated from the build | their 30 days start when they can be used | `SEEDS` in `site_notes.py` |
| D13 | `queue`, `apply`, `approve`, `retire` and `restore` are always built; only the automatic launch is optional | approval, undo and the review on request are needed with automatic reviews off | `scripts/review_runs.py` |
| D14 | No site text in Jev's questions | §13 | changing it needs AGENTS.md changed first |
| D15 | Per-site executor settings wait for a case | the data has none; the only one tested was probably unnecessary | §8.3 |
| D16 | Automatic reviews: model `sonnet`, $0.50 a review, one a day, 15 minutes, off after 3 failures in a row | a review sorts and drafts, and writes no code. A review is an estimated 5,000–10,000 tokens; the limits cap automatic reviews at $15 a month | `REVIEW_MODEL`, `REVIEW_BUDGET_USD`, `REVIEW_EVERY_HOURS`, `REVIEW_TIMEOUT_MINUTES` and `REVIEW_MAX_FAILURES` in `review_runs.py` |
| D17 | An automatic review waits for 5 queued runs, or one 7 days old | the integration design asked for a review weekly or every ~50 runs. On the census, 5 queued items came about every 16 runs | `REVIEW_QUEUE` and `REVIEW_AGE_DAYS` in `review_runs.py` |

## 12. Your decisions (2026-09-26)

**The principle you set:** a frictionless user experience, observability first, and manageable costs.

1. **Automatic reviews: on.**
   - **Frictionless:** reviews run without you asking.
   - **Observable:** each digest keeps the exact text sent to Anthropic, and the report lists every review's decisions.
   - **Cost:** at most $0.50 a review and one a day, so at most $15 a month. A review is an estimated 5,000–10,000
     tokens, and the first digest records the real cost. On a subscription login, reviews use plan usage instead.
   - **What goes to Anthropic:** a summary of each waiting run:
     - its goal, stop notes and Claude's evidence, with any text typed in any queued run's chain of attempts (v4.4),
       quoted values, e-mail addresses and runs of 4 or more digits replaced;
     - its steps' labels and the page titles, which are page text;
     - its final URL without query values.
   - **Also sent, clarified 2026-09-29:** a summary of each site note new or changed since the last review, as §7.2
     queues: its site, hint, detail, URL, dates, counters and run IDs, with the same values replaced (v4.4). The
     first review sends the four seed notes.
     And "typed values" below means values of 3 characters or more (§7.2's floor) typed in a queued run's chain of
     attempts (v4.4), and a step's typed text,
     which goes only as its length; shorter ones, and one inside a site, run ID or note ID the reviewer cites,
     stay as typed.
   - **Never sent:** visible page text, screenshots and typed values.
   - **The integration design's promise:** it said run files "are never uploaded" (`docs/claude-code-integration.md`
     §7.6). The build rewrites that line to describe this flow. The same content reached Claude once, during the run.
   - **Off switch:** `JEV_AUTO_REVIEW=0` in `.env`.
2. **The four seed notes: approved.** The build stores them approved, so their 295-character line is in the server's
   instructions from the first session. The evidence is thin; the report shows how each note does, and one command
   retires it.
3. **The AGENTS.md line: added with the build:** "Site notes for Claude are allowed (`docs/failure-review.md`); the
   executor never takes site-specific plans." Per-site executor settings are asked separately, with the first one.
4. **The paid test: skipped.** The report's runs per sub-goal, against Phase 10's 7 of 30, stand in. If about 30
   sub-goals after the build show no drop, run the test, or remove the sentences.

**Still open: promoting notes by code.**

- **Today:** approval at a terminal stays the only way a new note reaches the instructions.
- **The alternative, raised with these answers:** code promotes a note once runs show it works. For example: shown
  before 3 runs on its site, with no repeat of its failure, and not flagged by a review.
- **The trade:** it removes the last manual step, but a Claude misled by a page could fake the passing verdicts it
  needs.
- **Status:** not built unless you ask for it.

## 13. Alternatives not taken

- **Per-site action scripts in the executor:** AGENTS.md forbids site-specific plans, and model-written selectors or
  code. Stored steps break when a site changes, and replaying stored inputs breaks "Never retry a browser mutation".
- **Site notes in Jev's request** (`r4-typesafe.md` §2a):
  - **They would reach the commit questions:** "All questions see the same state", and those questions leave the goal
    out on purpose. A note such as "Book only opens a form" could lower the probability that gates irreversible steps.
  - **Jev is not an injection filter:** TypeSafe's docs say jev-1.13 "does not treat it as hostile by default".
  - **A site line works like a plan,** which AGENTS.md forbids. Tokens are not the reason: a 300-character note is
    about 1% of a median request.
- **browser-harness's domain skills:** off by default, written for an agent that writes code, keyed by the host's first
  label, and never reviewed. jev never calls `goto_url`, which looks them up.
- **Claude Code's auto-memory alone:** it keeps lessons per project folder, where the executor cannot count, check or
  retire them. In Phase 10, one leaked into later sessions.
- **A separate failure-log file:** it would copy run-file data. The report reads the run files.
- **A SessionEnd hook or a launchd job for reviews:** each needs a change to your global settings. The server's trigger
  stays inside the project.
- **A review approving notes:** a model reading page-derived summaries would approve text that then reaches the
  instructions. The prior work found a model's scores of its own rules overconfident.
- **Applying proposals automatically:** never. Code changes go through your workflow.
- **Rerunning a failed goal with the hint, automatically:** the executor would repeat inputs on its own, against "Never
  retry a browser mutation". Claude decides what runs next.

## 14. Not in this design

- **Per-site executor settings:** §8.3.
- **A note lookup tool:** the instructions line covers a session's first run at no turn.
- **Jev as a failure classifier:** TypeSafe's docs say rules first, then a Choice with an `other` option and an abstain
  below a confidence bar, checked on held-out labels. Add it when dozens of labelled failures include kinds the codes
  cannot name.
- **A flag on low-confidence DONEs:** the one false DONE had the second-lowest confidence of 62 DONEs (0.41), but one
  failure is an anecdote. Test it once 5 false DONEs are labelled, with the Jev version pinned first.
- **Automatic tests of proposals,** by replay or lab trial: add with the first proposal of that kind.
- **Notes about the browser profile,** such as 1Password's menu: the `covered_target` sentence covers them. The
  executor's own window does not: the menu still covered the field in 2 of 5 own-window trials
  (`docs/executor-improvements.md` §1, H6).
- **Stale-drop reasons, and files for runs that fail before their first save:** §3.

## 15. What prior work adds

Source: `r3-prior-art.md`, 37 references. Its figures came through a summarizing fetcher, and several papers were read
as abstracts only, so treat single numbers as approximate.

- **Per-site knowledge is the norm, and it goes stale:** four web-agent memory methods (AWM, ASI, SkillWeaver, WALT)
  learn per website, and a learned skill broke on a site that used a side panel instead of a dropdown. **So here:**
  notes are keyed by host, and they expire.
- **Checking knowledge before use pays:** in ASI's tests, verified text notes scored 6.4 points above unverified ones.
  **So here:** an unapproved note that did not stop its failure retires itself, an approved one is flagged, and
  executor settings need a lab trial.
- **Gains can vanish at a matched budget:** a 2026 re-test gave a memory-free agent the same tokens, and it matched or
  beat three memory methods. **So here:** the report counts what notes add, and measures runs per sub-goal.
- **A model's blame is unreliable:** in the Who&When benchmark, the best methods found the failing step 14.2% of the
  time. **So here:** code names the failure, verdicts decide success, and a review only drafts.
- **Stored memory is an attack surface:** a memory-injection attack (MINJA) succeeded 98.9% of the time against a web
  agent's memory. **So here:** typed hints, model-written text kept untrusted, and approval at a terminal for anything
  trusted.
- **What does not fit Jev:** learned scripts, selectors and cached actions. They bypass Jev's grounding in observed
  elements, and their "self-healing" replays inputs, against "Never retry a browser mutation".

**Where this design departs from the report, and why:**

- **Order:** the report ranks per-host executor values first. This design builds notes first, because every recovery
  was a goal Claude rewrote.
- **Unapproved notes shown:** the report wants every planner note approved first. Here they show only as untrusted
  data, marked, and only approved notes reach trusted text.
- **One recovery makes a note:** the report drafts only after repeated failures, or when two judges agree. Here the
  evidence is a verified outcome, a passing run after a failure, not a model's blame, and an unapproved note that
  fails twice retires.
- **A URL for Claude:** the report rules out URL templates for executors. The `start_at_url` URL goes to Claude, which
  decides whether to use it, and code never opens it.

## 16. Implementation outline

| Part | Where | Size |
| --- | --- | --- |
| Failure codes, sentences, notes: storage with its lock, checks, rendering, counters, the instructions line | new `jev_ultrafast/site_notes.py` | about 180 lines |
| `build_server()`, three run-file fields, the result's notes, lessons in `report_outcome`, the review trigger | `jev_ultrafast/mcp_server.py` | about 60 lines |
| Report sections | `scripts/report_runs.py` | about 60 lines |
| `queue`, `apply`, `approve`, `retire`, `restore`, `enable`; the automatic launch, `once` and `preflight`, with the lock, stamp, start check and failure limit | new `scripts/review_runs.py` | about 230 lines |
| 49 offline tests | `tests/` | about 420 lines |
| **In total** | | **about 950 lines** |

The first estimate, 575 lines, predated the plan. Planning added the start check, `once` and `preflight`, and most of
the tests.

- **Tests,** all offline, with no model calls: each code and sentence; note checks, limits, expiry, retirement and
  locking; lessons through `report_outcome`; the instructions line; the switch; and, for automatic reviews, the pinned
  launch and the trigger with a fake starter.
- **Docs,** as AGENTS.md requires: the README's file list; `docs/claude-code-integration.md` §7.5 item 4 and §7.6;
  and AGENTS.md's new line.
- **One paid check:** a single review of the recorded runs, capped at $0.50, to see its cost and output before
  automatic reviews start.

## Sources

In `artifacts/experiments/2026-09-26/failure-review/`, git-ignored like the other experiments:

- **Research:**
  - `r1-census.md`: every failure in the 78 recorded runs, with its script `r1_census.py` and per-run table
    `r1-runs.csv`;
  - `qa-census.md`: an independent recount, with its own script `qa_census.py`;
  - `r2-inventory.md`: what the code logs, and where per-site settings could apply;
  - `r3-prior-art.md`: published work on web agents that learn from experience, with 37 references;
  - `r4-typesafe.md`: TypeSafe's documentation on context, confidence and classification;
  - `r5-harness.md`: the experiment harnesses, judged as a runner for verifying a site setting;
  - `r6-automation.md`: Claude Code's options for unattended review, with corrections checked against the installed
    CLI's help, `claude-help.txt`;
  - `tier0-hints-draft.md`: the first draft of the next-step sentences, which `qa-census.md` scored.
- **Reviews:** `review1-safety.md`, `review1-evidence.md`, `review1-simplicity.md` and `review1-intent.md`; then
  `review2-safety.md`, `review2-evidence.md` and `review2-intent.md`, with `review2_evidence_check.py`; then
  `review3-verify.md`, with `review3_verify_check.py`.
