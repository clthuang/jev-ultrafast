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


SNAPSHOT_MUTATIONS = {
    "unchanged": "void 0",
    "geometry": "controls[0].style.left='1px'",
    "omitted": "controls[499].setAttribute('aria-label','Changed omitted')",
    "offscreen": "document.querySelector('#offscreen').value='changed'",
    "title": "document.title='Changed title'",
    "height": "document.body.style.height='1400px'",
}


def navigate_fixture(instance, url):
    instance.call("Page.navigate", url=url)
    deadline = time.monotonic() + 5
    while instance.evaluate("document.readyState") != "complete":
        assert time.monotonic() < deadline
        time.sleep(0.02)


@pytest.mark.parametrize("mutation", SNAPSHOT_MUTATIONS)
def test_snapshot_freshness_parity(native_browser, lab_manifest, request, mutation):
    baseline = (Path(__file__).parent / "fixtures/snapshot_select_baseline.js").read_text()
    url = lab_manifest["fixture_url"] + "/snapshot_dense.html?count=500"
    navigate_fixture(native_browser, url)
    old = native_browser.evaluate("(() => { window.originalSnapshot=" + baseline +
                                  "; return {offered:window.originalSnapshot.actions.length}; })()")
    native_browser.evaluate(SNAPSHOT_MUTATIONS[mutation])
    baseline_fresh = native_browser.evaluate("JSON.stringify(window.originalSnapshot.marker)===JSON.stringify((" +
                                              baseline + ").marker)")
    navigate_fixture(native_browser, url + "&candidate=1")
    page = native_browser.observe(screenshot=False)
    native_browser.evaluate(SNAPSHOT_MUTATIONS[mutation])
    checks = [native_browser.fresh(page), native_browser.fresh(page)]
    assert checks == [baseline_fresh, baseline_fresh]
    after = native_browser.observe(screenshot=False)
    changed = page["fingerprint"] != after["fingerprint"]
    assert changed is (mutation in {"geometry", "height"})
    assert native_browser.fresh(page) is False
    save_proof(lab_manifest, request, {"mutation": mutation, "baseline_fresh": baseline_fresh,
                                    "candidate_fresh": checks, "progress_changed": changed,
                                    "baseline_offered": old["offered"], "candidate_offered": len(page["actions"])})


def measure_snapshot(instance, source, baseline):
    # Measure original UTF-8 payload inside Chrome. A 30 MB old snapshot need not be transferred merely to count it.
    expression = """(()=>{scopeReads=0;const start=performance.now(),page=SOURCE;
      const scan_ms=performance.now()-start,serialize=performance.now();
      const bytes=new TextEncoder().encode(JSON.stringify(page)).byteLength;
      const serialization_ms=performance.now()-serialize;
      const actions=page.actions?.map(({node,guard_ref,...action})=>({...action,
        ...(node?{control:window.__jevFast.nodes.get(node)?.id}:{})}));
      return {bytes,scan_ms,serialization_ms,scope_reads:scopeReads,
        guard_builds:BASELINE ? Object.keys(page.guards||{}).length : page.diagnostics.guard_builds,
        strong_references:window.__jevFast.nodes.size,actions,status:page.status||'ok',
        internal:window.__jevFast.last_scan||null};})()"""
    expression = expression.replace("SOURCE", source).replace("BASELINE", str(baseline).lower())
    return instance.evaluate(expression)


