"""Schema-2 boundaries execute production JavaScript and actual Python adapters without paid I/O."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from readiness_fakes import attach_quiet_loading_source
from test_execution_contracts import ALL_OPERATIONS, choice, make_agent, observed_page, physical_agent

from jev_ultrafast import agent as loop
from jev_ultrafast import browser, demo, mcp_server
from jev_ultrafast.contracts import RunStopped

ROOT = Path(__file__).resolve().parents[1]
OVERFLOW = {"snapshot_schema": 2, "status": "snapshot_too_large", "attempted_bytes": 300000,
            "diagnostics": {"guard_builds": 250}}


def javascript(body, **config):
    program = """
const fs=require('node:fs'),dom=require(process.argv[1])(JSON.parse(process.argv[2]));
const source=fs.readFileSync(process.argv[3],'utf8'),page=eval(source);
const check=(action=null)=>window.__jevFast?.check({snapshot_schema:2,observation_token:page.observation_token,action});
const result=eval(process.argv[4]); console.log(JSON.stringify(result));
"""
    result = subprocess.run(["node", "-e", program, str(ROOT / "tests/fixtures/snapshot_dom.cjs"), json.dumps(config),
                             str(ROOT / "jev_ultrafast/snapshot.js"), body], capture_output=True, text=True,
                            check=True, timeout=20)
    return json.loads(result.stdout)


def test_freshness_does_not_replace_baseline():
    result = javascript("""(()=>{const baseline=window.__jevFast.baseline;dom.field.value='changed';
      return {checks:[check(),check()],same:baseline===window.__jevFast.baseline,
        token:window.__jevFast.baseline.page.observation_token,original:page.observation_token}})()""")
    assert result["checks"] == [False, False]
    assert result["same"] and result["token"] == result["original"]


def test_progress_excludes_nested_protocol_identity():
    result = javascript("({page,after:eval(source)})")
    assert result["page"]["observation_token"] != result["after"]["observation_token"]
    assert browser.fingerprint(result["page"]) == browser.fingerprint(result["after"])
    before, after = deepcopy(result["page"]), deepcopy(result["page"])
    after["actions"][0]["option"].update(document_id=999, cache_epoch="another")
    after["actions"][0]["guard_ref"] = {"generation": 99, "epoch": "new", "node": 1}
    after["evidence"] = [{"selected_options": [{"label": "Books", "guard_ref": {"generation": 4}}]}]
    before["evidence"] = [{"selected_options": [{"label": "Books", "guard_ref": {"generation": 1}}]}]
    assert browser.fingerprint(before) == browser.fingerprint(after)
    after["evidence"][0]["selected_options"][0]["label"] = "Changed"
    assert browser.fingerprint(before) != browser.fingerprint(after)


@pytest.mark.parametrize(("mutation", "fresh", "progress"), [
    ("dom.controls[499].label='changed'", False, False),
    ("dom.field.value='changed'", False, False),
    ("document.title='changed'", False, False),
    ("document.documentElement.scrollHeight+=500", True, True),
    ("dom.controls[0].getBoundingClientRect=()=>({x:1,y:1,width:8,height:8})", True, True),
])
def test_progress_and_freshness_keep_distinct_projections(mutation, fresh, progress):
    result = javascript(f"(()=>{{{mutation};const fresh=check();return {{page,fresh,after:eval(source)}}}})()",
                        count=500)
    assert result["fresh"] is fresh
    assert (browser.fingerprint(result["page"]) != browser.fingerprint(result["after"])) is progress


@pytest.mark.parametrize("change", ["observe", "reset", "navigation"])
def test_old_tokens_reject_after_observe_reset_or_navigation(change):
    mutation = {"observe": "eval(source)", "reset": "delete window.__jevFast;eval(source)",
                "navigation": "performance.timeOrigin++;global.document={...document};eval(source)"}[change]
    result = javascript(f"(()=>{{{mutation};return [check(),check(page.actions[0])]}})()")
    assert result == [False, False]


@pytest.mark.parametrize("count", [250, 1000, 5000])
@pytest.mark.parametrize("long_label", [False, True])
def test_guard_work_and_transport_are_bounded(count, long_label):
    result = javascript("({page,metrics:window.__jevFast.last_scan,scopes:dom.scopeReads(),"
                        "bytes:new TextEncoder().encode(JSON.stringify(page)).byteLength})", count=count,
                        long_label=long_label)
    assert result["metrics"]["guard_builds"] == 250
    assert result["metrics"]["scope_reads"] == result["scopes"] == 1
    if long_label:
        assert result["page"]["status"] == "snapshot_too_large"
        assert "actions" not in result["page"] and "observation_token" not in result["page"]
    else:
        assert result["page"]["omitted_actions"] == count - 250
        assert result["bytes"] <= browser.MAX_SNAPSHOT_BYTES
        assert len(result["page"]["actions"]) == 251


@pytest.mark.parametrize("count", [0, 250, 1000, 5000])
def test_strong_references_cover_only_offered_targets(count):
    result = javascript("""({actual:[...window.__jevFast.nodes.keys()].sort((a,b)=>a-b),
      expected:[...new Set(page.actions.flatMap(a=>a.node ? [a.node,...(a.option?[a.option.option_id]:[])]:[]))]
        .sort((a,b)=>a-b)})""", count=count)
    assert result["actual"] == result["expected"]
    assert len(result["actual"]) <= 500


def overflow_browser(monkeypatch):
    instance = browser.Browser.__new__(browser.Browser)
    attach_quiet_loading_source(instance)
    instance.session = "fixture"
    protocol = Mock(return_value={"result": {"value": deepcopy(OVERFLOW)}})
    monkeypatch.setattr(browser, "cdp", protocol)
    return instance, protocol


@pytest.mark.parametrize("adapter", ["observe", "fresh", "constructor", "predict", "click", "select", "post_input",
                                    "new_goal", "mcp_continuation", "mcp_final_done", "mcp_final_stopped", "inspector"])
def test_overflow_is_terminal_at_each_adapter(monkeypatch, tmp_path, adapter):
    instance, protocol = overflow_browser(monkeypatch)
    page = observed_page()
    page.update(snapshot_schema=2, observation_token={"epoch": "fixture", "generation": 1})
    if adapter in {"observe", "fresh"}:
        with pytest.raises(browser.SnapshotTooLarge):
            instance.observe(screenshot=False) if adapter == "observe" else instance.fresh(page)
        assert protocol.call_count == 1
        return
    if adapter == "constructor":
        instance.close = Mock()
        monkeypatch.setattr(loop, "Browser", Mock(return_value=instance))
        with pytest.raises(browser.SnapshotTooLarge):
            loop.Agent(page["url"], "Search", allowed_operations=[])
        instance.close.assert_called_once()
        assert protocol.call_count == 1
        return
    if adapter in {"click", "select", "post_input"}:
        action = "option" if adapter == "select" else "button"
        agent, _, calls, response = physical_agent(monkeypatch, action=action, trace_path=tmp_path / "run.json")

        def emit(method, **params):
            expression = params.get("expression", "")
            overflow = (adapter == "select" and expression.startswith(browser.SELECT_ACTION) or
                        adapter == "click" and expression.startswith(browser.FRESH_STATE) or
                        adapter == "post_input" and expression == browser.READ_STATE)
            return {"result": {"value": deepcopy(OVERFLOW)}} if overflow else response(method, params)

        monkeypatch.setattr(browser, "cdp", emit)
    else:
        agent = make_agent(monkeypatch, ALL_OPERATIONS, trace_path=tmp_path / "run.json")
        agent.browser = agent.state["browser"] = instance
    agent.pending_text = ("old", "text", {})
    agent.state["page"] = page
    agent.state["decision"] = choice("option" if adapter == "select" else "button")
    agent.state["status"] = "predicted"
    provider, helper = Mock(), Mock()
    monkeypatch.setattr(loop, "choose", provider)
    monkeypatch.setattr(loop, "field_text", helper)
    if adapter.startswith("mcp_final"):
        agent.state.update(status="done", notes_shown=[])
        if adapter == "mcp_final_stopped":
            agent.mark_stopped("execution_deadline")
        monkeypatch.setattr(mcp_server, "notes_block", lambda _state: ("", []))
        monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
        mcp_server.finish(agent, "snapshot", [])
    elif adapter == "mcp_continuation":
        monkeypatch.setattr(mcp_server, "AGENT", agent)
        target_probe = Mock(side_effect=AssertionError("No recovery target probe after overflow"))
        monkeypatch.setattr(mcp_server, "cdp", target_probe)
        result = mcp_server.start_run("New goal", None, [], None, False)
        assert "snapshot_too_large" in result[0]
        target_probe.assert_not_called()
    else:
        with pytest.raises((RunStopped, browser.SnapshotTooLarge)):
            if adapter == "new_goal":
                agent.new_goal("New goal", allowed_operations=[])
            elif adapter == "inspector":
                monkeypatch.setattr(demo, "AGENT", agent)
                demo.command("predict", {})
            else:
                agent.command("predict" if adapter == "predict" else "act", {"fingerprint": page["fingerprint"]})
    assert agent.state["status"] == "stopped"
    expected_stop = "execution_deadline" if adapter == "mcp_final_stopped" else "snapshot_too_large"
    assert agent.state["stop_code"] == expected_stop
    assert agent.state["page_fresh"] is False
    assert agent.state["decision"] is agent.pending_text is None
    assert len(agent.state["history"]) == (1 if adapter == "post_input" else 0)
    assert agent.state["stale_recoveries"] == 0
    provider.assert_not_called()
    helper.assert_not_called()
    before = protocol.call_count
    for command in ["predict", "act", "tick"]:
        with pytest.raises(RunStopped):
            agent.command(command)
    assert protocol.call_count == before
    if adapter == "inspector":
        assert demo.response_state()["status"] == "stopped"


def test_legacy_snapshots_report_but_cannot_execute(monkeypatch):
    from scripts import report_runs

    instance = browser.Browser.__new__(browser.Browser)
    attach_quiet_loading_source(instance)
    instance.evaluate = Mock(side_effect=AssertionError("Legacy page must reject without browser read"))
    page = observed_page()
    page.pop("snapshot_schema")
    page.pop("observation_token")
    assert browser.fingerprint(page)
    assert instance.fresh(page) is False
    with pytest.raises(browser.StalePage):
        instance.act(page["actions"][0], page)
    summary = report_runs.facts({"source": "library", **make_agent(monkeypatch, []).snapshot()})
    assert summary


@pytest.mark.parametrize("control", ["wait", "scroll_down", "scroll_up"])
def test_observed_control_freshness_allows_dispatch(monkeypatch, control):
    result = javascript("""(()=>{document.documentElement.scrollHeight=2000;global.scrollY=200;
      const observed=eval(source),action=observed.actions.find(a=>a.id===""" + json.dumps(control) + """);
      return {page:observed,action,fresh:window.__jevFast.check({snapshot_schema:2,
        observation_token:observed.observation_token,action})};})()""")
    assert result["fresh"] is True
    assert "node" not in result["action"] and "guard_ref" not in result["action"]
    protocol = Mock(return_value={"result": {"value": True}})
    monkeypatch.setattr(browser, "cdp", protocol)
    outcome = browser.browser_operation({"operation": "act", "session": "test", "action": result["action"],
                                         "snapshot_schema": 2,
                                         "observation_token": result["page"]["observation_token"]})
    assert outcome == {"executed": control}
    assert protocol.call_count == (1 if control == "wait" else 2)
    if control != "wait":
        assert protocol.call_args.kwargs["type"] == "mouseWheel"


def test_overflow_flight_verification_cannot_accept_old_page(monkeypatch, tmp_path):
    from examples import flights

    state = {"page": observed_page(), "page_fresh": False, "status": "stopped", "history": []}
    agent = Mock(snapshot=Mock(return_value=state))
    agent.browser.target, agent.browser.session = "owned-target", "owned-session"
    agent.run.side_effect = RunStopped("snapshot_too_large", "overflow")
    monkeypatch.setattr(flights, "Agent", Mock(return_value=agent))
    monkeypatch.setattr(flights, "verify", Mock(return_value={"passed": True, "checks": {"route": True}}))
    monkeypatch.setattr("sys.argv", ["flights.py", "--output", str(tmp_path)])
    with pytest.raises(RunStopped):
        flights.main()
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["verification"]["passed"] is False
    assert saved["verification"]["checks"]["fresh_page"] is False
    agent.close.assert_called_once()


def test_inspector_marks_diagnostic_page_and_disables_input(monkeypatch):
    agent = make_agent(monkeypatch, [])
    agent.mark_snapshot_overflow()
    state = agent.snapshot()
    state.update(text_model="test", max_steps=60)
    program = """
