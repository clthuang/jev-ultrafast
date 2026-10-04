"""Real DOM and event proofs in the separately owned, fixture-only native lab. Never call a model."""

import json
import re
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import browser, model
from jev_ultrafast.contracts import RunStopped

pytestmark = pytest.mark.native


@pytest.fixture
def native_browser(lab_manifest):
    instance = browser.Browser(lab_manifest["fixture_url"] + "/native_select.html")
    try:
        yield instance
    finally:
        instance.close()


def action_for(page, index=3):
    return next(action for action in page["actions"]
                if action.get("option", {}).get("observed_index") == index and action["label"].startswith("Category →"))


def selected_state(instance):
    return instance.evaluate("""(() => {const select=document.querySelector('#category');return {
      index:select.selectedIndex,key:select.selectedOptions[0]?.id,value:select.value,events:window.events
    }})()""")


def save_proof(manifest, request, result):
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", request.node.name)
    (Path(manifest["root"]) / f"select-proof-{name}.json").write_text(json.dumps(result, indent=2) + "\n")


@pytest.mark.parametrize(("index", "key"), [(2, "first"), (3, "second"), (4, "other-option")])
def test_select_targets_exact_option(native_browser, lab_manifest, request, index, key):
    page = native_browser.observe(screenshot=False)
    action = action_for(page, index)
    if index == 3:
        assert action["option"]["label"] == "Same"
        assert native_browser.evaluate("document.querySelector('#second').textContent") == "Second internal text"
    native_browser.act(action, page)
    result = selected_state(native_browser)
    assert result["index"] == index and result["key"] == key
    assert native_browser.evaluate(
        f"document.querySelector('#category').selectedOptions[0]===window.__jevFast.nodes.get({action['option']['option_id']})"
    )
    save_proof(lab_manifest, request, {"descriptor": action["option"], "result": result})


def test_select_emits_one_event_pair(native_browser, lab_manifest, request):
    page = native_browser.observe(screenshot=False)
    native_browser.act(action_for(page), page)
    result = selected_state(native_browser)
    assert result["events"] == [
        {"event": name, "select": "category", "index": 3, "key": "second"} for name in ("input", "change")
    ]
    save_proof(lab_manifest, request, result)


NATIVE_MUTATIONS = {
    "value swap": "first.value='changed';second.value='other'",
    "label": "second.label='Changed'",
    "replacement": "second.replaceWith(second.cloneNode(true))",
    "removal": "second.remove()",
    "reorder": "group.insertBefore(document.querySelector('#other-option'),second)",
    "owner": "document.querySelector('#owner').append(second)",
    "selected": "select.selectedIndex=3",
    "option disabled": "second.disabled=true",
    "optgroup disabled": "group.disabled=true",
    "fieldset disabled": "document.querySelector('#fieldset').disabled=true",
    "select disabled": "select.disabled=true",
    "multiple": "select.multiple=true",
    "hidden": "select.style.display='none'",
    "covered": "const cover=document.createElement('div');cover.style.cssText='position:fixed;inset:0;z-index:999';"
               "document.body.append(cover)",
    "aria disabled": "select.setAttribute('aria-disabled','true')",
    "unrelated field": "document.querySelector('#field').value='new'",
    "context": "document.querySelector('#context').textContent='Changed price'",
    "cache reset": "delete window.__jevFast",
    "navigation": None,
}


@pytest.mark.parametrize("mutation", NATIVE_MUTATIONS)
def test_native_select_rejects_changed_observed_option(native_browser, lab_manifest, request, monkeypatch, mutation):
    page = native_browser.observe(screenshot=False)
    action = action_for(page)
    if mutation == "navigation":
        native_browser.call("Page.navigate", url=lab_manifest["fixture_url"] + "/native_select.html?new-document")
        deadline = time.monotonic() + 5
        while native_browser.evaluate("document.readyState") != "complete":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        native_browser.observe(screenshot=False)  # Numeric IDs are deliberately reused in the identical new document.
    else:
        native_browser.evaluate("(() => {const select=document.querySelector('#category'),"
                                "first=document.querySelector('#first'),second=document.querySelector('#second'),"
                                "group=document.querySelector('#group');" + NATIVE_MUTATIONS[mutation] + "})()")
        if mutation == "cache reset":
            after = native_browser.observe(screenshot=False)
            assert after["fingerprint"] == page["fingerprint"]
            assert action_for(after)["option"]["cache_epoch"] != action["option"]["cache_epoch"]
    monkeypatch.setattr(native_browser, "fresh", Mock(side_effect=AssertionError("No separate SELECT freshness read")))
    with pytest.raises(browser.StalePage):
        native_browser.act(action, page)
    result = selected_state(native_browser)
    assert result["events"] == []
    native_browser.fresh.assert_not_called()
    save_proof(lab_manifest, request, {"mutation": mutation, "rejected_before_input": True, "result": result})


