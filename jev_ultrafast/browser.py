"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from browser_harness import _ipc as ipc
from browser_harness.admin import NAME, daemon_browser_kind, ensure_daemon, restart_daemon
from browser_harness.helpers import cdp

from .contracts import RunStopped

# Snapshot schema 2 (docs/robustness-efficiency/status.md §4.2): the page keeps the latest observation's exact
# baseline behind a small token. observe() alone replaces it; fresh(), target() and select() only read it.
LIBRARY = Path(__file__).with_name("snapshot.js").read_text().strip()
READ_STATE = f"({LIBRARY}).observe()"
FRESH = f"({LIBRARY}).fresh"  # FRESH(token, action): read-only comparison with that read's baseline
TARGET = f"({LIBRARY}).target"  # TARGET(token, action): an offered CLICK/fill node's geometry and hit test
# One synchronous browser task owns both validation and mutation. No await, retry, or value-based fallback.
SELECT_ACTION = f"({LIBRARY}).select"
SNAPSHOT_SCHEMA = 2
MAX_SNAPSHOT_BYTES = 262_144
MAX_TARGETS = 250
TOKEN_KEYS = frozenset({"schema", "epoch", "generation", "document_id"})
# Protocol identity, never progress: excluded from fingerprint() wherever it is nested.
PROTOCOL_KEYS = frozenset({"observation_token", "snapshot_schema", "snapshot_stats", "document_id", "cache_epoch"})
OVERFLOW_COUNTS = ("limit", "characters", "candidates", "omitted_actions", "evidence", "text_characters")
# lsof lives in /usr/sbin on macOS, which a minimal PATH leaves out.
LSOF = shutil.which("lsof", path="/usr/sbin:/usr/bin:/sbin:/bin")

def foreign_browser_port():
    """The local port jev's browser daemon uses when no process of this account listens on it, else None.

    With remote debugging off in this account's Chrome, browser-harness probes 127.0.0.1:9222 and 9223, which on a
    shared Mac can be another account's Chrome, with its logins. A daemon started with BU_CDP_URL or BU_CDP_WS reports
    kind "cdp": its browser was named on purpose. The live daemon decides, not this process's environment.
    """
    if daemon_browser_kind() == "cdp":
        return None
    daemon = ipc.identify(NAME)
    if not LSOF or not daemon:
        return None  # ponytail: no lsof, or no daemon yet, means nothing to check; the account boundary goes unchecked
    uid = str(os.getuid())
    lsof = lambda *args: subprocess.run(  # noqa: E731
        [LSOF, "-a", "-nP", *args], capture_output=True, text=True, timeout=5, check=False
    ).stdout
    connections = lsof("-p", str(daemon), "-iTCP", "-sTCP:ESTABLISHED", "-Fn")
    for port in re.findall(r"->(?:127\.0\.0\.1|\[::1\]):(\d+)", connections):
        if not lsof("-u", uid, f"-iTCP:{port}", "-sTCP:LISTEN", "-t").strip():
            return port
    return None


class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class UncertainAction(RuntimeError):
    """A dispatched mutation may have executed; preserve its attempt and never retry it."""


class SnapshotTooLarge(RunStopped):
    """An observation over the transport ceiling: a terminal stop, never a stale page to recover from or retry."""

    def __init__(self, details=None):
        details = details if isinstance(details, dict) else {}
        self.details = {key: details[key] for key in OVERFLOW_COUNTS if type(details.get(key)) is int}
        super().__init__("snapshot_too_large", f"The page's observation exceeds {MAX_SNAPSHOT_BYTES:,} bytes; "
                                               "no label was truncated and nothing ran from it.")


