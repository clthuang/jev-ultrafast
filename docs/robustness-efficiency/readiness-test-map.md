# Readiness inheritance and owned event adapter

Status: implemented on 2026-10-04. The tables below were the preparation's exact destinations; every node now exists and passes, with the deviations recorded in [Implementation record](#implementation-record). The adapter is `websockets`' sync client rather than `cdp_use`, with the same lifecycle, session and queue contract.

## Evidence and precedence

- Current design: `docs/executor-improvements.md` §2.5 (345–395), §4.4 (1514–1669), §4.6 (1730–1902).
- The original 24 executable loading tests and fixture are in [readiness-design-v41.diff](readiness-design-v41.diff), lines 269–637 (originally `artifacts/experiments/2026-09-24/h8-network-settle/design-check/v4/design-v41.diff`). They are historical test source, not current implementation evidence.
- Original cases 25–27 are specified in `docs/executor-improvements-plan.md:419–450`.
- Current stage contracts: `docs/robustness-efficiency-implementation-plan.md:543–587`; explicit exceptions: [implementation-clarifications.md](implementation-clarifications.md), items 3–5.
- Browser/Agent integration was read from the captured `baseline/jev_ultrafast/{browser,agent}.py`; POLICY is concurrently changing candidate Agent interfaces. Use the final POLICY/EXECUTION interfaces when implementing these tests.

Only three inherited adaptations are authorized here: valid new goals reset loading state (case 25), stop checks beat a loaded terminal answer (case 26), and private event ownership replaces the shared destructive daemon drain. Preserve all other behavioral assertions. A disconnected private stream gets a clear event-connection error instead of the obsolete shared-daemon empty-reply error text.

## Test fixture contract

Use the real `Agent.command` and real `Browser` loading logic with injected scripted decisions, a fake event source, fake CDP, and fake monotonic time. Do not use a FakeAgent.command that bypasses guards. Supply explicit allowed operations to constructor/new_goal. Patch `choose` with a signature accepting the current arguments and keywords.

The fake source exposes only its owned session, starts delivering Network events only after its acknowledged `Network.enable`, and holds at most 500 compact events. It has a locked queue, explicit loss/failure injection, and a separate other-session queue whose contents can be asserted unchanged. Keep the old schedule helpers `sent`, `ended`, `at`, and `click` conceptually; use a stable observer-session ID different from the browser's action-session ID. Fake-clock `sleep` advances test time. Thread coordination uses Events/barriers and short real joins, not the frozen fake clock.

Old pressure fixtures used OTHER-session events to fill the global daemon buffer. In the owned-source tests use own-session irrelevant Image events for the same pressure, and separately assert OTHER-session traffic is neither consumed nor counted as loss. This is a transport adaptation, not permission to drop saturation coverage. Retain the conservative full-buffer loss assertion, or expose an explicit source overflow flag that produces the same loss in the inherited 601-event cases.

`R` below expands exactly to `tests/test_readiness_contracts.py::`. Every table row must acquire its actual command/result/assertion record when implemented.

## §2.5 post-step read mapping

| Old case | Exact destination | Required assertion |
| --- | --- | --- |
| 1 | `Rtest_timed_out_read_after_a_step_is_repeated` | One completed click, first post-step observe raises TimeoutError, second returns a changed result page: act=1, observe=2, repeated_reads=1, status ready, history URL and page_changed come from the second page. Execution is already saved before either read. |
| 2 | `Rtest_timed_out_reads_stop_after_the_last_repeat` | Three post-step TimeoutErrors: act=1, observe=READ_TIMEOUT_REPEATS+1=3, repeated_reads=2, TimeoutError propagates through the direct act boundary, history retains page_changed=None. No input replay. |
| 3 | Withdrawn in §2 v2 | No dialog precheck is reintroduced. Mark this case withdrawn, not passed. |
| 4 | `Rtest_stop_check_runs_before_each_repeated_read` | First post-step observe times out; cancellation/deadline is injected before a retry starts. One act, one observe, repeated_reads=0, shared stop reason preserved. Use a phase-triggered callback, not the old brittle two-call Mock sequence, because the new guards run more often. |
| 5 | `Rtest_only_a_timed_out_read_is_repeated` | Direct act receives StalePage on its post-step read: exactly one observe, repeated_reads=0, StalePage propagates to tick's existing recovery owner. Parameterize a non-timeout RuntimeError too: it is not a retry. |
| 6 | `tests/test_agent.py::test_new_goal_resets_every_counter` | Valid new goal clears repeated_reads and loading_waits with all other per-goal counters; invalid-policy continuation preserves them and browser loading state (also §4 case25 replacement). |
| 7 | Withdrawn in §2 v2 | No private pending-dialog query or its fail-closed branch is restored. |
| 8 | `tests/test_mcp_server.py::test_a_read_that_timed_out_after_a_click_is_repeated` | Real Agent tick behind run_goal, scripted CLICK then DONE, one-shot post-click TimeoutError: response done, act=1, one history step, repeated_reads=1, page_changed=False for the unchanged fake page (not None). Preserve the independent final-read count separately. |
| 9 | `tests/test_report_runs.py::test_report_counts_false_and_missed_done` | One run has repeated_reads=2; old runs omit the key. Report includes `repeated reads 2`; missing historical fields are accepted. |
| Live10/11 | Withdrawn in §2 v2 | These were the removed dialog-precheck live checks; do not revive them. |

