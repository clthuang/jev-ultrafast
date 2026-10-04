"""The complete agent loop. Typed choices, observable state, bounded execution."""

import base64
import contextlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from .browser import Browser, StalePage
from .model import action_space, choose, field_context, field_text
from .questions import COMMIT_THRESHOLD, MAX_STEPS

# Delegated decision D16 (docs/executor-improvements.md §5): this many WAIT steps, each leaving the page unchanged, with
# no visible progress between them, return the run to Claude, which decides what follows. Jev's WAIT is its "still
# loading" answer. Visible progress is a read that differs from the one before, or a re-read that fails.
WAITS_BEFORE_CLAUDE = 2


class Agent:
    def __init__(
        self, url, goals, *, record_dir=None, screenshots=False, allowed_sites=None, allow_commit=False, trace_path=None
    ):
        task = goals.strip() if isinstance(goals, str) else "\n".join(goals).strip()
        if not task:
            raise ValueError("Supply a task")
        self.pending_text = None
        self.trace_path = trace_path
        self.before_input = None  # optional stop check before each text call and input; raising skips them
        self.browser = Browser(url)
        self.record_dir = Path(record_dir) if record_dir else None
        self.screenshots = screenshots or bool(record_dir)
        try:
            page = self.browser.observe(screenshot=self.screenshots)
        except Exception:
            self.browser.close()
            raise
        self._fresh_state(task, page, allowed_sites, allow_commit)
        if self.record_dir:
            self.record_dir.mkdir(parents=True, exist_ok=True)
            (self.record_dir / "000000.jpg").write_bytes(base64.b64decode(page["screenshot"]))

    def new_goal(self, goal, allowed_sites=None, allow_commit=False, trace_path=None):
        """Start a new run in the same tab: fresh counters and budgets, same browser and node identities."""
        task = goal.strip()
        if not task:
            raise ValueError("Supply a task")
        self.pending_text = None
        self.trace_path = trace_path
        self._fresh_state(task, self.browser.observe(screenshot=self.screenshots), allowed_sites, allow_commit)

    def _fresh_state(self, goal, page, allowed_sites, allow_commit=False):
        # The site boundary: the start page's site plus the sites the caller allows. "*" allows any site.
        start = urlparse(page["url"]).hostname
        sites = [start.removeprefix("www.")] if start else []
        for site in allowed_sites or []:
            host = "*" if site == "*" else urlparse(site if "://" in site else "//" + site).hostname
            if host and host.removeprefix("www.") not in sites:
                sites.append(host.removeprefix("www."))
        self.state = dict(
            browser=self.browser,
            goal=goal,
            page=page,
            decision=None,
            history=[],
            status="ready",
            decisions=[],
            text_calls=[],
            stale_decisions=0,
            stale_streak=0,
            attempt=None,
            allowed_sites=sites,
            allow_commit=allow_commit,
            elapsed_ms=0,
            started_at=None,
            record=bool(self.record_dir),
            wait_streak=0,  # unchanged WAIT steps since the last visible progress; decision D16
        )

    def snapshot(self):
        return {
            **{k: v for k, v in self.state.items() if k != "browser"},
            "elements": action_space(self.state["page"]["actions"])[0],
        }

    def save(self):
        """Write the run file atomically. Without a trace_path this does nothing."""
        if not self.trace_path:
            return
        try:
            snapshot = self.snapshot()
            snapshot["page"] = {k: v for k, v in snapshot["page"].items() if k != "screenshot"}
            path = Path(self.trace_path)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_text(json.dumps(snapshot, separators=(",", ":")))
            os.replace(temporary, path)
        except Exception as error:
            raise RuntimeError(f"Run file incomplete: {error}") from None

    def command(self, name, body=None):
        body = body or {}
        state = self.state
        if name == "tick":
            steps, decisions = len(state["history"]), len(state["decisions"])
            try:
                self.command("predict", {})
                return self.command("act", {"fingerprint": state["page"]["fingerprint"]})
            except StalePage as stale:
                dropped = len(state["history"]) == steps and len(state["decisions"]) > decisions
                if len(state["history"]) == steps:
                    # Decisions dropped because the page changed before their input.
                    state["stale_decisions"] += len(state["decisions"]) - decisions
                if state["attempt"]:
                    state["attempt"] = None  # StalePage is raised only before input, so nothing ran
                    self.save()
                state["decision"] = None
                state["status"] = "ready"
                unchanged = False
                try:
                    state["page"] = state["browser"].observe(screenshot=self.screenshots)
                    unchanged = dropped and state["page"]["fingerprint"] == state["decisions"][-1]["fingerprint"]
                except StalePage:
                    pass  # Still navigating: keep the old page; the next predict reads it again.
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                # Nothing ran and the page reads the same, so Jev would choose again: stop like unchanged actions.
                state["stale_streak"] = state["stale_streak"] + 1 if unchanged else 0
                if not unchanged:
                    state["wait_streak"] = 0  # the page changed or is still navigating: visible progress (D16)
                if state["stale_streak"] == 3:
                    state["status"] = "blocked"
                    raise ValueError(f"Three choices in a row went stale while the page read stayed the same: {stale}")
                return self.snapshot()
        elif name == "predict":
            if not state["browser"]:
                raise ValueError("Start a demo first")
            if state["started_at"] is None:
                state["started_at"] = time.perf_counter()
            if not state["browser"].fresh(state["page"]):
                previous = state["page"]["fingerprint"]
                state["page"] = state["browser"].observe(screenshot=self.screenshots)
                if state["page"]["fingerprint"] != previous:
                    state["wait_streak"] = 0  # the page changed since the last read: visible progress (D16)
            state["decision"] = None
            if state["status"] in {"done", "blocked"}:
                raise ValueError("This run has stopped. Start a fresh demo.")
            if len(state["decisions"]) >= MAX_STEPS * 2:
                state["status"] = "blocked"
                raise ValueError("Reached the demo's model-call budget")
            state["decision"] = choose(state["page"], state["goal"], state["history"])
            state["decisions"].append(
                {
                    **state["decision"],
                    "fingerprint": state["page"]["fingerprint"],
                    "omitted_actions": state["page"].get("omitted_actions", 0),
                    "elapsed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                }
            )
            state["status"] = "predicted"
        elif name == "act":
            decision, page = state["decision"], state["page"]
            if not decision or body.get("fingerprint") != page["fingerprint"]:
                raise ValueError("Observe and choose before acting")
            # Consume once, before any mutation or model call. A retry cannot double-click.
            state["decision"] = None
            selected = decision["choice"]
            if selected in {"DONE", "BLOCKED"}:
                if not state["browser"].fresh(page):
                    state["status"] = "ready"
                    raise StalePage("Page changed since the decision. Choose again.")
                state["status"] = "done" if selected == "DONE" else "blocked"
                state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
                return self.snapshot()
            # Judge the site of the page this decision was made on, before any input or model call.
            host = urlparse(page["url"]).hostname or ""
            sites = state["allowed_sites"]
            if "*" not in sites and not any(host == site or host.endswith("." + site) for site in sites):
                state["status"] = "blocked"
                raise ValueError(
                    f"Left the allowed sites at {host or 'a page without a host'}; widen allowed_sites to continue."
                )
            action = next(a for a in page["actions"] if a["id"] == selected)
            # The commit boundary: stop before a step Jev judges irreversible, unless the goal's caller allowed it.
            if not state["allow_commit"] and decision.get("commit_probability", 0) >= COMMIT_THRESHOLD:
                state["status"] = "blocked"
                raise ValueError(
                    f"'{action['label']}' may pay, buy, book, send, delete, or change account settings; "
                    "pass allow_commit if the user asked for it."
                )
            if len(state["history"]) >= MAX_STEPS:
                state["status"] = "blocked"
                raise ValueError(f"Stopped at the {MAX_STEPS}-action demo budget")
            text, helper = None, None
            if action["kind"] == "fill":
                if not state["browser"].fresh(page):
                    raise StalePage("Page changed before text generation. Choose again.")
                context = field_context(state["goal"], action, page, state["history"])
                if self.pending_text and self.pending_text[0] == context:
                    _, text, helper = self.pending_text
                else:
                    if self.before_input:
                        self.before_input()  # a stopped run skips the paid text call too
                    text, helper = field_text(context)
                    self.pending_text = (context, text, helper)
                    state["text_calls"].append({**helper, "field": action["label"], "value": text})
            if self.before_input:
                self.before_input()  # after this step's model calls, before its input and attempt
            # Save the input about to happen, so a stop between input and logging still shows it.
            state["attempt"] = {
                "step": len(state["history"]) + 1,
                "action": action["label"],
                "kind": action["kind"],
                "target": decision["target"],
                "text": text,
            }
            self.save()
            # Browser.act checks freshness immediately before input, including after text generation.
            state["browser"].act(action, page, text=text)
            self.pending_text = None
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            # Record execution before observing. A stale post-action observation must not erase the action.
            state["history"].append(
                {
                    "step": len(state["history"]) + 1,
                    "action": action["label"],
                    "kind": action["kind"],
                    "choice": selected,
                    "probability": decision["probabilities"][selected],
                    "confidence": decision["confidence"],
                    "latency_ms": decision["latency_ms"],
                    "text": text,
                    "text_helper": helper["model"] if helper else None,
                    "text_latency_ms": helper["latency_ms"] if helper else 0,
                    "operation": decision["operation"],
                    "target": decision["target"],
                    "page_changed": None,
                    "url": page["url"],
                    "usage": decision["usage"],
                    "executed_ms": round((time.perf_counter() - state["started_at"]) * 1000),
                    "elapsed_ms": state["elapsed_ms"],
                }
            )
            state["attempt"] = None
            state["stale_streak"] = 0  # a step ran
            self.save()
            state["page"] = state["browser"].observe(screenshot=self.screenshots)
            state["elapsed_ms"] = round((time.perf_counter() - state["started_at"]) * 1000)
            state["history"][-1].update(
                page_changed=state["page"]["fingerprint"] != page["fingerprint"],
                url=state["page"]["url"],
                elapsed_ms=state["elapsed_ms"],
            )
            if state["record"]:
                (self.record_dir / f"{state['elapsed_ms']:06d}.jpg").write_bytes(
                    base64.b64decode(state["page"]["screenshot"])
                )
            repeated = state["history"][-3:]
            state["status"] = (
                "blocked"
                if len(repeated) == 3 and all(h["page_changed"] is False and h["kind"] != "wait" for h in repeated)
                else "ready"
            )
            # D16: a changed page restarts the count, a WAIT that changed nothing adds one, and other steps keep it.
            if state["history"][-1]["page_changed"]:
                state["wait_streak"] = 0
            elif action["kind"] == "wait":
                state["wait_streak"] += 1
            if state["wait_streak"] == WAITS_BEFORE_CLAUDE:
                state["status"] = "blocked"
                raise ValueError("Jev judged the page still loading")
        else:
            raise ValueError("Unknown command")
        return self.snapshot()

    def run(self):
        try:
            while self.state["status"] not in {"done", "blocked"}:
                yield self.command("tick")
        except BaseException:
            with contextlib.suppress(RuntimeError):  # a failed save must not hide the error that stopped the run
                self.save()
            raise
        self.save()  # the stop: a library run's file ends complete, as run_goal's does

    def close(self):
        self.browser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
