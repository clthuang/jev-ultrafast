"""Offline contracts for a dynamic operation/target policy. No paid APIs."""

import json
import time
from copy import deepcopy
from datetime import date
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import model, site_notes
from jev_ultrafast.browser import StalePage, browser_operation, fingerprint


def page():
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def choice(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(action="e1"):
    return {
        "choice": action,
        "operation": "TYPE_TEXT",
        "target": "1",
        "confidence": 1.0,
        "probabilities": {action: 1.0},
        "latency_ms": 10,
        "usage": {},
    }


@pytest.mark.parametrize("mutation", ["unknown", "nan", "missing", "negative", "non_max", "confidence"])
def test_invalid_choice_is_rejected(mutation):
    a = choice(["a", "b"], "a")
    if mutation == "unknown":
        a["choice"] = "invented"
    elif mutation == "nan":
        a["probabilities"]["a"] = float("nan")
    elif mutation == "missing":
        del a["probabilities"]["b"]
    elif mutation == "negative":
        a["probabilities"]["b"] = -1
    elif mutation == "non_max":
        a["choice"] = "b"
    else:
        a["confidence"] = 5
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(a, {"a", "b"})


def test_one_index_per_node_with_operation_specific_targets():
    elements, targets, controls = model.action_space(page()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1"
    assert targets["CLICK"]["1"]["id"] == "e2"
    assert targets["CLICK"]["2"]["id"] == "e3"
    assert "WAIT" in controls


def test_all_heads_are_one_request_and_only_matching_head_executes(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "click_target": {"choice": "invented"},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert len(calls) == 1
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert set(calls[0]["questions"]) == {"operation", "click_target", "type_text_target", "commit_1", "commit_2"}


def test_click_cannot_consume_a_text_target(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "type_text_target": choice(["1"], "1"),
                "click_target": choice(["1", "2", "999"], "999"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


def test_target_head_receives_control_state_and_full_next_step_rules(monkeypatch):
    p = page()
    p["actions"].insert(0, {
        "id": "toggle", "kind": "click", "label": "Free cancellation", "node": 30,
        "role": "checkbox", "checked": "true", "selected": False,
    })

    def post(_url, _key, body):
        questions = body["questions"]
        target = questions["click_target"]
        assert target["criteria"]["1"]["checked"] == "true"
        assert target["criteria"]["1"]["selected"] is False
        assert questions["operation"]["instructions"]["rules"] in target["instructions"]["rules"]
        return {
            "model": "test",
            "answers": {
                "operation": choice(questions["operation"]["criteria"], "CLICK"),
                "click_target": choice(target["criteria"], "3"),
                "commit_3": {"type": "noul", "noul": 0.0},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Search with free cancellation", [])
    assert d["choice"] == "e3"


def test_quoted_task_text_still_uses_the_llm(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.field_context('Fly from "Zurich" to London', page()["actions"][0], page(), [])
    assert model.field_text(context)[0] == "Zurich"
    assert post.call_count == 1
    sent = json.loads(post.call_args.args[2]["messages"][1]["content"])
    assert sent["goal"] == 'Fly from "Zurich" to London'


def test_missing_text_credential_stops_before_guessing(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        model.field_text({"goal": 'Enter "Zurich"'})


@pytest.mark.parametrize("key", [None, ""])
def test_missing_typesafe_key_names_the_variable(monkeypatch, key):
    # .env.example ships the key blank, which sets it to an empty string.
    if key is None:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TYPESAFE_API_KEY", key)
    post = Mock()
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY is not set"):
        model.choose(page(), "Find a book", [])
    post.assert_not_called()


def test_null_text_names_the_missing_field(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": '{"text":null}'}}]}))
    context = model.field_context("Find a book", page()["actions"][0], page(), [])
    with pytest.raises(ValueError, match="The goal gives no value for 'Search'; nothing typed"):
        model.field_text(context)


def commit_answers(body, operation, target, **commit):
    return {
        "model": "test",
        "answers": {
            "operation": choice(body["questions"]["operation"]["criteria"], operation),
            operation.lower() + "_target": choice(body["questions"][operation.lower() + "_target"]["criteria"], target),
            **commit,
        },
    }


def test_commit_question_rides_in_the_same_request(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return commit_answers(body, "CLICK", "2", commit_1={"noul": 0.1}, commit_2={"noul": 0.9})

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    commits = {q: v for q, v in calls[0]["questions"].items() if q.startswith("commit_")}
    assert len(calls) == 1 and d["choice"] == "e3" and d["commit_probability"] == 0.9
    assert set(commits) == {"commit_1", "commit_2"} and commits["commit_2"]["type"] == "noul"
    assert "[2] Go" in commits["commit_2"]["instructions"]
    assert "Find a book" not in json.dumps(commits)  # What an element does must not depend on the goal.


def test_commit_probability_is_zero_without_a_click_or_select_target(monkeypatch):
    # The unused commit answer is invalid, and is neither validated nor consumed.
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", lambda _u, _k, body: commit_answers(body, "TYPE_TEXT", "1", commit_1={}))
    assert model.choose(page(), "Find a book", [])["commit_probability"] == 0


@pytest.mark.parametrize("answer", [{}, {"noul": 1.5}, {"noul": float("nan")}, {"noul": "0.9"}])
def test_invalid_commit_answer_is_rejected(monkeypatch, answer):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", lambda _u, _k, body: commit_answers(body, "CLICK", "2", commit_2=answer))
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


@pytest.fixture
def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.screenshots = False
    a.pending_text = None
    a.record_dir = None
    a.trace_path = None
    a.before_input = None
    p = page()
    a.browser = Mock(fresh=Mock(return_value=True), observe=Mock(return_value=p))
    # The real builder, so every state key the Agent adds is present here too.
    a._fresh_state("Find a book", p, None)
    a.state.update(decision=decision(), status="predicted", started_at=time.perf_counter())
    return a


def test_stale_decision_is_consumed_before_any_mutation(runner):
    runner.state["browser"].fresh.return_value = False
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["decision"] is None


def test_generated_text_reused_only_for_identical_retry_context(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 1
    assert runner.state["browser"].act.call_count == 2  # The first call rejects before any browser input.
    assert runner.pending_text is None


def test_changed_field_context_does_not_reuse_generated_text(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["page"]["text"] = "Different page context"
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 2


def test_loading_waits_do_not_trigger_no_progress_stop(runner):
    # Five unchanged steps, never three clicks in a row: a WAIT breaks the no-progress count, and one WAIT stays below
    # the count that hands the run back to Claude (docs/executor-improvements.md §5).
    for action in ("e3", "e3", "wait", "e3", "e3"):
        runner.state["decision"] = decision(action)
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert len(runner.state["history"]) == 5 and runner.state["status"] == "ready"


def test_two_unchanged_wait_steps_return_the_run_to_claude(runner):
    runner.state["decision"] = decision("wait")
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "ready" and runner.state["wait_streak"] == 1
    runner.state["decision"] = decision("wait")
    with pytest.raises(ValueError, match=f"^{site_notes.STILL_LOADING_STOP}$"):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "blocked" and len(runner.state["history"]) == loop.WAITS_BEFORE_CLAUDE


@pytest.mark.parametrize(
    "between",
    [
        "a WAIT step that changed the page",
        "another step that changed the page",
        "a read before Jev's answer that changed",
        "a stale answer whose re-read changed",
        "a failed re-read",
    ],
)
def test_visible_progress_between_waits_restarts_the_count(between, runner, monkeypatch):
    changed = dict(page(), text="Results")
    changed["fingerprint"] = fingerprint(changed)
    runner.state["decision"] = decision("wait")
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["wait_streak"] == 1
    if between in ("a WAIT step that changed the page", "another step that changed the page"):
        runner.state["browser"].observe.return_value = changed
        runner.state["decision"] = decision("wait" if between.startswith("a WAIT") else "e3")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    elif between == "a read before Jev's answer that changed":
        monkeypatch.setattr(loop, "choose", lambda *_: decision("wait"))
        runner.state["browser"].fresh.return_value = False  # the page changed after the last step's read
        runner.state["browser"].observe.return_value = changed
        runner.command("predict", {})
        runner.state["browser"].fresh.return_value = True
    else:
        monkeypatch.setattr(loop, "choose", lambda *_: decision("e3"))
        runner.state["browser"].act.side_effect = StalePage("Page changed since this decision. Observe again.")
        runner.state["browser"].observe.side_effect = (
            [changed] if between == "a stale answer whose re-read changed" else StalePage("Page did not settle")
        )
        runner.command("tick")
        runner.state["browser"].act.side_effect = runner.state["browser"].observe.side_effect = None
        runner.state["browser"].observe.return_value = runner.state["page"]
    assert runner.state["wait_streak"] == 0
    runner.state["decision"] = decision("wait")
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["status"] == "ready" and runner.state["wait_streak"] == 1


@pytest.mark.parametrize("between", ["a step that changed nothing", "a stale answer whose re-read matches"])
def test_no_visible_progress_between_waits_keeps_the_count(between, runner, monkeypatch):
    runner.state["decision"] = decision("wait")
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    if between == "a step that changed nothing":  # unchanged clicks and WAITs in turn escape the no-progress stop
        runner.state["decision"] = decision("e3")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    else:
        monkeypatch.setattr(loop, "choose", lambda *_: decision("e3"))
        runner.state["browser"].act.side_effect = StalePage("Target is covered by <div>. Observe again.")
        runner.command("tick")  # the re-read matches the read Jev answered on
        runner.state["browser"].act.side_effect = None
        assert runner.state["stale_decisions"] == 1
    assert runner.state["wait_streak"] == 1
    runner.state["decision"] = decision("wait")
    with pytest.raises(ValueError, match=site_notes.STILL_LOADING_STOP):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})


def test_stale_observation_preserves_executed_action(runner):
    runner.state["decision"] = decision("e3")
    runner.state["browser"].observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["action"] == "Go"
    runner.state["browser"].act.assert_called_once()


def test_observation_is_one_atomic_browser_read(monkeypatch):
    import jev_ultrafast.browser as browser

    p = page()
    cdp = Mock(return_value={"result": {"value": p}})
    monkeypatch.setattr(browser, "cdp", cdp)
    actual = browser_operation({"operation": "observe", "session": "test", "screenshot": False})
    assert actual["actions"] == p["actions"]
    assert cdp.call_count == 1
    assert cdp.call_args.args[0] == "Runtime.evaluate"


def test_executor_rejects_a_stale_page_before_browser_input(monkeypatch):
    import jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=False)
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    with pytest.raises(StalePage):
        b.act(page()["actions"][0], page(), "book")
    operation.assert_not_called()


def test_browser_caps_chrome_approval_wait(monkeypatch):
    import jev_ultrafast.browser as browser

    waits = []

    def ensure_daemon(**kwargs):
        waits.append(kwargs)
        raise RuntimeError("permission-blocked: Chrome did not approve the connection")

    cdp = Mock()
    monkeypatch.setattr(browser, "ensure_daemon", ensure_daemon)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="permission-blocked"):
        browser.Browser("https://example.test/")
    assert waits == [{"wait": 30}]
    cdp.assert_not_called()


def test_constructor_failure_closes_target(monkeypatch):
    import jev_ultrafast.browser as browser

    calls = []

    def cdp(method, session_id=None, **params):
        calls.append((method, params))
        if method == "Target.attachToTarget":
            raise RuntimeError("attach failed")
        return {"targetId": "T"}

    monkeypatch.setattr(browser, "ensure_daemon", lambda **_: None)
    monkeypatch.setattr(browser, "foreign_browser_port", lambda: None)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="attach failed"):
        browser.Browser("https://example.test/")
    assert calls[-1] == ("Target.closeTarget", {"targetId": "T"})


def test_browser_opens_its_own_unfocused_window_unless_background_tab_is_set(monkeypatch):
    import jev_ultrafast.browser as browser

    monkeypatch.setattr(browser, "ensure_daemon", lambda **_: None)
    monkeypatch.setattr(browser, "foreign_browser_port", lambda: None)

    def created(**environment):
        for key, value in {"JEV_BACKGROUND_TAB": None, **environment}.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        cdp = Mock(side_effect=lambda method, session_id=None, **params: (
            {"targetId": "T"} if method == "Target.createTarget" else
            {"sessionId": "S"} if method == "Target.attachToTarget" else
            {"result": {"value": "complete"}}
        ))
        monkeypatch.setattr(browser, "cdp", cdp)
        browser.Browser("https://example.test/")
        return cdp.call_args_list[0].kwargs

    assert created() == {"url": "about:blank", "background": True, "newWindow": True, "width": 1120, "height": 880}
    assert created(JEV_BACKGROUND_TAB="1") == {"url": "about:blank", "background": True}


def test_browser_of_another_account_opens_no_tab_and_drops_the_daemon(monkeypatch):
    import jev_ultrafast.browser as browser

    cdp, restart = Mock(), Mock()
    monkeypatch.setattr(browser, "ensure_daemon", lambda **_: None)
    monkeypatch.setattr(browser, "foreign_browser_port", lambda: "9223")
    monkeypatch.setattr(browser, "restart_daemon", restart)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="port 9223 belongs to another macOS account; no tab opened"):
        browser.Browser("https://example.test/")
    cdp.assert_not_called()
    restart.assert_called_once()


@pytest.mark.parametrize("listener, expected", [("", "9223"), ("4711\n", None)])
def test_foreign_browser_port_checks_only_this_daemon_with_exact_lsof_flags(monkeypatch, listener, expected):
    import jev_ultrafast.browser as browser

    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert kwargs["timeout"] == 5  # lsof can block; a hang must not hold the MCP run lock
        return Mock(stdout="p812\nn127.0.0.1:65093->127.0.0.1:9223\n" if "-p" in args else listener)

    monkeypatch.setattr(browser, "daemon_browser_kind", lambda: "local")
    monkeypatch.setattr(browser.ipc, "identify", lambda name: 812)
    monkeypatch.setattr(browser, "LSOF", "/usr/sbin/lsof")
    monkeypatch.setattr(browser.subprocess, "run", run)
    uid = str(browser.os.getuid())
    assert browser.foreign_browser_port() == expected
    # -a ANDs the filters; without it lsof lists every process. -sTCP:LISTEN keeps the daemon's own socket out.
    assert calls == [
        ["/usr/sbin/lsof", "-a", "-nP", "-p", "812", "-iTCP", "-sTCP:ESTABLISHED", "-Fn"],
        ["/usr/sbin/lsof", "-a", "-nP", "-u", uid, "-iTCP:9223", "-sTCP:LISTEN", "-t"],
    ]


@pytest.mark.parametrize("kind, daemon, checked", [("cdp", 812, False), ("local", None, False), ("local", 812, True)])
def test_account_check_runs_only_for_a_probed_live_daemon(monkeypatch, kind, daemon, checked):
    import jev_ultrafast.browser as browser

    # BU_CDP_URL in this process alone does not skip: an already-running daemon may still be on a probed port.
    monkeypatch.setenv("BU_CDP_URL", "http://127.0.0.1:9222")
    monkeypatch.setattr(browser, "daemon_browser_kind", lambda: kind)
    monkeypatch.setattr(browser.ipc, "identify", lambda name: daemon)
    run = Mock(return_value=Mock(stdout=""))
    monkeypatch.setattr(browser.subprocess, "run", run)
    browser.foreign_browser_port()
    assert run.called is checked


def test_close_popups_closes_only_targets_opened_by_this_tab(monkeypatch):
    import jev_ultrafast.browser as browser

    cdp = Mock(return_value={"targetInfos": [
        {"targetId": "T", "url": "https://example.test/"},
        {"targetId": "P", "openerId": "T", "url": "about:blank"},
        {"targetId": "Q", "openerId": "other", "url": "https://other.test/"},
    ]})
    monkeypatch.setattr(browser, "cdp", cdp)
    b = browser.Browser.__new__(browser.Browser)
    b.target = "T"
    assert b.close_popups() == ["about:blank"]
    closed = [c.kwargs["targetId"] for c in cdp.call_args_list if c.args[0] == "Target.closeTarget"]
    assert closed == ["P"]


@pytest.mark.parametrize("error, dismissed", [(None, True), (RuntimeError("No dialog is showing"), False)])
def test_dismiss_dialog_never_accepts(monkeypatch, error, dismissed):
    import jev_ultrafast.browser as browser

    cdp = Mock(return_value={}, side_effect=error)
    monkeypatch.setattr(browser, "cdp", cdp)
    b = browser.Browser.__new__(browser.Browser)
    b.session = "S"
    assert b.dismiss_dialog() is dismissed
    cdp.assert_called_once_with("Page.handleJavaScriptDialog", session_id="S", accept=False)


@pytest.mark.parametrize(
    "hit, message",
    [
        ({"covered": "com-1password-menu"}, "Target is covered by <com-1password-menu>. Observe again."),
        (None, "Target changed or is covered. Observe again."),  # e.g. disabled, hidden, or off-screen
    ],
)
def test_hit_test_names_what_covers_the_target(monkeypatch, hit, message):
    import jev_ultrafast.browser as browser

    cdp = Mock(return_value={"result": {"value": hit}})
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(StalePage) as stale:
        browser_operation({"operation": "act", "session": "test", "action": page()["actions"][0], "text": "book"})
    assert str(stale.value) == message and cdp.call_count == 1  # rejected before any input


@pytest.mark.parametrize(
    "response", [{"exceptionDetails": {}}, {"result": {}}, {"result": {"value": {"covered": "div"}}}]
)
def test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(monkeypatch, response):
    import jev_ultrafast.browser as browser

    # A navigation can destroy the evaluation result after the change event already fired.
    if "exceptionDetails" in response:
        response["exceptionDetails"] = {"text": "Execution context destroyed"}
    cdp = Mock(return_value=response)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="Dropdown execution"):
        browser_operation({"operation": "act", "session": "test", "action": {
            "id": "e1", "kind": "select", "node": 1, "value": "Design",
        }})
    assert cdp.call_count == 1


def test_fingerprint_tracks_values_and_identity_not_screenshots():
    p = page()
    other = deepcopy(p)
    other["screenshot"] = "changed"
    assert fingerprint(p) == fingerprint(other)
    other["actions"][0]["node"] = 99
    assert fingerprint(p) != fingerprint(other)


@pytest.mark.parametrize("changed", ["Departure", "Where from?", "Where to?", "year"])
def test_flight_verification_rejects_wrong_trip(changed):
    from examples.flights import verify

    actual = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": "Track prices from Zürich to London departing 2026-09-20",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", "London"),
                ("Departure", "Sun, Sep 20"),
                ("Nonstop flight on Sunday, September 20. Select flight", ""),
            ]
        ],
    }
    assert verify(actual, departure=date(2026, 9, 20))["passed"]
    if changed == "year":
        actual["text"] = actual["text"].replace("2026", "2027")
    else:
        next(a for a in actual["actions"] if a["label"] == changed)["value"] = "wrong"
    assert not verify(actual, departure=date(2026, 9, 20))["passed"]


def test_flight_verification_accepts_the_airport_label():
    from examples.flights import verify

    page = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": "Track prices from Zürich to London departing 2026-09-20",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from? Zürich ZRH", "Zürich"),  # the airport was chosen; the value is unchanged
                ("Where to?", "London"),
                ("Departure", "Sun, Sep 20"),
                ("Nonstop flight on Sunday, September 20. Select flight", ""),
            ]
        ],
    }
    assert verify(page, departure=date(2026, 9, 20))["passed"]
    page["actions"][1]["value"] = "Zug"
    assert not verify(page, departure=date(2026, 9, 20))["checks"]["origin"]


