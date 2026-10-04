"""Page readiness: the loading wait before a final answer (docs/executor-improvements.md §4 v4.2) and the reread of a
timed-out read after a step (§2 v2), on the tab's own event source (docs/robustness-efficiency/status.md §4.3).

A real Browser on fake CDP, a fake event source of the tab's own and a fake clock; the composition cases add the actual
schema-2 snapshot adapter in Node. Never a model, the daemon or a network call. Mapping to the historical cases:
docs/robustness-efficiency/readiness-test-map.md."""

import ast
import asyncio
import contextlib
import inspect
import json
import logging
import queue
import threading
import time
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from node_page import NodePage

from jev_ultrafast import agent as loop
from jev_ultrafast import browser, events
from jev_ultrafast.browser import StalePage, UncertainAction
from jev_ultrafast.contracts import RunStopped
from jev_ultrafast.events import EventConnectionLost
from jev_ultrafast.model import action_space

TOKEN = {"schema": 2, "epoch": "test-epoch", "generation": 1, "document_id": 1.5}
ALL_OPERATIONS = ["CLICK", "TYPE_TEXT", "SELECT", "SCROLL_UP", "SCROLL_DOWN", "WAIT"]


def page(text="Search", url="https://example.test/"):
    state = {
        "url": url, "title": "Search", "text": text, "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
        "snapshot_schema": 2, "observation_token": TOKEN,
    }
    state["fingerprint"] = browser.fingerprint(state)
    return state


def decision(action="e3"):
    operation, target = {
        "e1": ("TYPE_TEXT", "1"), "e2": ("CLICK", "1"), "e3": ("CLICK", "2"),
        "wait": ("WAIT", None), "DONE": ("DONE", None), "BLOCKED": ("BLOCKED", None),
    }[action]
    return {"choice": action, "operation": operation, "target": target, "confidence": 1.0,
            "probabilities": {action: 1.0}, "latency_ms": 10, "usage": {"input_tokens": 7}}


def sent(request_id, kind="XHR", frame="T"):
    """A request this tab sends, as the source keeps it: method, request ID, type and frame."""
    return ("Network.requestWillBeSent", request_id, kind, frame)


def ended(request_id, method="Network.loadingFinished"):
    return (method, request_id, None, None)


def images(count, prefix="image"):
    """The tab's own events that bring no content: the pressure another client's traffic used to put on the daemon's
    shared buffer (readiness-test-map.md: own-session Image events stand in for it)."""
    return [sent(f"{prefix}{number}", "Image") for number in range(count)]


def fake_time(clock):
    """One fake clock for browser.py and agent.py: sleeping advances it."""
    def sleep(seconds):
        clock["ms"] += round(seconds * 1000)

    return SimpleNamespace(monotonic=lambda: clock["ms"] / 1000, perf_counter=lambda: clock["ms"] / 1000, sleep=sleep)


class FakeEvents:
    """The tab's own source: its Network events only from its acknowledged enable on, at most 500 kept with the
    oldest dropped, and injected failures. A callable scheduled with the events runs when its time comes."""

    def __init__(self, tab, target, timeout):
        assert target == "T" and 0 < timeout <= events.SETUP_SECONDS
        tab.calls.append(("Network.enable", tab.clock["ms"]))  # acknowledged here, before the input runs
        self.tab, self.enabled = tab, tab.clock["ms"]

    def read(self):
        tab = self.tab
        if tab.failure:
            failure = tab.failure
            if not tab.permanent:
                tab.failure = None
            raise failure
        with tab.lock:
            due = [(at, item) for at, item in tab.schedule if at <= tab.clock["ms"]]
            tab.schedule[:] = [(at, item) for at, item in tab.schedule if at > tab.clock["ms"]]
        own = []
        for at, item in due:
            if callable(item):
                item()
            elif at >= self.enabled:  # Chrome sends nothing on a session before its Network.enable
                own.append(item)
        return own[-events.EVENT_QUEUE:], len(own) > events.EVENT_QUEUE

    def close(self):
        self.tab.closed_sources += 1


@pytest.fixture
def tab(monkeypatch):
    """A real Browser on fake CDP, with a fake clock and a fake event source of the tab's own."""
    state = SimpleNamespace(clock={"ms": 0}, schedule=[], lock=threading.Lock(), calls=[], failure=None,
                            permanent=False, closed_sources=0, sources=[])
    monkeypatch.setattr(browser, "time", fake_time(state.clock))
    monkeypatch.setattr(browser, "ensure_daemon", lambda **_: None)
    monkeypatch.setattr(browser, "foreign_browser_port", lambda: None)
    monkeypatch.setattr(browser, "daemon_browser_kind", lambda: "cdp")  # an explicit endpoint, as in the lab
    monkeypatch.delenv("JEV_LOADING_GATE", raising=False)

    def open_events(target, timeout):
        source = FakeEvents(state, target, timeout)
        state.sources.append(source)
        return source

    monkeypatch.setattr(events, "open_events", open_events)

    def cdp(method, session_id=None, **params):
        state.calls.append((method, state.clock["ms"]))
        if method == "Target.createTarget":
            return {"targetId": "T"}
        if method == "Target.attachToTarget":
            return {"sessionId": "S"}
        return {"result": {"value": "complete"}}

    monkeypatch.setattr(browser, "cdp", cdp)

    def operate(request, **_control):
        if request["operation"] == "observe":
            return page()
        return {"executed": request["action"]["id"]}

    operation = Mock(side_effect=operate)
    monkeypatch.setattr(browser, "browser_operation", operation)
    state.browser = browser.Browser("https://example.test/")
    state.browser.fresh = Mock(return_value=True)
    state.operation = operation

    def at(ms, *items):
        with state.lock:
            state.schedule.extend((ms, item) for item in items)

    state.at = at
    state.pending = lambda: bool(state.schedule)
    state.inputs = lambda: sum(call.args[0]["operation"] == "act" and call.args[0]["action"]["kind"] != "wait"
                               for call in operation.call_args_list)
    return state


def click(tab):
    return tab.browser.act(page()["actions"][2], page())


def until_drained(tab):
    deadline = time.monotonic() + 2  # the real clock: the drain thread paces itself on it
    while tab.pending() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert not tab.pending()


@pytest.fixture
def runner():
    """A real Agent over a stand-in browser, for what the agent does with the browser's answers."""
    agent = loop.Agent.__new__(loop.Agent)
    agent.screenshots, agent.pending_text, agent.record_dir, agent.trace_path, agent.before_input = (
        False, None, None, None, None)
    observed = page()
    agent.browser = Mock(fresh=Mock(return_value=True), observe=Mock(return_value=observed),
                         wait_for_loading=Mock(return_value=None), draining=contextlib.nullcontext,
                         reset_loading=Mock())
    agent._fresh_state("Find a book", observed, None, allowed_operations=ALL_OPERATIONS)
    agent.state.update(status="predicted", started_at=time.perf_counter())
    return agent


def act(agent, action="e3"):
    agent.state["decision"] = decision(action)
    return agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})