@pytest.mark.parametrize("count", [250, 1000, 5000])
def test_snapshot_payload_and_progress_contracts(native_browser, lab_manifest, request, count):
    import hashlib
    import statistics

    baseline_source = (Path(__file__).parent / "fixtures/snapshot_select_baseline.js").read_text()
    url = lab_manifest["fixture_url"] + f"/snapshot_dense.html?count={count}"
    navigate_fixture(native_browser, url)
    baseline_browser = browser.Browser(url)
    samples, expected = [], None
    try:
        # Two warmup pairs plus five alternating-order measured pairs. Keep every attempt and order.
        for index in range(7):
            order = [("baseline", baseline_browser, baseline_source), ("candidate", native_browser, browser.READ_STATE)]
            if index % 2:
                order.reverse()
            for mode, instance, source in order:
                sample = measure_snapshot(instance, source, mode == "baseline")
                actions = sample.pop("actions")
                if expected is None:
                    expected = actions
                assert actions == expected
                sample.update(mode=mode,iteration=index,warmup=index < 2,
                              actions_sha256=hashlib.sha256(json.dumps(actions, sort_keys=True).encode()).hexdigest())
                samples.append(sample)
                assert sample["status"] == "ok"
                if mode == "candidate":
                    assert sample["bytes"] <= browser.MAX_SNAPSHOT_BYTES
                    assert sample["guard_builds"] == sample["strong_references"] == 250
                    assert sample["scope_reads"] == 1
                else:
                    assert sample["guard_builds"] == count and sample["scope_reads"] == count
                    assert sample["strong_references"] == count + 1  # Old code retains offscreen form fields too.
        summary = {}
        for mode in ("baseline", "candidate"):
            rows = [sample for sample in samples if sample["mode"] == mode and not sample["warmup"]]
            summary[mode] = {key: {"min": min(row[key] for row in rows),
                                  "median": statistics.median(row[key] for row in rows),
                                  "max": max(row[key] for row in rows)}
                             for key in ("bytes", "scan_ms", "serialization_ms")}
        save_proof(lab_manifest, request, {"count": count, "samples": samples, "summary": summary,
                                        "scope": "Synthetic local fixture, not a general latency claim"})
    finally:
        baseline_browser.close()


def test_native_snapshot_overflow_invalidates_baseline(native_browser, lab_manifest, request):
    navigate_fixture(native_browser, lab_manifest["fixture_url"] + "/snapshot_dense.html?count=250")
    page = native_browser.observe(screenshot=False)
    native_browser.evaluate("controls.forEach(control=>control.setAttribute('aria-label','含義'.repeat(1200)))")
    with pytest.raises(browser.SnapshotTooLarge):
        native_browser.fresh(page)
    assert native_browser.fresh(page) is False
    assert native_browser.evaluate("window.__jevFast.nodes.size") == 0
    with pytest.raises(browser.SnapshotTooLarge):
        native_browser.observe(screenshot=False)
    assert native_browser.evaluate("events") == []
    save_proof(lab_manifest, request, {"overflow": True, "retained_nodes": 0, "events": []})


def test_native_snapshot_wait_and_scroll_still_execute(native_browser, lab_manifest, request):
    navigate_fixture(native_browser, lab_manifest["fixture_url"] + "/snapshot_dense.html?count=250")
    native_browser.evaluate("document.body.style.height='2000px';window.scrollTo(0,200)")
    executed = []
    for action_id in ("wait", "scroll_down", "scroll_up"):
        page = native_browser.observe(screenshot=False)
        action = next(action for action in page["actions"] if action["id"] == action_id)
        result = native_browser.act(action, page)
        assert result == {"executed": action_id}
        executed.append(action_id)
    assert native_browser.evaluate("events") == []
    save_proof(lab_manifest, request, {"executed": executed, "button_events": []})


def scripted_readiness_choice(page, _goal, history, allowed_operations, **_control):
    if history:
        action_id, operation, target = "DONE", "DONE", None
    else:
        _, targets, _ = model.action_space(page["actions"], allowed_operations)
        target, action = next((target, action) for target, action in targets["CLICK"].items()
                              if action["label"] == "Start once")
        action_id, operation = action["id"], "CLICK"
    return {"choice": action_id, "operation": operation, "target": target, "confidence": 1,
            "probabilities": {action_id: 1}, "operation_probabilities": {operation: 1},
            "target_probabilities": {target: 1} if target else {}, "target_confidence": 1 if target else None,
            "commit_probability": 0, "usage": {"input_tokens": 0}, "model": "scripted-native", "latency_ms": 0}