def test_flights_goal_and_verify_share_a_future_date():
    from examples.flights import DEPARTURE, GOALS, goal_for, verify

    assert DEPARTURE > date.today()
    assert GOALS == goal_for(DEPARTURE)
    page = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": f"Track prices from Zürich to London departing {DEPARTURE.isoformat()}",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", "London"),
                ("Departure", f"{DEPARTURE:%a}, {DEPARTURE:%b} {DEPARTURE.day}"),
                (f"Nonstop flight on {DEPARTURE:%A}, {DEPARTURE:%B} {DEPARTURE.day}. Select flight", ""),
            ]
        ],
    }
    assert verify(page)["passed"]


@pytest.mark.parametrize(
    "departure, shown, in_text, flight_day, failing",
    [
        (date(2026, 10, 5), "Mon, Oct 5", "2026-10-05", "Monday, October 5", []),
        (date(2026, 10, 1), "Thu, Oct 1", "2026-10-01", "Thursday, October 15", ["results"]),
    ],
)
def test_flight_verification_matches_whole_unpadded_dates(departure, shown, in_text, flight_day, failing):
    from examples.flights import verify

    page = {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": f"Track prices from Zürich to London departing {in_text}",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", "London"),
                ("Departure", shown),
                (f"Nonstop flight on {flight_day}. Select flight", ""),
            ]
        ],
    }
    checks = verify(page, departure=departure)["checks"]
    assert [name for name, passed in checks.items() if not passed] == failing


