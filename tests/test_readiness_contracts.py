"""Inherited readiness contracts through real Browser/Agent and deterministic private events."""

import asyncio
import contextlib
import threading
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_execution_contracts import ALL_OPERATIONS, choice, observed_page
from test_snapshot_contracts import javascript

from jev_ultrafast import agent as loop
from jev_ultrafast import browser
from jev_ultrafast.browser import StalePage, UncertainAction
from jev_ultrafast.contracts import RunStopped
from jev_ultrafast.readiness import ReadinessConnectionError

SNAPSHOT_OPERATION = browser.browser_operation


def sent(request_id, kind="XHR", frame="main", session="observer"):
    return {
        "method": "Network.requestWillBeSent",
        "requestId": request_id,
        "type": kind,
        "frameId": frame,
        "session": session,
    }


def ended(request_id, method="Network.loadingFinished"):
    return {"method": method, "requestId": request_id, "session": "observer"}


@pytest.fixture
def tab(monkeypatch):
    clock, scheduled, sources, calls = [0], [], [], []
    lock = threading.Lock()

    class Source:
        main_frame_id, session_id = "main", "observer"

        def __init__(self, target, **control):
            assert target == "target"
            self.enabled_at, self.closed, self.failure = clock[0], False, None
            self.drains = 0
            sources.append(self)
            calls.append("Network.enable")

        def read_events(self):
            self.check_health()
            self.drains += 1
            with lock:
                due = [
                    record
                    for at, record in scheduled
                    if at <= clock[0] and record["session"] == "observer" and at >= self.enabled_at
                ]
                scheduled[:] = [
                    (at, record) for at, record in scheduled if at > clock[0] or record["session"] != "observer"
                ]
            return [{key: value for key, value in record.items() if key != "session"} for record in due[-500:]], len(
                due
            ) > 500

        def check_health(self):
            if self.failure:
                raise self.failure
            assert not self.closed

        def close(self):
            self.closed = True

    def at(ms, *events):
        with lock:
            scheduled.extend((ms, event) for event in events)

    def sleep(seconds):
        clock[0] += round(seconds * 1000)

    monkeypatch.setattr(browser, "time", SimpleNamespace(monotonic=lambda: clock[0] / 1000, sleep=sleep))
    monkeypatch.setattr(browser, "OwnedNetworkEvents", Source)
    instance = browser.Browser.__new__(browser.Browser)
    instance.target, instance.session = "target", "action-session"
    instance.reset_loading()
    instance.call = Mock(return_value={})
    instance.fresh = Mock(return_value=True)
    current = observed_page()

    def operation(request, **control):
        if request["operation"] == "observe":
            return deepcopy(current)
        calls.append(request["action"]["kind"])
        return {}

    dispatch = Mock(side_effect=operation)
    monkeypatch.setattr(browser, "browser_operation", dispatch)
    yield SimpleNamespace(
        browser=instance,
        clock=clock,
        at=at,
        sources=sources,
        calls=calls,
        scheduled=scheduled,
        operation=dispatch,
        current=current,
    )
    if instance._event_source:
        instance._event_source.close()


def click(tab, kind="button"):
    page = observed_page()
    action = next(item for item in page["actions"] if item["id"] == kind)
    return tab.browser.act(action, page)


def runner(tab, policy=ALL_OPERATIONS):
    agent = loop.Agent.__new__(loop.Agent)
    agent.browser = tab.browser
    agent.screenshots = False
    agent.record_dir = agent.trace_path = agent.pending_text = agent.before_input = None
    agent._fresh_state("Find a book", observed_page(), None, allowed_operations=policy)
    agent.state["started_at"] = time.perf_counter()
    return agent


def act(agent, selected="button"):
    agent.state.update(decision=choice(selected), status="predicted")
    return agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})