@pytest.fixture
def agent_tab(tab, monkeypatch, tmp_path):
    """A real Agent over the tab's real Browser, sharing its fake clock, with a scripted Jev."""
    monkeypatch.setattr(loop, "time", fake_time(tab.clock))
    monkeypatch.setattr(loop, "Browser", lambda url: tab.browser)
    monkeypatch.setattr(loop, "field_text", Mock(side_effect=AssertionError("no text helper is asked")))

    def make(answers, allowed_operations=ALL_OPERATIONS, after_answer=None):
        pending = list(answers)

        def choose(observed, goal, history, operations, *, check_stop, remaining_budget, on_response):
            tab.choices = getattr(tab, "choices", 0) + 1
            tab.offered = [*getattr(tab, "offered", []), sorted(operations)]
            answer = decision(pending.pop(0))
            if after_answer:
                after_answer()
            return answer

        monkeypatch.setattr(loop, "choose", choose)
        agent = loop.Agent("https://example.test/", "Find a book", allowed_operations=allowed_operations,
                           trace_path=tmp_path / "run.json")
        return agent

    return make


# §2.5: the read after an executed step, repeated after a timeout (cases 1, 2, 4, 5).

def timing_out(tab, times, advance_ms=0, then=None):
    """The read after the input times out `times` times, each taking advance_ms of the fake clock."""
    original, count = tab.operation.side_effect, {"observe": 0}

    def operate(request, **control):
        if request["operation"] == "observe" and tab.inputs() and count["observe"] < times:
            count["observe"] += 1
            tab.clock["ms"] += advance_ms
            raise TimeoutError("Runtime.evaluate timed out after 5s waiting for the daemon")
        if request["operation"] == "observe" and then and tab.inputs():
            return then
        return original(request, **control)

    tab.operation.side_effect = operate
    return count


def observes(tab):
    return sum(call.args[0]["operation"] == "observe" for call in tab.operation.call_args_list)


def test_timed_out_read_after_a_step_is_repeated(agent_tab, tab):
    agent = agent_tab(["e3"])
    before = observes(tab)
    results = page("Results", url="https://example.test/results")
    timing_out(tab, 1, then=results)
    agent.command("tick")
    assert tab.inputs() == 1 and observes(tab) - before == 2
    step = agent.state["history"][0]
    assert step["url"] == "https://example.test/results" and step["page_changed"] is True
    assert agent.state["repeated_reads"] == 1 and agent.state["status"] == "ready"


def test_timed_out_reads_stop_after_the_last_repeat(agent_tab, tab):
    agent = agent_tab(["e3"])
    before = observes(tab)
    timing_out(tab, 99)
    with pytest.raises(TimeoutError):
        agent.command("tick")
    # Decision D1 (docs/executor-improvements.md §2): two repeats, so three reads at most, each up to 5 s.
    assert loop.READ_TIMEOUT_REPEATS == 2 and tab.inputs() == 1 and observes(tab) - before == 3
    assert agent.state["repeated_reads"] == 2
    assert len(agent.state["history"]) == 1 and agent.state["history"][0]["page_changed"] is None
    assert json.loads(agent.trace_path.read_text())["history"][0]["page_changed"] is None


def test_stop_check_runs_before_each_repeated_read(agent_tab, tab):
    agent = agent_tab(["e3"])
    before = observes(tab)
    timing_out(tab, 1)
    stopping = {"armed": False}

    def external():  # the server's stop check: armed once the first read after the click has timed out
        if stopping["armed"]:
            raise RunStopped("shutdown", "the server is shutting down")

    original = tab.operation.side_effect

    def operate(request, **control):
        try:
            return original(request, **control)
        except TimeoutError:
            stopping["armed"] = True
            raise

    tab.operation.side_effect = operate
    agent.before_input = external
    with pytest.raises(RunStopped, match="shutting down"):
        agent.command("tick")
    assert tab.inputs() == 1 and observes(tab) - before == 1 and agent.state["repeated_reads"] == 0
    assert agent.state["status"] == "stopped" and agent.state["stop_code"] == "shutdown"


@pytest.mark.parametrize("failure", [StalePage("Document is navigating"), RuntimeError("the daemon failed")])
def test_only_a_timed_out_read_is_repeated(agent_tab, tab, failure, monkeypatch):
    agent = agent_tab(["e3"])
    reads, real_observe = [], tab.browser.observe

    def observe(*args, **control):
        reads.append(control)
        return real_observe(*args, **control)

    monkeypatch.setattr(tab.browser, "observe", observe)
    original = tab.operation.side_effect

    def operate(request, **control):
        if request["operation"] == "observe" and tab.inputs():
            raise failure
        return original(request, **control)

    tab.operation.side_effect = operate
    agent.command("predict")
    with pytest.raises(type(failure)):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    # One read after the step, never repeated: a StalePage goes to tick's own recovery, anything else stops the run.
    assert len(reads) == 1 and tab.inputs() == 1 and agent.state["repeated_reads"] == 0
    assert len(agent.state["history"]) == 1 and agent.state["history"][0]["page_changed"] is None
    if isinstance(failure, StalePage):
        assert agent.state["status"] not in loop.TERMINAL_STATES
    else:
        assert agent.state["stop_code"] == "execution_error"


# §4.6: the loading wait (cases 1–24, the replacements of 25 and 26, and 27).

def test_loading_wait_tracks_only_this_tabs_content_requests(tab):
    click(tab)  # another session's events never reach this source: test_another_sessions_traffic_is_never_taken
    tab.at(0, sent("img", "Image"), sent("ad", "Document", frame="AD"))  # a cross-site iframe's document
    tab.at(0, sent("nav", "Document"), sent("api", "Fetch"), sent("nav", "Document"))  # the second "nav": a redirect
    tab.browser._track()
    assert set(tab.browser.loading) == {"nav", "api"}
    tab.at(0, ended("nav"), ended("api", "Network.loadingFailed"))
    tab.browser._track()
    assert tab.browser.loading == {}


def test_loading_wait_ends_after_quiet_or_5_s_after_the_input(tab):
    click(tab)  # nothing loading: no wait, so the freshness check decides at once
    assert tab.browser.wait_for_loading() == [0, False, False]
    click(tab)
    start = tab.clock["ms"]
    tab.at(start + 300, sent("results"))  # sent 300 ms after the click, as Google Flights does
    tab.at(start + 1100, ended("results"))
    tab.clock["ms"] = start + 400  # Jev's next answer: the request is in flight
    waited, capped, lost = tab.browser.wait_for_loading()  # until 100 ms of quiet after it ends
    assert 800 <= waited <= 820 and not capped and not lost
    click(tab)
    start = tab.clock["ms"]
    tab.at(start + 300, sent("poll"))  # never ends
    tab.clock["ms"] = start + 400
    waited, capped, lost = tab.browser.wait_for_loading()
    assert 4600 <= waited <= 4620 and capped  # capped 5 s after the input, not 5 s after the wait began


def test_loading_wait_runs_at_every_answer_until_5_s_after_the_input(tab):
    assert tab.browser.wait_for_loading() is None  # no input yet
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]
    assert tab.browser.wait_for_loading() == [0, False, False]  # Jev's next answer after the same input: checked too
    tab.clock["ms"] = 3000
    tab.browser.act(page()["actions"][3], page())  # a WAIT step is not an input: the 5 s still count from the click
    assert tab.browser.input_done == 0
    tab.clock["ms"] = 5000
    assert tab.browser.wait_for_loading() is None  # 5 s after the click: no wait, and the freshness check decides
    tab.clock["ms"] = 10000
    click(tab)
    tab.clock["ms"] = 15000  # a later goal's first answer, say
    assert tab.browser.wait_for_loading() is None