const fs=require('node:fs'),vm=require('node:vm'),nodes=new Map();
global.document={getElementById(id){if(!nodes.has(id))nodes.set(id,{value:'flights',addEventListener(){}});
return nodes.get(id)},querySelector(){return {content:'test'}},querySelectorAll(){return []}};
global.fetch=()=>new Promise(()=>{});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8')+'\\nstate='+process.argv[2]+';render();');
console.log(JSON.stringify({title:nodes.get('page-title').textContent,
  disabled:['choose','execute','auto'].map(id=>nodes.get(id).disabled)}));
"""
    result = subprocess.run(["node", "-e", program, str(ROOT / "jev_ultrafast/static/app.js"), json.dumps(state)],
                            check=True, capture_output=True, text=True, timeout=10)
    result = json.loads(result.stdout)
    assert result["disabled"] == [True, True, True]
    assert result["title"].endswith(" · not fresh")


@pytest.mark.parametrize("mutation", [
    "request.snapshot_schema=1", "delete request.observation_token", "request.observation_token.generation++",
    "request.observation_token.epoch='wrong'", "request.action.guard_ref.node++",
    "delete request.action.guard_ref", "request.action.id='invented'", "request.action.option.value='invented'",
])
def test_snapshot_rejects_malformed_authority(mutation):
    result = javascript("""(()=>{const request=JSON.parse(JSON.stringify({snapshot_schema:2,
      observation_token:page.observation_token,action:page.actions[0]}));""" + mutation + ";"
                        "return window.__jevFast.check(request)})()")
    assert result is False


def test_atomic_select_overflow_is_definitely_before_input():
    program = """
const fs=require('node:fs'),dom=require(process.argv[1])();
const source=fs.readFileSync(process.argv[2],'utf8'),page=eval(source);
const action=page.actions.find(a=>a.kind==='select'&&a.option.observed_index===3);
dom.field.value='含義'.repeat(100000);
const result=eval(process.argv[3])({action,snapshot_schema:2,observation_token:page.observation_token});
console.log(JSON.stringify({result,events:dom.events,index:dom.select.selectedIndex,nodes:window.__jevFast.nodes.size}));
"""
    result = subprocess.run(["node", "-e", program, str(ROOT / "tests/fixtures/select_dom.cjs"),
                             str(ROOT / "jev_ultrafast/snapshot.js"), browser.SELECT_ACTION], capture_output=True,
                            text=True, check=True, timeout=20)
    result = json.loads(result.stdout)
    assert result["result"]["status"] == "snapshot_too_large"
    assert result["events"] == [] and result["index"] == 0 and result["nodes"] == 0


def test_legacy_generic_dispatch_refuses_before_read_or_input(monkeypatch):
    protocol = Mock(side_effect=AssertionError("No legacy action can access the browser"))
    monkeypatch.setattr(browser, "cdp", protocol)
    for action in observed_page()["actions"]:
        with pytest.raises(browser.StalePage):
            browser.browser_operation({"operation": "act", "session": "test", "action": action})
    protocol.assert_not_called()


@pytest.mark.parametrize("stop_code", ["snapshot_too_large", "snapshot_protocol_error"])
def test_mcp_does_not_read_again_after_terminal_snapshot_overflow(monkeypatch, tmp_path, stop_code):
    agent = make_agent(monkeypatch, [], trace_path=tmp_path / "run.json")
    agent.state["notes_shown"] = []
    agent.mark_snapshot_invalid(stop_code)
    agent.browser.observe.side_effect = AssertionError("Invalid snapshot must not trigger a final fallback read")
    monkeypatch.setattr(mcp_server, "notes_block", lambda _state: ("", []))
    monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
    result = mcp_server.finish(agent, "snapshot", [])
    agent.browser.observe.assert_not_called()
    assert agent.state["final_read_fresh"] is False
    assert agent.state["stop_code"] == stop_code
    assert "not fresh" in result[0] and stop_code in result[0]


@pytest.mark.parametrize("malformation", [
    "legacy", "not_mapping", "schema_bool", "wrong_schema", "no_token", "token_list", "empty_epoch",
    "no_generation", "generation_bool", "generation_zero", "generation_float", "extra_token_key", "no_actions",
    "actions_object", "bad_action", "bad_kind", "no_guard", "wrong_guard", "bool_guard", "duplicate_action",
    "no_text", "no_height", "nan_width", "bad_scroll", "bad_evidence", "bad_evidence_item", "bad_omitted",
])
def test_new_observations_require_complete_schema2_at_cdp_boundary(monkeypatch, malformation):
    page = observed_page()
    if malformation == "legacy":
        page.pop("snapshot_schema")
        page.pop("observation_token")
    elif malformation == "not_mapping":
        page = []
    elif malformation == "schema_bool":
        page["snapshot_schema"] = True
    elif malformation == "wrong_schema":
        page["snapshot_schema"] = 1
    elif malformation == "no_token":
        page.pop("observation_token")
    elif malformation == "token_list":
        page["observation_token"] = []
    elif malformation == "empty_epoch":
        page["observation_token"]["epoch"] = ""
    elif malformation == "no_generation":
        page["observation_token"].pop("generation")
    elif malformation.startswith("generation_"):
        page["observation_token"]["generation"] = {"bool": True, "zero": 0, "float": 1.0}[malformation[11:]]
    elif malformation == "extra_token_key":
        page["observation_token"]["other"] = 1
    elif malformation == "no_actions":
        page.pop("actions")
    elif malformation == "actions_object":
        page["actions"] = {}
    elif malformation == "bad_action":
        page["actions"][0] = "invalid"
    elif malformation == "bad_kind":
        page["actions"][0]["kind"] = []
    elif malformation == "no_guard":
        page["actions"][0].pop("guard_ref")
    elif malformation == "wrong_guard":
        page["actions"][0]["guard_ref"]["epoch"] = "other"
    elif malformation == "bool_guard":
        page["actions"][0]["guard_ref"]["generation"] = True
    elif malformation == "duplicate_action":
        page["actions"].append(deepcopy(page["actions"][0]))
    elif malformation == "no_text":
        page.pop("text")
    elif malformation == "no_height":
        page.pop("h")
    elif malformation == "nan_width":
        page["w"] = float("nan")
    elif malformation == "bad_scroll":
        page["scroll"] = {"y": 0}
    elif malformation == "bad_evidence":
        page["evidence"] = {}
    elif malformation == "bad_evidence_item":
        page["evidence"] = ["invalid"]
    else:
        page["omitted_actions"] = True
    instance = browser.Browser.__new__(browser.Browser)
    attach_quiet_loading_source(instance)
    instance.session = "fixture"
    protocol = Mock(return_value={"result": {"value": page}})
    monkeypatch.setattr(browser, "cdp", protocol)
    with pytest.raises(browser.InvalidSnapshot, match="snapshot_protocol_error"):
        instance.observe(screenshot=True)
    assert protocol.call_count == 1  # No stale retries, screenshot, or browser input.


@pytest.mark.parametrize("adapter", ["constructor", "predict", "post_input", "new_goal", "mcp_continuation",
                                    "mcp_final_done", "inspector"])
def test_invalid_observation_stops_before_model_or_more_input(monkeypatch, tmp_path, adapter):
    invalid = observed_page()
    invalid.pop("snapshot_schema")
    instance = browser.Browser.__new__(browser.Browser)
    attach_quiet_loading_source(instance)
    instance.session = "fixture"
    protocol = Mock(return_value={"result": {"value": invalid}})
    monkeypatch.setattr(browser, "cdp", protocol)
    provider, helper = Mock(), Mock()
    monkeypatch.setattr(loop, "choose", provider)
    monkeypatch.setattr(loop, "field_text", helper)
    if adapter == "constructor":
        instance.close = Mock()
        monkeypatch.setattr(loop, "Browser", Mock(return_value=instance))
        with pytest.raises(browser.InvalidSnapshot):
            loop.Agent("https://example.test/", "Find", allowed_operations=[])
        instance.close.assert_called_once()
        assert protocol.call_count == 1
        return
    if adapter == "post_input":
        agent, _, calls, response = physical_agent(monkeypatch, action="button", trace_path=tmp_path / "run.json")
        monkeypatch.setattr(browser, "cdp", lambda method, **params:
                            {"result": {"value": invalid}} if params.get("expression") == browser.READ_STATE
                            else response(method, params))
    else:
        agent = make_agent(monkeypatch, ALL_OPERATIONS, trace_path=tmp_path / "run.json")
        agent.browser = agent.state["browser"] = instance
    agent.pending_text = ("old", "value", {})
    if adapter == "mcp_final_done":
        agent.state.update(status="done", notes_shown=[])
        monkeypatch.setattr(mcp_server, "notes_block", lambda _state: ("", []))
        monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
        result = mcp_server.finish(agent, "invalid", [])
        assert "snapshot_protocol_error" in result[0] and "not fresh" in result[0]
    elif adapter == "mcp_continuation":
        monkeypatch.setattr(mcp_server, "AGENT", agent)
        probe = Mock(side_effect=AssertionError("No target recovery for malformed observation"))
        monkeypatch.setattr(mcp_server, "cdp", probe)
        assert "snapshot_protocol_error" in mcp_server.start_run("New goal", None, [], None, False)[0]
        probe.assert_not_called()
    else:
        with pytest.raises((browser.InvalidSnapshot, RunStopped)):
            if adapter == "new_goal":
                agent.new_goal("New goal", allowed_operations=[])
            elif adapter == "inspector":
                monkeypatch.setattr(demo, "AGENT", agent)
                demo.command("predict", {})
            else:
                agent.command("act" if adapter == "post_input" else "predict",
                              {"fingerprint": agent.state["page"]["fingerprint"]})
    assert agent.state["status"] == "stopped" and agent.state["stop_code"] == "snapshot_protocol_error"
    assert agent.state["page_fresh"] is False and agent.pending_text is agent.state["decision"] is None
    assert agent.state["stale_recoveries"] == 0
    assert len(agent.state["history"]) == (1 if adapter == "post_input" else 0)
    provider.assert_not_called()
    helper.assert_not_called()
    for command in ("tick", "predict", "act"):
        with pytest.raises(RunStopped):
            agent.command(command)
