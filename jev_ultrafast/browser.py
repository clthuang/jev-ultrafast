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

# Atomically read visible content and controls, preserving actual DOM node identity.
READ_STATE = Path(__file__).with_name("snapshot.js").read_text()
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"
# One synchronous browser task owns both validation and mutation. No await, retry, or value-based fallback.
SELECT_ACTION = """(({action,page_key,guard}) => {
  const rejected=reason=>({status:'rejected_before_input',reason});
  const cache=window.__jevFast, option=action.option;
  if (!cache || !option || option.document_id!==performance.timeOrigin || option.cache_epoch!==cache.epoch)
    return rejected('Dropdown document or cache changed');
  if (!Number.isInteger(action.node) || option.select_id!==action.node || !Number.isInteger(option.option_id) ||
      !Number.isInteger(option.observed_index) || option.observed_index<0 || option.selected!==false ||
      option.effective_disabled!==false || !Array.isArray(page_key) || !Array.isArray(guard))
    return rejected('Dropdown descriptor is invalid');
  const select=cache.nodes.get(option.select_id), chosen=cache.nodes.get(option.option_id);
  if (!select?.isConnected || select.tagName!=='SELECT' || select.multiple || !chosen?.isConnected ||
      chosen.tagName!=='OPTION' || chosen.closest('select')!==select ||
      select.options[option.observed_index]!==chosen) return rejected('Dropdown option identity changed');
  const disabled=select.matches(':disabled') || chosen.disabled || !!chosen.closest('optgroup[disabled]');
  if (disabled!==option.effective_disabled || chosen.label!==option.label || chosen.value!==option.value ||
      chosen.selected!==option.selected) return rejected('Dropdown option meaning or state changed');
  if (select.closest('[aria-disabled="true"],[aria-hidden="true"],[inert]') ||
      !select.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return rejected('Dropdown is unavailable');
  if (JSON.stringify(cache.pageKey())!==JSON.stringify(page_key) ||
      JSON.stringify(cache.guard(select))!==JSON.stringify(guard)) return rejected('Dropdown page context changed');
  const r=select.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
  if (r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight ||
      !select.contains(document.elementFromPoint(x,y))) return rejected('Dropdown is covered or outside the viewport');
  select.selectedIndex=option.observed_index;
  select.dispatchEvent(new Event('input',{bubbles:true}));
  select.dispatchEvent(new Event('change',{bubbles:true}));
  return {status:'executed',action_id:action.id};
})"""
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
        if action is not None and action["kind"] in {"click", "select"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()", **control,
            )
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(MARKER, **control) == page["marker"]

    def act(self, action, page, text=None, *, check_stop=None, remaining_budget=None, on_phase=None):
        control = {"check_stop": check_stop, "remaining_budget": remaining_budget} if check_stop else {}
        if check_stop:
            check_stop()
        if action["kind"] != "select" and not self.fresh(page, action, **control):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(min(0.1, remaining_budget()) if remaining_budget else 0.1)
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text,
                                    "page_key": page.get("page_key"),
                                    "guard": page.get("guards", {}).get(str(action.get("node")))},
                                   on_phase=on_phase, **control)
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


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    content["actions"] = [
        {**action, "option": {key: value for key, value in action["option"].items()
                              if key not in {"document_id", "cache_epoch"}}} if "option" in action else action
        for action in state["actions"]
    ]
    if state.get("evidence"):
        content["evidence"] = state["evidence"]
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


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
            payload = {"action": action, "page_key": request.get("page_key"), "guard": request.get("guard")}
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
            if result != {"status": "executed", "action_id": action["id"]}:
                raise UncertainAction("Dropdown execution was not confirmed; inspect before starting another goal.")
            return {"executed": action["id"]}
        if kind == "scroll":
            mutate("Input.dispatchMouseEvent", "scroll", type="mouseWheel", x=550, y=650,
                   deltaX=0, deltaY=action["delta"])
        elif kind != "wait":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            target = evaluate("""(action => {
              const e=window.__jevFast?.nodes.get(action.node);
              if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
                  !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
              const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
              if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
              const hit=document.elementFromPoint(x,y);
              if (!e.contains(hit)) return hit ? {covered:hit.localName.slice(0,40)} : null;
              return {x,y};
            })(""" + json.dumps(action) + ")")
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
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
