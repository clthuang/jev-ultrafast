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
        return cdp(method, session_id=self.session, **params)

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def observe(self, screenshot=True):
        if getattr(self, "after_input", None):
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
                )
            except RuntimeError:
                pass
        for attempt in range(10):
            try:
                return browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot}
                )
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        if action is not None and action["kind"] in {"click", "select"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(MARKER) == page["marker"]

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(0.1)
        result = browser_operation({"operation": "act", "session": self.session, "action": action, "text": text})
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
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return cdp(method, session_id=session, **params)

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
        if kind == "scroll":
            call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=action["delta"])
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
              if (action.kind==='select') {
                if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
                    !o.disabled && !o.closest('optgroup[disabled]'))) return null;
                e.value=action.value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              }
              return {x,y};
            })(""" + json.dumps(action) + ")")
            if target is None or "covered" in target:
                if kind == "select":
                    raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
                if target:  # the topmost element at the target's center; its tag name is page-controlled text
                    raise StalePage(f"Target is covered by <{target['covered']}>. Observe again.")
                raise StalePage("Target changed or is covered. Observe again.")
            if kind != "select":
                x, y = target["x"], target["y"]
                for event in ("mousePressed", "mouseReleased"):
                    call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
                if kind == "fill":
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                        commands=["selectAll"],
                    )
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyUp",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call("Input.insertText", text=request["text"])
        return {"executed": action["id"]}

    info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