@pytest.mark.parametrize("scenario", ["network", "busy-1", "busy-2", "busy-3", "busy-4", "busy-5", "dialog"])
def test_busy_page_and_loading_gate_compose_without_repeated_input(lab_manifest, request, monkeypatch, tmp_path,
                                                                  scenario):
    """Actual renderer stalls/dialogs plus scripted decisions; no injected observation failure or paid model."""
    import secrets
    import threading

    from jev_ultrafast import mcp_server

    monkeypatch.setattr(loop, "choose", scripted_readiness_choice)
    trial_id = scenario + "-" + secrets.token_hex(8)
    agent = loop.Agent(lab_manifest["fixture_url"] + "/readiness.html?delay=1&trial_id=" + trial_id,
                       "Start once and wait for results", allowed_operations=["CLICK"],
                       trace_path=tmp_path / "run.json")
    original_observe, injected = agent.browser.observe, []

    def observe(*args, **kwargs):
        if agent.state["history"] and not injected and scenario != "network":
            injected.append(scenario)
            script = ("const until=performance.now()+7000;while(performance.now()<until){}"
                      if scenario.startswith("busy") else "alert('Owned readiness fixture dialog')")
            agent.browser.evaluate("setTimeout(()=>{" + script + "},0)")
        return original_observe(*args, **kwargs)

    monkeypatch.setattr(agent.browser, "observe", observe)
    monkeypatch.setattr(mcp_server, "AGENT", agent)
    monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
    monkeypatch.setattr(mcp_server, "PREVIOUS_RUN", None)
    monkeypatch.setattr(mcp_server, "STOP", threading.Event())
    monkeypatch.setattr(mcp_server, "notes_block", lambda _state: ("", []))
    monkeypatch.setattr(mcp_server.anyio.from_thread, "check_cancelled", lambda: None)
    try:
        result = mcp_server.start_run("Start once and wait for results", None, ["CLICK"], None, False)
        actual = agent.browser.evaluate("window.fixture")  # Independent DOM counter/result, never DONE as proof.
        state = agent.snapshot()
        server = readiness_submission_count(lab_manifest, trial_id)
        assert server["submissions"] == server["completed"] == 1 and server["active"] == 0
        assert actual["inputCount"] == 1 and actual["status"] == "ready"
        assert len(state["history"]) == 1 and state["history"][0]["kind"] == "click"
        assert state["attempt"] is None
        assert state["final_read_fresh"] is True and state["final_read_ms"] >= 0
        if scenario == "dialog":
            assert state["status"] == "stopped" and state["stop_code"] == "execution_error"
            assert state["repeated_reads"] == 2
            assert any("dialog; dismissed" in note for note in state["result"]["notes"])
        else:
            assert state["status"] == "done"
            assert state["repeated_reads"] == (1 if scenario.startswith("busy") else 0)
            if scenario.startswith("busy"):
                assert state["loading_waits"] == []  # Repeated read cannot restart the original five-second input age.
            else:
                assert any(wait[0] > 0 and not wait[1] and not wait[2] for wait in state["loading_waits"])
                assert state["stale_recoveries"] >= 1  # Ready DOM replaced the pre-gate pending DONE observation.
        save_proof(lab_manifest, request, {"scenario": scenario, "trial_id": trial_id,
            "server_submissions": server, "independent_fixture": actual,
            "status": state["status"], "stop_code": state["stop_code"], "history": state["history"],
            "repeated_reads": state["repeated_reads"], "loading_waits": state["loading_waits"],
            "stale_recoveries": state["stale_recoveries"], "final_read_ms": state["final_read_ms"],
            "final_read_fresh": state["final_read_fresh"], "notes": state["result"]["notes"],
            "response_text": result[0], "injected_renderer_scenarios": injected})
    finally:
        agent.close()