def snapshot_adapter(tab, agent, monkeypatch):
    """Use actual snapshot.js output and the production snapshot adapter for composition."""
    snapshots = javascript("({page,after:eval(source)})")
    for page in snapshots.values():
        page["fingerprint"] = browser.fingerprint(page)
    tab.current.clear()
    tab.current.update(snapshots["after"])
    agent._fresh_state(agent.state["goal"], snapshots["page"], None,
                       allowed_operations=sorted(agent.allowed_operations))
    fake_operation = tab.operation.side_effect

    def protocol(method, **params):
        assert method == "Runtime.evaluate" and params["expression"] == browser.READ_STATE
        return {"result": {"value": deepcopy(tab.current)}}

    def operation(request, **control):
        if request["operation"] == "observe":
            return SNAPSHOT_OPERATION(request, **control)
        return fake_operation(request, **control)

    monkeypatch.setattr(browser, "cdp", protocol)
    tab.operation.side_effect = operation


def test_loading_wait_tracks_only_this_tabs_content_requests(tab):
    click(tab)
    tab.at(
        0,
        sent("main", "Document"),
        sent("fetch", "Fetch"),
        sent("fetch", "Fetch"),
        sent("image", "Image"),
        sent("iframe", "Document", frame="iframe"),
        sent("foreign", session="other"),
    )
    tab.browser._track()
    assert set(tab.browser.loading) == {"main", "fetch"}
    tab.at(0, ended("main"), ended("fetch", "Network.loadingFailed"))
    tab.browser._track()
    assert not tab.browser.loading and len(tab.scheduled) == 1


def test_loading_wait_ends_after_quiet_or_5_s_after_the_input(tab):
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]
    tab.at(300, sent("result"))
    tab.at(1100, ended("result"))
    tab.clock[0] = 400
    wait, capped, lost = tab.browser.wait_for_loading()
    assert 800 <= wait <= 820 and not capped and not lost
    click(tab)
    started = tab.clock[0]
    tab.at(started + 300, sent("forever"))
    tab.clock[0] += 400
    wait, capped, lost = tab.browser.wait_for_loading()
    assert 4600 <= wait <= 4620 and capped and not lost


def test_loading_wait_runs_at_every_answer_until_5_s_after_the_input(tab):
    assert tab.browser.wait_for_loading() is None
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]
    assert tab.browser.wait_for_loading() == [0, False, False]
    tab.clock[0] = 3000
    click(tab, "wait")
    assert tab.browser.input_done == 0
    tab.clock[0] = 5000
    assert tab.browser.wait_for_loading() is None


def test_loading_wait_stops_when_the_run_stops(tab):
    click(tab)
    tab.at(0, sent("forever"))

    def stop():
        if tab.clock[0] >= 40:
            raise RunStopped("cancelled", "stop")

    with pytest.raises(RunStopped):
        tab.browser.wait_for_loading(check_stop=stop)
    assert tab.clock[0] == 40


@pytest.mark.parametrize("selected", ["DONE", "BLOCKED"])
def test_done_and_blocked_wait_for_loading_before_the_freshness_check(tab, selected):
    agent = runner(tab)
    order = []
    tab.browser.wait_for_loading = Mock(side_effect=lambda **_: order.append("wait") or [748, False, False])
    tab.browser.fresh.side_effect = lambda *a, **kw: order.append("fresh") or False
    with pytest.raises(StalePage):
        act(agent, selected)
    assert order == ["wait", "fresh"] and agent.state["loading_waits"] == [[748, False, False]]
    assert tab.browser.wait_for_loading.call_args.kwargs["check_stop"] == agent.check_stop
    assert agent.state["decision"] is None


def test_an_input_stopped_before_it_runs_keeps_the_last_inputs_deadline(tab):
    click(tab)
    tab.at(100, sent("forever"))
    tab.clock[0] = 300
    tab.operation.side_effect = StalePage("before input")
    with pytest.raises(StalePage):
        click(tab)
    assert tab.browser.input_done == 0 and tab.calls.count("click") == 1
    waited = tab.browser.wait_for_loading()
    assert 4700 <= waited[0] <= 4720 and waited[1]


