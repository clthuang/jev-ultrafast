"""Phase 10.2: per-kind comparison table and the design §9 keep-or-drop verdict.

Usage: uv run python scripts/phase10/compare.py [--from-first-action] [RESULTS_JSONL]
  (default: artifacts/phase10/comparison.jsonl, the interleaved run; artifacts/phase10/pilot.jsonl is the pilot)
  --from-first-action: a sensitivity check, not the §9 measure. Time and turns start at each arm's first browser
  action (Claude in Chrome's first navigate, the executor's first run_goal), leaving out each arm's setup turns.
"""

import glob
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

KINDS = ("navigation", "search", "forms")
MIN_RUNS = 5  # design §9, decided in plan 1.2


def is_first_action(call, arm):
    """Claude in Chrome's first navigate, alone or inside browser_batch; the executor's first run_goal."""
    if arm == "executor":
        return call["name"] == "mcp__jev-ultrafast__run_goal"
    batch = call["input"].get("actions", []) if call["name"] == "mcp__claude-in-chrome__browser_batch" else []
    return call["name"] == "mcp__claude-in-chrome__navigate" or any(a.get("name") == "navigate" for a in batch)


def from_first_action(record):
    """The session's turns and time from its first browser action to its final reply, from the transcript."""
    files = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{record['session_id']}.jsonl"))
    entries = [json.loads(line) for line in Path(files[0]).read_text().splitlines() if line.strip()]
    replies = [e for e in entries if e.get("type") == "assistant"]
    first = next(
        i
        for i, e in enumerate(replies)
        if any(c.get("type") == "tool_use" and is_first_action(c, record["arm"]) for c in e["message"]["content"])
    )
    stamp = lambda e: datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00"))  # noqa: E731
    return {
        **record,
        "turns": len({e["message"]["id"] for e in replies[first:]}),
        "transcript_ms": round((stamp(replies[-1]) - stamp(replies[first])).total_seconds() * 1000),
    }


def first_valid(records):
    """The first measured session per (task, arm) without a harness error. A later one never replaces it (§9 step 3)."""
    chosen, extra = {}, []
    for record in records:
        key = (record["task"], record["arm"])
        if record.get("turns") is None:  # no transcript to count: unmeasured, not a best case of 0 turns
            record.setdefault("harness_error", "no session transcript")
        if record.get("harness_error"):
            extra.append(record)
        elif key in chosen:
            extra.append(record)
        else:
            chosen[key] = record
    return chosen, extra


def jev_false_dones(record):
    """Runs Jev ended DONE that Claude labeled failed (design §7.3), even when Claude then recovered."""
    return sum(
        s == "done" and label is False
        for s, label in zip(record.get("run_statuses", []), record.get("claude_labels", []))
    )


def summary(sessions):
    if not sessions:
        return None
    # A session with no time timed out at run_arm.SESSION_SECONDS (600 s): count it at that ceiling.
    times = [s.get("transcript_ms") or s.get("duration_ms") or 600_000 for s in sessions]
    return {
        "n": len(sessions),
        "passed": sum(s["check_passed"] for s in sessions),
        "false_dones": sum(s["false_done"] for s in sessions),
        "jev_false_dones": sum(jev_false_dones(s) for s in sessions),
        "median_s": round(statistics.median(times) / 1000, 1),
        "median_turns": statistics.median(s["turns"] for s in sessions),
        "median_cost_usd": round(statistics.median(s["claude_cost_usd"] or 0 for s in sessions), 3),
    }


def verdict(chrome, executor):
    """Keep only when, over at least 5 runs per arm on the same goals, all three §9 conditions hold (session level)."""
    if not chrome or not executor or min(chrome["n"], executor["n"]) < MIN_RUNS:
        return "pending: fewer than 5 sessions in an arm"
    pass_rate = lambda s: s["passed"] / s["n"]  # noqa: E731
    halves = executor["median_s"] <= chrome["median_s"] / 2 or executor["median_turns"] <= chrome["median_turns"] / 2
    keep = pass_rate(executor) >= pass_rate(chrome) and executor["false_dones"] == 0 and halves
    return "keep" if keep else "drop"


def main():
    arguments = [a for a in sys.argv[1:] if a != "--from-first-action"]
    default = Path(__file__).resolve().parents[2] / "artifacts" / "phase10" / "comparison.jsonl"
    path = Path(arguments[0]) if arguments else default
    chosen, extra = first_valid(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    if "--from-first-action" in sys.argv:
        chosen = {key: from_first_action(record) for key, record in chosen.items()}
    paired = {t for (t, a) in chosen if a == "chrome"} & {t for (t, a) in chosen if a == "executor"}
    rows = []
    for kind in KINDS:
        arms = {}
        for arm in ("chrome", "executor"):
            # Same goals in both arms once the Chrome arm exists; before that, the executor pilot alone.
            arms[arm] = summary(
                [r for (t, a), r in chosen.items() if a == arm and r["kind"] == kind and (t in paired or not paired)]
            )
        rows.append({"kind": kind, **arms, "verdict": verdict(arms["chrome"], arms["executor"])})
    print(
        json.dumps(
            {"rows": rows, "set_aside": [(r["task"], r["arm"], r.get("harness_error", "duplicate")) for r in extra]},
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