def test_native_loading_ignores_actual_out_of_process_frame(lab_manifest, request, monkeypatch, tmp_path):
    import secrets
    from urllib.parse import quote

    stream_id = secrets.token_hex(8)
    monkeypatch.setattr(loop, "choose", scripted_readiness_choice)
    url = (lab_manifest["fixture_url"] + "/readiness.html?delay=1&iframe=" +
           quote(lab_manifest["iframe_url"], safe="") + "&stream_id=" + stream_id + "&trial_id=oopif-" + stream_id)
    agent = loop.Agent(url, "Start once and wait for main results", allowed_operations=["CLICK"],
                       trace_path=tmp_path / "run.json")
    iframe_session = None
    try:
        agent.command("tick")
        observer = agent.browser._event_source
        assert observer.session_id != agent.browser.session
        main_frame = agent.browser.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
        assert observer.main_frame_id == main_frame
        deadline, iframe_target = time.monotonic() + 3, None
        while time.monotonic() < deadline:
            targets = browser.cdp("Target.getTargets")["targetInfos"]
            iframe_target = next((target for target in targets if target["type"] == "iframe" and
                                  target["url"].startswith(lab_manifest["iframe_url"] + "/__readiness__/stream-frame")),
                                 None)
            if iframe_target:
                break
            time.sleep(0.02)
        assert iframe_target is not None, "A blocked iframe is not actual OOPIF coverage"
        assert iframe_target["targetId"] != agent.browser.target
        iframe_session = browser.cdp("Target.attachToTarget", targetId=iframe_target["targetId"],
                                     flatten=True)["sessionId"]
        assert iframe_session not in {observer.session_id, agent.browser.session}
        for _ in range(5):
            if agent.state["status"] == "done":
                break
            agent.command("tick")
        actual = agent.browser.evaluate("window.fixture")
        child = browser.cdp("Runtime.evaluate", session_id=iframe_session,
                            expression="({state:window.childState,readyState:document.readyState})",
                            returnByValue=True)["result"]["value"]
        stream = agent.browser.call("Runtime.evaluate", expression=
            "fetch('/__readiness__/stream-status?stream_id=" + stream_id + "').then(response=>response.json())",
            awaitPromise=True, returnByValue=True)["result"]["value"]
        server = readiness_submission_count(lab_manifest, "oopif-" + stream_id)
        assert server["submissions"] == 1
        assert agent.state["status"] == "done" and actual["status"] == "ready" and actual["inputCount"] == 1
        assert child == {"state": {"started": True, "finished": False}, "readyState": "loading"}
        assert stream["started"] and not stream["finished"] and stream["remaining_bytes"] > 0
        # The real child Document is still streaming after main-frame readiness; this is not merely a child Fetch.
        assert all(not wait[1] and not wait[2] and wait[0] < 4000 for wait in agent.state["loading_waits"])
        save_proof(lab_manifest, request, {"main_target": agent.browser.target, "main_frame": main_frame,
            "observer_session": observer.session_id, "action_session": agent.browser.session,
            "iframe_target": iframe_target, "iframe_session": iframe_session, "child_state": child,
            "pending_document_stream": stream, "server_submissions": server,
            "independent_fixture": actual, "loading_waits": agent.state["loading_waits"],
            "history_count": len(agent.state["history"]), "stale_recoveries": agent.state["stale_recoveries"]})
    finally:
        if iframe_session:
            browser.cdp("Target.detachFromTarget", sessionId=iframe_session)
        agent.close()


def readiness_submission_count(manifest, trial_id):
    """Read the owned server directly so proof collection cannot create main-tab loading events."""
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", manifest["fixture_port"], timeout=3)
    try:
        connection.request("GET", "/__readiness__/submissions?trial_id=" + trial_id)
        response = connection.getresponse()
        assert response.status == 200
        return json.loads(response.read())
    finally:
        connection.close()


def readiness_action(instance, kind="click"):
    page = instance.observe(screenshot=False)
    action = next(action for action in page["actions"] if action["kind"] == kind)
    instance.act(action, page)
    return page, action


def test_native_loading_has_zero_wait_before_a_later_request(native_browser, lab_manifest, request):
    import secrets

    trial_id = "deferred-" + secrets.token_hex(8)
    navigate_fixture(native_browser, lab_manifest["fixture_url"] +
                     "/readiness.html?request_delay=1&delay=1&trial_id=" + trial_id)
    readiness_action(native_browser)
    first = native_browser.wait_for_loading()
    assert first == [0, False, False]  # No minimum wait and no request yet, although an input has happened.
    assert readiness_submission_count(lab_manifest, trial_id)["submissions"] == 0
    deadline = time.monotonic() + 3
    while readiness_submission_count(lab_manifest, trial_id)["submissions"] == 0:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    second = native_browser.wait_for_loading()
    assert second[0] > 0 and second[1:] == [False, False]
    actual = native_browser.evaluate("window.fixture")
    server = readiness_submission_count(lab_manifest, trial_id)
    assert actual["status"] == "ready" and actual["inputCount"] == server["submissions"] == 1
    save_proof(lab_manifest, request, {"first_wait": first, "later_wait": second, "server_submissions": server,
                                    "independent_fixture": actual})