No constructor read, pre-choice refresh, recovery read, freshness check, text request, input dispatch, or final verification read gets this timeout retry wrapper. The wrapper starts only after completed execution has been logged/saved. Tick remains the only outer StalePage counter owner.

## §4.6 loading mapping

| Old case | Exact destination | Required assertion |
| --- | --- | --- |
| 1 | `Rtest_loading_wait_tracks_only_this_tabs_content_requests` | After first input, own main-frame Document and Fetch are tracked; duplicate requestId redirect remains one entry; other sessions, Image and cross-site iframe Document are ignored. loadingFinished and loadingFailed remove only their tracked IDs. |
| 2 | `Rtest_loading_wait_ends_after_quiet_or_5_s_after_the_input` | No pending request returns [0,False,False]. Request starts +300ms, ends +1100ms; answer at +400ms waits 800–820ms including 100ms quiet, uncapped/no loss. Never-ending request with answer at +400ms waits 4600–4620ms, capped at original input+5000ms. |
| 3 | `Rtest_loading_wait_runs_at_every_answer_until_5_s_after_the_input` | Before input returns None; two answers after an idle input each return [0,False,False]. WAIT at +3000ms does not move input_done; at +5000ms return None. Repeated answers never start a new five-second allowance. |
| 4 | `Rtest_loading_wait_stops_when_the_run_stops` | Pending request plus shared cancellation callback raises its stop before fake time reaches 100ms; interrupted wait is not appended to loading_waits. Preserve pending loss for a later recorded wait. |
| 5 | `Rtest_done_and_blocked_wait_for_loading_before_the_freshness_check` | A CLICK does not invoke the loading gate. DONE records [748,False,False], then checks fresh; changed results raise StalePage. Call order is wait then fresh. BLOCKED takes the same path; None return adds no wait entry. Gate receives the shared Agent limit checker, not the obsolete raw before_input callback. |
| 6 | `Rtest_an_input_stopped_before_it_runs_keeps_the_last_inputs_deadline` | First click succeeds; never-ending request starts +100ms; second click is pre-input stale at +300ms. Its input does not run; the next gate waits 4700–4720ms, capped at first click+5000ms. |
| 7 | `Rtest_each_read_drains_the_buffer_so_it_cannot_overflow_before_the_answer` | Request starts100ms/ends2000ms; a successful read at600ms consumes its private queue despite 300 irrelevant own events during read; another300 arrive700ms. Answer900ms returns [1200,False,False]. OTHER-session queue remains untouched. |
| 8 | `Rtest_requests_an_earlier_input_started_are_still_waited_for` | Search starts request300ms ending2000ms; another successful input600ms preserves the request and gate returns [1500,False,False]. A later never-ending request seen within five seconds is retained and caps [5000,True,False]; an input after that request is five seconds old drops it, so [0,False,False]. |
| 9 | `Rtest_the_buffer_drains_while_jev_decides_once_tracking_has_started` | Before first input, draining context leaves queued unrelated traffic untouched. After input, while choose is blocked on a barrier, two batches totaling601 events are consumed separately, tracked result survives and loss=False. A later decision after a capped gate still drains. |
| 10 | `Rtest_jev_decides_inside_the_browsers_draining` | Real predict records exactly enter, choose, exit around the scripted model call. Exception exits also release the consumer thread; post-response shared guard still accounts for a late completed response before discarding it. |
| 11 | `Rtest_a_full_drain_marks_the_wait_as_lost` | Queue receives one tracked request followed by600 irrelevant own events before consumption, dropping the tracked start. Gate returns [0,False,True], not a fabricated in-flight request. Saturation is represented explicitly. |
| 12 | `Rtest_an_owned_event_connection_that_closes_stops_with_a_clear_message` | Private transport EOF/disconnect becomes clear RuntimeError with event-connection context, marks loss, and stops instead of interpreting missing data as an empty healthy queue. No fallback to global drain_events. This replaces the obsolete empty-daemon-reply/KeyError mechanism only. |
| 13 | `Rtest_the_start_pages_own_requests_are_not_waited_for` | Start-page never-ending request before any accepted input is not tracked; initial observation never enables Network. First input enables observer Network exactly once; two inputs with no new requests give [0,False,False]. Other-session saturation does not create own loss. |
| 14 | `Rtest_a_full_drain_before_an_input_is_recorded_in_its_wait` | After an input,600 irrelevant own events accrue during a helper interval; next input's preflight consumes saturated queue. Its next recorded wait lost=True; a subsequent clean recorded wait lost=False. |
| 15 | `Rtest_draining_returns_only_after_its_thread_has_ended` | Inject a blocked private-queue drain and exit the choose context while it is in flight. Context waits for its owned consumer to finish; no consumer thread survives return. Persistent transport receiver, if used, is counted separately and must terminate on Browser.close/reset. Never join while holding its queue lock. |
| 16 | `Rtest_a_drain_that_fails_while_jev_decides_marks_the_wait_as_lost` | Inject one transient private-source drain failure during choose; consumer exits and marks lost. Restore source; next empty recorded wait returns [0,False,True]. Permanent transport disconnect is the terminal case12, not silently recovered. |
| 17 | `Rtest_a_later_answer_waits_for_loading_that_started_after_the_first` | First answer after click returns [0,False,False]. Request appears300ms/ends1100ms; another answer400ms waits800–820ms, uncapped/no loss. No once-per-input suppression. |
| 18 | `Rtest_blocked_waits_and_a_zero_wait_records_its_lost_flag` | BLOCKED calls gate with shared stop guard; [0,False,True] is appended even though duration zero. Do not use duration truthiness to decide whether to record. |
| 19 | `Rtest_network_is_enabled_before_the_first_input_runs` | Fake input emits main-frame Document request synchronously during dispatch. The observer already received Network.enable acknowledgment and registered callbacks; subsequent track contains that request. Exactly one physical mutation. |
| 20 | `Rtest_a_loss_before_an_answer_that_does_not_wait_is_kept` | Saturation consumed during read marks lost. At input age5200ms gate returns None, so no record and no clearing lost. Next successful input then empty recorded wait reports lost=True. |
| 21 | `Rtest_scripts_count_and_untracked_ends_do_not_hold_the_wait` | Script and Image starts leave only Script tracked. Its end clears it. After quiet, an Image finish immediately before answer does not restart quiet; result [0,False,False]. |
| 22 | `Rtest_a_request_that_ended_before_an_input_adds_no_quiet_after_it` | Request starts100ms/ends250ms; new input300ms consumes both before it runs. No in-flight request remains and the new input resets last_request, so gate immediately [0,False,False]. |
| 23 | `Rtest_a_stopped_first_input_carries_nothing_into_the_first_that_runs` | First attempted input enables observer but fails pre-input. Start-page poll arrives100ms; actual first successful input300ms discards that pre-input loading, giving [0,False,False]. No first-input timestamp is installed by an aborted mutation. |
| 24 | `Rtest_a_drain_that_fails_in_a_read_marks_the_next_wait_as_lost` | After an input, a successful DOM read followed by a source drain TimeoutError fails observe and preserves lost=True. After source recovery, next empty gate yields [0,False,True]. §2 may retry this post-step TimeoutError; it must not reset loading state or repeat the input. |
| 25, superseded | `Rtest_valid_continuation_resets_loading_but_invalid_policy_preserves_it` | Seed pending request/input_done/lost, pending decision/text and trace. Invalid policy changes none of these and causes no read/subscriber action. Valid policy/new goal resets old loading/request timestamp/loss and loading_waits; first terminal answer does not wait on the prior goal. Explicitly record that old [920,False,False] carry-over assertion is rejected by the new contract. |
| 26, superseded | `Rtest_a_loaded_done_cannot_override_a_pending_stop` | Parameterize cancellation and exact deadline. A loaded DONE with no request pending still becomes stopped with the correct stop_code, clears executable decision/text and performs no input. If model/helper just returned, its completed request/latency/known usage remain recorded. Old stop.assert_not_called()/DONE-stands assertions are intentionally not retained. |
| 27 | `Rtest_a_read_before_the_first_input_leaves_the_buffer_alone` | Pre-input observe never creates/enables/consumes the owned source and never consumes another session's buffer; after a successful input, observe consumes the owned queue. Source failure injection before any input must not turn a good read into failure. |