@pytest.mark.parametrize(
    "content", ["Thinking: Zurich", '{"text":"Zurich","extra":true}', '{"text":123}']
)
def test_text_helper_rejects_invalid_values(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Find a flight"})


def test_navigation_during_prediction_reobserves_without_action(runner):
    runner.state["browser"].fresh.side_effect = StalePage("Document navigating")
    runner.command("tick")
    assert runner.state["status"] == "ready"
    assert runner.state["decision"] is None
    runner.state["browser"].act.assert_not_called()


def act(runner, action="e3", **decision_fields):
    runner.state["decision"] = dict(decision(action), **decision_fields)
    return runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})


def test_new_goal_resets_every_counter(runner):
    browser = runner.browser
    runner.state.update(
        history=[{"step": 1}], decisions=[{}], text_calls=[{}], stale_decisions=2, stale_streak=2, elapsed_ms=5
    )
    runner.new_goal("  Open the cart  ", allowed_sites=["shop.test"])
    state = runner.state
    assert (state["history"], state["decisions"], state["text_calls"], state["stale_decisions"]) == ([], [], [], 0)
    assert state["stale_streak"] == 0
    assert state["decision"] is None and state["status"] == "ready" and state["attempt"] is None
    assert state["allow_commit"] is False
    assert state["started_at"] is None and state["elapsed_ms"] == 0
    assert state["goal"] == "Open the cart" and state["allowed_sites"] == ["example.test", "shop.test"]
    assert state["browser"] is browser
    browser.observe.assert_called_once()


