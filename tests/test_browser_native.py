"""Real DOM and event proofs in the separately owned, fixture-only native lab. Never call a model."""

import http.client
import json
import re
import secrets
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import browser, mcp_server, model
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
            assert after["observation_token"]["epoch"] != page["observation_token"]["epoch"]
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
    native_nodes = native_browser.evaluate("""(() => {const cache=window.__jevFast,
      select=document.querySelector('#multiple');return {ids:[select,...select.options].map(e=>cache.ids.get(e))
      .filter(id=>id!==undefined),retained:[...cache.nodes.values()].some(e=>select.contains(e))}})()""")
    assert native_nodes["ids"] and native_nodes["retained"] is False
    assert not any(action.get("node") in native_nodes["ids"] for action in page["actions"])
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


# Snapshot schema 2 against the frozen schema-1 script (c8a467c), each in its own owned tab.
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCHEMA1 = (FIXTURES / "snapshot_schema1.js").read_text().strip()
SELECT1 = (FIXTURES / "select_schema1.js").read_text().strip()
MARKER1 = f"(() => {{ const state={SCHEMA1}; return state?.marker ?? null; }})()"


def scoped1(node):
    return f"(() => {{ const c=window.__jevFast; return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"


def load(instance, url):
    instance.call("Page.navigate", url=url)
    deadline = time.monotonic() + 10
    while True:
        try:
            if instance.evaluate("document.readyState") == "complete" and instance.evaluate("location.href") == url:
                return
        except browser.StalePage:
            pass
        assert time.monotonic() < deadline, "the fixture did not load"
        time.sleep(0.02)


@pytest.fixture
def tab_pair(lab_manifest):
    first, second = browser.Browser("about:blank"), browser.Browser("about:blank")
    try:
        yield first, second
    finally:
        first.close()
        second.close()


def labelled(page, label, kind="click"):
    return next(action for action in page["actions"] if action["label"] == label and action["kind"] == kind)


def second_same(page):
    return next(action for action in page["actions"]
                if action.get("option", {}).get("observed_index") == 2 and action["label"] == "Category → Same")


PARITY = {
    "unchanged": "",
    "geometry within the viewport": "document.querySelector('#go').style.marginLeft='40px'",
    "title": "document.title='Renamed'",
    "url": "history.replaceState(null,'','?changed')",
    "relevant scope text": "document.querySelector('#scope').textContent='Total $100'",
    "unrelated visible text": "document.querySelector('#unrelated').textContent='Weather: rain'",
    "offscreen form property": "document.querySelector('#offscreen').value='changed'",
    "omitted control": "document.querySelector('#grid').lastElementChild.setAttribute('aria-label','Renamed')",
    "scroll height": "document.querySelector('#spacer').style.height='5000px'",
    "duplicate labels reordered": "const rows=document.querySelector('#rows');rows.prepend(rows.lastElementChild)",
    "option value": "document.querySelector('#second').value='changed'",
    "option label": "document.querySelector('#second').label='Changed'",
    "option owner": "document.querySelector('#owner').append(document.querySelector('#second'))",
    "option order": "document.querySelector('#category').insertBefore(document.querySelector('#other'),"
                    "document.querySelector('#second'))",
    "option disabled": "document.querySelector('#second').disabled=true",
    "cache recreation": "delete window.__jevFast",
    "identical-document navigation": None,
}


def mutate(instance, url, mutation):
    if PARITY[mutation] is None:
        load(instance, url)  # a new document, identical to the old one: numeric IDs restart and repeat
    elif PARITY[mutation]:
        instance.evaluate("(() => {" + PARITY[mutation] + "})()")