def test_each_read_drains_the_buffer_so_it_cannot_overflow_before_the_answer(tab):
    click(tab)
    tab.at(100, sent("result"))
    tab.at(2000, ended("result"))
    tab.at(500, *(sent(str(i), "Image") for i in range(300)), sent("other", session="other"))
    tab.clock[0] = 600
    tab.browser.observe(screenshot=False)
    tab.at(700, *(sent(str(i + 300), "Image") for i in range(300)))
    tab.clock[0] = 900
    waited = tab.browser.wait_for_loading()
    assert 1200 <= waited[0] <= 1220 and waited[1:] == [False, False]
    assert [record["requestId"] for _, record in tab.scheduled] == ["other"]


def test_requests_an_earlier_input_started_are_still_waited_for(tab):
    click(tab)
    tab.at(300, sent("search"))
    tab.at(2000, ended("search"))
    tab.clock[0] = 600
    click(tab, "scroll_down")
    assert tab.browser.loading == {"search": 0.6}
    waited = tab.browser.wait_for_loading()
    assert 1500 <= waited[0] <= 1520 and waited[1:] == [False, False]
    tab.at(tab.clock[0], sent("forever"))
    tab.browser._track()
    click(tab)
    assert tab.browser.wait_for_loading() == [5000, True, False]
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_the_buffer_drains_while_jev_decides_once_tracking_has_started(tab):
    with tab.browser.draining():
        assert not tab.sources
    click(tab)
    with tab.browser.draining():
        tab.at(0, sent("result"), *(sent(str(i), "Image") for i in range(300)))
        deadline = time.monotonic() + 1
        while "result" not in tab.browser.loading and time.monotonic() < deadline:
            time.sleep(0.001)
        assert "result" in tab.browser.loading
        tab.at(0, *(sent(str(i + 300), "Image") for i in range(300)))
    tab.browser._track()
    assert not tab.browser.loading_lost and "result" in tab.browser.loading
    assert tab.browser.wait_for_loading()[1]
    drains = tab.sources[0].drains
    with tab.browser.draining():
        pass
    assert tab.sources[0].drains > drains


def test_jev_decides_inside_the_browsers_draining(tab, monkeypatch):
    agent = runner(tab)
    order = []

    @contextlib.contextmanager
    def draining():
        order.append("enter")
        try:
            yield
        finally:
            order.append("exit")

    tab.browser.draining = draining
    monkeypatch.setattr(loop, "choose", lambda *a, **kw: order.append("choose") or choice("DONE"))
    agent.command("predict")
    assert order == ["enter", "choose", "exit"]


def test_a_full_drain_marks_the_wait_as_lost(tab):
    click(tab)
    tab.at(0, sent("displaced"), *(sent(str(i), "Image") for i in range(600)))
    assert tab.browser.wait_for_loading() == [0, False, True]


def test_an_owned_event_connection_that_closes_stops_with_a_clear_message(tab):
    click(tab)
    tab.sources[0].failure = ReadinessConnectionError("Loading event connection disconnected")
    with pytest.raises(ReadinessConnectionError, match="event connection"):
        tab.browser._track()
    assert tab.browser.loading_lost
    agent = runner(tab)
    with pytest.raises(RunStopped) as error:
        act(agent, "DONE")
    assert error.value.code == "readiness_connection_error" and agent.state["decision"] is None


def test_already_disconnected_observer_prevents_another_model_call(tab, monkeypatch):
    agent = runner(tab)
    click(tab)
    tab.sources[0].failure = ReadinessConnectionError("Loading event connection disconnected")
    choose = Mock()
    monkeypatch.setattr(loop, "choose", choose)
    with pytest.raises(RunStopped) as error:
        agent.command("predict")
    assert error.value.code == "readiness_connection_error" and tab.browser.loading_lost
    choose.assert_not_called()


@pytest.mark.parametrize("body_error", [None, RunStopped("execution_deadline", "limit"),
                                       asyncio.CancelledError("cancelled")])
def test_agent_context_cleanup_preserves_original_stop_or_surfaces_close_failure(tab, monkeypatch, body_error):
    agent = runner(tab)
    click(tab)
    close_error = ReadinessConnectionError("Loading event receiver did not stop")
    tab.sources[0].close = Mock(side_effect=close_error)
    monkeypatch.setattr(browser, "cdp", Mock(return_value={}))
    expected = body_error if body_error is not None else close_error
    with pytest.raises(type(expected)) as caught:
        with agent:
            if body_error is not None:
                raise body_error
    assert caught.value is expected and tab.browser.target is None
    if body_error is not None:
        assert body_error.__notes__ == ["Browser cleanup failed"]
    tab.sources[0].close = Mock()