def test_tick_survives_a_slow_navigation(runner):
    runner.state["browser"].fresh.side_effect = StalePage("Document is navigating")
    runner.state["browser"].observe.side_effect = StalePage("Page did not settle")
    before = runner.state["page"]
    runner.command("tick")
    assert runner.state["status"] == "ready" and runner.state["page"] is before
    runner.state["browser"].act.assert_not_called()


def test_stale_decisions_count_only_dropped_decisions(runner, monkeypatch):
    monkeypatch.setattr(loop, "choose", lambda *_: decision("e3"))
    runner.state["browser"].act.side_effect = StalePage("Page changed since this decision. Observe again.")
    runner.command("tick")
    assert runner.state["stale_decisions"] == 1
    assert runner.state["attempt"] is None  # the dropped decision performed no input
    runner.state["browser"].act.side_effect = None
    runner.state["browser"].observe.side_effect = StalePage("Page did not settle")
    runner.command("tick")
    assert runner.state["stale_decisions"] == 1 and runner.state["history"][-1]["action"] == "Go"


def test_three_stale_choices_on_an_unchanged_page_block(runner, monkeypatch):
    choose = Mock(return_value=decision("e3"))
    monkeypatch.setattr(loop, "choose", choose)
    runner.state["browser"].act.side_effect = StalePage("Target is covered by <com-1password-menu>. Observe again.")
    with pytest.raises(ValueError, match="Three choices in a row went stale.*covered by <com-1password-menu>"):
        list(runner.run())
    assert runner.state["status"] == "blocked" and runner.state["stale_decisions"] == 3
    assert choose.call_count == 3 and runner.state["browser"].act.call_count == 3