def test_loading_wait_stops_when_the_run_stops(tab):
    click(tab)
    tab.at(0, *images(600), sent("results"))  # loading, so the wait polls; and a loss: the oldest events dropped
    stop = Mock(side_effect=RunStopped("shutdown", "the server is shutting down"))
    with pytest.raises(RunStopped, match="shutting down"):
        tab.browser.wait_for_loading(check_stop=stop)
    assert tab.clock["ms"] < 100 and "results" in tab.browser.loading
    tab.at(0, ended("results"))
    assert tab.browser.wait_for_loading() == [100, False, True]  # the stopped wait recorded nothing: its loss is kept


def test_done_and_blocked_wait_for_loading_before_the_freshness_check(runner):
    browser_stub, calls = runner.browser, []
    runner.before_input = Mock()
    act(runner, "e3")
    browser_stub.wait_for_loading.assert_not_called()  # a CLICK does not wait
    browser_stub.wait_for_loading.side_effect = lambda **_control: calls.append("wait") or [748, False, False]
    browser_stub.fresh.side_effect = lambda _page, **_control: calls.append("fresh") or False
    with pytest.raises(StalePage):  # the results loaded, so the page changed: Jev answers again
        act(runner, "DONE")
    assert calls == ["wait", "fresh"] and runner.state["loading_waits"] == [[748, False, False]]
    # The gate gets the agent's shared stop and budget checks, not a raw callback.
    browser_stub.wait_for_loading.assert_called_once_with(check_stop=runner.check_stop,
                                                          remaining_budget=runner.remaining_budget)
    browser_stub.wait_for_loading.side_effect, browser_stub.fresh.side_effect = None, None
    act(runner, "BLOCKED")  # the stub's None: no input in the last 5 s, and nothing recorded
    assert runner.state["status"] == "blocked" and runner.state["loading_waits"] == [[748, False, False]]


def test_an_input_stopped_before_it_runs_keeps_the_last_inputs_deadline(tab):
    click(tab)
    tab.at(100, sent("poll"))  # never ends
    tab.clock["ms"] = 300
    tab.operation.side_effect = StalePage("Target is covered by <div>. Observe again.")
    with pytest.raises(StalePage):
        click(tab)
    waited, capped, lost = tab.browser.wait_for_loading()
    assert 4700 <= waited <= 4720 and capped  # 5 s after the first click, not the stopped one


def test_each_read_drains_the_buffer_so_it_cannot_overflow_before_the_answer(tab):
    click(tab)
    tab.at(100, sent("results"))
    tab.at(2000, ended("results"))
    tab.clock["ms"] = 600
    original = tab.operation.side_effect

    def read_with_traffic(request, **control):  # 300 events of the tab's own arrive during the read
        tab.at(tab.clock["ms"], *images(300, "during"))
        return original(request, **control)

    tab.operation.side_effect = read_with_traffic
    tab.browser.observe(screenshot=False)
    tab.operation.side_effect = original
    tab.at(700, *images(300, "after"))  # while Jev decides
    tab.clock["ms"] = 900
    assert tab.browser.wait_for_loading() == [1200, False, False]


def test_requests_an_earlier_input_started_are_still_waited_for(tab):
    click(tab)  # a search
    tab.at(300, sent("results"))
    tab.at(2000, ended("results"))
    tab.clock["ms"] = 600
    click(tab)  # another input, a scroll say, while the results still load
    assert tab.browser.wait_for_loading() == [1500, False, False]
    tab.at(2200, sent("poll"))  # never ends
    tab.clock["ms"] = 2300
    click(tab)
    assert tab.browser.wait_for_loading() == [5000, True, False]
    click(tab)  # the poll is now 5 s old: dropped, so nothing is loading and there is no wait
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_the_buffer_drains_while_jev_decides_once_tracking_has_started(tab):
    with tab.browser.draining():  # no input yet: nothing is tracked, so nothing drains
        tab.at(0, *images(5, "idle"))
        time.sleep(0.1)
    assert tab.pending()
    click(tab)
    with tab.browser.draining():
        tab.at(0, sent("results"), *images(300, "first"))
        until_drained(tab)
        tab.at(0, *images(300, "second"))
        until_drained(tab)
    assert "results" in tab.browser.loading and not tab.browser.lost  # 601 events, never more than 500 at a read
    tab.browser.wait_for_loading()  # capped 5 s after the click, since "results" never ends
    with tab.browser.draining():  # Jev answers again after the wait: it still drains
        tab.at(tab.clock["ms"], *images(1, "again"))
        until_drained(tab)


def test_jev_decides_inside_the_browsers_draining(runner, monkeypatch):
    calls = []

    @contextlib.contextmanager
    def draining():
        calls.append("enter")
        try:
            yield
        finally:
            calls.append("exit")

    runner.browser.draining = draining
    monkeypatch.setattr(loop, "choose", lambda *_args, **_kwargs: calls.append("choose") or decision("e3"))
    runner.state.update(decision=None, status="ready")
    runner.command("predict")
    assert calls == ["enter", "choose", "exit"]

    def fails(*_args, on_response, **_kwargs):  # a completed response, then a failure: the context still exits
        on_response({"model": "fake", "latency_ms": 5, "usage": {"input_tokens": 3}})
        calls.append("choose")
        raise RuntimeError("malformed reply")

    calls.clear()
    monkeypatch.setattr(loop, "choose", fails)
    with pytest.raises(RuntimeError):
        runner.command("predict")
    assert calls == ["enter", "choose", "exit"]
    assert runner.state["decisions"][-1]["usage"] == {"input_tokens": 3}  # the completed call stays accounted


def test_a_full_drain_marks_the_wait_as_lost(tab):
    click(tab)
    tab.at(100, sent("results"), *images(600))
    tab.clock["ms"] = 200
    assert tab.browser.wait_for_loading() == [0, False, True]  # "results" was dropped: nothing is seen loading


def test_an_owned_event_connection_that_closes_stops_with_a_clear_message(agent_tab, tab):
    """Replaces case 12's daemon reply: a closed source of the tab's own is a terminal stop, never a quiet page, and
    nothing falls back to the daemon's shared buffer."""
    agent = agent_tab(["e3", "DONE"])
    agent.command("tick")
    tab.failure, tab.permanent = EventConnectionLost("closed"), True
    with pytest.raises(EventConnectionLost, match="The loading wait's browser connection closed."):
        agent.command("tick")
    assert tab.browser.lost and agent.state["status"] == "stopped" and agent.state["decision"] is None
    assert agent.state["stop_code"] == "event_connection_lost" and tab.inputs() == 1
    assert len(tab.sources) == 1 and [method for method, _ms in tab.calls].count("Network.enable") == 1  # no reconnect
    assert json.loads(agent.trace_path.read_text())["stop_code"] == "event_connection_lost"


def test_the_final_read_never_touches_the_source(tab):
    """The server's final read (mcp_server.finish) passes track=False: the run is over, so a source that closed after
    its answer cannot fail the read that proves the outcome."""
    click(tab)
    tab.failure, tab.permanent = EventConnectionLost("closed"), True
    assert tab.browser.observe(screenshot=False, track=False)["url"] == "https://example.test/"
    with pytest.raises(EventConnectionLost):
        tab.browser.observe(screenshot=False)


