"""Offline checks for jev_ultrafast/site_notes.py, each test in its own temporary folder. No paid APIs."""

import fcntl
import json
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

from jev_ultrafast import site_notes

# Stop texts as agent.py, browser.py and browser-harness write them.
STALE_STREAK = "Three choices in a row went stale while the page read stayed the same: "
TIMEOUT = "Runtime.evaluate timed out after 5s waiting for the daemon"
BUDGET = "Reached the demo's model-call budget"
# A stored note's fields: docs/failure-review.md §6.1, then last_shown and the retired marker.
NOTE_FIELDS = [
    "id", "site", "hint", "detail", "url", "failure", "runs", "approved", "created", "shown", "last_shown",
    "failed_after", "retired",
]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    # No test reads or writes the real artifacts/ (docs/failure-review-plan.md, P4).
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JEV_LEARNING", raising=False)  # the shell's setting stays out


def steps(page_changed):
    """One recorded step; its page_changed stays None when the read after it failed."""
    return [{"step": 1, "action": "Search", "kind": "click", "page_changed": page_changed}]


def make_run(url, status="done", steps=1, passed=None, **keys):
    """A run file ending on url, with steps steps and, when passed is given, Claude's label."""
    return {
        "goal": "Open the page",
        "call": {"goal": "Open the page", "url": None},
        "page": {"url": url},
        "history": [{"step": n + 1, "text": None, "url": url, "page_changed": True} for n in range(steps)],
        "decisions": [],
        "text_calls": [],
        "result": {"status": status, "notes": [], "text": ""},
        "outcome": [] if passed is None else [{"passed": passed, "evidence": "", "by": "claude", "at": ""}],
        **keys,
    }


def visited_run(url):
    """A run that visited only url, in each place a run file records a URL."""
    return {
        "call": {"url": url},
        "decisions": [{"request": {"state": {"page": {"url": url}}}}],
        "history": [{"url": url}],
        "page": {"url": url},
    }


# Where a run file records a URL the run visited.
VISITED = {
    "call.url": lambda run, url: run["call"].update(url=url),
    "a decision's page URL": lambda run, url: run["decisions"][0]["request"]["state"]["page"].update(url=url),
    "a step's url": lambda run, url: run["history"][0].update(url=url),
    "the final page.url": lambda run, url: run["page"].update(url=url),
}


def blocked_run(notes, decisions, stale):
    return {
        "history": [],
        "decisions": [{"operation": "CLICK"}] * decisions,
        "stale_decisions": stale,
        "result": {"status": "blocked", "notes": notes, "text": ""},
    }


def test_covered_target_needs_a_stale_streak_note_naming_a_cover():
    covered = STALE_STREAK + "Target is covered by <mat-option>. Observe again."
    assert site_notes.failure_code("blocked", [covered], steps(True)) == "covered_target"
    # A commit stop begins with the page's own label, which can quote a whole stale-streak note.
    commit = (
        f"'{covered}' may pay, buy, book, send, delete, or change account settings; "
        "pass allow_commit if the user asked for it."
    )
    assert site_notes.failure_code("blocked", [commit], steps(True)) is None


def test_stale_streak_without_a_named_cover_has_no_code():
    for stale in ("Target changed or is covered. Observe again.", "Page changed since this decision. Observe again."):
        assert site_notes.failure_code("blocked", [STALE_STREAK + stale], steps(True)) is None


def test_jev_blocked_is_the_blocked_stop():
    assert site_notes.failure_code("blocked", ["Jev answered BLOCKED"], []) == "jev_blocked"
    # The first note is the stop reason; a failed fresh read after it changes nothing.
    notes = ["Jev answered BLOCKED", "fresh read failed: " + TIMEOUT]
    assert site_notes.failure_code("blocked", notes, []) == "jev_blocked"
    for other_blocked_stop in (
        "three actions in a row changed nothing",
        BUDGET,
        "Stopped at the 60-action demo budget",
        "Left the allowed sites at example.org; widen allowed_sites to continue.",
        "'Jev answered BLOCKED' may pay, buy, book, send, delete, or change account settings; "
        "pass allow_commit if the user asked for it.",
    ):
        assert site_notes.failure_code("blocked", [other_blocked_stop], steps(False)) is None


def test_still_loading_is_the_two_wait_stop():
    # The stop text Agent.command raises after two unchanged WAIT steps (docs/executor-improvements.md §5, D17).
    assert site_notes.failure_code("blocked", ["Jev judged the page still loading"], steps(False)) == "still_loading"
    assert site_notes.failure_code("stopped", ["Jev judged the page still loading"], steps(False)) is None
    assert site_notes.failure_code("blocked", ["Jev answered BLOCKED"], []) == "jev_blocked"


def test_busy_after_step_needs_a_timeout_and_an_unfinished_step():
    assert site_notes.failure_code("stopped", [TIMEOUT], steps(None)) == "busy_after_step"
    # The read after the step finished, so the timeout came later.
    assert site_notes.failure_code("stopped", [TIMEOUT], steps(True)) is None
    # The timeout form must start the first note.
    assert site_notes.failure_code("stopped", ["opened a new tab: " + TIMEOUT], steps(None)) is None
    notes = ["90 s budget reached", "fresh read failed: " + TIMEOUT]
    assert site_notes.failure_code("stopped", notes, steps(None)) is None
    # Only the first note is the stop reason, even when a later one would match on its own.
    assert site_notes.failure_code("stopped", ["90 s budget reached", TIMEOUT], steps(None)) is None


def test_a_timeout_before_any_step_has_no_code():
    assert site_notes.failure_code("stopped", [TIMEOUT], []) is None