def test_stale_streak_restarts_on_a_changed_page_a_failed_read_or_a_step(runner, monkeypatch):
    monkeypatch.setattr(loop, "choose", lambda *_: decision("e3"))
    covered, unsettled = StalePage("Target is covered by <div>. Observe again."), StalePage("Page did not settle")
    changed = dict(page(), text="Results")
    changed["fingerprint"] = fingerprint(changed)
    # Ticks 3, 6, 9, 12 each break the streak: a changed page, a failed re-read, a step, a step whose re-read fails.
    runner.state["browser"].act.side_effect = [covered] * 8 + [None] + [covered] * 2 + [None] + [covered] * 3
    reads = [page(), page()] + [changed] * 3 + [unsettled] + [changed] * 5 + [unsettled] + [changed] * 4
    runner.state["browser"].observe.side_effect = reads
    for _ in range(14):
        runner.command("tick")
    assert runner.state["status"] == "ready" and runner.state["stale_decisions"] == 12
    assert len(runner.state["history"]) == 2
    with pytest.raises(ValueError, match="Three choices in a row"):  # after the last break, the count resumes
        runner.command("tick")


def test_site_boundary_blocks_before_input(runner):
    runner.state["page"]["url"] = "https://elsewhere.test/pay"
    with pytest.raises(ValueError, match="Left the allowed sites at elsewhere.test"):
        act(runner)
    assert runner.state["status"] == "blocked"
    runner.state["browser"].act.assert_not_called()