def test_the_start_pages_own_requests_are_not_waited_for(tab):
    tab.at(0, sent("long-poll"))  # the start page's own request, which never ends
    tab.at(0, *images(600))  # and its other traffic
    tab.clock["ms"] = 100
    tab.browser.observe(screenshot=False)
    assert not any(method == "Network.enable" for method, _ms in tab.calls) and tab.sources == []
    click(tab)
    click(tab)
    assert [method for method, _ms in tab.calls].count("Network.enable") == 1  # at the first input, once
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_a_full_drain_before_an_input_is_recorded_in_its_wait(tab):
    click(tab)
    tab.at(100, *images(600))  # during a text call, say
    tab.clock["ms"] = 200
    click(tab)  # its drain before the input comes back full
    assert tab.browser.wait_for_loading()[2] is True
    click(tab)
    assert tab.browser.wait_for_loading()[2] is False  # lost covers only the reads since the last recorded wait


def test_a_stop_during_the_sources_setup_runs_no_input(agent_tab, tab, monkeypatch):
    """The first input's source setup is bounded by what is left of the run's budget and followed by its stop check:
    a deadline that passes while the source attaches runs no input."""
    agent = agent_tab(["e3"])
    timeouts, fake_open = [], events.open_events

    def slow_open(target, timeout):
        timeouts.append(timeout)
        source = fake_open(target, timeout)
        tab.clock["ms"] += 2000  # attaching took 2 s
        return source

    monkeypatch.setattr(events, "open_events", slow_open)
    agent.command("predict")
    agent.deadline = tab.clock["ms"] / 1000 + 1
    with pytest.raises(RunStopped):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert agent.state["stop_code"] == "execution_deadline" and tab.inputs() == 0 and agent.state["history"] == []
    assert agent.state["attempt"] is None and timeouts == [pytest.approx(1)]


def test_a_source_that_cannot_attach_stops_before_the_input(agent_tab, tab, monkeypatch):
    agent = agent_tab(["e3"])
    monkeypatch.setattr(events, "open_events", Mock(side_effect=EventConnectionLost("could not open (OSError)")))
    with pytest.raises(EventConnectionLost, match="could not open"):
        agent.command("tick")
    assert agent.state["stop_code"] == "event_connection_lost" and agent.state["status"] == "stopped"
    assert tab.inputs() == 0 and agent.state["history"] == [] and agent.state["attempt"] is None
    assert not tab.browser.network  # nothing half set up: a later goal attaches afresh


def test_draining_returns_only_after_its_thread_has_ended(tab):
    click(tab)
    source, in_read = tab.sources[0], threading.Event()
    real_read = source.read

    def slow_read():
        in_read.set()
        time.sleep(0.05)  # the real clock: a read still in flight when Jev answers
        return real_read()

    source.read = slow_read

    def draining_threads():
        return [thread for thread in threading.enumerate() if thread.name == "jev-drain"]

    with tab.browser.draining():
        assert in_read.wait(2) and len(draining_threads()) == 1
    assert draining_threads() == []


def test_a_drain_that_fails_while_jev_decides_marks_the_wait_as_lost(tab):
    click(tab)
    tab.failure = TimeoutError("the source's read failed")  # once: the source then recovers
    with tab.browser.draining():
        deadline = time.monotonic() + 2  # the real clock, as the drain thread's
        while tab.failure and time.monotonic() < deadline:
            time.sleep(0.005)
    assert tab.failure is None and tab.browser.wait_for_loading() == [0, False, True]


def test_a_later_answer_waits_for_loading_that_started_after_the_first(tab):
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]  # answer 1: nothing loading yet
    tab.at(300, sent("results"))
    tab.at(1100, ended("results"))
    tab.clock["ms"] = 400  # answer 2, after the same input
    waited, capped, lost = tab.browser.wait_for_loading()
    assert 800 <= waited <= 820 and not capped and not lost


def test_blocked_waits_and_a_zero_wait_records_its_lost_flag(runner):
    runner.browser.wait_for_loading.return_value = [0, False, True]
    act(runner, "BLOCKED")
    runner.browser.wait_for_loading.assert_called_once_with(check_stop=runner.check_stop,
                                                            remaining_budget=runner.remaining_budget)
    assert runner.state["loading_waits"] == [[0, False, True]]


def test_network_is_enabled_before_the_first_input_runs(tab):
    original = tab.operation.side_effect

    def submit(request, **control):  # the click itself starts a navigation, 1 ms into the input
        if request["operation"] == "act":
            assert any(method == "Network.enable" for method, _ms in tab.calls)  # acknowledged before it runs
            tab.at(tab.clock["ms"], sent("nav", "Document"))
            tab.clock["ms"] += 1
        return original(request, **control)

    tab.operation.side_effect = submit
    click(tab)
    tab.browser._track()
    assert "nav" in tab.browser.loading and tab.inputs() == 1


def test_a_loss_before_an_answer_that_does_not_wait_is_kept(tab):
    click(tab)
    tab.at(100, *images(600))
    tab.clock["ms"] = 200
    tab.browser.observe(screenshot=False)  # a full read
    tab.clock["ms"] = 5200
    assert tab.browser.wait_for_loading() is None  # 5 s after the input: no wait, nothing recorded
    click(tab)
    assert tab.browser.wait_for_loading()[2] is True


def test_scripts_count_and_untracked_ends_do_not_hold_the_wait(tab):
    click(tab)
    tab.at(0, sent("js", "Script"), sent("img", "Image"))
    tab.browser._track()
    assert set(tab.browser.loading) == {"js"}
    tab.at(0, ended("js"))
    tab.browser._track()
    tab.clock["ms"] = 300
    tab.at(300, ended("img"))  # an image ends just before the answer
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_a_request_that_ended_before_an_input_adds_no_quiet_after_it(tab):
    click(tab)
    tab.at(100, sent("suggestions"))
    tab.at(250, ended("suggestions"))
    tab.clock["ms"] = 300
    click(tab)  # its drain before the input takes in the start and the end
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_a_stopped_first_input_carries_nothing_into_the_first_that_runs(tab):
    original = tab.operation.side_effect
    tab.operation.side_effect = StalePage("Target is covered by <div>. Observe again.")
    with pytest.raises(StalePage):
        click(tab)  # the source is attached and Network enabled, but no input ran
    assert tab.browser.input_done is None
    tab.operation.side_effect = original
    tab.at(100, sent("poll"))  # the start page's own request, which never ends
    tab.clock["ms"] = 300
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]


def test_a_drain_that_fails_in_a_read_marks_the_next_wait_as_lost(tab):
    click(tab)
    tab.failure = TimeoutError("the source's read timed out")
    with pytest.raises(TimeoutError):
        tab.browser.observe(screenshot=False)  # §2 reads again after a TimeoutError; the loss must not vanish
    assert tab.browser.wait_for_loading() == [0, False, True]
    assert tab.inputs() == 1