def schema1_outcomes(instance, url, mutation):
    """Schema 1's own checks, as browser.py ran them at c8a467c: the CLICK guards first, read-only; then the global
    marker, which re-runs the whole snapshot; then the SELECT, which mutates."""
    load(instance, url)
    page = instance.evaluate(SCHEMA1)
    go, book, option = labelled(page, "Continue"), labelled(page, "Book"), second_same(page)
    mutate(instance, url, mutation)
    outcome = {}
    for name, action in (("click", go), ("click in a row", book)):
        node = action["node"]
        outcome[name] = instance.evaluate(scoped1(node)) == [page["page_key"], page["guards"].get(str(node))]
    outcome["global"] = instance.evaluate(MARKER1) == page["marker"]
    payload = {"action": option, "page_key": page["page_key"], "guard": page["guards"].get(str(option["node"]))}
    try:
        result = instance.evaluate(f"{SELECT1}({json.dumps(payload)})")
    except browser.StalePage:
        result = None
    outcome["select"] = result == {"status": "executed", "action_id": option["id"]}
    return outcome


def schema2_outcomes(instance, url, mutation):
    load(instance, url)
    page = instance.observe(screenshot=False)
    go, book, option = labelled(page, "Continue"), labelled(page, "Book"), second_same(page)
    mutate(instance, url, mutation)
    outcome = {"click": instance.fresh(page, go), "click in a row": instance.fresh(page, book),
               "global": instance.fresh(page)}
    try:
        outcome["select"] = instance.act(option, page) == {"executed": option["id"]}
    except browser.StalePage:
        outcome["select"] = False
    return outcome


def progress(instance, url, mutation, read):
    """A fresh document's fingerprint under one schema, and whether the mutation changes it."""
    load(instance, url)
    before = read()
    mutate(instance, url, mutation)
    return before, read() != before


def test_snapshot_freshness_parity(tab_pair, lab_manifest, request):
    """Every change schema 1 rejected, schema 2 rejects too, scoped and global checks compared separately; SELECT
    identity only adds rejections. What schema 1 accepted for a CLICK stays accepted where the guard is unchanged.
    Both schemas offer the same actions, so the same fingerprint, and count the same changes as progress."""
    url = lab_manifest["fixture_url"] + "/snapshot_parity.html"
    first, second = tab_pair
    results = {}
    for mutation in PARITY:
        baseline, candidate = schema1_outcomes(first, url, mutation), schema2_outcomes(second, url, mutation)
        results[mutation] = {"schema 1": baseline, "schema 2": candidate}
        for check in ("click", "click in a row", "global", "select"):
            assert baseline[check] or not candidate[check], (mutation, check, baseline, candidate)
        old = progress(first, url, mutation, lambda: browser.fingerprint(first.evaluate(SCHEMA1)))
        new = progress(second, url, mutation, lambda: second.observe(screenshot=False)["fingerprint"])
        assert old == new, mutation
        results[mutation]["progress"] = new[1]
    for mutation in ("geometry within the viewport", "scroll height"):
        assert results[mutation]["progress"], mutation
    for mutation in ("unchanged", "title", "offscreen form property", "omitted control"):
        assert not results[mutation]["progress"], mutation
    accepted = {"unchanged", "geometry within the viewport", "unrelated visible text", "omitted control", "title",
                "scroll height", "duplicate labels reordered"}
    for mutation in accepted:
        assert results[mutation]["schema 2"]["click"] and results[mutation]["schema 1"]["click"], mutation
    for mutation in ("unchanged", "geometry within the viewport", "scroll height"):
        assert all(results[mutation]["schema 2"].values()), mutation
    for mutation in set(PARITY) - {"unchanged", "geometry within the viewport", "scroll height"}:
        assert not results[mutation]["schema 2"]["global"], mutation
    assert results["duplicate labels reordered"]["schema 2"]["click in a row"]
    save_proof(lab_manifest, request, results)