def observation_token(page):
    """The page's schema-2 token, or None: a legacy or malformed page can be reported, never executed."""
    if not isinstance(page, dict) or page.get("snapshot_schema") != SNAPSHOT_SCHEMA:
        return None
    token = page.get("observation_token")
    if (not isinstance(token, dict) or set(token) != TOKEN_KEYS or token["schema"] != SNAPSHOT_SCHEMA
            or not isinstance(token["epoch"], str) or type(token["generation"]) is not int
            or token["generation"] < 1 or type(token["document_id"]) not in (int, float)):
        return None
    return token


def checked_cdp(method, *, session_id, check_stop=None, remaining_budget=None, **params):
    """Cooperative read bounds; the IPC connection has its separate normal bounded timeout."""
    if check_stop:
        check_stop()
    if remaining_budget:
        params["_response_timeout"] = min(5, remaining_budget())
    try:
        result = cdp(method, session_id=session_id, **params)
    except Exception:
        if check_stop:
            check_stop()
        raise
    if check_stop:
        check_stop()
    return result


class Browser:
    def __init__(self, url):
        # Bound the wait for Chrome's "Allow remote debugging?" answer instead of hanging silently.
        ensure_daemon(wait=30)
        if port := foreign_browser_port():
            restart_daemon()  # drop the daemon, so it stops watching that account's tab
            raise RuntimeError(
                f"The browser on port {port} belongs to another macOS account; no tab opened. Turn on "
                "chrome://inspect/#remote-debugging in your own Chrome, run `uv run browser-harness --reload`, "
                "and retry. To use that browser on purpose, set BU_CDP_URL, then run the same --reload."
            )
        # Its own window, so the user can watch without losing their tab; background, so it never takes keyboard
        # focus. JEV_BACKGROUND_TAB=1 opens a hidden tab in the current window instead, as before 2026-09-24.
        hidden_tab = os.environ.get("JEV_BACKGROUND_TAB") == "1"
        window = {} if hidden_tab else {"newWindow": True, "width": 1120, "height": 880}
        self.target = cdp("Target.createTarget", url="about:blank", background=True, **window)["targetId"]
        try:
            self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
            self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
            # Keep rAF/menus rendering in an owned tab that never takes focus, without activating the user's tab.
            self.call("Emulation.setFocusEmulationEnabled", enabled=True)
            # Page.handleJavaScriptDialog only reaches dialogs that open while Page is enabled on this session.
            self.call("Page.enable")
            self.call("Page.navigate", url=url)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if self.evaluate("document.readyState") == "complete":
                    break
                time.sleep(0.02)
        except Exception:
            # A failed setup must not leave an orphan background tab.
            self.close()
            raise

    def call(self, method, **params):
        return checked_cdp(method, session_id=self.session, **params)

    def evaluate(self, expression, **control):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True, **control)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def observe(self, screenshot=True, *, check_stop=None, remaining_budget=None, max_attempts=10, settle_input=True):
        control = {"check_stop": check_stop, "remaining_budget": remaining_budget} if check_stop else {}
        if check_stop:
            check_stop()
        if settle_input and getattr(self, "after_input", None):
            action, self.after_input = self.after_input, None
            # This is read-only and happens after execution was logged, even if navigation interrupts it.
            try:
                self.call(
                    "Runtime.evaluate",
                    expression="""(action => new Promise(resolve => {
                      const field=window.__jevFast?.nodes.get(action.node);
                      const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
                      let frames=0, stopped=false;
                      const finish=()=>{stopped=true;resolve()};
                      setTimeout(finish,autocomplete ? 200 : 50);
                      const ready=()=>{
                        if (stopped) return;
                        const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
                          .split(/\\s+/).filter(Boolean);
                        const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
                        const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
                        if (++frames>=2 && (!autocomplete || options.some(e=>{
                          const r=e.getBoundingClientRect();
                          return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
                            e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
                        }))) finish();
                        else requestAnimationFrame(ready);
                      };
                      requestAnimationFrame(ready);
                    }))(""" + json.dumps(action) + ")",
                    awaitPromise=True,
                    returnByValue=True,
                    **control,
                )
            except RuntimeError:
                pass
        for attempt in range(max_attempts):
            try:
                return browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot}, **control,
                )
            except StalePage:
                if attempt == max_attempts - 1:
                    raise
                if check_stop:
                    check_stop()
                time.sleep(min(0.02, remaining_budget()) if remaining_budget else 0.02)
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None, **control):
        """Compare the page with the baseline this read installed. Never installs one: asking again after a change
        is still false. CLICK and SELECT compare their own guard; anything else, the whole page's semantics."""
        token = observation_token(page)
        if token is None:
            return False
        result = self.evaluate(f"{FRESH}({json.dumps(token)},{json.dumps(action)})", **control)
        if result == {"status": "snapshot_too_large"}:
            raise SnapshotTooLarge()
        return result is True

    def act(self, action, page, text=None, *, check_stop=None, remaining_budget=None, on_phase=None):
        control = {"check_stop": check_stop, "remaining_budget": remaining_budget} if check_stop else {}
        if check_stop:
            check_stop()
        token = observation_token(page)
        if token is None:  # a legacy or malformed read: no browser call, nothing runs
            raise StalePage("This page read cannot be executed. Observe again.")
        if action["kind"] != "select" and not self.fresh(page, action, **control):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(min(0.1, remaining_budget()) if remaining_budget else 0.1)
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text,
                                    "token": token}, on_phase=on_phase, **control)
        self.after_input = action if action["kind"] != "wait" else None
        return result

    def close_popups(self):
        """Close tabs this tab opened, and return their URLs. The loop never follows a pop-up."""
        popups = [t for t in cdp("Target.getTargets")["targetInfos"] if t.get("openerId") == self.target]
        for popup in popups:
            cdp("Target.closeTarget", targetId=popup["targetId"])
        return [popup["url"] for popup in popups]

    def dismiss_dialog(self):
        """Dismiss a JavaScript dialog without accepting it. False means nothing was dismissed."""
        try:
            self.call("Page.handleJavaScriptDialog", accept=False)
        except RuntimeError:
            return False
        return True

    def close(self):
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