def test_valid_continuation_resets_loading_but_invalid_policy_preserves_it(dom_agent):
    """Replaces case 25 (its [920, False, False] carry-over is rejected by this contract): a valid new goal starts with
    nothing tracked; an invalid policy changes nothing, its read, baseline and source included. On the actual
    snapshot adapter."""
    tab = dom_agent(["Control 1"], n=3, field=True)
    agent, dom = tab.agent, tab.dom
    agent.command("tick")  # the click: tracking starts
    tab.schedule.append((tab.clock["ms"], sent("results")))  # never ends
    tab.clock["ms"] += 200
    tab.browser._track()
    agent.state.update(decision=decision("DONE"), loading_waits=[[920, False, False]])
    agent.pending_text = ("context", "books", {"model": "fake"})
    tab.browser.lost = True
    before = (dict(tab.browser.loading), tab.browser.input_done, tab.browser.lost, deepcopy(agent.state["decision"]))
    calls, generation = len(dom.calls), dom.evaluate("__jevFast.generation")
    assert isinstance(generation, int) and generation >= 2
    with pytest.raises(ValueError):
        agent.new_goal("Next", allowed_operations=["UNKNOWN"], trace_path=agent.trace_path.with_name("next.json"))
    assert (dict(tab.browser.loading), tab.browser.input_done, tab.browser.lost, agent.state["decision"]) == before
    assert agent.pending_text and agent.state["loading_waits"] == [[920, False, False]] and tab.closed_sources == 0
    assert len(dom.calls) == calls and dom.evaluate("__jevFast.generation") == generation  # no read, same baseline
    agent.new_goal("Next", allowed_operations=ALL_OPERATIONS, trace_path=agent.trace_path.with_name("next.json"))
    assert tab.closed_sources == 1 and tab.browser.input_done is None and not tab.browser.lost
    assert not tab.browser.network and tab.browser.loading is None and agent.pending_text is None
    assert agent.state["loading_waits"] == [] and agent.state["decision"] is None
    assert dom.evaluate("__jevFast.generation") == generation + 1  # the new goal's own read
    assert tab.browser.wait_for_loading() is None  # its first answer waits on nothing of the old goal


@pytest.mark.parametrize("stop", ["cancellation", "deadline"])
def test_a_loaded_done_cannot_override_a_pending_stop(agent_tab, tab, stop):
    """Replaces case 26: a stop wins over a DONE even with nothing loading; the completed model call stays
    accounted, discarded, and nothing runs."""
    pending = {"stop": False}

    def answered():  # Jev's DONE comes back just as the run is told to stop
        if tab.choices < 2:
            return
        if stop == "deadline":
            tab.clock["ms"] = round(agent.deadline * 1000)
        else:
            pending["stop"] = True

    agent = agent_tab(["e3", "DONE"], after_answer=answered)
    agent.command("tick")
    agent.before_input = lambda: (_ for _ in ()).throw(asyncio.CancelledError()) if pending["stop"] else None
    with pytest.raises((RunStopped, asyncio.CancelledError)):
        agent.command("tick")
    expected = "cancelled" if stop == "cancellation" else "execution_deadline"
    assert agent.state["status"] == "stopped" and agent.state["stop_code"] == expected
    assert agent.state["decision"] is None and agent.pending_text is None and tab.inputs() == 1
    done = agent.state["decisions"][-1]
    assert done["choice"] == "DONE" and done["usage"] == {"input_tokens": 7} and done["discarded"] == expected
    assert agent.state["loading_waits"] == []


def test_a_read_before_the_first_input_leaves_the_buffer_alone(tab):
    tab.at(0, sent("start"))
    tab.failure = TimeoutError("a source that would fail")  # no source exists yet, so nothing can fail
    page_read = tab.browser.observe(screenshot=False)
    assert page_read["url"] == "https://example.test/" and tab.sources == [] and tab.pending()
    tab.failure = None
    click(tab)
    tab.at(tab.clock["ms"], sent("after"))
    tab.browser.observe(screenshot=False)  # after an input, a read takes in the source's events
    assert not tab.pending() and "after" in tab.browser.loading


# The plan's composition nodes (READINESS-1…3).

@pytest.mark.parametrize("stop", ["deadline", "cancellation"])
def test_loading_gate_respects_shared_deadline_and_policy(agent_tab, tab, stop):
    """Every poll checks the shared deadline and cancellation; the wait is read-only and grants no WAIT."""
    agent = agent_tab(["e3", "DONE"], allowed_operations=["CLICK"])
    agent.command("tick")
    policy, start, checks = agent.state["allowed_operations"], tab.clock["ms"], tab.browser.fresh.call_count
    tab.at(start, sent("results"))  # in flight when Jev answers, and never ends
    if stop == "deadline":
        agent.deadline = (start + 1000) / 1000
    else:
        agent.before_input = lambda: (_ for _ in ()).throw(asyncio.CancelledError()) if (
            tab.clock["ms"] >= start + 1000) else None
    with pytest.raises((RunStopped, asyncio.CancelledError)):
        agent.command("tick")
    assert start + 1000 <= tab.clock["ms"] <= start + 1020  # stopped within one 20 ms poll
    assert agent.state["stop_code"] == ("execution_deadline" if stop == "deadline" else "cancelled")
    assert agent.state["loading_waits"] == [] and tab.inputs() == 1 and agent.state["decision"] is None
    assert tab.browser.fresh.call_count == checks + 1  # predict's own: the stopped DONE reached no freshness check
    assert [step["kind"] for step in agent.state["history"]] == ["click"]
    # The internal wait grants nothing: Jev was never offered a WAIT, and the policy is as the goal set it.
    assert all("WAIT" not in operations for operations in tab.offered) and agent.state["allowed_operations"] == policy


def test_gate_wait_does_not_install_freshness_baseline(monkeypatch, tmp_path):
    """The wait and the drain never read the page: the DONE's own read stays the baseline, so results that render
    while the wait runs make it stale."""
    page_dom = NodePage(n=3, field=True)
    try:
        clock, schedule = {"ms": 0}, []
        tab = SimpleNamespace(clock=clock, schedule=schedule, lock=threading.Lock(), calls=[], failure=None,
                              permanent=False, closed_sources=0, sources=[])
        monkeypatch.setattr(browser, "time", fake_time(clock))
        monkeypatch.setattr(events, "open_events", lambda target, timeout: FakeEvents(tab, target, timeout))
        monkeypatch.setattr(browser, "cdp", page_dom.cdp)
        tab_browser = browser.Browser.__new__(browser.Browser)
        tab_browser.session, tab_browser.target, tab_browser.gate = "node-session", "T", "first input"
        observed = tab_browser.observe(screenshot=False)
        go = next(action for action in observed["actions"] if action["label"] == "Control 1")
        tab_browser.act(go, observed)
        answered_on = tab_browser.observe(screenshot=False)  # Jev answers DONE on this read
        generation = page_dom.evaluate("__jevFast.generation")
        schedule.extend([(clock["ms"], sent("results")), (clock["ms"] + 600, ended("results")),
                         (clock["ms"] + 600, lambda: page_dom.evaluate("dom.texts[0].textContent='Results'"))])
        evaluations = len([call for call in page_dom.calls if call[0] == "Runtime.evaluate"])
        waited, capped, lost = tab_browser.wait_for_loading()
        assert 700 <= waited <= 720 and not capped and not lost  # until 100 ms after the results arrived
        assert len([call for call in page_dom.calls if call[0] == "Runtime.evaluate"]) == evaluations  # no read
        assert page_dom.evaluate("__jevFast.generation") == generation  # no baseline replaced
        assert tab_browser.fresh(answered_on) is False  # the results changed the page: the DONE is stale
    finally:
        page_dom.close()