def test_the_start_pages_own_requests_are_not_waited_for(tab):
    tab.at(0, sent("start-page"), *(sent(str(i), session="other") for i in range(601)))
    tab.browser.observe(screenshot=False)
    assert not tab.sources
    click(tab)
    click(tab)
    assert tab.calls.count("Network.enable") == 1
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_a_full_drain_before_an_input_is_recorded_in_its_wait(tab):
    click(tab)
    tab.at(0, *(sent(str(i), "Image") for i in range(600)))
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, True]
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_draining_returns_only_after_its_thread_has_ended(tab):
    click(tab)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    read = tab.sources[0].read_events

    def blocked():
        entered.set()
        assert release.wait(2)
        return read()

    tab.sources[0].read_events = blocked

    def choose():
        with tab.browser.draining():
            assert entered.wait(2)
        finished.set()

    thread = threading.Thread(target=choose)
    thread.start()
    try:
        assert entered.wait(2) and not finished.wait(0.02)
    finally:
        release.set()
        thread.join(2)
    assert finished.is_set() and not thread.is_alive()
    assert not any(thread.name == "jev-loading-consumer" for thread in threading.enumerate())


def test_a_drain_that_fails_while_jev_decides_marks_the_wait_as_lost(tab):
    click(tab)
    read = tab.sources[0].read_events
    failed = threading.Event()

    def timeout():
        failed.set()
        raise TimeoutError("drain reply lost")

    tab.sources[0].read_events = timeout
    with tab.browser.draining():
        assert failed.wait(1)
    tab.sources[0].read_events = read
    assert tab.browser.wait_for_loading() == [0, False, True]


def test_a_later_answer_waits_for_loading_that_started_after_the_first(tab):
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]
    tab.at(300, sent("later"))
    tab.at(1100, ended("later"))
    tab.clock[0] = 400
    waited = tab.browser.wait_for_loading()
    assert 800 <= waited[0] <= 820 and waited[1:] == [False, False]


def test_blocked_waits_and_a_zero_wait_records_its_lost_flag(tab):
    agent = runner(tab)
    click(tab)
    tab.at(0, *(sent(str(i), "Image") for i in range(601)))
    act(agent, "BLOCKED")
    assert agent.state["loading_waits"] == [[0, False, True]]


def test_network_is_enabled_before_the_first_input_runs(tab):
    def operation(request, **control):
        assert tab.calls == ["Network.enable"]
        tab.calls.append("click")
        tab.at(0, sent("navigation", "Document"))

    tab.operation.side_effect = operation
    click(tab)
    tab.browser._track()
    assert tab.calls == ["Network.enable", "click"] and "navigation" in tab.browser.loading


def test_a_loss_before_an_answer_that_does_not_wait_is_kept(tab):
    click(tab)
    tab.at(0, *(sent(str(i), "Image") for i in range(601)))
    tab.browser.observe(screenshot=False)
    tab.clock[0] = 5200
    assert tab.browser.wait_for_loading() is None and tab.browser.loading_lost
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, True]


def test_scripts_count_and_untracked_ends_do_not_hold_the_wait(tab):
    click(tab)
    tab.at(0, sent("script", "Script"), sent("image", "Image"))
    tab.browser._track()
    assert set(tab.browser.loading) == {"script"}
    tab.at(0, ended("script"))
    tab.browser._track()
    tab.clock[0] = 200
    tab.at(200, ended("image"))
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_a_request_that_ended_before_an_input_adds_no_quiet_after_it(tab):
    click(tab)
    tab.at(100, sent("old"))
    tab.at(250, ended("old"))
    tab.clock[0] = 300
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_a_stopped_first_input_carries_nothing_into_the_first_that_runs(tab):
    original = tab.operation.side_effect
    tab.operation.side_effect = StalePage("no input")
    with pytest.raises(StalePage):
        click(tab)
    assert tab.browser.input_done is None
    tab.at(100, sent("start-poll"))
    tab.clock[0] = 300
    tab.operation.side_effect = original
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_a_drain_that_fails_in_a_read_marks_the_next_wait_as_lost(tab):
    click(tab)
    read = tab.sources[0].read_events
    tab.sources[0].read_events = Mock(side_effect=TimeoutError("drain"))
    with pytest.raises(TimeoutError):
        tab.browser.observe(screenshot=False)
    tab.sources[0].read_events = read
    assert tab.browser.wait_for_loading() == [0, False, True]