def test_done_and_cancelled_runs_have_no_code():
    assert site_notes.failure_code("done", [], steps(True)) is None
    # Whether a DONE is right is the verdict's job, even after an unfinished step and a timeout.
    assert site_notes.failure_code("done", [TIMEOUT], steps(None)) is None
    assert site_notes.failure_code("stopped", ["cancelled"], steps(None)) is None


def test_stale_budget_flag_needs_mostly_stale_decisions():
    assert site_notes.stale_budget(blocked_run([BUDGET], decisions=120, stale=118))
    assert site_notes.stale_budget(blocked_run([BUDGET], decisions=120, stale=61))
    assert not site_notes.stale_budget(blocked_run([BUDGET], decisions=120, stale=60))  # half is not more than half
    # The first note is the stop reason; a failed fresh read after it changes nothing.
    assert site_notes.stale_budget(blocked_run([BUDGET, "fresh read failed: " + TIMEOUT], decisions=120, stale=118))
    # Mostly stale, but a stale-streak stop, not a budget stop.
    stale_streak = STALE_STREAK + "Target changed or is covered. Observe again."
    assert not site_notes.stale_budget(blocked_run([stale_streak], decisions=7, stale=6))
    # Only the first note is the stop reason, even when a later one would match on its own.
    assert not site_notes.stale_budget(blocked_run([stale_streak, BUDGET], decisions=120, stale=118))
    # A run file saved before its stop has no result.
    assert not site_notes.stale_budget({"history": [], "decisions": [], "stale_decisions": 0})


def test_every_code_has_a_next_step_sentence():
    assert site_notes.NEXT_BY_FAILURE.keys() == site_notes.FAILURE_RULES.keys()
    # Verbatim from docs/failure-review.md §5.
    assert site_notes.NEXT_BY_FAILURE == {
        "covered_target": "a control kept covering the target, such as an open suggestion list or a password "
        "manager's menu. Give one field or click per goal, starting with controls it does not cover. A goal may "
        "choose the site's suggestion the task needs; never choose an entry from a password manager's menu",
        "jev_blocked": "Jev answered BLOCKED. If the screenshot shows the page waiting for the user, such as for a "
        "sign-in, a passcode, a verification code or a CAPTCHA, call show_window, ask them to finish it there, and "
        "then continue with run_goal without url. If it shows the page still loading, run a goal for what remains "
        "without url: Jev answers again on the page as it is then, without reloading it. If Jev's last answer shows a "
        "runner-up within 0.2 of BLOCKED, that runner-up often names the step to try. If the control may be further "
        "down, first run a goal that only scrolls until it shows, then the rest. If Jev cannot see it at all, as with "
        "a search box inside a shadow DOM or frame, open the results URL directly, or use Claude in Chrome",
        "still_loading": "Jev judged the page still loading, twice, and the page did not change. If the screenshot "
        "shows it still loading, run a goal for what remains, often just its end state, without url: Jev answers "
        "again on the page as it is then, without reloading it. Re-ask at most twice. If it waits for the user, call "
        "show_window. If it looks finished, recover as for Jev answering BLOCKED",
        "busy_after_step": "the page stayed busy after the last step, which ran: check the page before running the "
        "goal again",
    }


def test_site_key_strips_www_and_keeps_subdomains():
    assert site_notes.site_key("https://www.clinicaltrials.gov/search?cond=asthma") == "clinicaltrials.gov"
    # Not the registrable domain, nasa.gov, and not browser-harness's first label, flights.
    assert site_notes.site_key("https://apod.nasa.gov/apod/astropix.html") == "apod.nasa.gov"
    assert site_notes.site_key("https://WWW.Flights.Google.com:443/search") == "flights.google.com"
    assert site_notes.site_key("https://www2.example.org/") == "www2.example.org"
    for no_host in ("about:blank", None, "https://[unclosed/"):
        assert site_notes.site_key(no_host) == ""


def test_hints_are_the_four_with_a_sentence_and_a_short_form():
    # Verbatim from docs/failure-review.md §6.1.
    assert site_notes.HINTS == {
        "one_action_per_goal": {
            "sentence": "give one field or click per goal on this site",
            "short_form": "one field or click per goal",
        },
        "scroll_first": {
            "sentence": "a control here sits below the first view: scroll to it first, as a goal of its own if Jev "
            "still answers BLOCKED",
            "short_form": "scroll to the control first, in its own goal",
        },
        "start_at_url": {
            "sentence": "start at this URL instead of using the page's controls: <url>",
            "short_form": "start at <url>",
        },
        "use_claude_in_chrome": {
            "sentence": "Jev cannot operate a control this site needs: use Claude in Chrome for it",
            "short_form": "use Claude in Chrome for its controls",
        },
    }


def test_seeds_are_the_four_approved_notes_of_the_design():
    # The sites, hints, details and MDN URL of docs/failure-review.md §6.2.
    assert [(note["site"], note["hint"], note["detail"], note["url"]) for note in site_notes.SEEDS] == [
        (
            "clinicaltrials.gov",
            "one_action_per_goal",
            "The condition field's suggestion list covers the next field: choose the suggestion first.",
            None,
        ),
        ("apod.nasa.gov", "scroll_first", "The Archive link sits below the day's image.", None),
        ("arxiv.org", "scroll_first", "The advanced search's date fields sit below the first view.", None),
        (
            "developer.mozilla.org",
            "start_at_url",
            "The search box sits inside a shadow DOM that Jev cannot read.",
            "https://developer.mozilla.org/en-US/search?q=",
        ),
    ]
    for note in site_notes.SEEDS:
        assert list(note) == NOTE_FIELDS
        assert note["id"] == note["site"] + "-1"
        assert note["failure"] in site_notes.NEXT_BY_FAILURE
        # Approved on the build date, a literal, so a recreated file keeps their 180 days.
        assert note["approved"] == note["created"] == "2026-09-27"
        assert (note["shown"], note["last_shown"], note["failed_after"], note["retired"]) == (0, None, 0, None)


