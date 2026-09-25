"""Offline checks for scripts/report_runs.py on synthetic run files. No paid APIs."""

import json
from datetime import date

from examples.flights import goal_for
from scripts import report_runs

DECISION = {
    "model": "jev-1.13.0",
    "latency_ms": 400,
    "usage": {"input_tokens": 900},
    "confidence": 0.9,
    "target_confidence": 0.6,
    "operation": "CLICK",
    "commit_probability": 0.1,
    "omitted_actions": 0,
}


def write_run(folder, index, status="done", labels=(), day="20260924", **keys):
    run = {
        "goal": "Open the pricing page",
        "page": {"url": "https://www.example.com/pricing", "text": "", "actions": []},
        "allowed_sites": ["example.com"],
        "history": [{"step": 1, "action": "Pricing", "kind": "click", "url": "https://www.example.com/pricing"}],
        "decisions": [DECISION],
        "text_calls": [],
        "stale_decisions": 0,
        "elapsed_ms": 1000,
        "result": {"status": status, "notes": [], "text": ""},
        "outcome": [{"passed": passed, "evidence": "", "by": by, "at": "2026-09-24T10:00:00"} for by, passed in labels],
        "source": "a" * 64,
        **keys,
    }
    (folder / f"{day}-1000{index:02d}-abcd.json").write_text(json.dumps(run))


def report(capsys, folder, *options):
    report_runs.main(["--runs", str(folder), *options])
    return capsys.readouterr().out.splitlines()


def flights_page(destination):
    return {
        "url": "https://www.google.com/travel/flights/search?tfs=example",
        "text": "Track prices from Zürich to London departing 2026-09-20",
        "actions": [
            {"label": k, "value": v}
            for k, v in [
                ("Change ticket type. One way", "One way"),
                ("Where from?", "Zürich"),
                ("Where to?", destination),
                ("Departure", "Sun, Sep 20"),
                ("Nonstop flight on Sunday, September 20. Select flight", ""),
            ]
        ],
    }


def test_report_counts_false_and_missed_done(tmp_path, capsys):
    write_run(tmp_path, 1, "done", [("claude", True), ("claude", False)])
    write_run(tmp_path, 2, "blocked", [("claude", True)])
    risky = {**DECISION, "confidence": 0.3, "commit_probability": 0.7}
    write_run(tmp_path, 3, "done", [("user", True), ("claude", False)], decisions=[risky])
    # The first action already left the start site; www. is not a site change.
    write_run(tmp_path, 4, "stopped", history=[{"url": "https://other.test/"}])
    write_run(tmp_path, 5, "stopped", [("claude", True)])
    everything = report(capsys, tmp_path)[0]
    for expected in [
        "runs 5, labeled 4, labeled by both 1",
        "pass 3/4 (75%)",
        "false DONE 1/4 (25%)",
        "missed DONE 2/4 (50%)",
        "unlabeled 1/5 (20%)",
        "failures by site example.com 1",
        "Claude agrees with user 0/1",
        "stops blocked 1, done 2, stopped 2",
        "pass by lowest confidence <0.5 1/1 (100%), 0.5-0.8 2/3 (67%), >=0.8 0/0",
        "CLICK/SELECT by commit_probability <0.2 4, 0.2-0.5 0, >=0.5 1",
        "site changes 1",
    ]:
        assert expected in everything


def test_report_checks_flights_runs_with_verify(tmp_path, capsys):
    flights_goal = goal_for(date(2026, 9, 20))
    write_run(tmp_path, 1, labels=[("claude", True)], goal=flights_goal, page=flights_page("London"))
    write_run(tmp_path, 2, labels=[("claude", True)], goal=flights_goal, page=flights_page("Paris"))
    # Another Google Flights trip: verify() checks only the example's trip, so this run is not checked.
    other_trip = flights_goal.replace("London", "Paris")
    write_run(tmp_path, 3, labels=[("claude", True)], goal=other_trip, page=flights_page("Paris"))
    # Claude rewrites goals before calling run_goal; the same trip in other words is still checked.
    rewritten = "On Google Flights, search one-way from Zürich (ZRH) to London on September 20, 2026. Do not book."
    write_run(tmp_path, 4, labels=[("claude", True)], goal=rewritten, page=flights_page("London"))
    assert "Claude agrees with verify() 2/3 (67%)" in report(capsys, tmp_path)[0]


def test_report_marks_small_groups_as_anecdotes(tmp_path, capsys):
    for index in range(5):
        write_run(tmp_path, index, labels=[("claude", True)])
    write_run(tmp_path, 5, labels=[("claude", True)], source="b" * 64, decisions=[])
    everything, large, small = report(capsys, tmp_path)
    assert everything.startswith("all runs · runs 6")
    assert large.startswith("aaaaaaaaaaaa jev-1.13.0 · runs 5")
    assert small.startswith("bbbbbbbbbbbb none (anecdote) · runs 1")


def test_report_handles_no_runs(tmp_path, capsys):
    assert report(capsys, tmp_path) == [f"No runs in {tmp_path}"]
    write_run(tmp_path, 1, day="20200101")
    for since in ["7d", "0h"]:
        assert report(capsys, tmp_path, "--since", since) == [f"No runs in {tmp_path}"]
    write_run(tmp_path, 2, day=f"{date.today():%Y%m%d}")
    assert report(capsys, tmp_path, "--since", "7d")[0].startswith("all runs (anecdote) · runs 1,")
    (tmp_path / "20200101-100003-abcd.json").write_text('{"goal": ')
    (tmp_path / "trace.json").write_text("{}")
    report_runs.main(["--runs", str(tmp_path)])
    output = capsys.readouterr()
    assert output.out.startswith("all runs (anecdote) · runs 2,")
    assert "skipped 20200101-100003-abcd.json: JSONDecodeError" in output.err
    assert "skipped trace.json: KeyError" in output.err