def test_valid_continuation_resets_loading_but_invalid_policy_preserves_it(tab):
    agent = runner(tab)
    click(tab)
    tab.at(0, sent("old"))
    tab.browser._track()
    tab.browser.loading_lost = True
    source = tab.sources[0]
    agent.pending_text = ("cached",)
    agent.trace_path = "old-trace"
    agent.state.update(decision=choice("DONE"), loading_waits=[[1, False, True]], repeated_reads=2)
    prior = deepcopy(agent.snapshot())
    pending = dict(tab.browser.loading)
    calls = tab.operation.call_count
    with pytest.raises(ValueError):
        agent.new_goal("Next", allowed_operations=["unknown"])
    assert agent.snapshot() == prior and not source.closed and tab.operation.call_count == calls
    assert tab.browser.loading == pending and tab.browser.loading_lost and agent.pending_text == ("cached",)
    agent.new_goal("Next", allowed_operations=[])
    assert source.closed and not tab.browser.loading and tab.browser.input_done is None
    assert not tab.browser.loading_lost and agent.state["loading_waits"] == []
    assert agent.state["repeated_reads"] == 0 and agent.pending_text is None
    act(agent, "DONE")
    assert agent.state["loading_waits"] == []


def test_valid_continuation_observer_close_failure_stops_before_any_new_model(tab, monkeypatch):
    agent = runner(tab)
    click(tab)
    agent.pending_text = ("cached",)
    agent.state.update(decision=choice("DONE"), status="predicted")
    original = ReadinessConnectionError("Loading event receiver did not stop")
    tab.sources[0].close = Mock(side_effect=original)
    choose = Mock()
    monkeypatch.setattr(loop, "choose", choose)
    with pytest.raises(ReadinessConnectionError) as error:
        agent.new_goal("Next goal", allowed_operations=[])
    assert error.value is original and agent.state["stop_code"] == "readiness_connection_error"
    assert agent.state["decision"] is None and agent.pending_text is None
    with pytest.raises(RunStopped):
        agent.command("predict")
    choose.assert_not_called()
    tab.sources[0].close = Mock()


@pytest.mark.parametrize("stop", ["cancelled", "execution_deadline"])
def test_a_loaded_done_cannot_override_a_pending_stop(tab, stop):
    agent = runner(tab)
    agent.deadline = time.monotonic() + 90
    if stop == "cancelled":
        agent.before_input = Mock(side_effect=asyncio.CancelledError("stop"))
        expected = asyncio.CancelledError
    else:
        agent.deadline = time.monotonic()
        expected = RunStopped
    with pytest.raises(expected):
        act(agent, "DONE")
    assert agent.state["stop_code"] == stop and agent.state["decision"] is None and not tab.calls


def test_a_read_before_the_first_input_leaves_the_buffer_alone(tab):
    tab.at(0, sent("other", session="other"))
    tab.browser.observe(screenshot=False)
    assert not tab.sources and len(tab.scheduled) == 1
    click(tab)
    drains = tab.sources[0].drains
    tab.browser.observe(screenshot=False)
    assert tab.sources[0].drains == drains + 1


