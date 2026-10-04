"""Run production snapshot/SELECT JavaScript against a DOM adapter, plus Python dispatch contracts."""

import json
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import browser, model
from jev_ultrafast.contracts import RunStopped

ROOT = Path(__file__).resolve().parents[1]
MUTATIONS = {
    "value swap": "[dom.options[2].value,dom.options[3].value]=['other','changed']",
    "label": "dom.options[3].label='Changed'",
    "replacement": "dom.options[3].isConnected=false;dom.select.options[3]={...dom.options[3],isConnected:true}",
    "removal": "dom.options[3].isConnected=false;dom.select.options.splice(3,1)",
    "reorder": "[dom.select.options[2],dom.select.options[3]]=[dom.options[3],dom.options[2]]",
    "owner": "dom.options[3].owner={}",
    "selected": "dom.select.selectedIndex=3",
    "option disabled": "dom.options[3].disabled=true",
    "optgroup disabled": "dom.group.disabled=true",
    "fieldset disabled": "dom.select.fieldsetDisabled=true",
    "select disabled": "dom.select.disabled=true",
    "multiple": "dom.select.multiple=true",
    "hidden": "dom.select.hidden=true",
    "covered": "dom.document.covered=true",
    "aria disabled": "dom.select.ariaDisabled=true",
    "unrelated field": "dom.field.value='new'",
    "context": "dom.form.innerText='Changed price'",
    "navigation": "performance.timeOrigin+=1",
    "cache reset": "delete window.__jevFast;eval(snapshot)",
}


def run_javascript(mutation="", **config):
    program = """
const fs=require('node:fs');
const dom=require(process.argv[1])(JSON.parse(process.argv[2]));
const snapshot=fs.readFileSync(process.argv[3],'utf8');
const page=eval(snapshot);
const action=page.actions.find(a=>a.kind==='select' && a.option.observed_index===3);
const payload=action ? {action,page_key:page.page_key,guard:page.guards[action.node]} : null;
eval(process.argv[4]);
const result=payload ? eval(process.argv[5])(payload) : null;
const after=eval(snapshot);
console.log(JSON.stringify({page,after,result,events:dom.events,index:dom.select.selectedIndex,
  key:dom.select.selectedOptions[0]?.key}));
"""
    result = subprocess.run(
        ["node", "-e", program, str(ROOT / "tests/fixtures/select_dom.cjs"), json.dumps(config),
         str(ROOT / "jev_ultrafast/snapshot.js"), mutation, browser.SELECT_ACTION],
        check=True, text=True, capture_output=True, timeout=10,
    )
    return json.loads(result.stdout)


def test_select_descriptor_tracks_identity_and_effective_state():
    result = run_javascript()
    page = result["page"]
    actions = [action for action in page["actions"] if action["kind"] == "select"]
    assert [action["option"]["observed_index"] for action in actions] == [2, 3, 4]
    assert len({action["option"]["option_id"] for action in actions}) == 3
    for action in actions:
        descriptor = action["option"]
        assert descriptor["select_id"] == action["node"]
        assert descriptor["selected"] is descriptor["effective_disabled"] is False
        assert descriptor["label"] == action["label"].split(" → ")[1]
        assert descriptor["value"] == action["value"]
        assert descriptor["document_id"] and descriptor["cache_epoch"]
    _, targets, _ = model.action_space(page["actions"])
    assert targets["SELECT"]["1:1"]["option"]["observed_index"] == 2
    assert targets["SELECT"]["1:2"]["option"]["observed_index"] == 3
    assert result["index"] == 3 and result["key"] == "second"
    assert result["events"] == [{"event": name, "index": 3, "key": "second"} for name in ("input", "change")]


@pytest.mark.parametrize("disabled", [False, True])
def test_multiple_select_is_evidence_only(monkeypatch, disabled):
    page = run_javascript(multiple=True, disabled=disabled)["page"]
    observed = page["evidence"][0]
    assert observed["selected_options"] == [{"label": "Same", "value": "same"}] * 2
    assert not any(action.get("node") == observed["node"] for action in page["actions"])
    assert not any(action.get("role") == "option" for action in page["actions"])
    elements, targets, controls = model.action_space(page["actions"], [], evidence=page["evidence"])
    assert targets == controls == {}
    assert elements[-1]["selected_options"] == observed["selected_options"]
    assert elements[-1]["operations"] == []
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {"model": "fake", "answers": {"operation": {"choice": "DONE", "confidence": 1,
                "probabilities": {"DONE": 1, "BLOCKED": 0}}}}

    monkeypatch.setenv("TYPESAFE_API_KEY", "fake")
    monkeypatch.setattr(model, "post_json", post)
    model.choose(page, "Read all selected values", [], frozenset())
    assert calls[0]["state"]["elements"][-1]["selected_options"] == observed["selected_options"]
    assert set(calls[0]["questions"]) == {"operation"}


