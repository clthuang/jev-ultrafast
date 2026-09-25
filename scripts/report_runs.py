"""Summarize Jev run files (artifacts/runs/*.json). Reads files only; makes no API calls."""

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
from examples.flights import verify  # noqa: E402

MIN_LABELED = 5
CONFIDENCE_BANDS = {"<0.5": 0.5, "0.5-0.8": 0.8, ">=0.8": float("inf")}
COMMIT_BANDS = {"<0.2": 0.2, "0.2-0.5": 0.5, ">=0.5": float("inf")}
STOP_NOTES = {
    "commit stops": "pass allow_commit",
    "new-tab stops": "opened a new tab:",
    "dialog stops": "the page showed a dialog",
    "stale stops": "went stale while the page read stayed the same",
}


def duration(text):
    match = re.fullmatch(r"(\d+)([dh])", text)
    if not match:
        raise ValueError(text)
    return timedelta(**{"days" if match[2] == "d" else "hours": int(match[1])})


def band(value, bands):
    return next(name for name, upper in bands.items() if value < upper)


def latest(run, by):
    return next((o["passed"] for o in reversed(run.get("outcome", [])) if o["by"] == by), None)


def flights_verdict(run):
    """verify() on the final page of a Flights-example trip; None for any other goal.

    Claude rewrites goals before calling run_goal, so the trip is matched by its words, not the exact goal_for() text.
    """
    found = re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", run["goal"])
    try:
        departure = datetime.strptime(found[0], "%B %d, %Y").date() if found else None
    except ValueError:
        departure = None
    words = run["goal"].lower()
    if departure and re.search(r"z[uü]rich", words) and "london" in words:
        return verify(run["page"], departure)["passed"]
    return None


def facts(run):
    decisions, result = run["decisions"], run.get("result", {})
    claude, user = latest(run, "claude"), latest(run, "user")
    confidences = [c for d in decisions for c in (d["confidence"], d["target_confidence"]) if c is not None]
    # allowed_sites starts with the start page's site; history URLs are read after each action.
    start_site = (run["allowed_sites"] or ["no site"])[0].removeprefix("www.")
    hosts = {start_site, *((urlparse(h["url"]).hostname or "").removeprefix("www.") for h in run["history"])}
    return {
        "group": (run["source"], "+".join(sorted({d["model"] for d in decisions})) or "none"),
        "site": start_site,
        "status": result.get("status", "incomplete"),
        "label": claude if user is None else user,
        "claude": claude,
        "user": user,
        "verify": flights_verdict(run),
        "elapsed_ms": run["elapsed_ms"],
        "latencies": [d["latency_ms"] for d in decisions],
        "lowest_confidence": band(min(confidences), CONFIDENCE_BANDS) if confidences else None,
        "commit_bands": [
            band(d["commit_probability"], COMMIT_BANDS) for d in decisions if d["operation"] in {"CLICK", "SELECT"}
        ],
        "totals": {
            **{name: any(marker in note for note in result.get("notes", [])) for name, marker in STOP_NOTES.items()},
            "runs with omitted actions": any(d["omitted_actions"] > 0 for d in decisions),
            "site changes": len(hosts) > 1,
            "stale decisions": run["stale_decisions"],
            "TypeSafe input tokens": sum(d["usage"].get("input_tokens", 0) for d in decisions),
            "text prompt tokens": sum(t["usage"].get("prompt_tokens", 0) for t in run["text_calls"]),
            "text completion tokens": sum(t["usage"].get("completion_tokens", 0) for t in run["text_calls"]),
        },
    }


def rate(count, total):
    return f"{count}/{total}" + (f" ({count / total:.0%})" if total else "")


def summary(name, rows):
    labeled = [r for r in rows if r["label"] is not None]
    both = [r for r in rows if r["claude"] is not None and r["user"] is not None]
    checked = [r for r in rows if r["claude"] is not None and r["verify"] is not None]
    passed = sum(r["label"] for r in labeled)
    false_done = sum(r["status"] == "done" and not r["label"] for r in labeled)
    missed_done = sum(r["status"] in {"blocked", "stopped"} and r["label"] for r in labeled)
    latencies = [ms for r in rows for ms in r["latencies"]]
    by_confidence = {b: [r["label"] for r in labeled if r["lowest_confidence"] == b] for b in CONFIDENCE_BANDS}
    commit_bands = Counter(b for r in rows for b in r["commit_bands"])
    failures = Counter(r["site"] for r in labeled if not r["label"])
    fields = [
        f"{name} (anecdote)" if len(labeled) < MIN_LABELED else name,
        f"runs {len(rows)}, labeled {len(labeled)}, labeled by both {len(both)}",
        f"pass {rate(passed, len(labeled))}",
        f"false DONE {rate(false_done, len(labeled))}",
        f"missed DONE {rate(missed_done, len(labeled))}",
        f"unlabeled {rate(len(rows) - len(labeled), len(rows))}",
        "failures by site " + (", ".join(f"{site} {n}" for site, n in failures.most_common()) or "none"),
        f"Claude agrees with verify() {rate(sum(r['claude'] == r['verify'] for r in checked), len(checked))}",
        f"Claude agrees with user {rate(sum(r['claude'] == r['user'] for r in both), len(both))}",
        "stops " + ", ".join(f"{status} {n}" for status, n in sorted(Counter(r["status"] for r in rows).items())),
        f"median run {statistics.median(r['elapsed_ms'] for r in rows):.0f} ms",
        f"median Jev {statistics.median(latencies):.0f} ms" if latencies else "median Jev n/a",
        "pass by lowest confidence " + ", ".join(f"{b} {rate(sum(v), len(v))}" for b, v in by_confidence.items()),
        "CLICK/SELECT by commit_probability " + ", ".join(f"{b} {commit_bands[b]}" for b in COMMIT_BANDS),
        *(f"{key} {sum(r['totals'][key] for r in rows)}" for key in rows[0]["totals"]),
    ]
    return " · ".join(fields)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=ROOT / "artifacts" / "runs")
    parser.add_argument("--since", type=duration, help="only runs started in the last <n>d or <n>h")
    args = parser.parse_args(argv)
    cutoff = None if args.since is None else datetime.now() - args.since
    rows = []
    for path in sorted(args.runs.glob("*.json")):
        try:
            if cutoff and datetime.strptime(path.stem[:15], "%Y%m%d-%H%M%S") < cutoff:
                continue
            rows.append(facts(json.loads(path.read_text())))
        except Exception as error:  # one unreadable or foreign file must not hide the other runs
            print(f"skipped {path.name}: {error!r}", file=sys.stderr)
    if not rows:
        print(f"No runs in {args.runs}")
        return
    groups = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    print(summary("all runs", rows))
    for (source, model), group in groups.items():
        print(summary(f"{source[:12]} {model}", group))


if __name__ == "__main__":
    main()