def test_loading_gate_records_loss_and_cap(tab):
    click(tab)
    tab.at(100, sent("poll"))  # never ends: a cap, with no loss
    tab.clock["ms"] = 200
    assert tab.browser.wait_for_loading() == [4800, True, False]
    tab.at(tab.clock["ms"], ended("poll"))
    click(tab)
    start = tab.clock["ms"]
    tab.at(start + 50, *images(600), sent("results"))  # a loss with no cap: the oldest events dropped
    tab.at(start + 400, ended("results"))
    tab.clock["ms"] = start + 100
    waited, capped, lost = tab.browser.wait_for_loading()
    assert 400 <= waited <= 420 and capped is False and lost is True
    click(tab)
    start = tab.clock["ms"]
    tab.at(start + 10, *images(600), sent("poll-2"))  # a loss, then a stop before the wait is recorded
    tab.clock["ms"] = start + 20
    stop = Mock(side_effect=RunStopped("shutdown", "the server is shutting down"))
    with pytest.raises(RunStopped):
        tab.browser.wait_for_loading(check_stop=stop)
    assert tab.browser.lost is True  # the stopped wait recorded nothing, so its loss is kept
    waited, capped, lost = tab.browser.wait_for_loading()
    assert 4980 <= waited <= 5000 and capped is True and lost is True  # the next recorded wait reports both
    tab.at(tab.clock["ms"], ended("poll-2"))
    click(tab)
    assert tab.browser.wait_for_loading() == [0, False, False]  # and only it: the loss is cleared


def test_timeout_reread_does_not_restart_loading_age(agent_tab, tab):
    agent = agent_tab(["e3", "DONE"])
    timing_out(tab, 1, advance_ms=5000)  # the first read after the click takes its full 5 s, then times out
    agent.command("tick")
    clicked = tab.browser.input_done
    assert agent.state["repeated_reads"] == 1 and tab.clock["ms"] / 1000 - clicked >= 5
    tab.at(tab.clock["ms"], sent("late"))  # loading after the reread: the 5 s since the click have passed
    agent.command("tick")
    assert agent.state["status"] == "done" and agent.state["loading_waits"] == []
    assert tab.browser.input_done == clicked and tab.inputs() == 1


def test_timeout_retries_preserve_single_input_and_uncertain_attempt(agent_tab, tab):
    agent = agent_tab(["e3"])
    before, original = observes(tab), tab.operation.side_effect
    timing_out(tab, 99)
    with pytest.raises(TimeoutError):
        agent.command("tick")
    assert tab.inputs() == 1 and len(agent.state["history"]) == 1 and agent.state["attempt"] is None
    assert observes(tab) - before == loop.READ_TIMEOUT_REPEATS + 1
    # An input whose own reply is lost is uncertain: no read follows it, and nothing repeats it.
    tab.operation.side_effect = original
    agent = agent_tab(["e3"])
    before, inputs, clicked = observes(tab), tab.inputs(), tab.browser.input_done

    def lost_reply(request, *, on_phase=None, **control):
        if request["operation"] == "act":  # the press went out; its reply did not come back
            on_phase("mouse_press_pending", False)
            on_phase("mouse_press_dispatched", True, persist=False)
            on_phase("mouse_press_uncertain", True, persist=False)
            raise UncertainAction("Browser input execution reply was lost; inspect before starting another goal.")
        return original(request, **control)

    tab.operation.side_effect = lost_reply
    with pytest.raises(RunStopped):
        agent.command("tick")
    assert agent.state["stop_code"] == "uncertain_action" and agent.state["attempt"]["outcome"] == "uncertain"
    assert agent.state["attempt"]["phase"] == "mouse_press_uncertain" and agent.state["attempt"]["input_started"]
    assert tab.browser.input_done == clicked  # an input that may not have run sets no new loading deadline
    assert agent.state["history"] == [] and agent.state["repeated_reads"] == 0
    assert observes(tab) == before and sum(call.args[0]["operation"] == "act" for call in
                                           tab.operation.call_args_list) - inputs == 1


def test_stop_before_retry_does_not_count_it(agent_tab, tab):
    agent = agent_tab(["e3"])
    before = observes(tab)
    timing_out(tab, 1, advance_ms=5000)
    agent.deadline = (tab.clock["ms"] + 3000) / 1000  # the 5 s read crosses the run's deadline
    with pytest.raises(RunStopped):
        agent.command("tick")
    assert agent.state["stop_code"] == "execution_deadline" and agent.state["repeated_reads"] == 0
    assert observes(tab) - before == 1 and tab.inputs() == 1


@pytest.fixture
def dom_agent(monkeypatch, tmp_path):
    """A real Agent and Browser on the actual snapshot adapter in Node, with the tab's own fake event source and
    one fake clock, and a scripted Jev."""
    made = []

    def make(answers, allowed_operations=ALL_OPERATIONS, **config):
        dom = NodePage(**config)
        made.append(dom)
        clock = {"ms": 0}
        tab = SimpleNamespace(clock=clock, schedule=[], lock=threading.Lock(), calls=[], failure=None,
                              permanent=False, closed_sources=0, sources=[], dom=dom, choices=0)
        monkeypatch.setattr(browser, "time", fake_time(clock))
        monkeypatch.setattr(loop, "time", fake_time(clock))
        monkeypatch.setattr(events, "open_events", lambda target, timeout: tab.sources.append(
            FakeEvents(tab, target, timeout)) or tab.sources[-1])
        tab.cdp = dom.cdp
        monkeypatch.setattr(browser, "cdp", lambda method, session_id=None, **params: tab.cdp(method, session_id,
                                                                                               **params))
        tab_browser = browser.Browser.__new__(browser.Browser)
        tab_browser.session, tab_browser.target, tab_browser.gate = "node-session", "T", "first input"
        monkeypatch.setattr(loop, "Browser", lambda url: tab_browser)
        pending = list(answers)

        def choose(observed, goal, history, operations, *, check_stop, remaining_budget, on_response):
            tab.choices += 1
            choice = pending.pop(0)
            if choice in {"DONE", "BLOCKED", "WAIT"}:
                return decision("wait" if choice == "WAIT" else choice)
            action = next(a for a in observed["actions"] if a.get("label") == choice)
            _, targets, _ = action_space(observed["actions"])
            head = next(key for key, value in targets["CLICK"].items() if value is action)
            return {"choice": action["id"], "operation": "CLICK", "target": head, "confidence": 1.0,
                    "probabilities": {action["id"]: 1.0}, "latency_ms": 10, "usage": {}}

        monkeypatch.setattr(loop, "choose", choose)
        agent = loop.Agent("http://fixture.test/dense", "Find the results", allowed_operations=allowed_operations,
                           trace_path=tmp_path / f"run-{len(made)}.json")
        tab.browser, tab.agent = tab_browser, agent
        tab.inputs = lambda: sum(method == "Input.dispatchMouseEvent" and params.get("type") == "mousePressed"
                                 for method, params in dom.calls)
        return tab

    yield make
    for dom in made:
        dom.close()


def test_two_unchanged_waits_hand_back_once(dom_agent):
    tab = dom_agent(["WAIT", "WAIT", "WAIT"], n=3, field=True)
    agent = tab.agent
    agent.command("tick")
    tokens = {agent.state["page"]["observation_token"]["generation"]}
    assert agent.state["status"] == "ready" and agent.state["wait_streak"] == 1
    with pytest.raises(ValueError, match="still loading"):
        agent.command("tick")
    tokens.add(agent.state["page"]["observation_token"]["generation"])
    assert len(tokens) == 2  # new observation tokens, the same progress: two unchanged WAITs hand back
    assert agent.state["status"] == "blocked" and len(agent.state["history"]) == loop.WAITS_BEFORE_CLAUDE
    assert tab.choices == 2 and tab.sources == [] and tab.inputs() == 0  # no third step, no input, no source
    with pytest.raises(ValueError):
        agent.command("tick")  # handed back once: nothing re-asks
    assert tab.choices == 2


