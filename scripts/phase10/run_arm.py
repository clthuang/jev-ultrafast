"""Phase 10 harness: one headless Claude Code session per (task, arm), judged by the task's deterministic check.

Usage: python run_arm.py TASK_ID ARM [--device DEVICE_ID]
  ARM is "executor" (run_goal + report_outcome only) or "chrome" (Claude in Chrome only; needs --device).
Appends one JSON line per session to results.jsonl.
"""

import argparse
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp
from tasks import TASKS

from jev_ultrafast.browser import browser_operation, foreign_browser_port

REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / "artifacts" / "runs"
OUT = REPO / "artifacts" / "phase10"
# A neutral working directory outside the repo, so no project context loads into the sessions.
WORK = Path(os.environ.get("TMPDIR", "/tmp")) / "jev-phase10-work"
RESULTS = OUT / "comparison.jsonl"
SESSION_SECONDS = 600
MODEL = "claude-opus-5-5"  # the pilot's model, pinned for both arms
# Hooks add about 0.6 s per tool call, which would inflate the arm that makes more tool calls.
SETTINGS = json.dumps({"disableAllHooks": True})
JEV_TOOLS = ["mcp__jev-ultrafast__run_goal", "mcp__jev-ultrafast__report_outcome"]
# The user-scope server with the executor's hidden tab, as in the first 30 sessions (the default became a window).
# Claude Code passes MCP servers only a few environment variables, so the setting goes in the server entry.
JEV_SERVER = json.dumps(
    {
        "mcpServers": {
            "jev-ultrafast": {
                "command": "uv",
                "args": ["run", "--directory", str(REPO), "jev-mcp"],
                "env": {"JEV_BACKGROUND_TAB": "1", "JEV_LEARNING": "0"},
            }
        }
    }
)
ENDING = "End your reply with exactly one line: DONE: <what you checked> or FAILED: <why>."
PROMPTS = {
    "executor": "{goal}\nStart at {url}. Do this with the jev-ultrafast run_goal tool. "
    "Every call requires allowed_operations: explicitly list only the CLICK, TYPE_TEXT, SELECT, SCROLL_UP, "
    "SCROLL_DOWN and WAIT operations this goal authorizes, including on continuations. "
    "Use [] for observation only; never broaden the list after a refusal. "
    "Verify the result, then call report_outcome.\n" + ENDING,
    "chrome": "{goal}\nStart at {url}. Use only the Claude in Chrome browser tools: first call select_browser "
    "with deviceId {device}, then open a new tab. Do not call run_goal.\n" + ENDING,
}