def test_chains_link_by_previous_run_or_pid_and_cut_at_a_pass_or_a_new_site():
    trials, arxiv = "https://clinicaltrials.gov/search", "https://www.arxiv.org/search/advanced"
    user_says_failed = [
        {"passed": True, "evidence": "", "by": "claude", "at": ""},
        {"passed": False, "evidence": "", "by": "user", "at": ""},
    ]
    runs = {
        # Recorded before the build: each links to the latest earlier run with its pid.
        "20260924-100000-0001": make_run(trials, "blocked", pid=7, passed=False),
        "20260924-100100-0002": make_run(trials, "blocked", pid=8),  # another server
        "20260924-100200-0003": make_run(trials, pid=7, passed=True),  # the recovery ends its chain
        "20260924-100300-0004": make_run(trials, pid=7),
        "20260924-100400-0005": make_run(arxiv, "blocked", pid=7),  # another site
        "20260924-100500-0006": make_run(arxiv, pid=7),
        # Recorded after it: previous_run is the link, even where an earlier server had the same pid.
        "20260927-100000-0007": make_run(trials, "blocked", pid=8, previous_run=None),
        "20260927-100100-0008": make_run(trials, pid=8, previous_run="20260927-100000-0007"),
        # The user's label outranks Claude's, so this chain goes on.
        "20260927-100200-0009": make_run(trials, pid=5, previous_run=None, outcome=user_says_failed),
        "20260927-100300-000a": make_run(trials, pid=5, previous_run="20260927-100200-0009"),
        # A run with neither key is its own chain.
        "20260927-100400-000b": make_run(trials),
        # Saved in one second, so their IDs sort against their order: the link still decides.
        "20260927-100500-00ff": make_run(trials, pid=5, previous_run=None),
        "20260927-100500-0011": make_run(trials, pid=5, previous_run="20260927-100500-00ff"),
        # Two runs linked to each other, which only a hand edit makes: the walk stops where it meets the loop.
        "20260927-100600-0021": make_run(trials, previous_run="20260927-100600-0022"),
        "20260927-100600-0022": make_run(trials, previous_run="20260927-100600-0021"),
    }
    assert [list(chain) for chain in site_notes.chains(runs)] == [
        ["20260924-100000-0001", "20260924-100200-0003"],
        ["20260924-100100-0002"],
        ["20260924-100300-0004"],
        ["20260924-100400-0005", "20260924-100500-0006"],
        ["20260927-100000-0007", "20260927-100100-0008"],
        ["20260927-100200-0009", "20260927-100300-000a"],
        ["20260927-100400-000b"],
        ["20260927-100500-00ff", "20260927-100500-0011"],
        ["20260927-100600-0022", "20260927-100600-0021"],
    ]
    assert all(chain[run_id] is runs[run_id] for chain in site_notes.chains(runs) for run_id in chain)


def test_a_possible_false_done_is_a_done_before_a_run_with_no_step():
    # A failed run (P21): it did not end done, or its latest label is failed, as a false DONE's is.
    assert site_notes.run_failed(make_run("https://example.com/", "done", passed=False))
    assert site_notes.run_failed(make_run("https://example.com/", "blocked"))
    assert not site_notes.run_failed(make_run("https://example.com/", "done"))
    flights, search = "https://www.google.com/travel/flights", "https://duckduckgo.com/?q=flights"
    runs = {
        # A DONE labelled passed is flagged too: the link, not the chain, leads to the next run.
        "20260924-100000-0001": make_run(flights, pid=3, passed=True),
        "20260924-100100-0002": make_run(flights, steps=0, pid=3),
        "20260924-100200-0003": make_run(flights, pid=4),
        "20260924-100300-0004": make_run(flights, steps=2, pid=4),  # the next run took a step
        "20260924-100400-0005": make_run(flights, pid=6),
        "20260924-100500-0006": make_run(search, steps=0, pid=6),  # on another site
        "20260924-100600-0007": make_run(flights, "blocked", pid=8),  # not a DONE
        "20260924-100700-0008": make_run(flights, steps=0, pid=8),
        "20260927-100000-0009": make_run(flights, steps=0, previous_run="20260924-100700-0008"),
        # Saved in one second, so the next run's ID sorts first: the link still leads to it.
        "20260927-100100-00ff": make_run(flights, previous_run=None),
        "20260927-100100-0011": make_run(flights, steps=0, previous_run="20260927-100100-00ff"),
        # A run saved mid-run has no result yet: it has not finished, so it flags nothing (P21).
        "20260927-100200-0021": make_run(flights, previous_run=None),
        "20260927-100200-0022": {
            key: value
            for key, value in make_run(flights, steps=0, previous_run="20260927-100200-0021").items()
            if key != "result"
        },
    }
    assert site_notes.possible_false_dones(runs) == [
        "20260924-100000-0001",
        "20260924-100700-0008",
        "20260927-100100-00ff",
    ]


@pytest.mark.parametrize("place", [*VISITED, "a listed run ID"])
def test_exclusion_matches_every_url_a_run_visited(place):
    exclude_file = Path("artifacts/review-exclude.txt")
    assert site_notes.read_exclude(exclude_file) == set()  # a missing file excludes nothing
    exclude_file.parent.mkdir()
    exclude_file.write_text(
        "# kept out\n\nWWW.Clinic.example  # with its subdomains\nhttps://Records.example/a\nold.example.\n"
        "20260101-000000-abcd\n"
    )
    exclude = site_notes.read_exclude(exclude_file)
    # A pasted URL stands for its host, and a trailing dot goes.
    assert exclude == {"clinic.example", "records.example", "old.example", "20260101-000000-abcd"}
    run_id, run = "20260924-120000-abcd", visited_run("https://arxiv.org/search")
    assert not site_notes.excluded(run_id, run, exclude)
    if place in VISITED:
        VISITED[place](run, "https://records.clinic.example./patient")  # a visited host's trailing dot changes nothing
        assert site_notes.excluded(run_id, run, exclude)
        VISITED[place](run, "https://records.clinic.example/patient")
    else:
        run_id = "20260101-000000-abcd"
    assert site_notes.excluded(run_id, run, exclude)