Additional inherited changes:

- Rename existing `tests/test_agent.py::test_loading_waits_do_not_trigger_no_progress_stop` to `::test_wait_steps_do_not_trigger_no_progress_stop`; preserve its assertions (WAIT steps differ from the network gate). Keep §5's two unchanged WAIT handback unchanged.
- Extend `tests/test_agent.py::test_new_goal_resets_every_counter` for `loading_waits`, `repeated_reads`, and the private subscriber lifecycle reset.
- Extend `tests/test_report_runs.py::test_report_counts_false_and_missed_done` with loading_waits `[[748,False,False],[5000,True,True]]`: report `loading wait ms 5748`, `loading caps 1`, `loading event losses 1`. Historical runs omitting these fields remain readable.
- Server fake browsers may stub `draining`/`wait_for_loading`, because their frozen global clock cannot drive a real gate. The dedicated readiness tests must use real Browser/Agent logic. Test the existing cancellation real-tick path too.

## Current-plan composition nodes

All destinations are `R` unless fully qualified.

| Exact node | Required assertion |
| --- | --- |
| `test_loading_gate_respects_shared_deadline_and_policy` | Deadline/cancellation checked before/after readiness operations and every poll; no denied mutation/helper starts. Internal read-only readiness waiting does not grant the model WAIT permission. |
| `test_gate_wait_does_not_install_freshness_baseline` | Waiting/draining events cannot observe/replace the compact snapshot baseline/token. Final freshness compares against the original model observation and rejects changed results. |
| `test_loading_gate_records_loss_and_cap` | Assert wait ms, capped and lost independently; loss survives unrecorded/aborted waits and clears only after a recorded wait. |
| `test_timeout_reread_does_not_restart_loading_age` | First post-step read consumes five seconds and times out; repeated read succeeds. Original input timestamp remains; next final answer gains no fresh five-second gate. |
| `test_timeout_retries_preserve_single_input_and_uncertain_attempt` | Completed-input read failure produces one history execution; input-dispatch uncertainty never enters the retry wrapper and preserves attempt/phase. Count physical inputs as well as status/history. |
| `test_stop_before_retry_does_not_count_it` | Shared stop before a proposed reread yields repeated_reads unchanged and no extra observe. |
| `test_two_unchanged_waits_hand_back_once` | Actual snapshot adapter returns identical progress projection despite fresh observation tokens. Two permitted WAIT actions hand back once; no automatic re-ask or third step. |
| `test_five_second_reread_leaves_no_new_loading_allowance` | Combined actual snapshot adapter, post-input timeout, reread and gate preserve the original input age and exactly one physical input. |
| `test_changed_results_drop_pending_done` | Gate ends after fixture content changes; old DONE is stale, pending decision cleared, then one fresh choice occurs within shared recovery budget. |
| `test_valid_continuation_resets_loading_but_invalid_policy_preserves_it` | Replacement25 plus actual snapshot adapter and permission validation ordering. |
| `tests/test_browser_native.py::test_busy_page_and_loading_gate_compose_without_repeated_input` | Real isolated Chrome, scripted decisions, actual snapshot adapter, delayed content/busy-page fixture; fixture-side counters prove each physical input once and independent page/server state proves the result. Record rereads, loading waits, stale recoveries, stop reason and final read separately. |