def test_timed_out_read_after_a_step_is_repeated(tab):
    agent = runner(tab)
    saved = []
    agent.save = lambda: saved.append(deepcopy(agent.snapshot()))
    changed = observed_page()
    changed.update(url="https://example.test/result", fingerprint="changed")
    original = tab.browser.observe

    def observe(**kwargs):
        assert len(saved[-1]["history"]) == 1 and saved[-1]["history"][0]["page_changed"] is None
        if tab.browser.observe.call_count == 1:
            raise TimeoutError("busy renderer")
        original(**kwargs)
        return changed

    tab.browser.observe = Mock(side_effect=observe)
    act(agent)
    assert tab.calls.count("click") == 1 and tab.browser.observe.call_count == 2
    assert agent.state["repeated_reads"] == 1 and agent.state["status"] == "ready"
    assert agent.state["history"][0]["page_changed"] is True
    assert agent.state["history"][0]["url"] == changed["url"]


def test_timed_out_reads_stop_after_the_last_repeat(tab):
    agent = runner(tab)
    tab.browser.observe = Mock(side_effect=TimeoutError("busy"))
    with pytest.raises(TimeoutError):
        act(agent)
    assert tab.calls.count("click") == 1 and tab.browser.observe.call_count == 3
    assert agent.state["repeated_reads"] == 2 and agent.state["history"][0]["page_changed"] is None


@pytest.mark.parametrize("error", [StalePage("stale"), RuntimeError("not a timeout")])
def test_only_a_timed_out_read_is_repeated(tab, error):
    agent = runner(tab)
    tab.browser.observe = Mock(side_effect=error)
    with pytest.raises(type(error)):
        act(agent)
    assert tab.browser.observe.call_count == 1 and agent.state["repeated_reads"] == 0


def test_stop_check_runs_before_each_repeated_read(tab):
    agent = runner(tab)
    timed_out = [False]

    def observe(**kwargs):
        timed_out[0] = True
        raise TimeoutError("first read")

    def stop():
        if timed_out[0]:
            raise asyncio.CancelledError("stop before retry")

    tab.browser.observe = Mock(side_effect=observe)
    agent.before_input = stop
    with pytest.raises(asyncio.CancelledError):
        act(agent)
    assert tab.browser.observe.call_count == 1 and agent.state["repeated_reads"] == 0
    assert agent.state["stop_code"] == "cancelled" and tab.calls.count("click") == 1


def test_stop_before_retry_does_not_count_it(tab):
    test_stop_check_runs_before_each_repeated_read(tab)


def test_timeout_reread_does_not_restart_loading_age(tab):
    agent = runner(tab)
    original = tab.browser.observe

    def observe(**kwargs):
        if tab.browser.observe.call_count == 1:
            tab.clock[0] = 5000
            raise TimeoutError("late read")
        return original(**kwargs)

    tab.browser.observe = Mock(side_effect=observe)
    act(agent)
    assert agent.state["repeated_reads"] == 1 and tab.browser.input_done == 0
    assert tab.browser.wait_for_loading() is None and tab.calls.count("click") == 1


def test_five_second_reread_leaves_no_new_loading_allowance(tab, monkeypatch):
    agent = runner(tab)
    snapshot_adapter(tab, agent, monkeypatch)
    action = next(item for item in agent.state["page"]["actions"] if item["kind"] == "click")
    _, targets, _ = loop.action_space(agent.state["page"]["actions"])
    target = next(key for key, item in targets["CLICK"].items() if item["id"] == action["id"])
    selected = {**choice("button"), "choice": action["id"], "target": target,
                "probabilities": {action["id"]: 1}}
    original = tab.browser.observe

    def observe(**kwargs):
        if tab.browser.observe.call_count == 1:
            tab.clock[0] = 5000
            raise TimeoutError("read timed out")
        return original(**kwargs)

    tab.browser.observe = Mock(side_effect=observe)
    agent.state.update(status="predicted", decision=selected)
    agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert agent.state["repeated_reads"] == 1 and tab.calls.count("click") == 1
    assert tab.browser.input_done == 0 and tab.browser.wait_for_loading() is None


def test_timeout_retries_preserve_single_input_and_uncertain_attempt(tab):
    agent = runner(tab)

    def uncertain(request, **control):
        control["on_phase"]("mouse_pressed_uncertain", True)
        tab.calls.append("uncertain-input")
        raise UncertainAction("uncertain input")

    tab.operation.side_effect = uncertain
    with pytest.raises(RunStopped) as error:
        act(agent)
    assert error.value.code == "uncertain_action" and tab.calls.count("uncertain-input") == 1
    assert agent.state["attempt"]["outcome"] == "uncertain" and not agent.state["history"]
    assert agent.state["repeated_reads"] == 0