def test_task_values_are_matched_per_word_ignoring_case():
    run = {
        "goal": 'Book "Hotel Adlon" for jane.doe@example.com from 20261003, in "NY"',
        "history": [
            {"text": "New  York"}, {"text": None}, {"text": "NY"}, {"text": "SFO"}, {"text": "Bo Lee"},
            {"text": "wanda_mercer"},
        ],
        "text_calls": [{"value": "John Smith"}],
    }
    values = site_notes.task_values({"20260924-120000-abcd": run})
    # Typed or quoted text of 3 characters or more, the goal's e-mail addresses and runs of 4 or more digits, and each
    # of their words of 4 characters or more (P16).
    assert values == {
        "new york", "york", "sfo", "john smith", "john", "smith", "hotel adlon", "hotel", "adlon",
        "jane.doe@example.com", "jane", "example", "20261003", "bo lee", "wanda_mercer", "wanda", "mercer",
    }
    pattern = site_notes.task_value_pattern(values)
    holding = ("NEW YORK hotels", "Smith's record", "fly to SFO", "mail Jane.Doe@Example.com.", "Hotel\nAdlon")
    # Words joined as URLs and handles join them, and an underscore ends a value.
    holding += ("github.com/bo-lee", "user Bo_Lee", "q=bo+lee", "sfo_flights", "Mercer Street", "Wanda Mercer")
    # A run of digits matches between non-digits, even where letters touch it.
    for text in (*holding, "on 20261003", "flight UA20261003"):
        assert pattern.search(text)
    # Whole words only, and never a word under 4 characters, such as "new" from "New York".
    for clean in ("a new page", "New Yorker", "Smithsonian", "120261003", "Bob Leeds", ""):
        assert not pattern.search(clean)
    assert pattern.sub("<value>", "Fly John Smith to New York on UA20261003") == "Fly <value> to <value> on UA<value>"
    assert not site_notes.task_value_pattern(set()).search("anything")


FAILED_ID, RECOVERED_ID = "20260924-113517-88f4", "20260924-113700-fc97"
CALL_URL = "https://clinicaltrials.gov/search?cond=asthma"
# Stripped of their query values, these two call.urls have exactly 100 and 101 characters.
LIMIT_CALL_URL = "https://clinicaltrials.gov/" + "a" * 67 + "?cond=asthma"
LONG_CALL_URL = "https://clinicaltrials.gov/" + "a" * 68 + "?cond=asthma"


def recovery_chain(call_url=CALL_URL):
    """A failed run that typed "inhaler", then a recovery that started at call_url, both with one goal."""
    goal = 'Search for "asthma" studies from 2019, then mail them to jane.doe@example.com'
    failed = make_run("https://clinicaltrials.gov/", "blocked", passed=False, goal=goal)
    failed["history"][0]["text"] = "inhaler"
    recovered = make_run(CALL_URL, passed=True, goal=goal, call={"goal": goal, "url": call_url})
    return {FAILED_ID: failed, RECOVERED_ID: recovered}


def lesson(**changes):
    """A note as a writer gives it to the store, before code checks it."""
    return {
        "site": "clinicaltrials.gov",
        "hint": "one_action_per_goal",
        "detail": "The condition field's suggestion list covers the next field: choose the suggestion first.",
        "url": None,
        "failure": "covered_target",
        "runs": {"failed": [FAILED_ID], "recovered": RECOVERED_ID},
        **changes,
    }


# Each: the note's changes, the recovered run's call.url, the exclude list, and the one reason expected.
REFUSALS = {
    "a hint not in the set": ({"hint": "other"}, CALL_URL, set(), "its hint is not one of"),
    "a site other than the run's final page": ({"site": "arxiv.org"}, CALL_URL, set(), "run's final page"),
    "a detail over 300 characters": ({"detail": "x" * 301}, CALL_URL, set(), "over 300 characters"),
    "a detail holding a URL": ({"detail": "Open https://clinicaltrials.gov/search first."}, CALL_URL, set(), "a URL"),
    "typed text in the detail": ({"detail": "Type INHALER once the list closes."}, CALL_URL, set(), "from the task"),
    "a quoted goal value": ({"detail": "The Asthma suggestion covers the field."}, CALL_URL, set(), "from the task"),
    "an e-mail address": ({"detail": "Results go to Jane.Doe@example.com."}, CALL_URL, set(), "from the task"),
    "4 or more digits": ({"detail": "Studies from 2019 load slowly."}, CALL_URL, set(), "from the task"),
    "an excluded site": ({}, CALL_URL, {"clinicaltrials.gov"}, "excluded"),
    "an excluded run": ({}, CALL_URL, {FAILED_ID}, "excluded"),
    "start_at_url without a call.url": ({"hint": "start_at_url"}, None, set(), "its call.url"),
    "a URL that is not https": (
        {"hint": "start_at_url"}, "http://clinicaltrials.gov/search?cond=asthma", set(), "not https"
    ),
    "a URL on another host": ({"hint": "start_at_url"}, "https://mirror.example/search?cond=asthma", set(), "site"),
    "a URL over 100 characters": (
        {"hint": "start_at_url", "url": LONG_CALL_URL.removesuffix("asthma")}, LONG_CALL_URL, set(), "over 100"
    ),
}