## Native inherited acceptance and harness constraint

- §2 H5 local acceptance: port the archived synthetic busy-page fixture to the owned lab. Five trials must each finish done with each input once, exactly one server submission, repeated_reads=1. One post-input alert trial must stop with dialog dismissed and repeated_reads=2. A click that itself blocks on a dialog is a different input-timeout case and must never be retried. The removed dialog *precheck* remains removed.
- §4 local acceptance: before-request terminal answer does not wait; after-request answer waits until visible Loaded uncapped; never-ending request caps at input+5s; cross-site iframe Document does not hold the gate; main-frame navigation does; scroll during an earlier request retains it. Assert actual target/event identity and independent fixture output, not only gate return values.
- The legacy cross-site iframe uses `localhost` versus `127.0.0.1`. The current exact-origin proxy intentionally rejects localhost. At the READINESS native stage only, add a manifest-owned second exact fixture origin/alias mapped to the same fixed owned fixture server, or prove an alternative local-only OOPIF construction. Then rerun the harness denial proof. Never let a blocked iframe count as the old acceptance test: first assert a real separate iframe target/session exists. Do not widen arbitrary origin forwarding or DNS access. Root accepted this stage-specific requirement; no harness change was made during preparation.
- Historical external-site H8c/H8d repetitions remain unperformed validation, not a local gate substitute. No paid/live-site trials are authorized by this preparation.

