"""Snapshot schema 2 through browser.py's own CDP calls into production snapshot.js on a Node page. Never a model."""

import hashlib
import json
import queue
import subprocess
import threading
import time
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from jev_ultrafast import agent as loop
from jev_ultrafast import browser, demo, mcp_server, model
from jev_ultrafast.browser import SnapshotTooLarge, StalePage
from jev_ultrafast.contracts import RunStopped, operation_for
from scripts import report_runs

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# The schema-1 snapshot, frozen from c8a467c (sha256 1103ab58…, the SELECT-stage checkpoint).
SCHEMA1 = (FIXTURES / "snapshot_schema1.js").read_text()
TARGETS = {"click", "fill", "select"}
OPERATIONS = ["CLICK", "TYPE_TEXT", "SELECT", "SCROLL_UP", "SCROLL_DOWN", "WAIT"]
# One label of 300,000 UTF-8 bytes: no observation of the page fits the ceiling, and none may truncate it.
OVERSIZE = "dom.controls[0].childNodes[0].textContent='€'.repeat(100000)"
RESTORE = "dom.controls[0].childNodes[0].textContent='Control 1'"


class NodePage:
    """One fake page in Node: every Runtime.evaluate runs browser.py's exact expression there. Records each call."""

    def __init__(self, **config):
        self.calls, self.reply_bytes = [], []
        self.process = subprocess.Popen(
            ["node", str(FIXTURES / "page_bridge.cjs"), str(FIXTURES / "dense_dom.cjs"), json.dumps(config)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8",
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def reply(self, expression):
        self.process.stdin.write(json.dumps({"expression": expression}) + "\n")
        self.process.stdin.flush()
        line = self.lines.get(timeout=60)
        assert line is not None, "the Node page exited"
        reply = json.loads(line)
        if "value" in reply:  # the exact UTF-8 bytes of JSON.stringify(value), as the page measures them
            self.reply_bytes.append(len(line.encode()) - len('{"value":}\n'))
        return reply

    def evaluate(self, expression):
        reply = self.reply(expression)
        assert "exception" not in reply, reply.get("exception")
        return reply.get("value")

    def cdp(self, method, session_id=None, **params):
        params.pop("_response_timeout", None)
        self.calls.append((method, params))
        if method == "Runtime.evaluate":
            reply = self.reply(params["expression"])
            if "exception" in reply:
                return {"exceptionDetails": {"text": reply["exception"]}}
            return {"result": {"value": reply["value"]} if "value" in reply else {}}
        if method == "Page.captureScreenshot":
            return {"data": "eA=="}
        return {}

    def inputs(self):
        return [params for method, params in self.calls if method.startswith("Input.")]

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)


@pytest.fixture
def open_page(monkeypatch):
    opened = []

    def open_page(**config):
        page = NodePage(**config)
        opened.append(page)
        monkeypatch.setattr(browser, "cdp", page.cdp)
        tab = browser.Browser.__new__(browser.Browser)
        tab.session, tab.target = "node-session", "node-target"
        return page, tab

    yield open_page
    for page in opened:
        page.close()


def target(page, label):
    return next(a for a in page["actions"] if a["kind"] in TARGETS and a["label"] == label)


def option(page, index=2):
    """The second of two options both labeled Same."""
    return next(a for a in page["actions"] if a.get("option", {}).get("observed_index") == index)


def baseline(page):
    """What the page's baseline holds: generation, token, exact semantics, guards and retained node IDs."""
    return page.evaluate("(() => {const c=window.__jevFast, b=c?.baseline; return b ? {generation:c.generation,"
                         "token:b.token,global:b.global,pageKey:b.pageKey,guards:[...b.guards],scopes:b.scopes,"
                         "offered:[...b.offered],nodes:[...c.nodes.keys()]} : null})()")


def decision(page, choice):
    """A scripted decision, shaped as choose() returns one, for an observed action ID, DONE or BLOCKED."""
    if choice in {"DONE", "BLOCKED"}:
        operation, head = choice, None
    else:
        action = next(a for a in page["actions"] if a["id"] == choice)
        operation = operation_for(action)
        _, targets, _ = model.action_space(page["actions"])
        head = next((key for key, value in targets.get(operation, {}).items() if value is action), None)
    return {
        "choice": choice, "operation": operation, "target": head, "confidence": 1, "probabilities": {choice: 1},
        "target_probabilities": {head: 1} if head else {}, "target_confidence": 1 if head else None,
        "operation_probabilities": {operation: 1}, "commit_probability": 0, "latency_ms": 1, "usage": {},
        "model": "scripted",
    }


def schema1_fingerprint(state):
    """The progress function before schema 2, verbatim (snapshot-preparation.json)."""
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    content["actions"] = [
        {**action, "option": {key: value for key, value in action["option"].items()
                              if key not in {"document_id", "cache_epoch"}}} if "option" in action else action
        for action in state["actions"]
    ]
    if state.get("evidence"):
        content["evidence"] = state["evidence"]
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def test_freshness_does_not_replace_baseline(open_page):
    page, tab = open_page(n=3, field=True, select=True)
    observed = tab.observe(screenshot=False)
    click, second = target(observed, "Control 1"), option(observed)
    before = baseline(page)
    assert before["token"] == observed["observation_token"]
    # A is observed; B changes a form value. Every check against A is false however often it is asked.
    page.evaluate("dom.field.value='new'")
    for _ in range(2):
        assert tab.fresh(observed) is False
        assert tab.fresh(observed, click) is False
        with pytest.raises(StalePage, match="page context"):
            tab.act(second, observed)
    assert baseline(page) == before and page.evaluate("dom.events") == []
    # Back to A: the same token is fresh again, so no check replaced the baseline with B.
    page.evaluate("dom.field.value='old'")
    assert tab.fresh(observed) is True and tab.fresh(observed, click) is True
    # The click's own scope text changes: its guard and the global check both see it, twice.
    original = page.evaluate("dom.form.text")
    page.evaluate("dom.texts[0].textContent=dom.form.text='Changed context'")
    for _ in range(2):
        assert tab.fresh(observed, click) is False
        assert tab.fresh(observed) is False
    page.evaluate(f"dom.texts[0].textContent=dom.form.text={json.dumps(original)}")
    # A node that appears during a check gets a weak ID only, never a retained reference.
    page.evaluate("dom.added=new dom.Element('BUTTON',{type:'submit',value:'',parentElement:dom.form,"
                  "rect:{x:900,y:30,width:50,height:20}});dom.candidates.push(dom.added)")
    assert tab.fresh(observed) is False
    assert page.evaluate("[__jevFast.ids.has(dom.added),[...__jevFast.nodes.values()].includes(dom.added)]") == [
        True, False]
    page.evaluate("dom.candidates.pop()")
    assert tab.fresh(observed) is True and baseline(page) == before
    # The SELECT every stale check refused now runs on the unchanged baseline: one input/change pair.
    assert tab.act(second, observed) == {"executed": second["id"]}
    assert page.evaluate("[dom.select.selectedIndex,dom.events.map(e=>e.event)]") == [2, ["input", "change"]]


def test_progress_excludes_nested_protocol_identity(open_page):
    page, tab = open_page(n=3, field=True, select=True, multiple=True)
    first, second = tab.observe(screenshot=False), tab.observe(screenshot=False)
    # An unchanged page read twice: a new token, the old one stale, the same progress.
    assert first["observation_token"] != second["observation_token"]
    assert second["observation_token"]["generation"] == first["observation_token"]["generation"] + 1
    assert first["fingerprint"] == second["fingerprint"]
    assert tab.fresh(first) is False and tab.fresh(second) is True
    noisy = deepcopy(second)
    noisy.update(snapshot_schema=3, snapshot_stats={"candidates": 0}, observation_token={"schema": 3})
    for item in noisy["actions"] + noisy["evidence"]:
        item.update(observation_token={"epoch": "other", "generation": 9}, snapshot_stats={"references": 1})
        if "option" in item:
            item["option"].update(document_id=7.5, cache_epoch="other", snapshot_schema=1)
    noisy["scroll"]["document_id"] = 3.0
    assert browser.fingerprint(noisy) == second["fingerprint"]
    for change in (
        lambda p: p["actions"][0].update(label="Changed"), lambda p: p["scroll"].update(height=900),
        lambda p: p["evidence"][0]["selected_options"].pop(), lambda p: p.update(text="Changed"),
        lambda p: p["actions"][0]["rect"].update(x=1),
    ):
        changed = deepcopy(second)
        change(changed)
        assert browser.fingerprint(changed) != second["fingerprint"]
    # Schema 1's own read of the same document has the same progress under the old and the new function.
    legacy = page.evaluate("delete window.__jevFast;" + SCHEMA1)
    assert {"marker", "page_key", "guards"} <= set(legacy) and "observation_token" not in legacy
    assert any("cache_epoch" in a.get("option", {}) for a in legacy["actions"])
    assert browser.fingerprint(legacy) == schema1_fingerprint(legacy) == second["fingerprint"]


# mutation: (global freshness, CLICK freshness, progress changes)
PROJECTIONS = {
    "geometry within the viewport": ("dom.controls[0].rect={...dom.controls[0].rect,x:dom.controls[0].rect.x+3}",
                                     True, True, True),
    "scroll height": ("dom.document.documentElement.scrollHeight=4000", True, True, True),
    "offscreen form field": ("dom.offscreen.value='changed'", False, False, False),
    "omitted control": ("dom.controls.at(-1).childNodes[0].textContent='Renamed'", False, True, False),
    "title": ("dom.document.title='Renamed'", False, True, False),
    "multi-select selection": ("dom.multiple.options[2].selected=true", False, False, True),
}


@pytest.mark.parametrize("mutation", PROJECTIONS)
def test_progress_and_freshness_keep_distinct_projections(open_page, mutation):
    expression, global_fresh, click_fresh, progress = PROJECTIONS[mutation]
    # 3 options + fill and click + 255 buttons: the last 10 buttons are omitted; the context fills the text window.
    page, tab = open_page(n=255, scopeChars=6000, select=True, multiple=True, field=True, offscreen=True)
    observed = tab.observe(screenshot=False)
    assert observed["omitted_actions"] == 10
    assert "Control 255" not in observed["text"]
    click = target(observed, "Control 1")
    page.evaluate(expression)
    assert tab.fresh(observed) is global_fresh
    assert tab.fresh(observed, click) is click_fresh
    after = tab.observe(screenshot=False)
    assert (after["fingerprint"] != observed["fingerprint"]) is progress
    # A multi-select is evidence: never a SELECT target, and none of its options becomes a CLICK.
    interests = next(item for item in after["evidence"] if item["label"] == "Interests")
    assert not any(a.get("node") == interests["node"] for a in after["actions"])
    assert not any(a.get("role") == "option" for a in after["actions"])


STALE_TOKENS = ["re-observed", "cache reset", "identical-document navigation", "newer generation", "other epoch",
                "other document", "legacy schema", "no token"]


@pytest.mark.parametrize("change", STALE_TOKENS)
def test_old_tokens_reject_after_observe_reset_or_navigation(open_page, change):
    page, tab = open_page(n=3, field=True, select=True)
    observed = tab.observe(screenshot=False)
    stale, current = deepcopy(observed), None
    token = stale["observation_token"]
    if change == "re-observed":
        current = tab.observe(screenshot=False)
    elif change == "cache reset":
        page.evaluate("delete window.__jevFast")
        current = tab.observe(screenshot=False)
    elif change == "identical-document navigation":
        page.evaluate("performance.timeOrigin+=1;delete window.__jevFast")
        current = tab.observe(screenshot=False)
    elif change == "newer generation":
        token["generation"] += 1
    elif change == "other epoch":
        token["epoch"] += "-other"
    elif change == "other document":
        token["document_id"] += 1
    elif change == "legacy schema":
        stale["snapshot_schema"] = 1
    else:
        del stale["observation_token"]
    if current:
        # The same numeric IDs as before: only the token tells the two reads apart.
        assert [a.get("node") for a in current["actions"]] == [a.get("node") for a in stale["actions"]]
        assert tab.fresh(current) is True
    page.calls.clear()
    click, fill = target(stale, "Control 1"), target(stale, "Query")
    assert tab.fresh(stale) is False and tab.fresh(stale, click) is False
    for action in (click, fill, option(stale)):
        with pytest.raises(StalePage):
            tab.act(action, stale, text="new")
    assert page.inputs() == []
    if change in {"legacy schema", "no token"}:
        assert page.calls == []  # no browser call at all
    assert page.evaluate("[dom.select.selectedIndex,dom.events,dom.field.value]") == [0, [], "old"]


@pytest.mark.parametrize("labels", ["short", "long", "oversize"])
@pytest.mark.parametrize("scope", ["shared", "row"])
@pytest.mark.parametrize("n", [250, 1000, 5000])
def test_guard_work_and_transport_are_bounded(open_page, n, scope, labels):
    padding = {"short": 0, "long": 200, "oversize": 1000}[labels]
    page, tab = open_page(n=n, scope=scope, scopeChars=6000, labelChars=padding, multibyte=True)
    unique_scopes = 1 if scope == "shared" else 25  # 250 offered controls, ten per row
    if labels == "oversize":
        with pytest.raises(SnapshotTooLarge) as overflow:
            tab.observe(screenshot=False)
        assert overflow.value.code == "snapshot_too_large"
        details = overflow.value.details
        assert details["limit"] == browser.MAX_SNAPSHOT_BYTES
        assert details["characters"] > browser.MAX_SNAPSHOT_BYTES // 3
        assert details | {"limit": 0, "characters": 0} == {"limit": 0, "characters": 0, "candidates": n,
                                                            "omitted_actions": n - 250, "evidence": 0,
                                                            "text_characters": 6000}
        assert page.reply_bytes[-1] < 512  # counts only: no action, label or token crosses
        assert page.evaluate("dom.counters.scopeReads") == unique_scopes
        assert baseline(page) is None and page.evaluate("__jevFast.nodes.size") == 0
        return
    observed = tab.observe(screenshot=False)
    size = page.reply_bytes[-1]
    assert size <= browser.MAX_SNAPSHOT_BYTES
    targets = [a for a in observed["actions"] if a["kind"] in TARGETS]
    suffix = " " + "€" * padding if padding else ""
    # The first 250 in document order, with their full labels.
    assert [a["label"] for a in targets] == [f"Control {i + 1}{suffix}" for i in range(250)]
    assert observed["omitted_actions"] == n - 250
    assert observed["snapshot_stats"] == {"candidates": n, "guard_builds": 250, "scope_reads": unique_scopes,
                                          "references": 250}
    assert page.evaluate("dom.counters.scopeReads") == unique_scopes
    # A global check builds no guard; a CLICK check reads its one scope. Each answer is a boolean.
    page.evaluate("dom.counters.scopeReads=0")
    assert tab.fresh(observed) is True
    assert page.evaluate("dom.counters.scopeReads") == 0
    assert tab.fresh(observed, targets[-1]) is True
    assert page.evaluate("dom.counters.scopeReads") == 1
    assert page.reply_bytes[-4] == page.reply_bytes[-2] == len("true")


def test_strong_references_cover_only_offered_targets(open_page):
    page, tab = open_page(n=300, field=True, select=True, multiple=True, offscreen=True)
    observed = tab.observe(screenshot=False)
    targets = [a for a in observed["actions"] if a["kind"] in TARGETS]
    offered = {a["node"] for a in targets} | {a["option"]["option_id"] for a in targets if "option" in a}
    retained = set(page.evaluate("[...__jevFast.nodes.keys()]"))
    assert retained == offered and len(retained) <= 2 * browser.MAX_TARGETS
    assert observed["snapshot_stats"]["references"] == len(retained)
    # Omitted controls, the offscreen field and the multi-select have weak IDs and no retained reference.
    weak = page.evaluate("[dom.offscreen,dom.multiple,...dom.multiple.options.filter(o=>o.selected),"
                         "...dom.controls.slice(-5)].map(e=>__jevFast.ids.get(e))")
    assert all(isinstance(node, int) for node in weak) and not retained & set(weak)
    assert page.evaluate("[...__jevFast.nodes.values()].every(e=>dom.candidates.includes(e)||"
                         "dom.options.includes(e))")
    # Checks and targeting never add one.
    click = target(observed, "Control 1")
    assert tab.fresh(observed) is True and tab.fresh(observed, click) is True
    assert page.evaluate(f"{browser.TARGET}({json.dumps(observed['observation_token'])},{json.dumps(click)})")
    assert set(page.evaluate("[...__jevFast.nodes.keys()]")) == retained
    # An overflowing read drops every reference with the baseline: nothing from either read can execute.
    page.evaluate(OVERSIZE)
    with pytest.raises(SnapshotTooLarge):
        tab.observe(screenshot=False)
    assert page.evaluate("__jevFast.nodes.size") == 0 and baseline(page) is None


def scripted(monkeypatch, choices, before=None):
    """choose() without a model: each call answers the next choice; before(page) runs first. Returns the calls."""
    calls, pending = [], list(choices)

    def choose(page, goal, history, allowed_operations, *, check_stop, remaining_budget, on_response):
        calls.append(page["observation_token"])
        if before:
            before(page)
        return decision(page, pending.pop(0))

    monkeypatch.setattr(loop, "choose", choose)
    monkeypatch.setattr(loop, "field_text", Mock(return_value=("books", {"model": "fake", "latency_ms": 1})))
    return calls


def start(open_page, monkeypatch, tmp_path, **config):
    page, tab = open_page(n=3, field=True, select=True, **config)
    monkeypatch.setattr(loop, "Browser", lambda url: tab)
    agent = loop.Agent("http://fixture.test/dense", "Choose the second Same category", allowed_operations=OPERATIONS,
                       trace_path=tmp_path / "run.json")
    agent.state.update(source="a" * 64, notes_shown=[])
    return page, tab, agent


def assert_stopped(agent, page, calls_before):
    """Terminal: no decision or text pending; a later command makes no browser call and asks no model."""
    assert agent.state["status"] == "stopped" and agent.state["stop_code"] == "snapshot_too_large"
    assert agent.state["decision"] is None and agent.pending_text is None
    saved = json.loads(agent.trace_path.read_text())
    assert saved["status"] == "stopped" and saved["stop_code"] == "snapshot_too_large"
    count = len(page.calls)
    for command in ("tick", "predict", "act"):
        with pytest.raises(RunStopped):
            agent.command(command, {"fingerprint": agent.state["page"]["fingerprint"]})
    assert len(page.calls) == count
    assert page.inputs() == calls_before


def overflow_elsewhere(page):
    """Another reader's observation overflows, then the page shrinks back: the baseline it dropped stays gone."""
    page.evaluate(OVERSIZE)
    assert "snapshot_too_large" in page.evaluate(browser.READ_STATE)
    page.evaluate(RESTORE)


@pytest.mark.parametrize("stage", [
    "setup", "new goal, unfinished run", "new goal, finished run", "predict read", "predict freshness",
    "recovery read", "before CLICK input", "before SELECT input", "after one logged input", "MCP final read after DONE",
    "MCP final read after BLOCKED", "inspector",
])
def test_overflow_is_terminal_at_each_adapter(open_page, monkeypatch, tmp_path, capsys, stage):
    if stage == "setup":
        page, tab = open_page(n=3, field=True, labelChars=100000, multibyte=True)
        monkeypatch.setattr(loop, "Browser", lambda url: tab)
        calls = scripted(monkeypatch, [])
        with pytest.raises(SnapshotTooLarge):
            loop.Agent("http://fixture.test/dense", "Open it", allowed_operations=OPERATIONS,
                       trace_path=tmp_path / "run.json")
        assert page.calls[-1] == ("Target.closeTarget", {"targetId": "node-target"})  # the owned tab is closed
        assert calls == [] and page.inputs() == [] and not (tmp_path / "run.json").exists()
        return
    page, tab, agent = start(open_page, monkeypatch, tmp_path)
    observed = agent.state["page"]
    click, second = target(observed, "Control 1"), option(observed)
    if stage.startswith("new goal"):
        calls = scripted(monkeypatch, [])
        if stage == "new goal, finished run":
            agent.state.update(status="done")
        else:
            agent.state.update(status="predicted", decision=decision(observed, click["id"]))
            agent.pending_text = ("context", "books", {"model": "fake"})
        agent.save()
        before = agent.trace_path.read_bytes()
        page.evaluate(OVERSIZE)
        with pytest.raises(SnapshotTooLarge):
            agent.new_goal("Next goal", allowed_operations=OPERATIONS, trace_path=tmp_path / "next.json")
        assert not (tmp_path / "next.json").exists() and agent.trace_path == tmp_path / "run.json"
        assert agent.state["decision"] is None and agent.pending_text is None and calls == []
        if stage == "new goal, finished run":  # a finished run's file is never rewritten
            assert agent.state["status"] == "done" and agent.trace_path.read_bytes() == before
        else:
            assert_stopped(agent, page, [])
        return
    if stage == "predict read":
        calls = scripted(monkeypatch, [click["id"]])
        page.evaluate(OVERSIZE)
        with pytest.raises(SnapshotTooLarge):
            agent.command("predict")
        assert calls == [] and agent.state["page"] is observed
        assert_stopped(agent, page, [])
        return
    if stage == "predict freshness":
        calls = scripted(monkeypatch, [click["id"]])
        overflow_elsewhere(page)
        with pytest.raises(SnapshotTooLarge):
            agent.command("predict")
        assert calls == []
        assert_stopped(agent, page, [])
        return
    if stage == "recovery read":  # the page grows while Jev decides: the click is stale, and so is the recovery
        calls = scripted(monkeypatch, [click["id"]], before=lambda _page: page.evaluate(OVERSIZE))
        with pytest.raises(SnapshotTooLarge):
            agent.command("tick")
        assert len(calls) == 1 and agent.state["stale_recoveries"] == 1 and agent.state["history"] == []
        assert agent.state["attempt"] is None
        assert_stopped(agent, page, [])
        return
    if stage in {"before CLICK input", "before SELECT input"}:
        chosen = click if stage == "before CLICK input" else second
        calls = scripted(monkeypatch, [chosen["id"]])
        agent.command("predict")
        overflow_elsewhere(page)
        with pytest.raises(SnapshotTooLarge):
            agent.command("act", {"fingerprint": observed["fingerprint"]})
        assert len(calls) == 1 and agent.state["attempt"] is None and agent.state["history"] == []
        assert page.evaluate("[dom.select.selectedIndex,dom.events]") == [0, []]
        assert_stopped(agent, page, [])
        return
    if stage == "after one logged input":  # the click runs; the page it opens is too large to read
        calls = scripted(monkeypatch, [click["id"]])

        def grows_after_click(method, session_id=None, **params):
            result = page.cdp(method, session_id, **params)
            if method == "Input.dispatchMouseEvent" and params["type"] == "mouseReleased":
                page.evaluate(OVERSIZE)
            return result

        monkeypatch.setattr(browser, "cdp", grows_after_click)
        with pytest.raises(SnapshotTooLarge):
            agent.command("tick")
        inputs = page.inputs()
        assert [params["type"] for params in inputs] == ["mousePressed", "mouseReleased"]
        history = agent.state["history"]
        assert len(history) == 1 and history[0]["page_changed"] is None and agent.state["attempt"] is None
        assert json.loads(agent.trace_path.read_text())["history"] == history
        assert len(calls) == 1
        assert_stopped(agent, page, inputs)
        return
    if stage.startswith("MCP final read"):
        answer = "DONE" if stage.endswith("DONE") else "BLOCKED"
        scripted(monkeypatch, [answer])
        agent.command("tick")
        assert agent.state["status"] == answer.lower()
        monkeypatch.setattr(mcp_server, "notes_block", lambda _state: ("", []))
        monkeypatch.setattr(mcp_server, "RUNS", tmp_path)
        elapsed, final_read = [], tab.observe

        def slow_final_read(*args, **kwargs):  # the run's time, as finish() sets it, then a read that takes time
            elapsed.append(agent.state["elapsed_ms"])
            time.sleep(0.005)
            return final_read(*args, **kwargs)

        monkeypatch.setattr(tab, "observe", slow_final_read)
        page.evaluate(OVERSIZE)
        notes = [] if answer == "DONE" else ["Jev answered BLOCKED"]
        mcp_server.finish(agent, "run", notes)
        result = agent.state["result"]
        assert agent.state["final_read_fresh"] is False and agent.state["page"] is observed
        assert any(note.startswith("fresh read failed: The page's observation exceeds") for note in result["notes"])
        assert agent.state["elapsed_ms"] == elapsed[0] and agent.state["final_read_ms"] >= 5  # the read stays outside
        assert page.inputs() == []
        if answer == "DONE":  # a DONE its final read cannot verify is not reported as done
            assert result["status"] == agent.state["status"] == "stopped"
            assert agent.state["stop_code"] == "snapshot_too_large" and agent.state["failure"] is None
            offered = sum(a["kind"] in TARGETS for a in observed["actions"])
            assert agent.state["snapshot_overflow"]["candidates"] == offered
        else:  # a stop keeps its own code, so failure codes are unchanged
            assert result["status"] == agent.state["status"] == "blocked"
            assert agent.state["stop_code"] is None and agent.state["failure"] == "jev_blocked"
        assert "no screenshot: the fresh read failed" in result["text"]
        report_runs.main(["--runs", str(tmp_path), "--artifacts", str(tmp_path)])
        assert f"snapshot overflow stops {int(answer == 'DONE')}" in capsys.readouterr().out
        return
    assert stage == "inspector"
    calls = scripted(monkeypatch, [click["id"]])
    monkeypatch.setattr(demo, "AGENT", agent)
    page.evaluate(OVERSIZE)
    with pytest.raises(ValueError):  # the inspector's handler answers 400 with this message
        demo.command("tick", {})
    assert calls == [] and demo.response_state()["status"] == "stopped"
    assert_stopped(agent, page, [])


def test_legacy_snapshots_report_but_cannot_execute(open_page, monkeypatch, tmp_path, capsys):
    page, tab, agent = start(open_page, monkeypatch, tmp_path)
    legacy = page.evaluate(SCHEMA1)  # a schema-1 read of the same page: marker, page key and guards, no token
    legacy["fingerprint"] = browser.fingerprint(legacy)
    assert browser.observation_token(legacy) is None and "marker" in legacy
    # The browser never executes it: no check, no hit test, no input, not a single call.
    page.calls.clear()
    click, fill = target(legacy, "Control 1"), target(legacy, "Query")
    assert tab.fresh(legacy) is False and tab.fresh(legacy, click) is False
    for action in (click, fill, option(legacy)):
        with pytest.raises(StalePage, match="cannot be executed"):
            tab.act(action, legacy, text="new")
    assert page.calls == []
    # Neither does the agent holding one: the decision goes stale before input, as any stale read does.
    scripted(monkeypatch, [])
    agent.state.update(page=legacy, status="predicted", decision=decision(legacy, click["id"]))
    with pytest.raises(StalePage):
        agent.command("act", {"fingerprint": legacy["fingerprint"]})
    assert page.inputs() == [] and agent.state["history"] == [] and agent.state["attempt"] is None
    # Readers still report it: a run file written before schema 2 keeps its page as data.
    agent.state.update(status="done", page=legacy, result={"status": "done", "notes": [], "text": ""})
    agent.save()
    run = json.loads(agent.trace_path.read_text())
    assert run["page"]["marker"] == legacy["marker"]
    assert report_runs.facts(run)["status"] == "done"
    report_runs.main(["--runs", str(tmp_path), "--artifacts", str(tmp_path)])
    assert "runs 1, labeled 0" in capsys.readouterr().out
    monkeypatch.setattr(mcp_server.site_notes, "learning_on", lambda: False)
    text = mcp_server.render("run", "done", [], {**agent.state, "page": legacy}, fresh=False)
    assert "Control 1" in text and "no screenshot: the fresh read failed" in text