def test_site_boundary_allows_subdomains_and_star(runner):
    start = dict(page(), url="https://www.example.test/")
    runner._fresh_state("Find a book", start, ["https://www.Shop.test/cart"])
    assert runner.state["allowed_sites"] == ["example.test", "shop.test"]
    runner.state["started_at"] = time.perf_counter()
    for url in ["https://accounts.example.test/", "https://shop.test/cart"]:
        runner.state["page"] = dict(start, url=url)
        act(runner)
    runner._fresh_state("Find a book", start, ["*"])
    runner.state["started_at"] = time.perf_counter()
    runner.state["page"] = dict(start, url="https://anywhere.test/")
    act(runner)
    assert runner.state["browser"].act.call_count == 3


def test_attempt_is_saved_before_input(runner, tmp_path):
    runner.trace_path = tmp_path / "run.json"
    seen = []
    runner.state["browser"].act.side_effect = lambda *_a, **_k: seen.append(
        json.loads(runner.trace_path.read_text())["attempt"]
    )
    act(runner)
    assert seen == [{"step": 1, "action": "Go", "kind": "click", "target": "1", "text": None}]
    saved = json.loads(runner.trace_path.read_text())
    assert saved["attempt"] is None and saved["history"][-1]["action"] == "Go"


def test_failed_save_before_input_executes_nothing(runner, tmp_path):
    runner.trace_path = tmp_path / "missing" / "run.json"
    with pytest.raises(RuntimeError, match="Run file incomplete"):
        act(runner)
    runner.state["browser"].act.assert_not_called()