def test_native_loading_caps_a_never_ending_request(native_browser, lab_manifest, request):
    import secrets

    trial_id = "never-ending-" + secrets.token_hex(8)
    navigate_fixture(native_browser, lab_manifest["fixture_url"] + "/readiness.html?hold=1&trial_id=" + trial_id)
    readiness_action(native_browser)
    deadline = time.monotonic() + 2
    while readiness_submission_count(lab_manifest, trial_id)["active"] != 1:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    original_input_done = native_browser.input_done
    waited = native_browser.wait_for_loading()
    assert waited[1:] == [True, False]
    assert 4.9 <= time.monotonic() - original_input_done < 6
    assert native_browser.input_done == original_input_done
    assert native_browser.wait_for_loading() is None  # No renewed allowance for another answer.
    server = readiness_submission_count(lab_manifest, trial_id)
    actual = native_browser.evaluate("window.fixture")
    assert server["submissions"] == server["active"] == 1 and server["completed"] == 0
    assert actual["inputCount"] == 1 and actual["status"] == "loading"
    save_proof(lab_manifest, request, {"wait": waited, "original_input_done": original_input_done,
                                    "server_submissions": server, "independent_fixture": actual})


def test_native_loading_waits_for_delayed_main_frame_navigation(native_browser, lab_manifest, request):
    import secrets

    trial_id = "navigation-" + secrets.token_hex(8)
    navigate_fixture(native_browser, lab_manifest["fixture_url"] +
                     "/readiness.html?mode=navigation&delay=2&trial_id=" + trial_id)
    original, _ = readiness_action(native_browser)
    deadline = time.monotonic() + 2
    while readiness_submission_count(lab_manifest, trial_id)["active"] != 1:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    waited = native_browser.wait_for_loading()
    assert waited[0] > 0 and waited[1:] == [False, False]
    assert native_browser.fresh(original) is False  # The loading gate must not install a replacement baseline.
    result = native_browser.observe(screenshot=False)
    server = readiness_submission_count(lab_manifest, trial_id)
    assert "/__readiness__/navigation?" in result["url"]
    assert "Results ready after navigation" in result["text"]
    assert server["submissions"] == server["completed"] == 1 and server["kinds"] == ["Document"]
    main_frame = native_browser.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
    assert native_browser._event_source.main_frame_id == main_frame
    save_proof(lab_manifest, request, {"wait": waited, "server_submissions": server,
                                    "main_frame": main_frame, "url": result["url"], "text": result["text"]})


def test_native_scroll_preserves_an_earlier_pending_request(native_browser, lab_manifest, request):
    import secrets

    trial_id = "scroll-" + secrets.token_hex(8)
    navigate_fixture(native_browser, lab_manifest["fixture_url"] +
                     "/readiness.html?scroll=1&delay=2&trial_id=" + trial_id)
    readiness_action(native_browser)
    page = native_browser.observe(screenshot=False)
    before_scroll = set(native_browser.loading)
    assert before_scroll, "The initial real Fetch request must be in flight before scrolling"
    scroll = next(action for action in page["actions"] if action["id"] == "scroll_down")
    native_browser.act(scroll, page)
    after_scroll = set(native_browser.loading)
    assert before_scroll <= after_scroll
    waited = native_browser.wait_for_loading()
    assert waited[0] > 0 and waited[1:] == [False, False]
    actual = native_browser.evaluate("({fixture:window.fixture,scrollY})")
    server = readiness_submission_count(lab_manifest, trial_id)
    assert actual["scrollY"] > 0 and actual["fixture"]["status"] == "ready"
    assert actual["fixture"]["inputCount"] == server["submissions"] == 1
    save_proof(lab_manifest, request, {"requests_before_scroll": sorted(before_scroll),
        "requests_after_scroll": sorted(after_scroll), "wait": waited,
        "server_submissions": server, "independent_fixture": actual})