def project_folder():
    """The Claude Code project folder of sessions started in WORK: their transcripts and their auto-memory."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(WORK.resolve()))


def clear_memory(folder):
    """Move the sessions' auto-memory folder to folder, returning its file names ([] when there is none).

    Every session shares WORK's Claude Code project, so a memory one session writes would load into every later one.
    Each session starts without any memory, like the first 30 (a session wrote the first memory at 10:26 on 2026-09-24).
    """
    memory = project_folder() / "memory"
    if not memory.exists():
        return []
    folder.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(memory, folder)
    return sorted(p.name for p in folder.iterdir())


def page_targets():
    return {t["targetId"] for t in cdp("Target.getTargets")["targetInfos"] if t["type"] == "page"}


def read_tab(target_id):
    """Read a tab like the executor reads its own: the same 1120x780 viewport (browser.py), scrolled to the top."""
    session = cdp("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
    try:
        cdp(
            "Emulation.setDeviceMetricsOverride",
            session_id=session,
            width=1120,
            height=780,
            deviceScaleFactor=1,
            mobile=False,
        )
        cdp("Runtime.evaluate", session_id=session, expression="window.scrollTo(0, 0)")
        time.sleep(0.5)
        return browser_operation({"operation": "observe", "session": session, "screenshot": False})
    finally:
        cdp("Target.detachFromTarget", sessionId=session)


def site(url):
    """A tab's exact host without "www.": mail.google.com never counts as google.com's Flights tab."""
    return (urlparse(url).hostname or "").removeprefix("www.")


def run_ids_in(entries):
    """Run IDs from run_goal results in the session transcript, in order."""
    return list(dict.fromkeys(re.findall(r"run (\d{8}-\d{6}-[0-9a-f]{4}) ·", json.dumps(entries, ensure_ascii=False))))


def transcript_metrics(session_id, prompt):
    """Claude turns and time between the task prompt and the final reply, from the session transcript."""
    files = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{session_id}.jsonl"))
    if not files:
        return {"turns": None, "transcript_ms": None}
    entries = [json.loads(line) for line in Path(files[0]).read_text().splitlines() if line.strip()]
    start = next(
        (
            i
            for i, e in enumerate(entries)
            if e.get("type") == "user" and prompt[:40] in json.dumps(e, ensure_ascii=False)
        ),
        None,
    )
    if start is None:
        return {"turns": None, "transcript_ms": None, "transcript_run_ids": []}
    replies = [e for e in entries[start:] if e.get("type") == "assistant"]

    def stamp(entry):
        """Seconds since the epoch from a transcript timestamp such as 2026-09-24T05:21:12.345Z."""
        seconds = time.mktime(time.strptime(entry["timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
        return seconds + float("0." + (entry["timestamp"][20:23] or "0"))

    return {
        "transcript_run_ids": run_ids_in(entries[start:]),
        "turns": len({e["message"]["id"] for e in replies}),
        "transcript_ms": round((stamp(replies[-1]) - stamp(entries[start])) * 1000) if replies else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("arm", choices=PROMPTS)
    parser.add_argument("--device")
    parser.add_argument("--results", default=str(RESULTS), help="JSON lines file to append to")
    args = parser.parse_args()
    task = next(t for t in TASKS if t["id"] == args.task)
    if args.arm == "chrome" and not args.device:
        parser.error("the chrome arm needs --device, the Claude in Chrome browser the user chose")
    prompt = PROMPTS[args.arm].format(goal=task["goal"], url=task["url"], device=args.device)
    # A known session ID finds the transcript even when a timeout leaves no JSON reply.
    session_id = str(uuid.uuid4())
    command = [
        "claude",
        "-p",
        prompt,
        "--output-format",
        "json",
        "--model",
        MODEL,
        "--settings",
        SETTINGS,
        "--session-id",
        session_id,
    ]
    if args.arm == "executor":
        command += ["--mcp-config", JEV_SERVER]
        command += ["--disallowedTools", "mcp__claude-in-chrome", "--allowedTools", *JEV_TOOLS]
    else:
        command += ["--chrome", "--disallowedTools", *JEV_TOOLS, "--allowedTools", "mcp__claude-in-chrome"]
    # This harness reads and closes tabs through the daemon directly, so it needs the same account check.
    ensure_daemon(wait=30)
    if port := foreign_browser_port():
        parser.error(f"the browser on port {port} belongs to another macOS account; see Browser() for the fix")
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    left_behind = clear_memory(OUT / "auto-memory" / f"before-{session_id}")
    before, started = page_targets(), time.time()
    # Own process group, so a timeout also stops the session's MCP server, whose SIGTERM handler closes its tab.
    process = subprocess.Popen(
        command,
        cwd=WORK,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=SESSION_SECONDS)
        exit_code = process.returncode
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            output, _ = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            output, _ = process.communicate()
        exit_code = "timeout"
    try:
        reply = json.loads(output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        reply = {}
    record = {
        "task": task["id"],
        "kind": task["kind"],
        "arm": args.arm,
        "goal": task["goal"],
        "url": task["url"],
        "started": started,
        "exit_code": exit_code,
        "session_id": reply.get("session_id") or session_id,
        "duration_ms": reply.get("duration_ms"),
        "claude_cost_usd": reply.get("total_cost_usd"),
        "claude_usage": reply.get("usage"),
    }
    text = (reply.get("result") or "").strip()
    last = text.splitlines()[-1] if text else ""
    record.update(final_line=last[:300], claimed_done=re.match(r"^\W*DONE\b", last) is not None)
    if record["session_id"]:
        record.update(transcript_metrics(record["session_id"], prompt))
    pages = []
    if args.arm == "executor":
        runs = [RUNS / f"{run_id}.json" for run_id in record.get("transcript_run_ids", [])]
        runs = [p for p in runs if p.is_file()]
        record["run_ids"] = [p.stem for p in runs]
        loaded = [json.loads(p.read_text()) for p in runs]
        record["jev_calls"] = sum(len(r["decisions"]) for r in loaded)
        record["jev_input_tokens"] = sum(d["usage"].get("input_tokens", 0) for r in loaded for d in r["decisions"])
        record["run_statuses"] = [r.get("result", {}).get("status") for r in loaded]
        record["claude_labels"] = [(r.get("outcome") or [{}])[-1].get("passed") for r in loaded]
        if loaded:
            pages = [loaded[-1]["page"]]
    else:
        infos = {t["targetId"]: t for t in cdp("Target.getTargets")["targetInfos"] if t["type"] == "page"}
        # Only new tabs on the task's site: tabs the user opens meanwhile are neither read nor closed.
        task_tabs = [i for i in set(infos) - before if site(infos[i]["url"]) == site(task["url"])]
        record["new_tabs"] = len(task_tabs)
        if not task_tabs:
            record["harness_error"] = "no new tab on the task's site: wrong browser selected, or its tab was closed"
        for target in task_tabs:
            try:
                pages.append(read_tab(target))
            except Exception as error:  # a tab that cannot be read counts as not passing
                record.setdefault("read_errors", []).append(str(error)[:200])
            cdp("Target.closeTarget", targetId=target)
    record["auto_memory_before"] = left_behind  # [] unless an earlier session's memory had to be moved first
    record["auto_memory_written"] = clear_memory(OUT / "auto-memory" / session_id)
    if not (project_folder() / f"{session_id}.jsonl").is_file():  # clear_memory would be clearing the wrong folder
        raise SystemExit(f"No transcript in {project_folder()} (claude exit {exit_code}); fix it, then rerun.")
    record["final_urls"] = [p["url"][:300] for p in pages]
    try:
        record["check_passed"] = any(task["check"](p) for p in pages)
    except Exception as error:  # a check that cannot read the page fails the session instead of stopping the run
        record.update(check_passed=False, check_error=str(error)[:200])
    record["false_done"] = record["claimed_done"] and not record["check_passed"]
    with Path(args.results).open("a") as results:
        results.write(json.dumps(record) + "\n")
    print(
        json.dumps(
            {
                k: record[k]
                for k in ("task", "arm", "check_passed", "claimed_done", "turns", "transcript_ms", "claude_cost_usd")
            }
        )
    )


if __name__ == "__main__":
    main()