def test_five_second_reread_leaves_no_new_loading_allowance(dom_agent):
    tab = dom_agent(["Control 1", "DONE"], n=3, field=True)
    agent, real, timed_out = tab.agent, tab.cdp, []

    def cdp(method, session_id=None, **params):
        if (method == "Runtime.evaluate" and params.get("expression") == browser.READ_STATE and tab.inputs()
                and not timed_out):
            timed_out.append(True)
            tab.clock["ms"] += 5000  # the read after the click takes its full 5 s, then times out
            raise TimeoutError("Runtime.evaluate timed out after 5s waiting for the daemon")
        return real(method, session_id, **params)

    tab.cdp = cdp
    agent.command("tick")
    clicked = tab.browser.input_done
    # The fixture page does not react to the click, so the repeated read finds it unchanged.
    assert timed_out and agent.state["repeated_reads"] == 1 and agent.state["history"][0]["page_changed"] is False
    tab.schedule.append((tab.clock["ms"], sent("late")))  # loading now: but the click is 5 s old
    agent.command("tick")
    assert agent.state["status"] == "done" and agent.state["loading_waits"] == []
    assert tab.browser.input_done == clicked and tab.inputs() == 1


def test_changed_results_drop_pending_done(dom_agent):
    tab = dom_agent(["Control 1", "DONE", "DONE"], n=3, field=True)
    agent, dom = tab.agent, tab.dom
    agent.command("tick")  # the click; its results load after it
    now = tab.clock["ms"]
    tab.schedule.extend([(now, sent("results")), (now + 700, ended("results")),
                         (now + 700, lambda: dom.evaluate("dom.texts[0].textContent='Results for the search'"))])
    agent.command("tick")  # DONE on the read before the results: the wait sees them load, then the page changed
    assert agent.state["status"] == "ready" and agent.state["decision"] is None
    [waited] = agent.state["loading_waits"]
    assert 800 <= waited[0] <= 820 and waited[1:] == [False, False]
    assert agent.state["stale_recoveries"] == 1 and agent.state["stale_decisions"] == 1
    assert "Results for the search" in agent.state["page"]["text"]  # the recovery read shows the results
    agent.command("tick")  # one fresh choice on the results: it stands
    assert agent.state["status"] == "done" and tab.choices == 3 and tab.inputs() == 1


# The tab's own connection: the real Connection and OwnedEvents on a scripted DevTools socket.

class FakeChrome:
    """A DevTools WebSocket that answers each call and sends Network events on the sessions that enabled them."""

    def __init__(self, targets=None, hang=()):
        self.targets = targets or {"T": "page", "FRAME": "iframe"}
        self.hang, self.sent, self.inbox = set(hang), [], queue.Queue()
        self.enabled, self.closed, self.attached = set(), False, 0

    def send(self, text):
        message = json.loads(text)
        self.sent.append(message)
        method, params = message["method"], message.get("params") or {}
        if method in self.hang:
            return
        if method == "Target.getTargetInfo":
            if params["targetId"] in self.targets:
                result = {"targetInfo": {"targetId": params["targetId"], "type": self.targets[params["targetId"]]}}
            else:
                return self.inbox.put(json.dumps({"id": message["id"], "error": {"message": "No target"}}))
        elif method == "Target.attachToTarget":
            self.attached += 1
            result = {"sessionId": f"OBSERVER-{self.attached}"}
        elif method == "Network.enable":
            self.enabled.add(message.get("sessionId"))
            result = {}
        else:
            result = {}
        self.inbox.put(json.dumps({"id": message["id"], "result": result}))

    def emit(self, session, method, **params):
        self.inbox.put(json.dumps({"method": method, "params": params, "sessionId": session}))

    def __iter__(self):
        while True:
            item = self.inbox.get()
            if item is None:
                return
            yield item

    def close(self):
        self.closed = True
        self.inbox.put(None)


@pytest.fixture
def chrome(monkeypatch):
    fake, opened, real = FakeChrome(), [], events.connect

    def connect(url, **options):
        inspect.signature(real).bind(url, **options)  # options the installed websockets accepts, as called
        assert options["proxy"] is None and options["open_timeout"] <= events.APPROVAL_SECONDS
        opened.append(url)
        return fake

    monkeypatch.setattr(events, "connect", connect)
    monkeypatch.setattr(events, "SHARED", {"connection": None})
    fake.opened = opened
    return fake


def test_owned_events_attach_their_own_session_and_enable_before_any_input(chrome):
    connection = events.Connection("ws://127.0.0.1:9/devtools/browser/secret", 1)
    try:
        source = events.OwnedEvents(connection, "T", 1)
        methods = [(message["method"], message.get("sessionId")) for message in chrome.sent]
        assert methods == [("Target.getTargetInfo", None), ("Target.attachToTarget", None),
                           ("Network.enable", "OBSERVER-1")]  # its own session, never the daemon's
        assert chrome.sent[1]["params"] == {"targetId": "T", "flatten": True}
        chrome.emit("OBSERVER-1", "Network.requestWillBeSent", requestId="r1", type="XHR", frameId="T",
                    request={"url": "https://example.test/private?q=value", "headers": {"Cookie": "secret"}})
        chrome.emit("OTHER-SESSION", "Network.requestWillBeSent", requestId="r2", type="XHR", frameId="X")
        chrome.emit("OBSERVER-1", "Network.loadingFinished", requestId="r1")
        deadline = time.monotonic() + 2
        while len(source.queue) < 2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert source.read() == ([("Network.requestWillBeSent", "r1", "XHR", "T"),
                                  ("Network.loadingFinished", "r1", None, None)], False)
        assert source.read() == ([], False)
    finally:
        connection.close()


def test_owned_events_never_attach_to_another_tab(chrome):
    connection = events.Connection("ws://127.0.0.1:9/devtools/browser/secret", 1)
    try:
        for target in ("ANOTHER", "FRAME"):  # gone, or not a page: never a replacement target or default tab
            with pytest.raises(EventConnectionLost):
                events.OwnedEvents(connection, target, 1)
        assert [message["method"] for message in chrome.sent] == ["Target.getTargetInfo"] * 2
    finally:
        connection.close()


def test_owned_events_keep_500_and_record_the_overflow(chrome):
    connection = events.Connection("ws://127.0.0.1:9/devtools/browser/secret", 1)
    try:
        source = events.OwnedEvents(connection, "T", 1)
        for number in range(events.EVENT_QUEUE):
            chrome.emit("OBSERVER-1", "Network.requestWillBeSent", requestId=f"f{number}", type="Image", frameId="T")
        deadline = time.monotonic() + 2
        while len(source.queue) < events.EVENT_QUEUE and time.monotonic() < deadline:
            time.sleep(0.005)
        batch, overflow = source.read()
        assert len(batch) == events.EVENT_QUEUE and overflow is False  # a full queue that dropped nothing lost nothing
        for number in range(events.EVENT_QUEUE + 1):
            chrome.emit("OBSERVER-1", "Network.requestWillBeSent", requestId=f"r{number}", type="Image", frameId="T")
        chrome.emit("OBSERVER-1", "Network.loadingFinished", requestId="marker")
        deadline = time.monotonic() + 2
        while (not source.queue or source.queue[-1][1] != "marker") and time.monotonic() < deadline:
            time.sleep(0.005)
        batch, overflow = source.read()
        assert len(batch) == events.EVENT_QUEUE and overflow is True and batch[-1][1] == "marker"
        assert source.read() == ([], False)  # the loss is reported once
    finally:
        connection.close()