@pytest.mark.parametrize("changes, call_url, exclude, reason", REFUSALS.values(), ids=REFUSALS)
def test_a_note_is_refused_for_each_failed_check(changes, call_url, exclude, reason):
    assert site_notes.check_note(lesson(), recovery_chain(), set()) == []
    # At the limits: a 300-character detail, and a 100-character URL, are stored.
    assert site_notes.check_note(lesson(detail="x" * 300), recovery_chain(), set()) == []
    at_limit = lesson(hint="start_at_url", url=LIMIT_CALL_URL.removesuffix("asthma"))
    assert site_notes.check_note(at_limit, recovery_chain(LIMIT_CALL_URL), set()) == []
    # A run that ended off the web has no site for a note: about:blank has none, Chrome's error page a fake one.
    for off_web in ("about:blank", "chrome-error://chromewebdata/"):
        chain = recovery_chain()
        chain[RECOVERED_ID]["page"]["url"] = off_web
        off_web_note = lesson(site=site_notes.run_site(chain[RECOVERED_ID]))
        assert site_notes.check_note(off_web_note, chain, set()) == ["its run did not end on a web page"]
    [refusal] = site_notes.check_note(lesson(**changes), recovery_chain(call_url), exclude)
    assert reason in refusal


def test_start_at_url_comes_from_call_url_without_query_values():
    goal = "Find the flexbox guide on MDN"
    failed = make_run("https://developer.mozilla.org/en-US/", "blocked", steps=0, passed=False, goal=goal)
    recovered = make_run(
        "https://developer.mozilla.org/en-US/search?q=flexbox", steps=0, passed=True, goal=goal,
        call={"goal": goal, "url": "https://developer.mozilla.org/en-US/search?q=flexbox"},
    )
    chain = {"20260924-111225-096c": failed, "20260924-111244-b98c": recovered}
    # The MDN seed's URL: the recovered run's call.url, its query value removed.
    assert site_notes.note_url(chain) == "https://developer.mozilla.org/en-US/search?q="
    note = lesson(
        site="developer.mozilla.org", hint="start_at_url", url=site_notes.note_url(chain),
        detail="The search box sits inside a shadow DOM that Jev cannot read.",
    )
    assert site_notes.check_note(note, chain, set()) == []
    # The host is the note's own site: typed text equal to part of it refuses nothing, and typed text in the path does.
    failed["text_calls"] = [{"value": "Mozilla"}]
    assert site_notes.check_note(note, chain, set()) == []
    failed["text_calls"] = [{"value": "en-US"}]
    assert site_notes.check_note(note, chain, set()) == ["its detail or URL holds a value from the task"]
    # However the path joins or encodes a typed value, or the value joins its own words, it is found.
    for typed, path in (
        ("Jane Doe", "/en-US/docs/Jane_Doe"),
        ("Jane Doe", "/en-US/docs/Mr%20Jane%20Doe"),
        ("jane_doe", "/en-US/docs/jane_doe"),
    ):
        failed["text_calls"] = [{"value": typed}]
        recovered["call"]["url"] = "https://developer.mozilla.org" + path
        joined = {**note, "url": site_notes.note_url(chain)}
        assert site_notes.check_note(joined, chain, set()) == ["its detail or URL holds a value from the task"]
    failed["text_calls"] = []
    recovered["call"]["url"] = "https://developer.mozilla.org/en-US/search?q=flexbox"
    # A writer cannot keep the query value, or set a URL on another hint.
    with_value = {**note, "url": "https://developer.mozilla.org/en-US/search?q=flexbox"}
    [refusal] = site_notes.check_note(with_value, chain, set())
    assert refusal == "its URL is not the run's call.url without its user info, query values and fragment"
    assert site_notes.check_note({**note, "hint": "scroll_first"}, chain, set()) == ["only start_at_url takes a URL"]
    # Names stay; user info, values, nameless parts and the fragment go; a subdomain of the site counts as the site.
    recovered["call"]["url"] = "https://jane:hunter2@www.developer.mozilla.org/en-US/search?q=grid&css&topic=a#results"
    assert site_notes.note_url(chain) == "https://www.developer.mozilla.org/en-US/search?q=&topic="
    assert site_notes.strip_query("https://clinicaltrials.gov/search?asthma+inhaler") == "https://clinicaltrials.gov/search"
    # A browser reads a backslash as "/", so its host would be evil.com, where Python reads an MDN subdomain.
    backslashed = "https://evil.com\\.developer.mozilla.org/x"
    off_site = ("http://developer.mozilla.org/en-US/search?q=grid", "https://mdn.example/search?q=grid", backslashed)
    for refused in (*off_site, None):
        recovered["call"]["url"] = refused
        assert site_notes.note_url(chain) is None
    assert site_notes.url_refusal(backslashed, "developer.mozilla.org") is not None


def days_ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


def stored(note_id, site="clinicaltrials.gov", **changes):
    """A note as the notes file stores it: created today, unapproved and never shown, unless changes say otherwise."""
    return {
        "id": note_id,
        **lesson(site=site),
        "approved": None,
        "created": date.today().isoformat(),
        "shown": 0,
        "last_shown": None,
        "failed_after": 0,
        "retired": None,
        **changes,
    }


def write_notes(text):
    site_notes.NOTES_PATH.parent.mkdir(exist_ok=True)
    site_notes.NOTES_PATH.write_text(text if isinstance(text, str) else json.dumps(text))


def notes_by_id():
    notes, error = site_notes.load()
    assert error is None
    return {note["id"]: note for note in notes}


