"""Offline checks for scripts/phase10/compare.py: the design §9 verdict and which sessions count. No paid APIs."""

from scripts.phase10 import compare


def arm(passed=5, n=5, false_dones=0, median_s=100.0, median_turns=8):
    return {"n": n, "passed": passed, "false_dones": false_dones, "median_s": median_s, "median_turns": median_turns}


def test_verdict_keeps_only_when_all_three_conditions_hold():
    chrome = arm()
    assert compare.verdict(chrome, arm(median_s=50.0, median_turns=8)) == "keep"  # halves time
    assert compare.verdict(chrome, arm(median_s=90.0, median_turns=4)) == "keep"  # halves turns
    assert compare.verdict(chrome, arm(median_s=50.1, median_turns=5)) == "drop"  # halves neither
    assert compare.verdict(chrome, arm(passed=4, median_s=10.0)) == "drop"  # one failure at a 5/5 tie
    assert compare.verdict(chrome, arm(false_dones=1, median_s=10.0)) == "drop"
    assert compare.verdict(arm(passed=3), arm(passed=3, median_s=10.0)) == "keep"  # a tie below 100% keeps
    assert compare.verdict(chrome, arm(n=4, median_s=10.0)).startswith("pending")


def test_first_valid_keeps_the_first_measured_session_per_task_and_arm():
    first = {"task": "t", "arm": "chrome", "turns": 9}
    records = [
        {"task": "t", "arm": "chrome", "harness_error": "no new tab", "turns": 3},
        {"task": "t", "arm": "chrome", "turns": None},  # no transcript: nothing to count, so set aside
        first,
        {"task": "t", "arm": "chrome", "turns": 2},  # a later session never replaces the first
    ]
    chosen, extra = compare.first_valid(records)
    assert chosen == {("t", "chrome"): first}
    assert len(extra) == 3


def test_first_browser_action_skips_each_arms_setup():
    def call(name, **arguments):
        return {"name": name, "input": arguments}

    assert compare.is_first_action(call("mcp__claude-in-chrome__navigate", url="https://a.test/"), "chrome")
    batch = call("mcp__claude-in-chrome__browser_batch", actions=[{"name": "navigate", "input": {}}])
    assert compare.is_first_action(batch, "chrome")
    setup = call("mcp__claude-in-chrome__browser_batch", actions=[{"name": "tabs_create_mcp", "input": {}}])
    assert not compare.is_first_action(setup, "chrome")
    assert not compare.is_first_action(call("mcp__claude-in-chrome__tabs_create_mcp"), "chrome")
    assert compare.is_first_action(call("mcp__jev-ultrafast__run_goal", goal="g"), "executor")
    assert not compare.is_first_action(call("ToolSearch", query="run_goal"), "executor")