def test_another_sessions_traffic_is_never_taken(chrome):
    """The connection routes by session: 600 events on another session (the daemon's tab, another tab) neither reach
    this source nor count as its loss, and nothing here reads the daemon's shared buffer."""
    connection = events.Connection("ws://127.0.0.1:9/devtools/browser/secret", 1)
    try:
        source = events.OwnedEvents(connection, "T", 1)
        for number in range(600):
            chrome.emit("OTHER-SESSION", "Network.requestWillBeSent", requestId=f"o{number}", type="XHR", frameId="X")
        chrome.emit("OBSERVER-1", "Network.requestWillBeSent", requestId="mine", type="Fetch", frameId="T")
        deadline = time.monotonic() + 2
        while not source.queue and time.monotonic() < deadline:
            time.sleep(0.005)
        assert source.read() == ([("Network.requestWillBeSent", "mine", "Fetch", "T")], False)
        assert set(connection.sources) == {"OBSERVER-1"}
    finally:
        connection.close()
    for module in (events, browser):  # no code path that could fall back to it: no import, name or attribute
        tree = ast.parse(Path(module.__file__).read_text())
        assert not [node for node in ast.walk(tree) if "drain_events" in {
            getattr(node, "id", None), getattr(node, "attr", None),
            *(alias.name for alias in getattr(node, "names", []) if isinstance(alias, ast.alias))}]


def test_an_owned_source_whose_setup_hangs_is_bounded_and_cleaned_up(chrome):
    chrome.hang.add("Network.enable")
    connection = events.Connection("ws://127.0.0.1:9/devtools/browser/secret", 1)
    try:
        started = time.monotonic()
        with pytest.raises(EventConnectionLost, match="did not answer Network.enable in time"):
            events.OwnedEvents(connection, "T", 0.2)
        assert time.monotonic() - started < 2 and connection.sources == {}  # nothing left registered
        assert chrome.sent[-1]["method"] == "Target.detachFromTarget"
    finally:
        connection.close()


def test_a_connection_that_closes_during_setup_fails_it_at_once(chrome):
    chrome.hang.add("Network.enable")
    connection = events.Connection("ws://127.0.0.1:9/devtools/browser/secret", 1)
    threading.Timer(0.1, chrome.close).start()
    started = time.monotonic()
    with pytest.raises(EventConnectionLost, match="closed"):
        events.OwnedEvents(connection, "T", 3)
    assert time.monotonic() - started < 2 and connection.sources == {}  # not the 3 s setup bound


def test_an_owned_connection_that_closes_is_never_quiet(chrome):
    connection = events.Connection("ws://127.0.0.1:9/devtools/browser/secret", 1)
    source = events.OwnedEvents(connection, "T", 1)
    chrome.close()  # no call pending: only the reader sees it
    assert connection.closed.wait(2)
    connection.reader.join(2)
    assert not connection.reader.is_alive()
    with pytest.raises(EventConnectionLost, match="closed"):
        source.read()
    with pytest.raises(EventConnectionLost):
        connection.call("Target.getTargetInfo", {"targetId": "T"}, timeout=1)


def test_no_endpoint_reaches_an_error_or_a_log(monkeypatch, caplog):
    secret = "ws://127.0.0.1:9/devtools/browser/0123-secret-token"

    def refused(url, **options):
        raise OSError(f"connection to {url} refused")

    monkeypatch.setattr(events, "connect", refused)
    monkeypatch.setattr(events, "SHARED", {"connection": None})
    monkeypatch.setenv("BU_CDP_WS", secret)
    with caplog.at_level(logging.DEBUG), pytest.raises(EventConnectionLost) as error:
        events.open_events("T", 1)
    assert "secret" not in str(error.value) and "127.0.0.1" not in str(error.value)
    assert error.value.code == "event_connection_lost" and "secret" not in caplog.text


def test_one_connection_serves_every_tab_and_goal(chrome, monkeypatch):
    monkeypatch.setenv("BU_CDP_WS", "ws://127.0.0.1:9/devtools/browser/secret")
    first, second = events.open_events("T", 1), events.open_events("T", 1)
    try:
        assert len(chrome.opened) == 1 and first.connection is second.connection
        session = first.session
        assert session != second.session  # each goal's source has its own observer session
        first.close()
        assert chrome.sent[-1] == {"id": chrome.sent[-1]["id"], "method": "Target.detachFromTarget",
                                   "params": {"sessionId": session}}
        assert set(first.connection.sources) == {second.session}  # closing one leaves the other attached
        second.connection.close()
        assert second.connection.closed.wait(2)
        third = events.open_events("T", 1)  # a closed connection is opened again, once
        assert len(chrome.opened) == 2 and third.connection is not second.connection
        assert events.open_events("T", 1).connection is third.connection
    finally:
        events.SHARED["connection"].close()


@pytest.mark.parametrize(("kind", "setting", "mode"), [
    ("cdp", None, "first input"), ("cdp", "1", "first input"), ("cdp", "0", None),
    ("local", None, None), ("local", "1", "setup"), ("local", "0", None), ("cloud", None, None), (None, None, None),
])
def test_the_loading_gate_asks_no_approval_unless_opted_in(monkeypatch, kind, setting, mode):
    """An explicit endpoint costs no approval; your own Chrome asks once per connection (Chrome 144+), so only
    JEV_LOADING_GATE=1 opens one, at browser setup (status.md §4.3)."""
    if setting is None:
        monkeypatch.delenv("JEV_LOADING_GATE", raising=False)
    else:
        monkeypatch.setenv("JEV_LOADING_GATE", setting)
    assert events.gate_mode(kind) == mode


def test_your_own_chrome_is_asked_at_setup_never_inside_a_run(tab, monkeypatch):
    opened = []
    monkeypatch.setattr(browser, "daemon_browser_kind", lambda: "local")
    monkeypatch.setenv("JEV_LOADING_GATE", "1")
    monkeypatch.setattr(events, "shared_connection", lambda timeout: opened.append(timeout))
    setup = browser.Browser("https://example.test/")
    assert setup.gate == "setup" and opened == [events.APPROVAL_SECONDS] and not setup.network
    monkeypatch.delenv("JEV_LOADING_GATE")
    assert browser.Browser("https://example.test/").gate is None and len(opened) == 1


def test_a_new_goal_prepares_the_approval_connection_before_its_budget(agent_tab, tab, monkeypatch):
    """With your own Chrome opted in, a valid new goal opens the loading wait's connection again if it closed, at
    setup; an invalid one asks nothing. The first input then only attaches to the tab."""
    agent = agent_tab(["e3"])
    tab.browser.gate, opened = "setup", []
    monkeypatch.setattr(events, "shared_connection", lambda timeout: opened.append(timeout))
    with pytest.raises(ValueError):
        agent.new_goal("Next", allowed_operations=["UNKNOWN"], trace_path=agent.trace_path.with_name("next.json"))
    assert opened == []
    agent.new_goal("Next", allowed_operations=ALL_OPERATIONS, trace_path=agent.trace_path.with_name("next.json"))
    assert opened == [events.APPROVAL_SECONDS] and agent.deadline is None  # before the goal's budget started