## Smallest compatible owned event adapter

Keep the action connection through browser-harness unchanged. Add a small private event source per Browser; it never consumes `browser_harness.helpers.drain_events`.

1. **Lazy lifecycle.** Before the first physical input only, create an owned WebSocket client on an existing endpoint. No subscriber for an observation-only goal or WAIT alone. The source owns its receiver task/thread, attached session, locked capped queue and failure/loss state. Failed setup closes everything before input. Valid new_goal closes/resets the prior source after policy validation; invalid policy performs no source action.
2. **Endpoint binding.** Installed `browser_harness.daemon.get_ws_url()` is zero-argument and returns a WS URL string; BU_CDP_WS wins, BU_CDP_URL resolves /json/version, otherwise it probes profiles/default ports. It does not launch browsers/daemons. Import has .env/directory side effects: isolated BH_* and BU_* must already be configured. Resolve during bounded setup, do not log WS credentials, and confirm `Target.getTargetInfo(targetId=existing_browser_target)` on that connection before attaching. A mismatch/absence is terminal; never discover a replacement target or default tab.
3. **Public client API.** Installed `cdp_use.client.CDPClient(url)` has async `start()`, `send_raw(method, params, session_id=...)`, `stop()`; public `client.register.Network.requestWillBeSent/loadingFinished/loadingFailed` callbacks receive `(params, session_id)`. Attach with `Target.attachToTarget(targetId=existing_target,flatten=True)`. This returns a NEW observer session; never reuse the daemon's action session ID on the private connection. Register callbacks and await `Network.enable` for the observer before any physical input.
4. **Bounded setup/teardown.** `send_raw` itself has no timeout; wrap every setup request and start/stop in an explicit finite await timeout. Wait for setup acknowledgement in the caller; check the Agent guard before and after setup, then again after freshness/hit-test reads at the mutation boundary. Monitor receiver/connection completion even when no request is pending, so a dead source cannot look like network quiet. Never retry input or silently reconnect into a new page/session.
5. **Queue contract.** Callbacks ignore non-owned sessions; copy only method/requestId/type/frameId into a lock-protected bounded queue (no request bodies, headers or URLs). Full/lost delivery latches loss. `read_events()` atomically returns/clears only this source's events and loss marker; source errors surface to Browser._track. Do not silently change the old notion of request seen-time: the old tracker timestamps events when `_track` consumes them, using the injected monotonic clock, not Chrome's unrelated Network timestamp.
6. **Preserve Browser semantics.** `_track` maintains loading IDs and last_request; observe consumes only after tracking starts; pre-input consumption retains unfinished requests seen less than five seconds ago only if a prior input actually succeeded. Set input_done only after successful mutation completion. WAIT/aborted input do not move it. The five-second gate uses original input_done, 100ms quiet and20ms polls with no minimum delay; terminal freshness follows it without replacing the baseline.
7. **Keep the inherited consumer context.** A persistent receiver can fill the private queue, while `Browser.draining()` consumes it every20ms around choose. This small consumer context preserves old enter/choose/exit and join assertions without touching the daemon. Its worker must join before leaving the context; the persistent receiver closes separately on Browser.close/new_goal. No queue lock may be held across CDP, model work, or thread join. Main read failures propagate; background consumer failures latch loss for the next main read/wait.
8. **Diagnostics.** Permanently closed receiver is a clear terminal event-connection error; transient injected queue-read failure preserves lost for the inherited tests. Never treat a malformed reply/disconnected source as an empty queue. Private-source failures must not erase completed mutation history or an uncertain attempt. Preserve unknown model usage and existing final-read overhead semantics.

Public API evidence was inspected locally under candidate `.venv/lib/python3.13/site-packages`: `browser_harness/helpers.py:80` and `daemon.py:678–680` prove the global drain clears all events; `daemon.py:264–342` implements resolver behavior; `cdp_use/client.py:229–299,361–389` exposes client lifecycle/raw calls; `cdp_use/cdp/network/registration.py:96–123,158–171` exposes the three callbacks. No dependency modification is needed.