def test_a_missing_file_starts_with_the_approved_seeds():
    assert site_notes.load(create=False) == ([], None)
    assert not Path("artifacts").exists()  # create=False writes nothing
    notes, error = site_notes.load()
    assert error is None and notes == site_notes.SEEDS
    assert json.loads(site_notes.NOTES_PATH.read_text())["notes"] == site_notes.SEEDS
    notes[0]["shown"] = 1
    assert site_notes.SEEDS[0]["shown"] == 0  # the file started from a copy
    assert site_notes.load(create=False) == (site_notes.SEEDS, None)


def test_a_writer_waits_for_the_lock():
    site_notes.load()
    before = site_notes.NOTES_PATH.read_text()
    signalled = threading.Event()

    def writer():
        signalled.set()
        site_notes.add_note(lesson(site="arxiv.org"))

    thread = threading.Thread(target=writer)
    with open("artifacts/site-notes.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        thread.start()
        assert signalled.wait(5)
        time.sleep(0.5)
        assert site_notes.NOTES_PATH.read_text() == before
        write_notes(json.loads(before)["notes"][:3])  # another writer's change, made while holding the lock
    thread.join(5)  # closing the lock file released the lock
    assert not thread.is_alive()
    # The waiting writer read the file after the lock, so it kept the other change.
    assert list(notes_by_id()) == [seed["id"] for seed in site_notes.SEEDS[:3]] + ["arxiv.org-2"]


def test_notes_expire_after_30_or_180_days():
    today = date.today()
    assert site_notes.active(stored("arxiv.org-2", created=days_ago(29)), today)
    assert not site_notes.active(stored("arxiv.org-2", created=days_ago(30)), today)
    # An approved note counts from its approval, however old the note is.
    assert site_notes.active(stored("arxiv.org-2", created=days_ago(400), approved=days_ago(179)), today)
    assert not site_notes.active(stored("arxiv.org-2", created=days_ago(400), approved=days_ago(180)), today)
    # Expired notes stay in the file, like retired ones, and no longer count toward the site's 5.
    write_notes([stored(f"clinicaltrials.gov-{n}", created=days_ago(30)) for n in range(1, 6)])
    assert site_notes.add_note(lesson()) == "clinicaltrials.gov-6"
    notes = notes_by_id()
    assert len(notes) == 6 and not any(note["retired"] for note in notes.values())


def test_an_unapproved_note_retires_after_two_failures_and_an_approved_one_is_flagged():
    today = date.today().isoformat()
    write_notes([
        stored("clinicaltrials.gov-1"),
        stored("clinicaltrials.gov-2"),
        stored("clinicaltrials.gov-3"),  # never shown
        stored("clinicaltrials.gov-4", failure="jev_blocked"),  # another code
        stored("arxiv.org-2", site="arxiv.org"),  # another site
    ])
    site_notes.set_state("clinicaltrials.gov-2", "approve")
    site_notes.record_failure("clinicaltrials.gov", "covered_target")  # before any result showed a note
    site_notes.record_shown(["clinicaltrials.gov-1", "clinicaltrials.gov-2", "clinicaltrials.gov-4", "arxiv.org-2"])
    site_notes.record_failure("clinicaltrials.gov", None)  # a failure with no code counts against no note
    site_notes.record_failure("clinicaltrials.gov", "covered_target")
    assert [notes_by_id()["clinicaltrials.gov-1"][key] for key in ("failed_after", "retired")] == [1, None]
    site_notes.record_failure("clinicaltrials.gov", "covered_target")
    notes = notes_by_id()
    keys = ("shown", "last_shown", "failed_after", "retired")
    assert [notes["clinicaltrials.gov-1"][key] for key in keys] == [1, today, 2, today]
    # Code never retires an approved note: at the same count, the report flags it.
    assert [notes["clinicaltrials.gov-2"][key] for key in ("approved", *keys)] == [today, 1, today, 2, None]
    untouched = ("clinicaltrials.gov-3", "clinicaltrials.gov-4", "arxiv.org-2")
    assert [notes[note_id]["failed_after"] for note_id in untouched] == [0, 0, 0]
    with pytest.raises(ValueError, match="restore it first"):  # an approval never lands on a retired note
        site_notes.set_state("clinicaltrials.gov-1", "approve")
    # By hand: restore undoes a retirement and resets its count (P17), and retire marks a note.
    site_notes.set_state("clinicaltrials.gov-1", "restore")
    site_notes.set_state("clinicaltrials.gov-3", "retire")
    notes = notes_by_id()
    assert [notes["clinicaltrials.gov-1"][key] for key in ("retired", "failed_after")] == [None, 0]
    assert notes["clinicaltrials.gov-3"]["retired"] == today
    # P20: a server whose results never showed the unapproved note does not count it; the approved one always counts.
    site_notes.record_failure("clinicaltrials.gov", "covered_target", shown={"clinicaltrials.gov-2"})
    notes = notes_by_id()
    assert [notes[f"clinicaltrials.gov-{n}"]["failed_after"] for n in (1, 2)] == [0, 3]
    site_notes.record_failure("clinicaltrials.gov", "covered_target", shown={"clinicaltrials.gov-1"})
    notes = notes_by_id()
    assert [notes[f"clinicaltrials.gov-{n}"]["failed_after"] for n in (1, 2)] == [1, 4]
    with pytest.raises(ValueError, match="no note clinicaltrials.gov-9"):
        site_notes.set_state("clinicaltrials.gov-9", "retire")


@pytest.mark.parametrize("approved", [4, 5], ids=["4 approved and 1 unapproved", "5 approved"])
def test_a_sixth_note_replaces_the_oldest_unapproved_or_is_refused(approved):
    today = date.today().isoformat()
    write_notes([stored(f"clinicaltrials.gov-{n}", approved=today if n <= approved else None) for n in range(1, 6)])
    before = site_notes.NOTES_PATH.read_text()
    if approved == 5:
        with pytest.raises(ValueError, match="already has 5 approved notes"):
            site_notes.add_note(lesson())
        assert site_notes.NOTES_PATH.read_text() == before
        return
    # A writer cannot approve its own note.
    assert site_notes.add_note({**lesson(), "approved": today}) == "clinicaltrials.gov-6"
    notes = notes_by_id()
    assert notes["clinicaltrials.gov-5"]["retired"] == today  # the unapproved one goes, and stays in the file
    assert notes["clinicaltrials.gov-6"]["approved"] is None
    assert sum(site_notes.active(note, date.today()) for note in notes.values()) == 5


def test_an_unreadable_notes_file_shows_no_notes_and_is_never_overwritten():
    writes = (
        lambda: site_notes.add_note(lesson()),
        lambda: site_notes.record_shown(["clinicaltrials.gov-1"]),
        lambda: site_notes.record_failure("clinicaltrials.gov", "covered_target"),
        lambda: site_notes.set_state("clinicaltrials.gov-1", "retire"),
    )
    # Hand edits of the wrong type, such as a hand approval, which no reader could use.
    hand_edits = (
        {"approved": True}, {"created": "yesterday"}, {"shown": "3"}, {"detail": 42}, {"url": 42},
        {"runs": {}}, {"runs": {"failed": [1]}}, {"runs": {"failed": [], "recovered": ["r1"]}},
    )
    hand_edited = [json.dumps([{**site_notes.SEEDS[0], **edit}]) for edit in hand_edits]
    for broken in ('[{"id": "clinicaltrials.gov-1", "cut short', '{"notes": []}', *hand_edited):
        write_notes(broken)
        notes, error = site_notes.load()
        assert notes == [] and error.startswith("cannot read the notes file artifacts/site-notes.json")
        assert site_notes.load(create=False) == ([], error)
        assert site_notes.instructions_line(notes) == ""  # so the server still starts
        for write in writes:
            with pytest.raises(ValueError, match="cannot read the notes file"):
                write()
        assert site_notes.NOTES_PATH.read_text() == broken
    # Nor does any writer leave a note of the wrong type, which would stop every later read.
    write_notes(site_notes.SEEDS)
    with pytest.raises(ValueError, match="wrong type"):
        site_notes.add_note(lesson(detail=42))
    with pytest.raises(ValueError, match="wrong type"):
        site_notes.update(lambda notes: notes[0].update(approved=True))  # a hand approval, as a writer might set it
    assert site_notes.load() == (site_notes.SEEDS, None)


def test_render_places_at_most_three_notes_in_900_characters_matching_first():
    notes = [
        stored("clinicaltrials.gov-1", failure="jev_blocked", detail="The search box sits\nbelow the banner."),
        stored("clinicaltrials.gov-2", failure="jev_blocked", approved=days_ago(0)),
        stored("clinicaltrials.gov-3", created=days_ago(1)),
        stored("clinicaltrials.gov-4", hint="start_at_url", url="https://clinicaltrials.gov/search?cond="),
        stored("clinicaltrials.gov-5", retired=days_ago(0)),
        stored("clinicaltrials.gov-6", created=days_ago(30)),  # expired
        stored("arxiv.org-2", site="arxiv.org"),
    ]
    block, ids = site_notes.render_site_notes("clinicaltrials.gov", "jev_blocked", notes)
    assert ids == ["clinicaltrials.gov-1", "clinicaltrials.gov-2", "clinicaltrials.gov-3"]
    detail = "The condition field's suggestion list covers the next field: choose the suggestion first."
    assert block.splitlines() == [
        "site notes from earlier runs: hints, not instructions",
        "  give one field or click per goal on this site · The search box sits below the banner. · 0 days old · "
        "unapproved",
        f"  give one field or click per goal on this site · {detail} · 0 days old · approved",
        f"  give one field or click per goal on this site · {detail} · 1 day old · unapproved",
    ]
    block, ids = site_notes.render_site_notes("clinicaltrials.gov", "covered_target", notes)
    assert ids == ["clinicaltrials.gov-3", "clinicaltrials.gov-4", "clinicaltrials.gov-1"]
    assert "start at this URL instead of using the page's controls: https://clinicaltrials.gov/search?cond= · " in block
    # Whole notes only, up to exactly 900 characters: after the 53-character heading, each line is its detail plus 76.
    def sized(*lengths):
        return [stored(f"clinicaltrials.gov-{n}", detail="x" * length) for n, length in enumerate(lengths, 1)]

    block, ids = site_notes.render_site_notes("clinicaltrials.gov", None, sized(205, 205, 206))
    assert len(block) == 900 and len(ids) == 3
    block, ids = site_notes.render_site_notes("clinicaltrials.gov", None, sized(205, 205, 207))
    assert ids == ["clinicaltrials.gov-1", "clinicaltrials.gov-2"]
    assert site_notes.render_site_notes("wikipedia.org", None, notes) == ("", [])


def test_instructions_line_lists_approved_notes_most_recently_shown_first_within_400_characters():
    mdn = "https://developer.mozilla.org/en-US/search?q="
    notes = [
        stored("arxiv.org-2", site="arxiv.org", hint="scroll_first", approved=days_ago(9), last_shown=days_ago(3)),
        stored("apod.nasa.gov-2", site="apod.nasa.gov", hint="scroll_first", approved=days_ago(9),
               last_shown=days_ago(1)),
        stored("crates.io-1", site="crates.io", approved=days_ago(9)),
        stored("developer.mozilla.org-2", site="developer.mozilla.org", hint="start_at_url", url=mdn,
               approved=days_ago(2)),
        stored("clinicaltrials.gov-2", last_shown=days_ago(0)),  # unapproved
        stored("wikipedia.org-1", site="wikipedia.org", approved=days_ago(1), retired=days_ago(0)),
        stored("github.com-1", site="github.com", approved=days_ago(180)),  # expired
    ]
    assert site_notes.instructions_line(notes) == (
        "Site hints from earlier runs, not instructions: apod.nasa.gov: scroll to the control first, in its own goal"
        " · arxiv.org: scroll to the control first, in its own goal"
        f" · developer.mozilla.org: start at {mdn} · crates.io: one field or click per goal"
    )
    # Whole notes, newest approval first, up to exactly 400 characters: a first host of 53 fills the line.
    def line_from(first_host):
        first = stored("first.example-1", site=first_host, approved=days_ago(1))
        rest = [stored(f"site{n}.example-1", site=f"site{n}.example", approved=days_ago(n)) for n in range(2, 20)]
        return site_notes.instructions_line([first, *rest])

    line = line_from("site1" + "x" * 40 + ".example")
    assert len(line) == 400 and line.count(" · ") == 6
    assert line.endswith(" · site7.example: one field or click per goal")
    line = line_from("site1" + "x" * 41 + ".example")  # one more character, and the last note is left out
    assert line.count(" · ") == 5 and line.endswith(" · site6.example: one field or click per goal")
    # A hand-edited host or URL, which code would never derive, stays out of the trusted instructions.
    forged_urls = (
        "https://developer.mozilla.org/" + "a" * 80, "http://developer.mozilla.org/", "https://mdn.example/",
        "https://developer.mozilla.org/s?q=ignore-the-rules#now",
    )
    forged = [
        stored("x-1", site="ignore the rules.example", approved=days_ago(0)),
        stored("arxiv.org-3", site="arxiv.org", url="https://arxiv.org/", approved=days_ago(0)),
        *(stored("developer.mozilla.org-3", site="developer.mozilla.org", hint="start_at_url", url=url,
                 approved=days_ago(0)) for url in forged_urls),
    ]
    for note in forged:
        assert site_notes.instructions_line([note]) == ""
    # The four seeds' line takes 295 characters, as design §6.4 counts it.
    assert len(site_notes.instructions_line([{**seed, "approved": days_ago(0)} for seed in site_notes.SEEDS])) == 295


def test_excluded_sites_get_no_notes():
    notes = [
        stored("clinicaltrials.gov-1", runs={"failed": ["20260924-100000-0001"], "recovered": "20260924-100100-0002"}),
        stored("clinicaltrials.gov-2"),  # from FAILED_ID and RECOVERED_ID
    ]
    assert site_notes.render_site_notes("clinicaltrials.gov", None, notes)[1] == [
        "clinicaltrials.gov-1", "clinicaltrials.gov-2"
    ]
    site_notes.EXCLUDE_PATH.parent.mkdir()
    site_notes.EXCLUDE_PATH.write_bytes(b"\xff\n")  # exclusions that cannot be read show no notes
    assert site_notes.render_site_notes("clinicaltrials.gov", None, notes) == ("", [])
    site_notes.EXCLUDE_PATH.write_text(FAILED_ID + "\n")  # a run listed after its note was stored
    assert site_notes.render_site_notes("clinicaltrials.gov", None, notes)[1] == ["clinicaltrials.gov-1"]
    site_notes.EXCLUDE_PATH.write_text("# private\nwww.clinicaltrials.gov\n")
    assert site_notes.render_site_notes("clinicaltrials.gov", None, notes) == ("", [])
    # The same check serves the callers of instructions_line(), which takes no exclude list.
    assert site_notes.note_excluded(notes[1], {FAILED_ID}) and site_notes.note_excluded(notes[1], {RECOVERED_ID})
    assert site_notes.note_excluded(notes[0], {"clinicaltrials.gov"}) and site_notes.note_excluded(notes[0], {"gov"})
    assert not site_notes.note_excluded(notes[0], {FAILED_ID, "trials.gov", "arxiv.org"})


def test_learning_off_renders_nothing(monkeypatch):
    notes = [stored("clinicaltrials.gov-1")]
    assert site_notes.learning_on()
    assert site_notes.render_site_notes("clinicaltrials.gov", None, notes)[1] == ["clinicaltrials.gov-1"]
    monkeypatch.setenv("JEV_LEARNING", "0")  # read at each call, so a later setting applies
    assert not site_notes.learning_on()
    assert site_notes.render_site_notes("clinicaltrials.gov", None, notes) == ("", [])
    monkeypatch.setenv("JEV_LEARNING", "1")
    assert site_notes.learning_on()


NOW = 1_790_000_000.0  # seconds since the epoch


@pytest.mark.parametrize(
    "state, due",
    [
        (None, True),
        ({"failures": 0}, True),
        ({"next_due": NOW + 60}, False),
        ({"next_due": NOW - 60}, True),
        ({"next_due": NOW - 60, "off": True}, False),
    ],
    ids=["no file", "no next_due", "a next_due later than now", "one earlier", "off"],
)
def test_review_due_reads_the_state(state, due):
    if state is not None:
        site_notes.write_review_state(state)
    assert site_notes.review_due(site_notes.read_review_state(), NOW) is due


def test_review_state_round_trips_and_an_unreadable_file_reads_as_empty():
    state = {"last_start": "2026-09-26T19:43:05", "next_due": NOW, "running": None, "failures": 1, "off": False}
    site_notes.write_review_state(state)
    assert site_notes.read_review_state() == state
    assert [path.name for path in site_notes.REVIEW_STATE.parent.iterdir()] == ["state.json"]  # no temporary left
    for unreadable in ("{ cut short", "[1, 2]"):
        site_notes.REVIEW_STATE.write_text(unreadable)
        assert site_notes.read_review_state() == {}