IN_PAGE = """(() => {{
  const described=Object.getOwnPropertyDescriptor(HTMLElement.prototype,'innerText'); let reads=0;
  Object.defineProperty(HTMLElement.prototype,'innerText',
    {{...described,get(){{reads++;return described.get.call(this)}}}});
  try {{
    const started=performance.now(), result={expression}, scanned=performance.now()-started;
    const text=JSON.stringify(result), measured=performance.now()-started;
    return {{scan_ms:scanned, scan_and_serialize_ms:measured, bytes:new TextEncoder().encode(text).length,
      scope_reads:reads, stats:result?.snapshot_stats ?? null, overflow:result?.snapshot_too_large ?? null,
      guards:result?.guards ? Object.keys(result.guards).length : null,
      references:window.__jevFast?.nodes?.size ?? null, omitted:result?.omitted_actions ?? null}};
  }} finally {{ Object.defineProperty(HTMLElement.prototype,'innerText',described); }}
}})()"""


def sample(instance, expression, end_to_end):
    """One in-page measurement, then one end-to-end read over CDP; every attempt is kept, failures included."""
    record = {}
    try:
        record["in_page"] = instance.evaluate(IN_PAGE.format(expression=expression))
    except Exception as error:  # a measurement that fails is still a sample
        record["in_page_error"] = type(error).__name__
    started = time.perf_counter()
    try:
        end_to_end()
        record["end_to_end_ms"] = round((time.perf_counter() - started) * 1000, 3)
    except Exception as error:
        record["end_to_end_error"] = type(error).__name__
        record["end_to_end_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return record


def idle(instance):
    """Wait, outside any timing, until a tab has finished its earlier script: a sample that timed out keeps running
    in the page, and would slow the next sample in either tab."""
    instance.call("Runtime.evaluate", expression="0", returnByValue=True, _response_timeout=60)


def schema1_guards(instance):
    """Schema 1's guard count on this page, read once without the 5 s limit a timed sample has."""
    expression = f"(() => {{ const state={SCHEMA1}; return Object.keys(state.guards).length; }})()"
    return instance.call("Runtime.evaluate", expression=expression, returnByValue=True,
                         _response_timeout=60)["result"]["value"]


def distribution(values):
    values = sorted(values)
    if not values:
        return None
    p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
    return {"count": len(values), "min": values[0], "median": values[len(values) // 2] if len(values) % 2 else
            (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2, "p95": p95, "max": values[-1]}


def test_snapshot_payload_and_progress_contracts(tab_pair, lab_manifest, request):
    """Dense canonical pages return full capped evidence below the ceiling with bounded guard work, measured against
    schema 1 in its own tab (3 warmups, then 10 alternating samples, every attempt kept); an oversized label stops;
    rereads keep progress, a taller page changes it; CDP returns the offered action JSON exactly."""
    first, second = tab_pair
    base = lab_manifest["fixture_url"] + "/snapshot_dense.html"
    proof = {"samples": {}, "summary": {}}
    for n in (250, 1000, 5000):
        url = f"{base}?n={n}"
        load(first, url)
        load(second, url)
        page = second.observe(screenshot=False)
        targets = [action for action in page["actions"] if action["kind"] in {"click", "fill", "select"}]
        assert [action["label"] for action in targets] == [f"Control {i + 1}" for i in range(250)]
        assert page["omitted_actions"] == n - 250 and page["snapshot_stats"] == {
            "candidates": n, "guard_builds": 250, "scope_reads": 1, "references": 250}
        rows = []
        for number in range(13):
            for schema in (("schema 1", "schema 2") if number % 2 else ("schema 2", "schema 1")):
                if schema == "schema 1":
                    rows.append({"schema": schema, "warmup": number < 3,
                                 **sample(first, SCHEMA1, lambda: first.evaluate(SCHEMA1))})
                    idle(first)
                else:
                    rows.append({"schema": schema, "warmup": number < 3,
                                 **sample(second, browser.READ_STATE, lambda: second.observe(screenshot=False))})
                    idle(second)
        proof["samples"][n] = rows
        summary = {}
        for schema in ("schema 1", "schema 2"):
            measured = [row for row in rows if row["schema"] == schema and not row["warmup"]]
            pages = [row["in_page"] for row in measured if "in_page" in row]
            summary[schema] = {
                "bytes": distribution([item["bytes"] for item in pages]),
                "scan_ms": distribution([item["scan_ms"] for item in pages]),
                "scan_and_serialize_ms": distribution([item["scan_and_serialize_ms"] for item in pages]),
                "end_to_end_ms": distribution([row["end_to_end_ms"] for row in measured
                                               if "end_to_end_error" not in row]),
                "end_to_end_errors": sorted({row["end_to_end_error"] for row in measured if "end_to_end_error" in row}),
                "scope_reads": sorted({item["scope_reads"] for item in pages}),
                "guards": sorted({item["guards"] if schema == "schema 1" else item["stats"]["guard_builds"]
                                  for item in pages}),
                "references": sorted({item["references"] for item in pages}),
            }
        summary["schema 1"]["guards_untimed"] = schema1_guards(first)
        proof["summary"][n] = summary
        candidate = summary["schema 2"]
        assert candidate["bytes"]["max"] <= browser.MAX_SNAPSHOT_BYTES and not candidate["end_to_end_errors"]
        assert candidate["scope_reads"] == [1] and candidate["guards"] == [250] and candidate["references"] == [250]
        # Schema 1 built a guard for every candidate; at 5,000 its timed samples can all outlast the 5 s read.
        assert summary["schema 1"]["guards_untimed"] == n and set(summary["schema 1"]["guards"]) <= {n}
    # Ten controls per row and long multibyte labels: still below the ceiling, one read per offered row.
    load(second, f"{base}?n=1000&scope=row&pad=200")
    page = second.observe(screenshot=False)
    assert page["snapshot_stats"] == {"candidates": 1000, "guard_builds": 250, "scope_reads": 25, "references": 250}
    assert labelled(page, "Control 1 " + "€" * 200)
    # A label no read can carry whole stops the run: counts only, nothing truncated, nothing left to execute.
    load(second, f"{base}?n=250&pad=1000")
    with pytest.raises(browser.SnapshotTooLarge) as overflow:
        second.observe(screenshot=False)
    assert overflow.value.details["candidates"] == 250 and overflow.value.details["characters"] > 250_000
    assert second.evaluate("[window.__jevFast.baseline, window.__jevFast.nodes.size]") == [None, 0]
    # Progress: an unchanged reread keeps it under a new token; a taller page changes it.
    load(second, f"{base}?n=250")
    read, reread = second.observe(screenshot=False), second.observe(screenshot=False)
    assert read["fingerprint"] == reread["fingerprint"] and read["observation_token"] != reread["observation_token"]
    second.evaluate("document.querySelector('#spacer').style.height='3000px'")
    assert second.observe(screenshot=False)["fingerprint"] != reread["fingerprint"]
    # CDP hands back each offered action exactly, a lone surrogate in a label included: the click still runs.
    second.evaluate("document.querySelector('button').textContent='Lone \\ud800 surrogate'")
    page = second.observe(screenshot=False)
    lone = next(action for action in page["actions"] if action["label"].startswith("Lone"))
    proof["lone_surrogate_label"] = lone["label"].encode("utf-8", "surrogatepass").hex()
    assert second.act(lone, page) == {"executed": lone["id"]} and second.evaluate("window.clicks") == 1
    save_proof(lab_manifest, request, proof)


# Page readiness (docs/robustness-efficiency/status.md §4.3): the loading wait on the tab's own event source and the
# reread of a timed-out read after a step, in real Chromium. A scripted Jev; the fixture server and the page count
# every input independently of the run's own record.
BUSY_MS = 7000  # docs/executor-improvements.md H5: a synthetic page that stays busy past the 5 s read


def submissions(manifest, key):
    """The submissions the fixture server received for this key: evidence outside the browser and the run."""
    connection = http.client.HTTPConnection("127.0.0.1", manifest["fixture_port"], timeout=5)
    try:
        connection.request("GET", f"/__lab__/count?key={key}")
        return json.loads(connection.getresponse().read())["count"]
    finally:
        connection.close()


def scripted_jev(monkeypatch, answers):
    """choose() without a model: each answer is an observed button's label (a CLICK), DONE or BLOCKED."""
    pending = list(answers)

    def choose(page, goal, history, allowed_operations, *, check_stop, remaining_budget, on_response):
        answer = pending.pop(0)
        common = {"confidence": 1, "commit_probability": 0, "latency_ms": 1, "usage": {}, "model": "scripted"}
        if answer in {"DONE", "BLOCKED"}:
            return {"choice": answer, "operation": answer, "target": None, "probabilities": {answer: 1}, **common}
        action = next(a for a in page["actions"] if a["kind"] == "click" and a["label"] == answer)
        _, targets, _ = model.action_space(page["actions"])
        head = next(key for key, value in targets["CLICK"].items() if value is action)
        return {"choice": action["id"], "operation": "CLICK", "target": head, "probabilities": {action["id"]: 1},
                **common}

    monkeypatch.setattr(loop, "choose", choose)
    monkeypatch.setattr(loop, "field_text", Mock(side_effect=AssertionError("no text is generated")))
    return pending


@pytest.fixture
def server_run(lab_manifest, monkeypatch, tmp_path):
    """mcp_server.start_run, the server's own loop and final read, in the lab with a scripted Jev. Returns the reply,
    the saved run file and the page's own click counters; the tab is closed afterwards."""
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr(mcp_server, "RUNS", runs)
    monkeypatch.setattr(mcp_server, "notes_block", lambda _state: ("", []))
    monkeypatch.setattr(mcp_server.anyio.from_thread, "check_cancelled", lambda: None)

    def run(url, answers):
        pending = scripted_jev(monkeypatch, answers)
        text = mcp_server.start_run("Find the results", url, ["CLICK", "WAIT"], None, False)[0]
        [saved] = runs.glob("*.json")  # one run per test
        clicks = mcp_server.AGENT.browser.evaluate("window.clicks")
        assert pending == []  # every scripted answer was asked for, and no more
        return text, json.loads(saved.read_text()), clicks, mcp_server.AGENT

    try:
        yield run
    finally:
        mcp_server.close_browser()


def readiness_url(manifest, key, **params):
    query = "&".join(f"{name}={value}" for name, value in {"key": key, **params}.items())
    return f"{manifest['fixture_url']}/readiness.html?{query}"


def test_busy_page_and_loading_gate_compose_without_repeated_input(server_run, lab_manifest, request):
    """READINESS-3 in real Chromium: a 7 s busy results page times out the read after the Search, which is read again
    without repeating the input; then Jev answers DONE while the details it asked for still load, the wait sees them
    arrive, the stale DONE is dropped and the one on the loaded page stands. The fixture server counts one submission,
    the page one click per button, and the server's separately timed final read shows the details."""
    key = "compose-" + secrets.token_hex(4)
    text, run, clicks, agent = server_run(readiness_url(lab_manifest, key, busy=BUSY_MS),
                                          ["Search", "Load details", "DONE", "DONE"])
    assert run["status"] == "done" and run["stop_code"] is None and " · done · " in text
    assert submissions(lab_manifest, key) == 1 and clicks == {"search": 1, "details": 1}
    assert [step["action"] for step in run["history"]] == ["Search", "Load details"]
    # The repeated read shows the Search's results; the details had not arrived when their click was read.
    assert [step["page_changed"] for step in run["history"]] == [True, False]
    assert run["repeated_reads"] == 1  # the Search's read timed out once and was read again
    [loaded, settled] = run["loading_waits"]
    assert 500 <= loaded[0] <= 3000 and loaded[1:] == [False, False]  # the DONE waited for the details request
    assert settled[0] < 500 and settled[1:] == [False, False]
    assert run["stale_recoveries"] == 1 and run["stale_decisions"] == 1  # the DONE made before they loaded
    assert [decision["choice"] for decision in run["decisions"]][2:] == ["DONE", "DONE"]  # each asked once
    assert run["final_read_fresh"] is True and run["final_read_ms"] >= 0
    assert f"Details loaded for {key}" in run["page"]["text"]
    source = agent.browser.events  # the wait followed the tab's own observer session, never the daemon's
    assert source.session not in {None, agent.browser.session} and not source.connection.closed.is_set()
    save_proof(lab_manifest, request, {key: run[key] for key in (
        "status", "stop_code", "repeated_reads", "loading_waits", "stale_recoveries", "stale_decisions",
        "final_read_ms", "final_read_fresh", "elapsed_ms")} | {"submissions": 1, "clicks": clicks})


@pytest.mark.parametrize("trial", [1, 2, 3, 4, 5, "dialog"])
def test_busy_page_reads_again_without_repeating_the_input(server_run, lab_manifest, request, trial):
    """docs/executor-improvements.md §2's local acceptance (H5): on a page busy 7 s after the Search, five runs each
    end done with the input once, one submission and one repeated read. A dialog opened after the input blocks every
    read: two repeats, then the run stops with the dialog dismissed, the step recorded once and never repeated."""
    key = f"busy-{trial}-" + secrets.token_hex(4)
    if trial == "dialog":
        text, run, clicks, _agent = server_run(readiness_url(lab_manifest, key), ["Alert"])
        assert run["status"] == "stopped" and run["stop_code"] == "execution_error"
        assert "the page showed a dialog; dismissed" in run["result"]["notes"]
        assert run["repeated_reads"] == 2 and clicks == {"alert": 1}
        assert len(run["history"]) == 1 and run["history"][0]["page_changed"] is None
    else:
        text, run, clicks, _agent = server_run(readiness_url(lab_manifest, key, busy=BUSY_MS), ["Search", "DONE"])
        assert run["status"] == "done" and run["repeated_reads"] == 1
        assert submissions(lab_manifest, key) == 1 and clicks == {"search": 1}
        assert len(run["history"]) == 1 and run["history"][0]["page_changed"] is True
        assert f"Results for {key}" in run["page"]["text"]
    save_proof(lab_manifest, request, {"trial": trial, "status": run["status"], "stop_code": run["stop_code"],
                                       "repeated_reads": run["repeated_reads"], "clicks": clicks,
                                       "notes": run["result"]["notes"], "elapsed_ms": run["elapsed_ms"]})


def press(tab, label):
    page = tab.observe(screenshot=False)
    tab.act(next(a for a in page["actions"] if a["kind"] == "click" and a["label"] == label), page)


def until(condition, seconds=3):
    deadline = time.monotonic() + seconds
    while not (result := condition()):
        assert time.monotonic() < deadline, "the condition never held"
        time.sleep(0.02)
    return result


@pytest.fixture
def readiness_tab(lab_manifest):
    """A real Browser on the readiness fixture; every event its own source hands over is kept, with its time."""
    opened = []

    def open_tab():
        tab = browser.Browser(readiness_url(lab_manifest, "gate-" + secrets.token_hex(4),
                                            frame=lab_manifest["frame_url"]))
        opened.append(tab)
        tab.seen = []
        return tab

    def watch(tab):
        source, real = tab.events, tab.events.read

        def read():
            batch, overflow = real()
            tab.seen.extend(batch)
            return batch, overflow

        source.read = read

    open_tab.watch = watch
    try:
        yield open_tab
    finally:
        for tab in opened:
            tab.close()


def tracked(tab, kind="Fetch"):
    """Drain as a read does until a request of this kind is in flight, as it is when Jev answers after a read."""
    def seen():
        tab._track()
        return any(event[2] == kind and event[0] == "Network.requestWillBeSent" and event[1] in tab.loading
                   for event in tab.seen)

    return until(seen)


def status_text(tab):
    return tab.evaluate("document.querySelector('#status').textContent")


def test_loading_gate_follows_this_tabs_content_requests(readiness_tab, lab_manifest, request):
    """docs/executor-improvements.md §4's local acceptance on the tab's own event source: an answer before the
    request does not wait; one while it loads waits until the page shows it, uncapped; a request that never ends
    caps 5 s after the input; a cross-site iframe's document (a real separate target) does not hold the wait; a
    main-frame navigation does; a scroll during an earlier request keeps it. Each checked against the page itself."""
    proof = {}
    tab = readiness_tab()
    press(tab, "Start later")  # the first input opens the tab's own source, Network acknowledged before it ran
    assert tab.events.session not in {None, tab.session} and tab.network
    readiness_tab.watch(tab)
    proof["before the request"] = tab.wait_for_loading()
    assert proof["before the request"] == [0, False, False]  # no minimum wait: nothing was loading yet
    until(lambda: status_text(tab) == "Later loaded")  # its request did follow, after the answer

    tab = readiness_tab()
    press(tab, "Slow request")
    readiness_tab.watch(tab)
    tracked(tab)
    proof["while it loads"] = waited = tab.wait_for_loading()
    assert 800 <= waited[0] <= 2500 and waited[1:] == [False, False] and status_text(tab) == "Slow loaded"

    tab = readiness_tab()
    press(tab, "Poll forever")
    readiness_tab.watch(tab)
    tracked(tab)
    proof["never ends"] = waited = tab.wait_for_loading()
    assert waited[1] is True and time.monotonic() - tab.input_done >= browser.LOADING_CAP_SECONDS
    assert status_text(tab) == "Ready"  # capped, not loaded

    tab = readiness_tab()
    press(tab, "Open frame")
    readiness_tab.watch(tab)
    frames = until(lambda: [t for t in browser.cdp("Target.getTargets")["targetInfos"] if t["type"] == "iframe"
                            and t.get("parentFrameId") == tab.target], seconds=5)
    assert frames[0]["url"].startswith(lab_manifest["frame_url"])  # a real out-of-process iframe target
    until(lambda: tab._track() or any(event[2] == "Document" for event in tab.seen))
    [document] = [event for event in tab.seen if event[2] == "Document"]
    assert document[3] == frames[0]["targetId"] != tab.target  # seen here, as the iframe's own frame
    proof["cross-site iframe"] = waited = tab.wait_for_loading()
    assert waited[0] < 300 and waited[1:] == [False, False] and not tab.loading

    tab = readiness_tab()
    press(tab, "Navigate")
    readiness_tab.watch(tab)
    tracked(tab, "Document")
    [navigation] = [event for event in tab.seen if event[2] == "Document"]
    assert navigation[3] == tab.target  # the main frame's id is the tab's target id
    proof["main-frame navigation"] = waited = tab.wait_for_loading()
    assert 400 <= waited[0] <= 2500 and waited[1:] == [False, False]
    assert until(lambda: tab.evaluate("location.pathname") == "/delay")

    tab = readiness_tab()
    press(tab, "Slow request")
    readiness_tab.watch(tab)
    tracked(tab)
    time.sleep(0.3)
    page = tab.observe(screenshot=False)
    tab.act(next(a for a in page["actions"] if a["kind"] == "scroll"), page)  # another input, during the request
    proof["scroll during an earlier request"] = waited = tab.wait_for_loading()
    assert 500 <= waited[0] <= 2000 and waited[1:] == [False, False] and status_text(tab) == "Slow loaded"
    save_proof(lab_manifest, request, proof)

