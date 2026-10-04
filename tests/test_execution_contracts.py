"""Operation policy contracts through public entries, model heads, and inspector rendering."""

import ast
import asyncio
import json
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import browser, demo, mcp_server, model
from jev_ultrafast.browser import StalePage, fingerprint
from jev_ultrafast.contracts import RunStopped
from scripts import report_runs

ROOT = Path(__file__).resolve().parents[1]
ALL_OPERATIONS = ["CLICK", "TYPE_TEXT", "SELECT", "SCROLL_UP", "SCROLL_DOWN", "WAIT"]
INVALID_POLICIES = [
    None, "CLICK", ("CLICK",), {"CLICK": True}, 1, [None], [1], [[]],
    ["CLICK", "CLICK"], ["click"], ["UNKNOWN"], ["DONE"], ["BLOCKED"],
]


def observed_page():
    page = {
        "url": "https://example.test/", "title": "Search", "text": "Search results", "w": 1000, "h": 800,
        "scroll": {"y": 0}, "screenshot": "",
        "actions": [
            {"id": "button", "node": 10, "kind": "click", "role": "button", "label": "Search", "value": ""},
            {"id": "field", "node": 20, "kind": "fill", "role": "textbox", "label": "Query", "value": "old",
             "rect": {"x": 10, "y": 20, "w": 100, "h": 30}},
            {"id": "field_click", "node": 20, "kind": "click", "role": "textbox", "label": "Query", "value": "old",
             "rect": {"x": 10, "y": 20, "w": 100, "h": 30}},
            {"id": "option", "node": 30, "kind": "select", "role": "combobox", "label": "Category → Books",
             "value": "books", "current_value": "All"},
            {"id": "wait", "kind": "wait", "label": "Wait"},
            {"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 500},
            {"id": "scroll_up", "kind": "scroll", "label": "Scroll up", "delta": -500},
        ],
    }
    page["fingerprint"] = fingerprint(page)
    return page


def choice(action="field"):
    operation, target = {
        "button": ("CLICK", "1"), "field": ("TYPE_TEXT", "2"), "field_click": ("CLICK", "2"),
        "option": ("SELECT", "3:1"), "wait": ("WAIT", None), "scroll_down": ("SCROLL_DOWN", None),
        "scroll_up": ("SCROLL_UP", None), "DONE": ("DONE", None), "BLOCKED": ("BLOCKED", None),
    }[action]
    return {
        "choice": action, "operation": operation, "target": target, "confidence": 1,
        "probabilities": {action: 1}, "target_probabilities": {target: 1} if target else {},
        "target_confidence": 1 if target else None, "operation_probabilities": {operation: 1},
        "latency_ms": 1, "usage": {},
    }


def make_agent(monkeypatch, policy, *, allow_commit=False, trace_path=None):
    browser = Mock(observe=Mock(side_effect=lambda **_: deepcopy(observed_page())), fresh=Mock(return_value=True))
    monkeypatch.setattr(loop, "Browser", Mock(return_value=browser))
    agent = loop.Agent("https://example.test/", "Find a book", allowed_operations=policy,
                       allow_commit=allow_commit, trace_path=trace_path)
    browser.reset_mock()
    agent.state["started_at"] = time.perf_counter()
    return agent


@pytest.mark.parametrize("policy", INVALID_POLICIES)
@pytest.mark.parametrize("entry", ["library", "mcp", "demo"])
def test_policy_rejects_before_setup(monkeypatch, policy, entry):
    browser, old = Mock(), Mock()
    monkeypatch.setattr(loop, "Browser", browser)
    monkeypatch.setattr(mcp_server, "AGENT", old)
    monkeypatch.setattr(demo, "AGENT", old)
    environment, protocol = Mock(), Mock()
    monkeypatch.setattr(mcp_server, "load_environment", environment)
    monkeypatch.setattr(mcp_server, "cdp", protocol)
    if entry == "mcp":
        assert "allowed_operations" in mcp_server.run_goal("Search", policy, url="https://example.test/")[0]
    else:
        with pytest.raises(ValueError, match="allowed_operations"):
            if entry == "library":
                loop.Agent("https://example.test/", "Search", allowed_operations=policy)
            else:
                demo.command("reset", {"goal": "Search", "allowed_operations": policy})
    browser.assert_not_called()
    old.close.assert_not_called()
    environment.assert_not_called()
    protocol.assert_not_called()


@pytest.mark.parametrize("policy", INVALID_POLICIES)
def test_invalid_continuation_preserves_entire_old_goal(monkeypatch, tmp_path, policy):
    agent = make_agent(monkeypatch, ["TYPE_TEXT"], trace_path=tmp_path / "old.json")
    agent.pending_text = ({"field": "Query"}, "cached", {"model": "test"})
    agent.state.update(decision=choice(), status="predicted", stale_streak=2, stale_decisions=7, wait_streak=1)
    before, state, pending = deepcopy(agent.snapshot()), agent.state, agent.pending_text
    path, original_policy = agent.trace_path, agent.allowed_operations
    with pytest.raises(ValueError, match="allowed_operations"):
        agent.new_goal("Another goal", allowed_operations=policy, trace_path=tmp_path / "new.json")
    assert agent.snapshot() == before and agent.state is state
    assert agent.pending_text is pending and agent.trace_path == path and agent.allowed_operations is original_policy
    agent.browser.observe.assert_not_called()
    agent.browser.close.assert_not_called()
    assert not path.exists()


@pytest.mark.parametrize("goal", ["", " \n\t ", None, 17])
@pytest.mark.parametrize("entry", ["library", "continuation", "mcp_replace", "mcp_continue", "demo"])
def test_invalid_goal_preserves_browser_before_setup(monkeypatch, goal, entry):
    agent = make_agent(monkeypatch, ["TYPE_TEXT"])
    agent.state.update(decision=choice(), status="predicted", wait_streak=1)
    before = deepcopy(agent.snapshot())
    monkeypatch.setattr(mcp_server, "AGENT", agent)
    monkeypatch.setattr(demo, "AGENT", agent)
    environment, protocol = Mock(), Mock()
    monkeypatch.setattr(mcp_server, "load_environment", environment)
    monkeypatch.setattr(mcp_server, "cdp", protocol)
    if entry.startswith("mcp"):
        url = "https://example.test/new" if entry == "mcp_replace" else None
        assert "nonempty task" in mcp_server.run_goal(goal, [], url=url)[0]
    else:
        with pytest.raises(ValueError, match="nonempty task"):
            if entry == "library":
                loop.Agent("https://example.test/", goal, allowed_operations=[])
            elif entry == "continuation":
                agent.new_goal(goal, allowed_operations=[])
            else:
                demo.command("reset", {"goal": goal, "allowed_operations": []})
    assert agent.snapshot() == before
    agent.browser.observe.assert_not_called()
    agent.browser.close.assert_not_called()
    environment.assert_not_called()
    protocol.assert_not_called()


def test_every_new_goal_requires_explicit_policy(monkeypatch):
    supplied = ["TYPE_TEXT"]
    agent = make_agent(monkeypatch, supplied)
    supplied.append("CLICK")
    assert agent.allowed_operations == frozenset({"TYPE_TEXT"})
    assert agent.state["allowed_operations"] == ["TYPE_TEXT"]
    with pytest.raises(TypeError, match="allowed_operations"):
        loop.Agent("https://example.test/", "Search")
    with pytest.raises(TypeError, match="allowed_operations"):
        agent.new_goal("Search again")
    with pytest.raises(TypeError, match="allowed_operations"):
        mcp_server.run_goal("Search")
    with pytest.raises(ValueError, match="allowed_operations"):
        demo.command("reset", {"goal": "Search"})
    agent.browser.observe.assert_not_called()
    agent.new_goal("  Wait for results  ", allowed_operations=["WAIT"])
    assert agent.allowed_operations == frozenset({"WAIT"}) and agent.state["allowed_operations"] == ["WAIT"]
    assert agent.state["goal"] == "Wait for results"


@pytest.mark.parametrize("policy", [[], ["WAIT"], ["TYPE_TEXT"], ["SELECT"]])
def test_policy_preserves_canonical_element_indices(monkeypatch, policy):
    agent = make_agent(monkeypatch, policy)
    before = deepcopy(agent.state["page"])
    elements, targets, _ = model.action_space(before["actions"], policy)
    assert [(element["node"], element["index"]) for element in elements] == [(10, "1"), (20, "2"), (30, "3")]
    assert [(element["node"], element["index"]) for element in agent.snapshot()["elements"]] == [
        (10, "1"), (20, "2"), (30, "3"),
    ]
    if "TYPE_TEXT" in policy:
        assert targets["TYPE_TEXT"]["2"]["id"] == "field"
    if "SELECT" in policy:
        assert targets["SELECT"]["3:1"]["id"] == "option"
    assert agent.state["page"] == before and fingerprint(before) == before["fingerprint"]


def test_empty_policy_retains_field_values_and_options(monkeypatch):
    agent = make_agent(monkeypatch, [])
    elements, targets, controls = model.action_space(agent.state["page"]["actions"], [])
    assert elements[1]["value"] == "old"
    assert elements[2]["value"] == "All"
    assert elements[2]["options"] == [{"index": "3:1", "label": "Category → Books", "value": "books"}]
    assert all(element["operations"] == [] for element in elements)
    assert targets == controls == {}


@pytest.mark.parametrize("policy, heads", [
    ([], set()), (["WAIT"], set()), (["TYPE_TEXT"], {"type_text_target"}),
    (["CLICK"], {"click_target", "commit_1", "commit_2"}), (["SELECT"], {"select_target", "commit_3_1"}),
])
def test_only_allowed_target_heads_are_requested(monkeypatch, policy, heads):
    calls = []

    def post(_url, _key, body, **_control):
        calls.append(body)
        operations = body["questions"]["operation"]["criteria"]
        return {"model": "test", "answers": {"operation": {
            "choice": "DONE", "confidence": 1, "probabilities": {name: int(name == "DONE") for name in operations},
        }}}

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    result = model.choose(observed_page(), "Read the fields", [], frozenset(policy))
    assert result["operation"] == "DONE" and len(calls) == 1
    body = calls[0]
    assert set(body["questions"]) == heads | {"operation"}
    assert set(body["questions"]["operation"]["criteria"]) == set(policy) | {"DONE", "BLOCKED"}
    assert [element["index"] for element in body["state"]["elements"]] == ["1", "2", "3"]
    assert body["state"]["elements"][1]["value"] == "old" and body["state"]["elements"][2]["options"]


@pytest.mark.parametrize("action", ["field", "button", "option", "wait", "scroll_down", "scroll_up"])
def test_forbidden_action_executes_nothing(monkeypatch, tmp_path, action):
    agent = make_agent(monkeypatch, [], trace_path=tmp_path / "run.json")
    helper = Mock()
    monkeypatch.setattr(loop, "field_text", helper)
    agent.state["decision"] = choice(action)
    with pytest.raises(RunStopped) as error:
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert error.value.code == "operation_not_allowed"
    helper.assert_not_called()
    agent.browser.act.assert_not_called()
    agent.browser.fresh.assert_not_called()
    assert agent.state["attempt"] is None and agent.state["history"] == []
    saved = json.loads(agent.trace_path.read_text())
    assert saved["allowed_operations"] == [] and saved["stop_code"] == "operation_not_allowed"
    assert saved["status"] == "stopped" and saved["decision"] is None and agent.pending_text is None
    assert saved["operation_refusal"]["actual_operation"] == choice(action)["operation"]
    assert saved["operation_refusal"]["choice"] == action


@pytest.mark.parametrize("forged", [
    {"choice": "button"}, {"operation": "CLICK"}, {"target": "1"}, {"choice": "unobserved"},
])
def test_mislabeled_action_cannot_bypass_policy(monkeypatch, forged):
    agent = make_agent(monkeypatch, ["TYPE_TEXT"])
    helper = Mock()
    monkeypatch.setattr(loop, "field_text", helper)
    agent.state["decision"] = {**choice(), **forged}
    with pytest.raises(RunStopped, match="operation|target|observed|authorized"):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    helper.assert_not_called()
    agent.browser.act.assert_not_called()
    assert agent.state["attempt"] is None


@pytest.mark.parametrize("malformed", [
    [], {}, "button", {"choice": []}, {"choice": {}}, {"operation": "TYPE_TEXT"},
    {**choice(), "target": []}, {**choice(), "target": {}},
    {**choice("DONE"), "operation": "TYPE_TEXT"}, {**choice("DONE"), "target": "2"},
    {"choice": "x" * 1000, "operation": "y" * 1000, "target": "z" * 1000},
])
def test_malformed_local_decision_stops_with_inert_diagnostics(monkeypatch, tmp_path, malformed):
    agent = make_agent(monkeypatch, ALL_OPERATIONS, trace_path=tmp_path / "run.json")
    helper = Mock()
    monkeypatch.setattr(loop, "field_text", helper)
    agent.state["decision"] = malformed
    with pytest.raises(RunStopped) as error:
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert error.value.code == "operation_not_allowed"
    saved = json.loads(agent.trace_path.read_text())
    assert saved["operation_refusal"]["reason"] and saved["decision"] is None
    assert all(value is None or isinstance(value, str) and len(value) <= 160
               for value in saved["operation_refusal"].values())
    assert saved["attempt"] is None and agent.pending_text is None
    for command in ("predict", "act", "tick"):
        with pytest.raises(ValueError, match="stopped"):
            agent.command(command)
    agent.browser.act.assert_not_called()
    helper.assert_not_called()


@pytest.mark.parametrize("kind", ["forbidden_operation", "malformed_operation", "malformed_target", "unknown_target"])
def test_provider_operation_refusal_is_terminal_without_another_request(monkeypatch, tmp_path, kind):
    agent = make_agent(monkeypatch, ["TYPE_TEXT"], trace_path=tmp_path / "run.json")
    agent.pending_text = ({"old": "context"}, "cached", {"model": "test"})
    helper, calls = Mock(), []
    monkeypatch.setattr(loop, "field_text", helper)
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")

    def post(_url, _key, body, **_control):
        calls.append(body)
        operations = body["questions"]["operation"]["criteria"]
        selected = "CLICK" if kind == "forbidden_operation" else [] if kind == "malformed_operation" else "TYPE_TEXT"
        target = [] if kind == "malformed_target" else "999" if kind == "unknown_target" else "2"
        return {"model": "test", "answers": {
            "operation": {"choice": selected, "confidence": 1,
                          "probabilities": {name: int(name == selected) for name in operations}},
            "type_text_target": {"choice": target, "confidence": 1, "probabilities": {"2": 1}},
        }}

    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(RunStopped) as error:
        agent.command("predict")
    assert error.value.code == "operation_not_allowed"
    assert len(calls) == 1 and agent.state["decision"] is None and agent.pending_text is None
    diagnostic = json.loads(agent.trace_path.read_text())["operation_refusal"]
    assert diagnostic["claimed_operation"] == (
        "CLICK" if kind == "forbidden_operation" else "<invalid list>" if kind == "malformed_operation" else "TYPE_TEXT"
    )
    for command in ("act", "predict", "tick"):
        with pytest.raises(ValueError, match="stopped"):
            agent.command(command)
    assert len(calls) == 1 and agent.state["attempt"] is None and agent.state["history"] == []
    helper.assert_not_called()
    agent.browser.act.assert_not_called()


def test_provider_transport_and_missing_key_are_not_operation_refusals(monkeypatch):
    agent = make_agent(monkeypatch, [])
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API_KEY"):
        agent.command("predict")
    assert agent.state["stop_code"] is None and agent.state["operation_refusal"] is None
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(side_effect=RuntimeError("Model connection failed")))
    with pytest.raises(RuntimeError, match="connection failed"):
        agent.command("predict")
    assert agent.state["stop_code"] is None and agent.state["operation_refusal"] is None