@pytest.mark.parametrize("text_calls", [0, 1])  # stopped before the text call, or during it
def test_stop_check_skips_the_text_call_and_the_input(runner, monkeypatch, tmp_path, text_calls):
    runner.trace_path = tmp_path / "run.json"
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.before_input = Mock(side_effect=[None] * text_calls + [ValueError("stopped")])
    with pytest.raises(ValueError, match="stopped"):
        act(runner, "e1")
    assert helper.call_count == text_calls
    runner.state["browser"].act.assert_not_called()
    assert runner.state["attempt"] is None and not runner.trace_path.exists()


def test_failed_save_after_input_skips_the_reread(runner, monkeypatch):
    monkeypatch.setattr(runner, "save", Mock(side_effect=[None, RuntimeError("Run file incomplete: disk full")]))
    with pytest.raises(RuntimeError, match="Run file incomplete"):
        act(runner)
    runner.state["browser"].act.assert_called_once()
    runner.state["browser"].observe.assert_not_called()
    assert runner.state["history"][-1]["action"] == "Go"


def test_step_is_saved_when_the_reread_fails(runner, tmp_path):
    runner.trace_path = tmp_path / "run.json"
    runner.state["browser"].observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        act(runner)
    saved = json.loads(runner.trace_path.read_text())
    assert saved["history"][-1]["action"] == "Go" and saved["attempt"] is None