def test_two_unchanged_waits_hand_back_once(tab, monkeypatch):
    agent = runner(tab, ["WAIT"])
    snapshot_adapter(tab, agent, monkeypatch)
    act(agent, "wait")
    with pytest.raises(ValueError, match="still loading"):
        act(agent, "wait")
    with pytest.raises(RunStopped):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert tab.calls == ["wait", "wait"] and len(agent.state["history"]) == 2 and not tab.sources


def test_gate_wait_does_not_install_freshness_baseline(tab):
    agent = runner(tab)
    original = agent.state["page"]
    click(tab)
    tab.at(0, sent("pending"))
    tab.at(100, ended("pending"))
    observed = tab.operation.call_count
    act(agent, "DONE")
    assert agent.state["page"] is original and tab.operation.call_count == observed
    assert tab.browser.fresh.call_args.args[0] is original


def test_changed_results_drop_pending_done(tab, monkeypatch):
    agent = runner(tab)
    click(tab)
    tab.at(0, sent("pending"))
    tab.at(100, ended("pending"))
    tab.browser.fresh.side_effect = [True, False, True, True]
    tab.current["fingerprint"] = "new-results"
    choose = Mock(side_effect=[choice("DONE"), choice("DONE")])
    monkeypatch.setattr(loop, "choose", choose)
    agent.command("tick")
    assert agent.state["decision"] is None and agent.state["stale_recoveries"] == 1
    assert agent.state["page"]["fingerprint"] == "new-results"
    agent.command("tick")
    assert agent.state["status"] == "done" and choose.call_count == 2 and tab.calls.count("click") == 1


def test_loading_gate_records_loss_and_cap(tab):
    agent = runner(tab)
    click(tab)
    tab.at(0, *(sent(str(i), "Image") for i in range(600)), sent("forever"))
    act(agent, "DONE")
    assert agent.state["loading_waits"] == [[5000, True, True]]


@pytest.mark.parametrize("policy", [[], ["CLICK"]])
def test_loading_gate_respects_shared_deadline_and_policy(tab, policy):
    agent = runner(tab, policy)
    click(tab)
    tab.at(0, sent("forever"))

    def stop():
        if tab.clock[0] >= 40:
            raise RunStopped("execution_deadline", "limit")

    agent.before_input = stop
    with pytest.raises(RunStopped) as error:
        act(agent, "DONE")
    assert error.value.code == "execution_deadline" and tab.clock[0] == 40
    assert agent.state["loading_waits"] == [] and agent.state["allowed_operations"] == sorted(policy)


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("cleanup_stage", ["health", "join"])
def test_completed_model_usage_survives_observer_cleanup_failure(tab, monkeypatch, cancelled, cleanup_stage):
    agent = runner(tab)
    click(tab)
    original_join = threading.Thread.join

    def failed_join(thread, *args, **kwargs):
        original_join(thread, *args, **kwargs)
        if thread.name == "jev-loading-consumer":
            raise RuntimeError("observer consumer cleanup failed")

    if cleanup_stage == "join":
        monkeypatch.setattr(threading.Thread, "join", failed_join)

    def choose(*args, **kwargs):
        if cleanup_stage == "health":
            tab.sources[0].failure = ReadinessConnectionError("Loading event connection disconnected")
        if cancelled:
            agent.before_input = Mock(side_effect=asyncio.CancelledError("stop"))
        return {**choice("DONE"), "usage": {"input_tokens": 17}, "latency_ms": 12}

    monkeypatch.setattr(loop, "choose", choose)
    with pytest.raises(asyncio.CancelledError if cancelled else RunStopped):
        agent.command("predict")
    assert agent.state["decisions"][-1]["usage"]["input_tokens"] == 17
    assert agent.state["decisions"][-1]["latency_ms"] == 12 and agent.state["decision"] is None
    assert agent.state["stop_code"] == ("cancelled" if cancelled else "readiness_connection_error")