Add focused adapter tests for target mismatch before enable/input, distinct observer/action sessions, Network.enable ordering, another source's queue untouched, saturation, setup timeout cleanup, disconnect with no pending command, consumer join, receiver close and valid/invalid continuation lifecycle. The existing native manifest/endpoint guard applies before any direct WebSocket connection.

## Implementation record

Command: `uv run python scripts/plan_tests.py READINESS --native`, which collects every node above (the plan's
Verify nodes plus `readiness-required-tests.json`) and fails on a missing node, an empty collection or any failed,
skipped or xfailed variant: 45 named nodes, 48 variants passed (47 offline, 1 native), no problems. Each row's
assertions are as specified above, except where noted here.

- **§2.5 cases 1, 2:** as specified. Case 2 also pins `READ_TIMEOUT_REPEATS == 2` literally, so a smaller cap fails.
- **§2.5 case 4:** the stop is armed by the first post-step read's own timeout (a phase trigger, not a call count).
- **§2.5 case 5:** "exactly one observe" is one `Browser.observe` call after the step; inside it, browser.py's existing
  settle loop re-reads a navigating document up to 10 times, which is not a §2 repeat. The RuntimeError variant stops
  the run with `execution_error`; the StalePage variant leaves it running for tick's recovery.
- **§4.6 case 1:** the fake source holds only the tab's own events, so the other-session half is asserted on the real
  connection: `test_another_sessions_traffic_is_never_taken` (600 events on another session neither delivered nor
  counted as loss; no import, name or attribute `drain_events` in `events.py` or `browser.py`).
- **§4.6 cases 7, 9, 11, 14, 20 (pressure):** own-session Image events stand in for the old shared-buffer pressure.
  Loss is the source's explicit overflow flag; a read of exactly 500 events is not loss (pinned on the real queue).
- **§4.6 case 9:** the drain thread runs on the real clock and the test waits for the queue to empty, instead of a
  barrier inside `choose`; case 10 asserts the enter/choose/exit order around the real `predict`.
- **§4.6 case 12 (replaced):** `EventConnectionLost` is a `RunStopped` (a `ValueError`, like every structured stop), not
  a `RuntimeError`; its message is "The loading wait's browser connection closed."; the run is stopped with
  `event_connection_lost`, one source only (no reconnect), the run file saved.
- **§4.6 case 15:** the drain thread is found by its name, `jev-drain`, so unrelated threads cannot mask a survivor.
- **§4.6 case 19:** the fake source acknowledges `Network.enable` in its constructor, which `Browser.act` calls before
  the input; the input asserts the acknowledgment is already recorded.
- **§4.6 cases 25, 26 (replaced):** as specified. Case 25 runs on the actual snapshot adapter (no read, the same
  generation, for an invalid policy; one new read for a valid goal), so it is also the composition node. Case 26's
  completed DONE stays accounted with `discarded` set to the stop's code.
- **Composition nodes:** `test_loading_gate_respects_shared_deadline_and_policy` also asserts that Jev was never offered
  WAIT under a CLICK-only policy and that the stopped DONE reached no freshness check;
  `test_timeout_retries_preserve_single_input_and_uncertain_attempt` records the uncertain input's phases
  (`mouse_press_uncertain`, input started) and that it set no loading deadline.
- **Additional tests, not in the tables:** the first input's setup is bounded by the run's remaining budget and
  followed by its stop check; a source that cannot attach stops the run before the input; the final read never touches
  the source (`test_the_final_read_never_touches_the_source`, and the server passes `track=False`); the gate modes;
  your own Chrome's connection opens at setup, or at a new goal's setup, never inside a run.
- **Native acceptance:** the composition node and §4's six local lines run in the owned lab against
  `tests/fixtures/readiness.html`; §2's H5 acceptance is
  `tests/test_browser_native.py::test_busy_page_reads_again_without_repeating_the_input` (5 busy-page trials and the
  dialog trial). The cross-site iframe uses the lab's second fixture site, `jev-frame.test` at the fixture's port, not
  `localhost`; the test first asserts a real out-of-process iframe target, then that its document request arrived as
  the iframe's own frame. The egress proof was rerun with the new site (canary: 0 connections). Results: status.md §4.3.
- **Withdrawn, not passed:** §2.5 cases 3 and 7 and the live checks 10 and 11, as specified above.
- **Not performed:** the historical live-site trials (H8c/H8d, and H5 on arXiv). They need live sites and paid models
  and remain validation limits.