def test_stale_input_clears_the_saved_attempt(runner, monkeypatch, tmp_path):
    runner.trace_path = tmp_path / "run.json"
    monkeypatch.setattr(loop, "choose", lambda *_: decision("e3"))
    runner.state["browser"].act.side_effect = StalePage("changed before input")
    runner.command("tick")
    assert json.loads(runner.trace_path.read_text())["attempt"] is None


def test_run_saves_the_final_state(runner, monkeypatch, tmp_path):
    runner.trace_path = tmp_path / "run.json"
    runner.state["status"] = "ready"
    monkeypatch.setattr(loop, "choose", lambda *_: decision("DONE"))
    list(runner.run())
    saved = json.loads(runner.trace_path.read_text())
    assert saved["status"] == "done" and saved["decisions"][-1]["choice"] == "DONE"


def test_failed_final_save_keeps_the_error_that_stopped_the_run(runner, monkeypatch):
    monkeypatch.setattr(runner, "command", Mock(side_effect=ConnectionError("Model connection lost")))
    monkeypatch.setattr(runner, "save", Mock(side_effect=RuntimeError("Run file incomplete: disk full")))
    with pytest.raises(ConnectionError):
        list(runner.run())
    runner.save.assert_called_once()
    runner.command.side_effect = lambda _name: runner.state.update(status="done")
    with pytest.raises(RuntimeError, match="Run file incomplete"):  # a clean stop still reports its failed save
        list(runner.run())


def test_closing_a_run_early_saves_its_state(runner, monkeypatch, tmp_path):
    runner.trace_path = tmp_path / "run.json"
    monkeypatch.setattr(runner, "command", Mock(return_value={}))  # a step that saves nothing itself
    steps = runner.run()
    next(steps)
    steps.close()  # what a for loop's break, or dropping the generator, does
    assert json.loads(runner.trace_path.read_text()) == json.loads(json.dumps(runner.snapshot()))


def test_decision_records_omitted_actions(runner, monkeypatch):
    monkeypatch.setattr(loop, "choose", lambda *_: decision("e3"))
    runner.state["page"]["omitted_actions"] = 12
    runner.command("predict")
    assert runner.state["decisions"][-1]["omitted_actions"] == 12


def test_model_call_budget_blocks(runner):
    runner.state["decisions"] = [{}] * (loop.MAX_STEPS * 2)
    with pytest.raises(ValueError, match="model-call budget"):
        runner.command("predict")
    assert runner.state["status"] == "blocked"


def test_unallowed_commit_stops_before_input(runner):
    with pytest.raises(ValueError, match="'Go' may pay, buy, book, send, delete.*pass allow_commit"):
        act(runner, commit_probability=0.9)
    assert runner.state["status"] == "blocked"
    runner.state["browser"].act.assert_not_called()


def test_allowed_commit_executes(runner):
    runner.state["allow_commit"] = True
    act(runner, commit_probability=0.9)
    runner.state["browser"].act.assert_called_once()