def without_protocol(value):
    """value with protocol identity removed at every depth: tokens and caches are not progress."""
    if isinstance(value, dict):
        return {key: without_protocol(item) for key, item in value.items() if key not in PROTOCOL_KEYS}
    if isinstance(value, list):
        return [without_protocol(item) for item in value]
    return value


def fingerprint(state):
    """Progress: URL, visible text, the offered actions with their geometry, scroll position and height, and
    multi-select evidence. Unchanged from schema 1, so a re-read of an unchanged page is no progress."""
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    if state.get("evidence"):
        content["evidence"] = state["evidence"]
    return hashlib.sha256(json.dumps(without_protocol(content), sort_keys=True).encode()).hexdigest()


def browser_operation(request, *, check_stop=None, remaining_budget=None, on_phase=None):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return checked_cdp(method, session_id=session, check_stop=check_stop,
                           remaining_budget=remaining_budget, **params)

    input_started = False

    def phase(name, *, persist=True):
        if on_phase:
            on_phase(name, input_started, persist=persist)

    def mutate(method, phase_name, *, release=False, **params):
        nonlocal input_started
        if not release:
            if check_stop:
                check_stop()
            phase(phase_name + "_pending")
            if check_stop:
                check_stop()  # Persisting intent can itself take time.
            if remaining_budget:
                params["_response_timeout"] = min(5, remaining_budget())
        # A confirmed press's release has the normal bounded timeout, even after expiry or cancellation.
        input_started = True
        phase(phase_name + "_dispatched", persist=False)
        try:
            return cdp(method, session_id=session, **params)
        except BaseException as error:
            phase(phase_name + "_uncertain", persist=False)
            if not isinstance(error, Exception):
                raise  # Keep cancellation/interrupt transport semantics, with uncertain dispatch evidence.
            message = ("Dropdown" if phase_name == "select" else "Browser input") + (
                " execution reply was lost; inspect before starting another goal."
            )
            raise UncertainAction(message) from error

    def pair(method, press, release, phase_name, *, completes_action=False):
        mutate(method, phase_name + "_press", **press)
        pending_error = None
        try:
            phase(phase_name + "_pressed", persist=not completes_action)
        except BaseException as error:
            pending_error = error
        try:
            mutate(method, phase_name + "_release", release=True, **release)
            phase(phase_name + "_released", persist=not completes_action)
        except BaseException as release_error:
            if pending_error is None:
                raise
            raise pending_error from release_error
        if pending_error is not None:
            raise pending_error

    def evaluate(expression):
        result = call("Runtime.evaluate", expression=expression, returnByValue=True)
        if result.get("exceptionDetails"):
            if operation == "act" and request["action"]["kind"] == "select":
                raise RuntimeError("Dropdown execution was interrupted; inspect before retrying.")
            raise StalePage("Document changed during evaluation")
        return result.get("result", {}).get("value")

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "select":
            payload = {"action": action, "token": request.get("token")}
            response = mutate("Runtime.evaluate", "select",
                              expression=SELECT_ACTION + "(" + json.dumps(payload) + ")", returnByValue=True)
            try:
                result = response.get("result", {}).get("value") if "exceptionDetails" not in response else None
            except Exception as error:
                raise UncertainAction(
                    "Dropdown execution reply was lost; inspect before starting another goal."
                ) from error
            if (isinstance(result, dict) and set(result) == {"status", "reason"}
                    and result["status"] == "rejected_before_input" and isinstance(result["reason"], str)):
                input_started = False
                phase("rejected_before_input", persist=False)
                raise StalePage(result["reason"])
            if result == {"status": "snapshot_too_large"}:  # tagged before any assignment: nothing ran
                input_started = False
                phase("rejected_before_input", persist=False)
                raise SnapshotTooLarge()
            if result != {"status": "executed", "action_id": action["id"]}:
                raise UncertainAction("Dropdown execution was not confirmed; inspect before starting another goal.")
            return {"executed": action["id"]}
        if kind == "scroll":
            mutate("Input.dispatchMouseEvent", "scroll", type="mouseWheel", x=550, y=650,
                   deltaX=0, deltaY=action["delta"])
        elif kind != "wait":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors: the target is
            # the node this read offered under its token, resolved with current geometry and hit-tested.
            target = evaluate(f"{TARGET}({json.dumps(request.get('token'))},{json.dumps(action)})")
            if target is None or "covered" in target:
                if target:  # the topmost element at the target's center; its tag name is page-controlled text
                    raise StalePage(f"Target is covered by <{target['covered']}>. Observe again.")
                raise StalePage("Target changed or is covered. Observe again.")
            if kind != "select":
                x, y = target["x"], target["y"]
                position = {"x": x, "y": y, "button": "left", "clickCount": 1}
                pair("Input.dispatchMouseEvent", {"type": "mousePressed", **position},
                     {"type": "mouseReleased", **position}, "mouse", completes_action=kind == "click")
                if kind == "fill":
                    key = {"key": "a", "code": "KeyA", "modifiers": 4 if sys.platform == "darwin" else 2}
                    pair("Input.dispatchKeyEvent", {"type": "keyDown", "commands": ["selectAll"], **key},
                         {"type": "keyUp", **key}, "select_all")
                    mutate("Input.insertText", "text", text=request["text"])
        return {"executed": action["id"]}

    info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    if isinstance(info, dict) and "snapshot_too_large" in info:  # before the screenshot: no partial page escapes
        raise SnapshotTooLarge(info["snapshot_too_large"])
    if (observation_token(info) is None or not isinstance(info.get("actions"), list)
            or sum(isinstance(a, dict) and a.get("kind") in {"click", "fill", "select"} for a in info["actions"])
            > MAX_TARGETS):
        raise StalePage("The page returned a malformed observation")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