def test_allow_commit_does_not_broaden_operations(monkeypatch):
    agent = make_agent(monkeypatch, ["TYPE_TEXT"], allow_commit=True)
    agent.state["decision"] = {**choice("button"), "commit_probability": 1}
    with pytest.raises(RunStopped) as error:
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert error.value.code == "operation_not_allowed"
    agent.browser.act.assert_not_called()
    assert agent.allowed_operations == frozenset({"TYPE_TEXT"})
    for command in ("act", "predict", "tick"):
        with pytest.raises(ValueError, match="stopped"):
            agent.command(command)


def test_callers_supply_policy_and_share_target_mapping(monkeypatch):
    # Inspect every maintained runtime caller, without executing paid examples.
    for folder in ("jev_ultrafast", "examples", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Agent":
                    assert any(keyword.arg == "allowed_operations" for keyword in node.keywords), path
    agent = make_agent(monkeypatch, ["TYPE_TEXT"])
    helper = Mock(return_value=("books", {"model": "test", "latency_ms": 1}))
    monkeypatch.setattr(loop, "field_text", helper)
    agent.state["decision"] = choice()
    state = agent.snapshot()
    state.update(text_model="test", max_steps=60)
    # Run the real inspector script in an inert DOM. The first element has no rectangle: its omitted overlay
    # must not renumber the textbox, whose model target is still [2].
    program = """
const fs=require('node:fs'), vm=require('node:vm');
const nodes=new Map();
global.document={
  getElementById(id) {
    if(!nodes.has(id)) nodes.set(id,{value:id==='scenario'?'flights':'',checked:true,addEventListener(){}});
    return nodes.get(id);
  },
  querySelector(){return {content:'test'}}, querySelectorAll(){return []}
};
global.fetch=()=>new Promise(()=>{});
const source=fs.readFileSync(process.argv[1],'utf8');
vm.runInThisContext(source+'\\nstate='+process.argv[2]+'; render();');
console.log(JSON.stringify({targets:nodes.get('targets').innerHTML,choices:nodes.get('choices').innerHTML}));
"""
    output = subprocess.run(
        ["node", "-e", program, str(ROOT / "jev_ultrafast/static/app.js"), json.dumps(state)],
        capture_output=True, text=True, check=True, timeout=10,
    )
    rendered = json.loads(output.stdout)
    assert 'class="target selected" data-action="2"' in rendered["targets"]
    assert 'data-action="1"' not in rendered["targets"]
    assert 'class="choice best" data-action="2"' in rendered["choices"]
    agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert agent.browser.act.call_args.args[0]["node"] == 20
    assert agent.state["history"][-1]["target"] == "2"
    helper.assert_called_once()


def timed_agent(monkeypatch, *, action=None, trace_path=None):
    clock = [0.0]
    monkeypatch.setattr(loop.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(loop.time, "perf_counter", lambda: clock[0])
    agent = make_agent(monkeypatch, ALL_OPERATIONS, trace_path=trace_path)
    if action:
        agent.state.update(status="predicted", decision=choice(action))
    return agent, clock


@pytest.mark.parametrize("status", ["done", "blocked", "stopped"])
@pytest.mark.parametrize("command", ["tick", "predict", "act"])
def test_terminal_state_precedes_all_work(monkeypatch, status, command):
    agent, _ = timed_agent(monkeypatch, action="button")
    agent.state["status"] = status
    provider, external = Mock(), Mock()
    monkeypatch.setattr(loop, "choose", provider)
    agent.before_input = external
    with pytest.raises(RunStopped, match="stopped"):
        agent.command(command)
    assert agent.deadline is None
    assert agent.browser.mock_calls == []
    provider.assert_not_called()
    external.assert_not_called()


def test_stale_outcomes_119_and_120(monkeypatch):
    agent, _ = timed_agent(monkeypatch)
    agent.browser.fresh.side_effect = StalePage("Navigating")
    for _ in range(119):
        agent.command("tick")
    assert agent.state["stale_recoveries"] == 119
    assert agent.browser.observe.call_count == 119
    with pytest.raises(RunStopped) as stopped:
        agent.command("tick")
    assert stopped.value.code == "stale_recovery_limit"
    assert agent.state["stale_recoveries"] == 120
    assert agent.state["stale_reason"] == "Navigating"
    assert agent.browser.observe.call_count == 119


def test_nested_commands_count_one_recovery(monkeypatch):
    agent, _ = timed_agent(monkeypatch)
    agent.browser.fresh.side_effect = StalePage("First stale")
    agent.browser.observe.side_effect = StalePage("Recovery also stale")
    agent.command("tick")
    assert agent.state["stale_recoveries"] == 1 and agent.browser.observe.call_count == 1
    with pytest.raises(StalePage):
        agent.command("predict")
    assert agent.state["stale_recoveries"] == 1


def test_changing_pages_do_not_replenish_budget(monkeypatch):
    agent, _ = timed_agent(monkeypatch)
    agent.browser.fresh.side_effect = StalePage("Changed")
    pages = iter({**observed_page(), "fingerprint": str(i)} for i in range(120))
    agent.browser.observe.side_effect = lambda **_: next(pages)
    generator = agent.run()
    for _ in range(119):
        next(generator)
    with pytest.raises(RunStopped) as stopped:
        next(generator)
    assert stopped.value.code == "stale_recovery_limit"
    assert agent.state["stale_streak"] == 0 and agent.browser.observe.call_count == 119


@pytest.mark.parametrize("command", ["tick", "predict", "act"])
def test_direct_commands_share_deadline(monkeypatch, command):
    agent, clock = timed_agent(monkeypatch)
    provider = Mock(return_value=choice("button"))
    monkeypatch.setattr(loop, "choose", provider)
    agent.command("predict")
    assert agent.deadline == 90
    clock[0] = 90
    reads = agent.browser.mock_calls[:]
    with pytest.raises(RunStopped) as stopped:
        agent.command(command, {"fingerprint": agent.state["page"]["fingerprint"]})
    assert stopped.value.code == "execution_deadline"
    assert agent.browser.mock_calls == reads and provider.call_count == 1
    assert agent.state["elapsed_ms"] == 90000
    assert agent.state["decision"] is None and agent.pending_text is None
    agent.new_goal("Start again", allowed_operations=[])
    assert agent.deadline is None and agent.state["stale_recoveries"] == 0
    clock[0] = 110
    monkeypatch.setattr(loop, "choose", Mock(return_value=choice("DONE")))
    agent.command("predict")
    assert agent.deadline == 200


def test_stopped_ui_and_mcp_use_the_same_state(monkeypatch, tmp_path):
    agent, _ = timed_agent(monkeypatch, trace_path=tmp_path / "run.json")
    with pytest.raises(RunStopped):
        agent.stop("execution_deadline", "90 s budget reached")
    agent.state["notes_shown"] = []
    monkeypatch.setattr(mcp_server, "notes_block", lambda _state: ("", []))
    mcp_server.finish(agent, "test", ["90 s budget reached"])
    assert agent.state["result"]["status"] == agent.state["status"] == "stopped"
    state = agent.snapshot()
    state.update(text_model="test", max_steps=60)
    program = """
const fs=require('node:fs'),vm=require('node:vm'),nodes=new Map();
global.document={getElementById(id){if(!nodes.has(id))nodes.set(id,{value:'flights',addEventListener(){}});
return nodes.get(id)},querySelector(){return {content:'test'}},querySelectorAll(){return []}};
global.fetch=()=>new Promise(()=>{});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8')+'\\nstate='+process.argv[2]+';render();');
console.log(JSON.stringify({status:nodes.get('status').textContent,disabled:['choose','execute','auto']
.map(id=>nodes.get(id).disabled)}));
"""
    result = subprocess.run(["node", "-e", program, str(ROOT / "jev_ultrafast/static/app.js"), json.dumps(state)],
                            check=True, capture_output=True, text=True, timeout=10)
    rendered = json.loads(result.stdout)
    assert rendered["disabled"] == [True, True, True] and rendered["status"].startswith("Stopped")


def test_expiry_during_helper_prevents_input(monkeypatch):
    agent, clock = timed_agent(monkeypatch, action="field")

    def helper(*_args, **_control):
        clock[0] = 90
        return "book", {"model": "fake", "latency_ms": 90000, "usage": {"prompt_tokens": 4}}

    monkeypatch.setattr(loop, "field_text", helper)
    with pytest.raises(RunStopped) as stopped:
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert stopped.value.code == "execution_deadline"
    agent.browser.act.assert_not_called()
    assert agent.pending_text is None and agent.state["attempt"] is None
    assert agent.state["text_calls"][0]["usage"] == {"prompt_tokens": 4}
    assert agent.state["text_calls"][0]["discarded"] == "execution_deadline"


def test_expiry_between_http_attempts_prevents_retry(monkeypatch):
    agent, clock = timed_agent(monkeypatch)
    agent.deadline = 90
    clock[0] = 89.8
    transport = Mock(return_value=Mock(status_code=503, is_error=True))
    monkeypatch.setattr(model.CLIENT, "post", transport)
    monkeypatch.setattr(model.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    with pytest.raises(RunStopped):
        model.post_json("https://provider.invalid", "fake", {}, check_stop=agent.check_stop,
                        remaining_budget=agent.remaining_budget)
    assert transport.call_count == 1 and clock[0] == 90
    assert 0 < transport.call_args.kwargs["timeout"] <= 0.2 + 1e-12


def test_late_done_cannot_override_stop(monkeypatch):
    agent, clock = timed_agent(monkeypatch)

    def choose_late(*_args, **_control):
        clock[0] = 90
        return choice("DONE")

    monkeypatch.setattr(loop, "choose", choose_late)
    with pytest.raises(RunStopped):
        agent.command("tick")
    assert agent.state["status"] == "stopped" and agent.state["decision"] is None
    agent.browser.act.assert_not_called()


def test_wall_clock_jump_does_not_change_deadline(monkeypatch):
    agent, clock = timed_agent(monkeypatch)
    monkeypatch.setattr(loop, "choose", Mock(return_value=choice("button")))
    agent.command("predict")
    monkeypatch.setattr(loop.time, "time", lambda: 1e12)
    clock[0] = 20
    agent.command("predict")
    monkeypatch.setattr(loop.time, "time", lambda: -1e12)
    assert agent.deadline == 90 and agent.remaining_budget() == 70


def test_first_command_starts_budget_before_external_stop_callback(monkeypatch):
    agent, clock = timed_agent(monkeypatch)
    first = []

    def external():
        if not first:
            first.append(True)
            clock[0] = 90

    agent.before_input = external
    provider = Mock(return_value=choice("DONE"))
    monkeypatch.setattr(loop, "choose", provider)
    with pytest.raises(RunStopped):
        agent.command("predict")
    assert agent.deadline == 90 and agent.browser.mock_calls == []
    provider.assert_not_called()


@pytest.mark.parametrize("failure", ["timeout", "stale", "late", "success"])
def test_final_read_cannot_resume_or_hide_stop(monkeypatch, tmp_path, failure):
    agent, clock = timed_agent(monkeypatch, trace_path=tmp_path / "run.json")
    real_browser = browser.Browser.__new__(browser.Browser)
    real_browser.session = "test"
    real_browser.after_input = {"kind": "fill", "node": 20}
    agent.browser = agent.state["browser"] = real_browser
    agent.deadline = 90
    agent.state.update(started_at=0, notes_shown=[], attempt={
        "phase": "mouse_released", "input_started": True, "step": 1, "action": "Query", "kind": "fill", "text": "books",
    })
    clock[0] = 90
    with pytest.raises(RunStopped):
        agent.check_stop()
    calls = []

    def protocol(method, **params):
        calls.append((method, params))
        if method == "Page.captureScreenshot":
            return {"data": "eA=="}
        assert params["expression"] == browser.READ_STATE  # No leftover input settling.
        clock[0] += 5 if failure == "late" else 2
        if failure == "timeout":
            raise TimeoutError("opaque")
        return {"result": {"value": None if failure == "stale" else observed_page()}}

    monkeypatch.setattr(browser, "cdp", protocol)
    monkeypatch.setattr(mcp_server, "notes_block", lambda _state: ("", []))
    monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
    mcp_server.finish(agent, "test", ["90 s budget reached"])
    assert len(calls) == (2 if failure == "success" else 1)
    assert calls[0][1]["_response_timeout"] == 5
    if failure == "success":
        assert calls[1][1]["_response_timeout"] == 3
    assert agent.state["elapsed_ms"] == 90000
    assert agent.state["final_read_ms"] == (5000 if failure == "late" else 2000)
    assert agent.state["final_read_fresh"] is (failure == "success")
    assert agent.state["status"] == "stopped" and agent.state["stop_code"] == "execution_deadline"
    assert agent.state["attempt"]["phase"] == "mouse_released"


def physical_agent(monkeypatch, *, action="button", trace_path=None):
    agent, clock = timed_agent(monkeypatch, action=action, trace_path=trace_path)
    page = agent.state["page"]
    page.update(marker="marker", page_key=[], guards={"10": [], "20": []})
    real_browser = browser.Browser.__new__(browser.Browser)
    real_browser.session = "test"
    agent.browser = agent.state["browser"] = real_browser
    calls = []

    def response(method, params):
        calls.append((method, params))
        if method != "Runtime.evaluate":
            return {}
        expression = params["expression"]
        if expression == browser.MARKER:
            value = "marker"
        elif expression == browser.READ_STATE:
            value = deepcopy(page)
        elif expression.startswith(browser.SELECT_ACTION):
            value = {"status": "executed", "action_id": "option"}
        elif "return c ?" in expression:
            value = [[], []]
        else:
            value = {"x": 50, "y": 60}
        return {"result": {"value": value}}

    monkeypatch.setattr(browser, "cdp", lambda method, **params: response(method, params))
    monkeypatch.setattr(loop, "field_text", Mock(return_value=("books", {"model": "fake", "latency_ms": 1})))
    return agent, clock, calls, response


@pytest.mark.parametrize("action", ["button", "option", "scroll_down"])
def test_post_input_failure_preserves_one_execution(monkeypatch, tmp_path, action):
    agent, clock, calls, response = physical_agent(monkeypatch, action=action, trace_path=tmp_path / "run.json")

    def protocol(method, **params):
        result = response(method, params)
        if method.startswith("Input.") or params.get("expression", "").startswith(browser.SELECT_ACTION):
            clock[0] = 90
        return result

    monkeypatch.setattr(browser, "cdp", protocol)
    with pytest.raises(RunStopped):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert len(agent.state["history"]) == 1 and agent.state["attempt"] is None
    assert agent.state["history"][0]["page_changed"] is None
    before = calls[:]
    with pytest.raises(RunStopped):
        agent.command("tick")
    assert calls == before
    assert len(json.loads(agent.trace_path.read_text())["history"]) == 1


@pytest.mark.parametrize("stage", ["freshness", "hit_test"])
@pytest.mark.parametrize("stop", ["deadline", "cancellation"])
def test_expiry_during_browser_preflight_prevents_input(monkeypatch, tmp_path, stage, stop):
    agent, clock, calls, response = physical_agent(monkeypatch, trace_path=tmp_path / "run.json")
    cancelled = [False]

    def external():
        if cancelled[0]:
            raise asyncio.CancelledError("cancelled during preflight")

    agent.before_input = external

    def protocol(method, **params):
        result = response(method, params)
        expression = params.get("expression", "")
        if (stage == "freshness" and "return c ?" in expression or
                stage == "hit_test" and "document.elementFromPoint" in expression):
            clock[0] = 90 if stop == "deadline" else 1
            cancelled[0] = stop == "cancellation"
        return result

    monkeypatch.setattr(browser, "cdp", protocol)
    with pytest.raises(RunStopped if stop == "deadline" else asyncio.CancelledError):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert not any(method.startswith("Input.") for method, _ in calls)
    assert agent.state["attempt"] is None and agent.state["history"] == []
    assert json.loads(agent.trace_path.read_text())["status"] == "stopped"


@pytest.mark.parametrize("press", ["mousePressed", "keyDown"])
@pytest.mark.parametrize("stop", ["deadline", "cancellation", "ambiguous"])
def test_partial_fill_releases_pair_once_then_stops(monkeypatch, tmp_path, press, stop):
    agent, clock, calls, response = physical_agent(monkeypatch, action="field", trace_path=tmp_path / "run.json")
    cancelled = [False]

    def external():
        if cancelled[0]:
            raise asyncio.CancelledError("cancelled after confirmed press")

    agent.before_input = external

    def protocol(method, **params):
        result = response(method, params)
        if params.get("type") == press:
            if stop == "ambiguous":
                raise TimeoutError("reply lost after press")
            clock[0] = 90 if stop == "deadline" else 1
            cancelled[0] = stop == "cancellation"
        return result

    monkeypatch.setattr(browser, "cdp", protocol)
    with pytest.raises(asyncio.CancelledError if stop == "cancellation" else RunStopped):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    inputs = [(method, params) for method, params in calls if method.startswith("Input.")]
    release = "mouseReleased" if press == "mousePressed" else "keyUp"
    assert sum(params.get("type") == release for _, params in inputs) == (0 if stop == "ambiguous" else 1)
    assert all(method != "Input.insertText" for method, _ in inputs)
    if stop != "ambiguous":
        assert "_response_timeout" not in next(params for _, params in inputs if params.get("type") == release)
    assert agent.state["history"] == [] and agent.state["attempt"]["input_started"] is True
    assert agent.state["status"] == "stopped" and agent.pending_text is None
    saved = json.loads(agent.trace_path.read_text())
    assert saved["attempt"]["phase"] == agent.state["attempt"]["phase"]
    assert saved["attempt"].get("outcome") == ("uncertain" if stop == "ambiguous" else None)
    count = len(calls)
    for command in ("tick", "predict", "act"):
        with pytest.raises(RunStopped):
            agent.command(command)
    assert len(calls) == count


@pytest.mark.parametrize("kind", ["decision", "helper"])
@pytest.mark.parametrize("malformed", [False, True])
@pytest.mark.parametrize("missing_usage", [False, True])
def test_late_successful_model_response_is_counted_but_not_executed(monkeypatch, kind, malformed, missing_usage):
    agent, clock = timed_agent(monkeypatch, action="field" if kind == "helper" else None)
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "fake")
    usage = {"input_tokens": 123} if kind == "decision" else {"prompt_tokens": 45, "completion_tokens": 6}
    if missing_usage:
        usage = {}

    def post(_url, **params):
        clock[0] = 90
        body = params["json"]
        if kind == "decision":
            operations = body["questions"]["operation"]["criteria"]
            payload = {"model": "fake", "usage": usage, "answers": {"operation": {
                "choice": "DONE", "confidence": 1, "probabilities": {name: int(name == "DONE") for name in operations},
            }}}
        else:
            payload = {"usage": usage, "choices": [{"message": {"content": '{"text":"books"}'}}]}
        if malformed:
            payload = {"model": "fake", "usage": usage}  # Accounting precedes interpretation.
        return Mock(status_code=200, is_error=False, json=Mock(return_value=payload))

    transport = Mock(side_effect=post)
    monkeypatch.setattr(model.CLIENT, "post", transport)
    with pytest.raises(RunStopped):
        agent.command("act" if kind == "helper" else "tick", {"fingerprint": agent.state["page"]["fingerprint"]})
    rows = agent.state["decisions" if kind == "decision" else "text_calls"]
    assert len(rows) == transport.call_count == 1
    assert rows[0]["usage"] == usage and rows[0]["latency_ms"] == 90000
    assert rows[0]["discarded"] == "execution_deadline"
    assert agent.state["decision"] is None and agent.pending_text is None
    assert agent.state["history"] == [] and agent.state["attempt"] is None
    agent.browser.act.assert_not_called()


@pytest.mark.parametrize("phase", ["mouse_pressed", "mouse_released", "select_all_pressed", "select_all_released"])
def test_partial_fill_save_failure_is_terminal_and_keeps_release(monkeypatch, tmp_path, phase):
    agent, _, calls, _ = physical_agent(monkeypatch, action="field", trace_path=tmp_path / "run.json")
    original_save, failed = agent.save, []

    def fail_one_phase_save():
        if not failed and (agent.state["attempt"] or {}).get("phase") == phase:
            failed.append(True)
            raise RuntimeError("phase save failed")
        return original_save()

    monkeypatch.setattr(agent, "save", fail_one_phase_save)
    with pytest.raises(RuntimeError, match="phase save failed"):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert failed and agent.state["status"] == "stopped" and agent.pending_text is None
    assert agent.state["history"] == [] and agent.state["attempt"]["input_started"]
    events = [params.get("type") for method, params in calls if method.startswith("Input.")]
    assert events.count("mousePressed") == events.count("mouseReleased") == 1
    if phase.startswith("select_all"):
        assert events.count("keyDown") == events.count("keyUp") == 1
    assert not any(method == "Input.insertText" for method, _ in calls)
    count = len(calls)
    for command in ("tick", "predict", "act"):
        with pytest.raises(RunStopped):
            agent.command(command)
    assert len(calls) == count
    assert json.loads(agent.trace_path.read_text())["status"] == "stopped"


def test_completed_click_save_failure_keeps_history_and_stops(monkeypatch, tmp_path):
    agent, _, calls, _ = physical_agent(monkeypatch, trace_path=tmp_path / "run.json")
    original_save, failed = agent.save, []

    def fail_completed_save():
        if agent.state["history"] and not failed:
            failed.append(True)
            raise RuntimeError("completed save failed")
        return original_save()

    monkeypatch.setattr(agent, "save", fail_completed_save)
    with pytest.raises(RuntimeError, match="completed save failed"):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert len(agent.state["history"]) == 1 and agent.state["attempt"] is None
    assert agent.state["status"] == "stopped" and agent.state["stop_code"] == "execution_error"
    events = [params.get("type") for method, params in calls if method.startswith("Input.")]
    assert events == ["mousePressed", "mouseReleased"]
    with pytest.raises(RunStopped):
        agent.command("predict")
    assert len(json.loads(agent.trace_path.read_text())["history"]) == 1


@pytest.mark.parametrize("action,press", [("field", "mousePressed"), ("field", "keyDown"), ("option", "select")])
@pytest.mark.parametrize("failed_save", [False, True])
def test_transport_cancellation_preserves_uncertain_attempt_and_original_error(
    monkeypatch, tmp_path, action, press, failed_save,
):
    agent, _, calls, response = physical_agent(monkeypatch, action=action, trace_path=tmp_path / "run.json")
    original = asyncio.CancelledError("raw cancelled transport")
    cancelled, original_save = [], agent.save

    def save():
        if cancelled and failed_save:
            raise RuntimeError("disk failed during cancellation")
        original_save()

    monkeypatch.setattr(agent, "save", save)

    def protocol(method, **params):
        result = response(method, params)
        if (params.get("type") == press or
                press == "select" and params.get("expression", "").startswith(browser.SELECT_ACTION)):
            cancelled.append(True)
            raise original
        return result

    monkeypatch.setattr(browser, "cdp", protocol)
    with pytest.raises(asyncio.CancelledError) as caught:
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    assert caught.value is original
    assert agent.state["status"] == "stopped" and agent.state["stop_code"] == "cancelled"
    saved = agent.snapshot() if failed_save else json.loads(agent.trace_path.read_text())
    assert saved["attempt"]["outcome"] == "uncertain" and saved["attempt"]["phase"].endswith("_uncertain")
    assert saved["history"] == [] and agent.pending_text is None
    events = [params.get("type") for method, params in calls if method.startswith("Input.")]
    if press == "mousePressed":
        assert events == ["mousePressed"]
    if press == "keyDown":
        assert events == ["mousePressed", "mouseReleased", "keyDown"]
    count = len(calls)
    with pytest.raises(RunStopped):
        agent.command("tick")
    assert len(calls) == count


def test_failed_phase_save_and_release_timeout_retain_uncertainty(monkeypatch, tmp_path):
    agent, _, calls, response = physical_agent(monkeypatch, action="field", trace_path=tmp_path / "run.json")
    original_save, failed = agent.save, []

    def save():
        if (agent.state["attempt"] or {}).get("phase") == "mouse_pressed" and not failed:
            failed.append(True)
            raise RuntimeError("first save failure")
        original_save()

    def protocol(method, **params):
        result = response(method, params)
        if params.get("type") == "mouseReleased":
            raise TimeoutError("release was not confirmed")
        return result

    monkeypatch.setattr(agent, "save", save)
    monkeypatch.setattr(browser, "cdp", protocol)
    with pytest.raises(RuntimeError, match="first save failure"):
        agent.command("act", {"fingerprint": agent.state["page"]["fingerprint"]})
    saved = json.loads(agent.trace_path.read_text())
    assert saved["attempt"]["phase"] == "mouse_release_uncertain" and saved["attempt"]["outcome"] == "uncertain"
    assert saved["status"] == "stopped" and saved["history"] == []
    assert sum(params.get("type") == "mouseReleased" for _, params in calls) == 1


def test_unknown_and_partial_usage_are_not_rendered_as_measured_zero(monkeypatch):
    agent, _ = timed_agent(monkeypatch)
    decision = {**choice("DONE"), "model": "fake", "omitted_actions": 0}
    agent.state.update(source="test", outcome=[], failure=None, result={"status": "stopped", "notes": [], "text": ""},
                       decisions=[{**decision, "usage": {"input_tokens": 0}},
                                  {**decision, "usage": {"input_tokens": 7}}, {**decision, "usage": {}}],
                       text_calls=[{"usage": {"prompt_tokens": 0, "completion_tokens": 3}}, {"usage": {}}])
    rendered = mcp_server.render("test", "stopped", [], agent.state)
    assert "7 known input tokens; 1 call unknown" in rendered
    report = report_runs.summary("test", [report_runs.facts(agent.snapshot())])
    assert "TypeSafe input tokens 7 known; 1 call unknown" in report
    assert "text prompt tokens 0 known; 1 call unknown" in report
    assert "text completion tokens 3 known; 1 call unknown" in report
    agent.state["decisions"] = [{**decision, "usage": {}}]
    assert "input tokens unknown" in mcp_server.render("test", "stopped", [], agent.state)
    agent.state["decisions"] = [{**decision, "usage": {"input_tokens": 0}}]
    rendered = mcp_server.render("test", "stopped", [], agent.state)
    assert "0 input tokens" in rendered.splitlines()[0] and "unknown" not in rendered.splitlines()[0]


def test_late_decision_preserves_visited_private_url(monkeypatch):
    from jev_ultrafast import site_notes

    agent, clock = timed_agent(monkeypatch)
    agent.state['call'] = {'url': 'https://public.example/start'}
    agent.state['page']['url'] = 'https://private.example/secret'

    def late(*args, on_response, **kwargs):
        clock[0] = 90
        on_response({'model': 'fake', 'latency_ms': 90000, 'usage': {}})
        agent.check_stop()

    monkeypatch.setattr(loop, 'choose', late)
    with pytest.raises(RunStopped):
        agent.command('predict')
    agent.state['page']['url'] = 'https://public.example/finish'
    assert agent.state['decisions'][0]['observed_url'] == 'https://private.example/secret'
    assert 'request' not in agent.state['decisions'][0]
    assert site_notes.excluded('20261003-100000-abcd', agent.state, {'private.example'})
    assert agent.state['decision'] is None and agent.pending_text is None
    agent.browser.act.assert_not_called()