@pytest.mark.parametrize("mutation", MUTATIONS)
def test_select_rejects_changed_observed_option(mutation):
    result = run_javascript(MUTATIONS[mutation])
    assert result["result"]["status"] == "rejected_before_input"
    assert result["events"] == []


def test_select_protocol_epoch_is_not_progress():
    result = run_javascript("delete window.__jevFast")
    before, after = result["page"], result["after"]
    assert before["actions"][0]["option"]["cache_epoch"] != after["actions"][0]["option"]["cache_epoch"]
    assert browser.fingerprint(before) == browser.fingerprint(after)
    assert before["marker"] != after["marker"]


UNCERTAIN_RESPONSES = [
    TimeoutError("lost"), RuntimeError("disconnected"), {"exceptionDetails": {"text": "context destroyed"}},
    {}, {"result": {}}, {"result": {"value": None}}, {"result": {"value": {"status": "unknown"}}},
    {"result": {"value": {"status": "executed", "action_id": "different"}}},
    {"result": {"value": {"status": "rejected_before_input"}}},
    {"result": {"value": {"status": "rejected_before_input", "reason": "late", "executed": True}}},
]


@pytest.mark.parametrize("response", UNCERTAIN_RESPONSES)
def test_select_uncertainty_never_retries(monkeypatch, tmp_path, response):
    page = run_javascript()["page"]
    page["fingerprint"] = browser.fingerprint(page)
    selected = next(action for action in page["actions"] if action.get("option", {}).get("observed_index") == 3)
    real_browser = browser.Browser.__new__(browser.Browser)
    real_browser.session = "fake-session"
    real_browser.observe = Mock(return_value=page)
    real_browser.fresh = Mock(side_effect=AssertionError("SELECT freshness must be inside its atomic evaluation"))
    monkeypatch.setattr(loop, "Browser", Mock(return_value=real_browser))
    agent = loop.Agent(page["url"], "Select the second option", allowed_operations=["SELECT"],
                       trace_path=tmp_path / "trace.json")
    agent.state.update(started_at=time.perf_counter(), status="predicted", decision={
        "choice": selected["id"], "operation": "SELECT", "target": "1:2", "commit_probability": 0,
    })
    real_browser.observe.reset_mock()
    dispatch = Mock(side_effect=response) if isinstance(response, Exception) else Mock(return_value=response)
    monkeypatch.setattr(browser, "cdp", dispatch)
    helper, choose = Mock(), Mock()
    monkeypatch.setattr(loop, "field_text", helper)
    monkeypatch.setattr(loop, "choose", choose)
    with pytest.raises(RunStopped) as error:
        agent.command("act", {"fingerprint": page["fingerprint"]})
    assert error.value.code == "uncertain_action"
    assert isinstance(error.value.__cause__, browser.UncertainAction)
    if isinstance(response, Exception):
        assert error.value.__cause__.__cause__ is response
    for command in ("tick", "act", "predict"):
        with pytest.raises(ValueError, match="stopped"):
            agent.command(command)
    saved = json.loads(agent.trace_path.read_text())
    assert saved["attempt"]["outcome"] == "uncertain" and saved["history"] == []
    assert saved["attempt"]["option"] == selected["option"]
    assert saved["status"] == "stopped" and saved["decision"] is None
    assert dispatch.call_count == 1
    real_browser.observe.assert_not_called()
    helper.assert_not_called()
    choose.assert_not_called()


def test_only_tagged_preinput_rejection_is_stale(monkeypatch):
    result = run_javascript()
    page = result["page"]
    action = next(action for action in page["actions"] if action["kind"] == "select")
    dispatch = Mock(return_value={"result": {"value": {"status": "rejected_before_input", "reason": "changed"}}})
    monkeypatch.setattr(browser, "cdp", dispatch)
    with pytest.raises(browser.StalePage, match="changed"):
        browser.browser_operation({"operation": "act", "session": "S", "action": action,
                                   "page_key": page["page_key"], "guard": page["guards"][str(action["node"])]})
    assert dispatch.call_count == 1


def test_multiselect_evidence_changes_progress():
    page = run_javascript(multiple=True)["page"]
    changed = deepcopy(page)
    changed["evidence"][0]["selected_options"].pop()
    assert browser.fingerprint(page) != browser.fingerprint(changed)