def test_native_select_honors_first_legend_enabled_exception(native_browser, lab_manifest, request):
    native_browser.evaluate("""(() => {const fieldset=document.querySelector('#fieldset');
      const legend=document.createElement('legend');fieldset.prepend(legend);
      legend.append(document.querySelector('#category'));fieldset.disabled=true})()""")
    assert native_browser.evaluate("document.querySelector('#category').matches(':disabled')") is False
    page = native_browser.observe(screenshot=False)
    native_browser.act(action_for(page), page)
    result = selected_state(native_browser)
    assert result["key"] == "second" and len(result["events"]) == 2
    save_proof(lab_manifest, request, result)


def test_native_multiple_select_has_evidence_without_any_click(native_browser, lab_manifest, request):
    page = native_browser.observe(screenshot=False)
    observed = next(item for item in page["evidence"] if item["label"] == "Interests")
    assert observed["selected_options"] == [
        {"label": "First interest", "value": "one"}, {"label": "Second interest", "value": "two"}
    ]
    native_nodes = native_browser.evaluate("""[...window.__jevFast.nodes].filter(([id,e])=>
      e.closest('select')?.id==='multiple').map(([id])=>id)""")
    assert not any(action.get("node") in native_nodes for action in page["actions"])
    assert not any(action.get("role") == "option" for action in page["actions"])
    elements, targets, controls = model.action_space(page["actions"], [], evidence=page["evidence"])
    assert targets == controls == {}
    assert elements[-1]["selected_options"] == observed["selected_options"]
    actual = native_browser.evaluate("""({selected:[...document.querySelector('#multiple').selectedOptions]
      .map(option=>({label:option.label,value:option.value})),events:window.events})""")
    assert actual == {"selected": observed["selected_options"], "events": []}
    save_proof(lab_manifest, request, {"evidence": observed, "offered_operations": list(targets), "actual": actual})


def test_native_select_recovers_only_after_new_observation(native_browser, lab_manifest, request):
    page = native_browser.observe(screenshot=False)
    native_browser.evaluate("document.querySelector('#second').value='changed'")
    with pytest.raises(browser.StalePage):
        native_browser.act(action_for(page), page)
    assert selected_state(native_browser)["events"] == []
    fresh = native_browser.observe(screenshot=False)
    native_browser.act(action_for(fresh), fresh)
    result = selected_state(native_browser)
    assert result["key"] == "second" and result["value"] == "changed" and len(result["events"]) == 2
    save_proof(lab_manifest, request, result)


@pytest.mark.parametrize("failure", ["timeout", "missing_reply", "malformed_success"])
def test_lost_reply_after_select_preserves_single_execution(lab_manifest, request, monkeypatch, tmp_path, failure):
    agent = loop.Agent(lab_manifest["fixture_url"] + "/native_select.html", "Select the second Same option",
                       allowed_operations=["SELECT"], trace_path=tmp_path / "trace.json")
    try:
        page = agent.state["page"]
        action = action_for(page)
        _, targets, _ = model.action_space(page["actions"])
        target = next(index for index, candidate in targets["SELECT"].items() if candidate is action)
        agent.state.update(started_at=time.perf_counter(), status="predicted", decision={
            "choice": action["id"], "operation": "SELECT", "target": target, "commit_probability": 0,
        })
        original = browser.cdp
        executions = []

        def lose_reply(method, **params):
            result = original(method, **params)
            if method == "Runtime.evaluate" and params.get("expression", "").startswith(browser.SELECT_ACTION):
                executions.append(result)
                if failure == "timeout":
                    raise TimeoutError("Deliberately lost the reply after real execution")
                if failure == "missing_reply":
                    return {}
                return {"result": {"value": {"status": "executed"}}}
            return result

        monkeypatch.setattr(browser, "cdp", lose_reply)
        choose, helper = Mock(), Mock()
        monkeypatch.setattr(loop, "choose", choose)
        monkeypatch.setattr(loop, "field_text", helper)
        with pytest.raises(RunStopped) as error:
            agent.command("act", {"fingerprint": page["fingerprint"]})
        assert error.value.code == "uncertain_action"
        for command in ("act", "tick", "predict"):
            with pytest.raises(ValueError, match="stopped"):
                agent.command(command)
        saved = json.loads(agent.trace_path.read_text())
        assert saved["attempt"]["outcome"] == "uncertain" and saved["history"] == []
        assert saved["attempt"]["option"] == action["option"]
        assert saved["decision"] is None and saved["status"] == "stopped"
        assert len(executions) == 1
        choose.assert_not_called()
        helper.assert_not_called()
        result = selected_state(agent.browser)
        assert result["key"] == "second" and result["events"] == [
            {"event": name, "select": "category", "index": 3, "key": "second"} for name in ("input", "change")
        ]
        save_proof(lab_manifest, request, {"reply_failure": failure, "actual": result,
                                         "attempt": saved["attempt"], "status": saved["status"]})
    finally:
        agent.close()
