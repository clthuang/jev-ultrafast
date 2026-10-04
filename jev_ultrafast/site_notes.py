"""Learning from failed runs: failure codes, next steps, site notes and review state; the executor never imports it."""

import fcntl
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from . import store_io

# Stop texts, copied from the code that writes them.
STALE_STREAK_STOP = "Three choices in a row went stale while the page read stayed the same:"  # Agent.command
NAMED_COVER = "Target is covered by <"  # browser_operation's stale message, naming the element over the target
JEV_BLOCKED_STOP = "Jev answered BLOCKED"  # start_run
STILL_LOADING_STOP = "Jev judged the page still loading"  # Agent.command
BUDGET_STOP = "Reached the demo's model-call budget"  # Agent.command
# browser-harness's timeout, as in "Runtime.evaluate timed out after 5s waiting for the daemon" (helpers.py, _send).
HARNESS_TIMEOUT = re.compile(r"[\w.]+ timed out after [\d.]+s")

# Each rule reads the run's status and its first stop note, the stop reason; later notes, such as "fresh read
# failed: …", are not. A rule matches server text from the note's start, so page text quoted in a note can at worst
# pick the wrong one of four fixed sentences. Their statuses and texts differ, so a run matches one rule at most.
FAILURE_RULES = {
    "covered_target": lambda status, note, last_step: (
        status == "blocked" and note.startswith(STALE_STREAK_STOP) and NAMED_COVER in note
    ),
    "jev_blocked": lambda status, note, last_step: status == "blocked" and note == JEV_BLOCKED_STOP,
    "still_loading": lambda status, note, last_step: status == "blocked" and note == STILL_LOADING_STOP,
    # The read after the last step timed out: the step ran, and its page_changed is still None.
    "busy_after_step": lambda status, note, last_step: (
        status == "stopped"
        and HARNESS_TIMEOUT.match(note)
        and last_step is not None
        and last_step["page_changed"] is None
    ),
}
# Delegated decision D8 (docs/failure-review.md §11): each failure code has a sentence. still_loading came later, with
# decision D17 (docs/executor-improvements.md §5).
# Verbatim from docs/failure-review.md §5. With a failure code, the result's next: line names its recovery.
NEXT_BY_FAILURE = {
    "covered_target": "a control kept covering the target, such as an open suggestion list or a password manager's "
    "menu. Give one field or click per goal, starting with controls it does not cover. A goal may choose the site's "
    "suggestion the task needs; never choose an entry from a password manager's menu",
    "jev_blocked": "Jev answered BLOCKED. If the screenshot shows the page waiting for the user, such as for a "
    "sign-in, a passcode, a verification code or a CAPTCHA, call show_window, ask them to finish it there, and then "
    "continue with run_goal without url. If it shows the page still loading, run a goal for what remains without url: "
    "Jev answers again on the page as it is then, without reloading it. If Jev's last answer shows a runner-up within "
    "0.2 of BLOCKED, that runner-up often names the step to try. If the control may be further down, first run a goal "
    "that only scrolls until it shows, then the rest. If Jev cannot see it at all, as with a search box inside a "
    "shadow DOM or frame, open the results URL directly, or use Claude in Chrome",
    "still_loading": "Jev judged the page still loading, twice, and the page did not change. If the screenshot shows "
    "it still loading, run a goal for what remains, often just its end state, without url: Jev answers again on the "
    "page as it is then, without reloading it. Re-ask at most twice. If it waits for the user, call show_window. "
    "If it looks finished, recover as for Jev answering BLOCKED",
    "busy_after_step": "the page stayed busy after the last step, which ran: check the page before running the goal "
    "again",
}


def failure_code(status, notes, history):
    """The code of the rule that the run's status, first stop note and last step match, or None."""
    note = notes[0] if notes else ""
    last_step = history[-1] if history else None
    return next((code for code, rule in FAILURE_RULES.items() if rule(status, note, last_step)), None)


def stale_budget(run):
    """The report's flag for a budget stop with more than half of its decisions stale; no code can name its cause."""
    notes = (run.get("result") or {}).get("notes") or []  # a run file saved before its stop has no result
    note = notes[0] if notes else ""
    return note == BUDGET_STOP and run["stale_decisions"] > len(run["decisions"]) / 2


def host_of(url):
    """The URL's host, lowercase and without a trailing dot, or "" when it has none or does not parse."""
    try:
        return (urlsplit(url or "").hostname or "").rstrip(".")  # clinicaltrials.gov. is clinicaltrials.gov
    except ValueError:  # a malformed URL, such as one with an unclosed IPv6 bracket
        return ""


# Delegated decision D1 (docs/failure-review.md §11): key notes by the host without www.
def site_key(url):
    """The key of a site's notes: the URL's host without www., keeping subdomains, as in apod.nasa.gov."""
    return host_of(url).removeprefix("www.")


# Delegated decision D2 (docs/failure-review.md §11): four hints, each with a fixed sentence; no free-form hint.
# From design §6.1: the sentence a result shows, and the short form for the server's instructions. <url> stands for
# the note's URL, which only start_at_url has.
HINTS = {
    "one_action_per_goal": {
        "sentence": "give one field or click per goal on this site",
        "short_form": "one field or click per goal",
    },
    "scroll_first": {
        "sentence": "a control here sits below the first view: scroll to it first, as a goal of its own if Jev still "
        "answers BLOCKED",
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

BUILD_DATE = "2026-09-27"
# A note is shaped as design §6.1, plus last_shown (P10) and retired, the marker of a retired note: the date it was
# retired, or null while it is in use. Retired and expired notes stay in the file for the report, and are never shown.
# Delegated decision D12 (docs/failure-review.md §11): seed notes are dated from the build.
# Delegated decision P7 (docs/failure-review-plan.md): seed notes live in code, dated by the build date as a literal;
# the notes file is created from them when missing.
# The four notes of design §6.2, which the user approved on 2026-09-26 (§12, decision 2). Their runs are the
# recoveries in qa-census.md, and ClinicalTrials.gov's code comes from the later re-test of its quirk (§6.1).
SEEDS = [
    {"id": "clinicaltrials.gov-1", "site": "clinicaltrials.gov", "hint": "one_action_per_goal",
     "detail": "The condition field's suggestion list covers the next field: choose the suggestion first.",
     "url": None, "failure": "covered_target",
     "runs": {"failed": ["20260924-113417-40d8", "20260924-113517-88f4"], "recovered": "20260924-113700-fc97"},
     "approved": BUILD_DATE, "created": BUILD_DATE, "shown": 0, "last_shown": None, "failed_after": 0, "retired": None},
    {"id": "apod.nasa.gov-1", "site": "apod.nasa.gov", "hint": "scroll_first",
     "detail": "The Archive link sits below the day's image.",
     "url": None, "failure": "jev_blocked",
     "runs": {"failed": ["20260924-110859-1ba9"], "recovered": "20260924-110909-aefe"},
     "approved": BUILD_DATE, "created": BUILD_DATE, "shown": 0, "last_shown": None, "failed_after": 0, "retired": None},
    {"id": "arxiv.org-1", "site": "arxiv.org", "hint": "scroll_first",
     "detail": "The advanced search's date fields sit below the first view.",
     "url": None, "failure": "jev_blocked",
     "runs": {"failed": ["20260924-112406-f39e", "20260924-112421-fc87"], "recovered": "20260924-112457-6710"},
     "approved": BUILD_DATE, "created": BUILD_DATE, "shown": 0, "last_shown": None, "failed_after": 0, "retired": None},
    {"id": "developer.mozilla.org-1", "site": "developer.mozilla.org", "hint": "start_at_url",
     "detail": "The search box sits inside a shadow DOM that Jev cannot read.",
     "url": "https://developer.mozilla.org/en-US/search?q=", "failure": "jev_blocked",
     "runs": {"failed": ["20260924-111127-8224", "20260924-111150-69f5", "20260924-111225-096c"],
              "recovered": "20260924-111244-b98c"},
     "approved": BUILD_DATE, "created": BUILD_DATE, "shown": 0, "last_shown": None, "failed_after": 0, "retired": None},
]


def run_site(run):
    """A run's site: the host of its final page, without www. (design §3)."""
    return site_key((run.get("page") or {}).get("url"))


def within(host, domain):
    """True when host is domain or one of its subdomains."""
    return host == domain or host.endswith("." + domain)


# Delegated decision P21 (docs/failure-review-plan.md): one definition of a failed run, for the server's lessons and
# the review's queue and recoveries alike.
def run_failed(run):
    """A run that failed: it did not end done, or its latest label is failed. A run with no result has not finished."""
    return (run.get("result") or {}).get("status") != "done" or latest_label(run) is False


def latest_label(run):
    """A run's latest label by the user, else by Claude, as scripts/report_runs.py reads them; None when unlabelled."""
    for by in ("user", "claude"):
        label = next((o["passed"] for o in reversed(run.get("outcome") or []) if o.get("by") == by), None)
        if label is not None:
            return label
    return None


def links(runs):
    """Each run's link, the run its server ran before it: its previous_run; for runs recorded before the build, the
    latest earlier run with the same pid; None when it has neither key, or its link is not another run in runs.

    A previous_run can sort after its own run: two runs saved in one second sort by their random suffix."""
    found, last_by_pid = {}, {}
    for run_id in sorted(runs):
        run = runs[run_id]
        link = run["previous_run"] if "previous_run" in run else last_by_pid.get(run.get("pid"))
        found[run_id] = link if isinstance(link, str) and link != run_id and link in runs else None
        if run.get("pid") is not None:
            last_by_pid[run["pid"]] = run_id
    return found


# Delegated decision P14 (docs/failure-review-plan.md): a chain is the attempts at one sub-goal, linked runs cut where
# the site changes or after a run labelled passed; a possible false DONE follows the link, not the chain.
def chains(runs):
    """The attempts at each sub-goal: a list of chains, each a dict from run ID to run, oldest first.

    runs: a dict from run ID to run. A run joins its link's chain unless the link ended on another site, or its latest
    label is passed. The links set the order, not the IDs; a loop of links, which only a hand edit makes, is cut where
    the walk meets it."""
    joins = {}  # each run's link, if the run joins that link's chain
    for run_id, link in links(runs).items():
        ended = link is None or run_site(runs[link]) != run_site(runs[run_id]) or latest_label(runs[link]) is True
        joins[run_id] = None if ended else link
    chain_of, found = {}, []
    for last in sorted(runs):
        path, run_id = [], last  # from this run back along the joins, to a run already placed or a chain's first run
        while run_id is not None and run_id not in chain_of and run_id not in path:
            path.append(run_id)
            run_id = joins[run_id]
        for run_id in reversed(path):  # oldest first
            if joins[run_id] in chain_of:
                chain_of[run_id] = chain_of[joins[run_id]]
            else:
                chain_of[run_id] = {}
                found.append(chain_of[run_id])
            chain_of[run_id][run_id] = runs[run_id]
    return found


def possible_false_dones(runs):
    """IDs of DONE runs whose next linked run, on the same site, took no step (design §4), whatever their label."""
    flagged, followed = [], set()
    for run_id, link in links(runs).items():
        if link is None or link in followed:
            continue
        followed.add(link)  # only the next run counts
        done, run = runs[link], runs[run_id]
        was_done = (done.get("result") or {}).get("status") == "done"
        finished = run.get("result") is not None  # a run file saved mid-run has no result yet
        if was_done and finished and run_site(run) == run_site(done) and not run.get("history"):
            flagged.append(link)
    return flagged


def visited_urls(run):
    """Every URL a run visited (design §6.7): call.url, each decision's page URL, each step's url and page.url."""
    urls = [(run.get("call") or {}).get("url")]
    urls += [d.get("observed_url") for d in run.get("decisions", [])]
    urls += [((d.get("request") or {}).get("state") or {}).get("page", {}).get("url")
             for d in run.get("decisions", [])]
    urls += [step.get("url") for step in run.get("history", [])]
    urls.append((run.get("page") or {}).get("url"))
    return [url for url in urls if url]


# Delegated decision D11 (docs/failure-review.md §11): the exclude file starts with the user's two private runs.
EXCLUDE_PATH = Path("artifacts/review-exclude.txt")


def read_exclude(path):
    """The run IDs and hosts a file lists, one per line, # starting a comment; a missing file excludes nothing.

    www. and a trailing dot are dropped, as in site keys, so a listed host covers the whole site and its subdomains;
    a pasted URL stands for its host. Any other read error raises: exclusions that cannot be read must stop what
    depends on them."""
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        return set()
    exclude = set()
    for line in lines:
        entry = line.split("#", 1)[0].strip().lower()
        if "://" in entry:
            entry = host_of(entry) or entry
        if entry := entry.rstrip(".").removeprefix("www."):
            exclude.add(entry)
    return exclude


def excluded(run_id, run, exclude):
    """True when exclude lists the run's ID, or a host the run visited, or a domain above that host (design §6.7)."""
    hosts = {host_of(url) for url in visited_urls(run)}
    return run_id in exclude or any(within(host, entry) for host in hosts for entry in exclude)


# Shorter values, typed or quoted, would match common words.
MIN_VALUE_CHARACTERS = 3
# Delegated decision P16 (docs/failure-review-plan.md): task values match whole, and by each of their words of 4
# characters or more, at word boundaries, so a surname typed with its first name counts alone; shorter words, such
# as "the" and "new", would refuse nearly every detail. A run of digits matches between non-digits, so UA1234 holds
# 1234, and a start_at_url URL is checked without its host.
MIN_WORD_CHARACTERS = 4
# Double quotes, straight or curly, only: a single quote is also an apostrophe.
QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DIGIT_RUN = re.compile(r"\d{4,}")


def task_values(chain):
    """The task's values, lowercase, that no note may hold (design §6.5): text of 3 characters or more typed in the
    chain's runs, and the quoted values, e-mail addresses and runs of 4 or more digits in their goals. Each value's
    words of MIN_WORD_CHARACTERS or more are values too (P16)."""
    values = set()
    for run in chain.values():
        goal = run.get("goal") or ""
        texts = [step.get("text") for step in run.get("history", [])]
        texts += [call.get("value") for call in run.get("text_calls", [])]
        texts += [straight or curly for straight, curly in QUOTED.findall(goal)]
        values.update(" ".join(text.split()).lower() for text in texts if text)
        values.update(email.lower() for email in EMAIL.findall(goal))
        values.update(DIGIT_RUN.findall(goal))
    values = {value for value in values if len(value) >= MIN_VALUE_CHARACTERS}
    words = {word for value in values for word in re.findall(r"[^\W_]+", value) if len(word) >= MIN_WORD_CHARACTERS}
    return values | words


def task_value_pattern(values):
    """A regex for any of the values, ignoring case and spacing: how every check and summary matches task values
    (design §6.5). A value's words match joined by spaces, underscores, pluses or hyphens, as URLs and names join them,
    between characters that are not letters or digits; when it is all digits, between non-digits (P16)."""
    alternatives = []
    for value in sorted(values, key=len, reverse=True):  # longest first, so a summary replaces "john smith" whole
        words = [word for word in re.split(r"[\s_+-]+", value) if word]
        if not words:
            continue  # only joining characters: nothing to find
        edge = r"\d" if value.isdigit() else r"[^\W_]"
        alternatives.append(rf"(?<!{edge})" + r"[\s_+-]+".join(map(re.escape, words)) + rf"(?!{edge})")
    return re.compile("|".join(alternatives) if alternatives else r"(?!)", re.IGNORECASE)  # (?!): no match


DETAIL_CHARACTERS = 300
URL_CHARACTERS = 100
# A scheme, www., or a dotted host followed by a path.
URL_IN_TEXT = re.compile(r"\w+://|\bwww\.|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}/", re.IGNORECASE)
# A URL's scheme and host, which the task-value check skips: the host is the note's own site, already stored in site
# and shown in plain view, so a search typed for "mozilla" must not refuse MDN's URL (P16). Any user info stays.
SCHEME_AND_HOST = re.compile(r"^\w[\w+.-]*://(?P<userinfo>[^/?#@]*@)?[^/?#]*")


def strip_query(url):
    """The URL without its user info, query values or fragment, each of which can hold values. Query names stay, as
    in MDN's ?q=; a query part with no name, such as ?flexbox, is a value, and goes."""
    parts = urlsplit(url)
    pairs = (part.partition("=") for part in parts.query.split("&"))
    names = "&".join(f"{name}=" for name, equals, _ in pairs if equals and name)
    return urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], parts.path, names, ""))


def url_refusal(url, site):
    """Why a start_at_url URL is refused, or None: it must be https, on the site or one of its subdomains."""
    if not url.lower().startswith("https://"):
        return "its URL is not https"
    # A browser reads a backslash as "/": https://evil.com\.developer.mozilla.org/x opens evil.com, where urlsplit
    # reads a host on MDN. A plain host name, with no backslash anywhere, reads the same in both.
    if "\\" in url or not HOST.fullmatch(host_of(url)):
        return "its URL's host is not a plain host name"
    if not site or not within(host_of(url), site):
        return "its URL is not on the note's site"
    return None


def note_url(chain):
    """For start_at_url: the last run's call.url without its query values, if it is https on the run's site or a
    subdomain; otherwise None (design §6.3). Code derives it; no free text does."""
    run = list(chain.values())[-1]
    url = (run.get("call") or {}).get("url")
    return strip_query(url) if url and url_refusal(url, run_site(run)) is None else None


VALUE_REFUSAL = "its detail or URL holds a value from the task"


def url_holds(url, values):
    """True when a note URL holds one of the values (a task_value_pattern()) outside its scheme and host: raw, as
    /u/jane_doe holds a typed jane_doe, and decoded with underscores as spaces, as /u/Jane_Doe and /people/Mr%20Smith
    hold a typed name."""
    raw = SCHEME_AND_HOST.sub(r"\g<userinfo>", url or "")
    return bool(values.search(raw) or values.search(unquote_plus(raw).replace("_", " ")))


def check_note(note, chain, exclude):
    """The reasons code refuses to store a note, before any write (design §6.5); none when it may be stored.

    chain: the note's runs, oldest first; its last run is the one the lesson follows. exclude: from read_exclude()."""
    run = list(chain.values())[-1]
    values = task_value_pattern(task_values(chain))
    detail = note["detail"] or ""  # a lesson's detail is optional
    reasons = []
    if note["hint"] not in HINTS:
        reasons.append("its hint is not one of " + ", ".join(HINTS))
    if not str((run.get("page") or {}).get("url") or "").lower().startswith(("https://", "http://")):
        reasons.append("its run did not end on a web page")  # about:blank has no site; an error page, a fake one
    elif note["site"] != run_site(run):
        reasons.append("its site is not the site of the run's final page")
    if len(detail) > DETAIL_CHARACTERS:
        reasons.append(f"its detail is over {DETAIL_CHARACTERS} characters")
    if URL_IN_TEXT.search(detail):
        reasons.append("its detail holds a URL")
    if values.search(detail) or url_holds(note["url"], values):
        reasons.append(VALUE_REFUSAL)
    if any(excluded(run_id, chain[run_id], exclude) for run_id in chain):
        reasons.append("its site or one of its runs is excluded")
    call_url = (run.get("call") or {}).get("url")
    if note["hint"] == "start_at_url":
        if not call_url:
            reasons.append("start_at_url needs a run that started at a URL: its call.url")
        elif refusal := url_refusal(call_url, note["site"]):
            reasons.append(refusal)
        elif len(strip_query(call_url)) > URL_CHARACTERS:
            reasons.append(f"its URL is over {URL_CHARACTERS} characters")
        elif note["url"] != strip_query(call_url):
            reasons.append("its URL is not the run's call.url without its user info, query values and fragment")
    elif note["url"] is not None:
        reasons.append("only start_at_url takes a URL")
    return reasons


# Relative to the working directory, like mcp_server.py's RUNS. Its lock sits beside it: artifacts/site-notes.lock.
NOTES_PATH = Path("artifacts/site-notes.json")
# What a writer gives add_note(); the store adds the rest of a note's fields (see SEEDS).
WRITER_FIELDS = ("site", "hint", "detail", "url", "failure", "runs")
NOTE_KEYS = ("id", *WRITER_FIELDS, "approved", "created", "shown", "last_shown", "failed_after", "retired")
# Delegated decision D3 (docs/failure-review.md §11): at most 3 notes and 900 characters per result, 5 notes per
# site, and 400 characters in the instructions.
MAX_NOTES_SHOWN = 3
SITE_NOTES_CHARACTERS = 900
MAX_NOTES_PER_SITE = 5
INSTRUCTION_NOTES_CHARACTERS = 400
# Delegated decision D5 (docs/failure-review.md §11): notes expire, unapproved after 30 days, approved 180 days after
# their approval.
UNAPPROVED_DAYS = 30
APPROVED_DAYS = 180
# Delegated decision D6 (docs/failure-review.md §11): an unapproved note retires after 2 failures with its code, on
# its site, after it was shown.
RETIRE_AFTER_FAILURES = 2


def active(note, today):
    """True until a note is retired or expires (D5): unapproved, UNAPPROVED_DAYS after its creation; approved,
    APPROVED_DAYS after its approval. Neither kind is shown, and both stay in the file."""
    start, days = (note["approved"], APPROVED_DAYS) if note["approved"] else (note["created"], UNAPPROVED_DAYS)
    return not note["retired"] and today < date.fromisoformat(start) + timedelta(days=days)


class NotesStoreError(ValueError):
    """Malformed notes are infrastructure failure, never a semantic decision refusal."""


def validate_envelope(envelope):
    if (not isinstance(envelope, dict) or type(envelope.get("schema_version")) is not int
            or envelope["schema_version"] != 2):
        raise NotesStoreError("unsupported notes schema")
    if not isinstance(envelope.get("notes"), list) or not all(map(well_formed, envelope["notes"])):
        raise NotesStoreError("a note lacks a field, or has one of the wrong type")
    if "pending_review" not in envelope:
        raise NotesStoreError("missing pending review field")
    receipt = envelope["pending_review"]
    if receipt is not None:
        from . import review_records
        if not isinstance(receipt, dict) or not isinstance(receipt.get("digest"), dict):
            raise NotesStoreError("malformed pending review receipt")
        digest = review_records.validate(receipt["digest"], "digest")
        if receipt.get("batch_id") != digest["batch_id"] or receipt.get("reply_sha256") != digest["reply_sha256"]:
            raise NotesStoreError("pending receipt identity mismatch")
    return envelope


def read_envelope(path):
    try:
        value = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise NotesStoreError(f"cannot read the notes file {path}: {error}") from error
    if isinstance(value, list):
        value = {"schema_version": 2, "notes": value, "pending_review": None}
    try:
        return validate_envelope(value)
    except ValueError as error:
        raise NotesStoreError(f"cannot read the notes file {path}: {error}") from error


def read_notes(path):
    """Public list reader accepts legacy lists and the transaction envelope."""
    try:
        envelope = read_envelope(path)
        return (None if envelope is None else envelope["notes"]), None
    except NotesStoreError as error:
        return [], str(error)


def is_date(value):
    """True for a date as the store writes one: an ISO string, such as "2026-09-27"."""
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def well_formed(note):
    """True when a note has every field, each of the type the store writes, as a hand edit need not leave it."""
    if not isinstance(note, dict) or not set(NOTE_KEYS) <= note.keys() or not isinstance(note["runs"], dict):
        return False
    failed, recovered = note["runs"].get("failed"), note["runs"].get("recovered")
    return (
        all(isinstance(note[key], str) for key in ("id", "site", "hint"))
        and note["hint"] in HINTS
        and all(isinstance(note[key], (str, type(None))) for key in ("detail", "url", "failure"))
        and is_date(note["created"])
        and all(note[key] is None or is_date(note[key]) for key in ("approved", "last_shown", "retired"))
        and all(type(note[key]) is int for key in ("shown", "failed_after"))
        and isinstance(failed, list)
        and all(isinstance(run_id, str) for run_id in failed)
        and isinstance(recovered, (str, type(None)))
    )


# Delegated decision P8 (docs/failure-review-plan.md): an unreadable notes file shows no notes, and nothing writes it
# until it parses again; replies and the report show its error.
def load(path=NOTES_PATH, create=True):
    """The notes and None, or no notes and the error that stops them. A missing file is created from SEEDS (P7), unless
    create is false: then there are no notes, and nothing is written."""
    notes, error = read_notes(path)
    if notes is not None or not create:
        return notes or [], error
    try:
        return update(lambda notes: notes, path), None
    except (OSError, ValueError) as error:
        return [], str(error)


def transaction(change, path=NOTES_PATH, *, write=True):
    """One notes lock around a private envelope; callbacks use only pure helpers."""
    path = Path(path).parent.resolve() / Path(path).name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        envelope = read_envelope(path)
        if envelope is None:
            envelope = {"schema_version": 2, "notes": json.loads(json.dumps(SEEDS)), "pending_review": None}
        result = change(envelope)
        validate_envelope(envelope)
        if write:
            store_io.publish(path, envelope)
        return result


def update(change, path=NOTES_PATH):
    """List-facing writer preserves every envelope field, including pending receipt."""
    return transaction(lambda envelope: change(envelope["notes"]), path)


# Delegated decision P9 (docs/failure-review-plan.md): a new note on a site whose 5 notes are all approved is refused,
# with the reason in the reply.
def add_note_to(notes, note):
    """Pure helper: reserve an ID and site capacity on this transaction's list."""
    today = date.today()
    on_site = [n for n in notes if n["site"] == note["site"]]
    in_use = [n for n in on_site if active(n, today)]
    if len(in_use) >= MAX_NOTES_PER_SITE:
        unapproved = [n for n in in_use if not n["approved"]]
        if not unapproved:
            raise ValueError(f"{note['site']} already has {MAX_NOTES_PER_SITE} approved notes")
        min(unapproved, key=lambda n: n["created"])["retired"] = today.isoformat()
    ids, number = {n["id"] for n in notes}, len(on_site) + 1
    while f"{note['site']}-{number}" in ids:
        number += 1
    stored = {"id": f"{note['site']}-{number}", **{field: note[field] for field in WRITER_FIELDS}, "approved": None,
              "created": today.isoformat(), "shown": 0, "last_shown": None, "failed_after": 0, "retired": None}
    notes.append(stored)
    return stored["id"]


def add_note(note, path=NOTES_PATH):
    return update(lambda notes: add_note_to(notes, note), path)


def record_shown(ids, path=NOTES_PATH):
    """Counts a result that showed these notes: shown, and last_shown, for the instructions line's order (P10)."""
    if not ids:
        return
    today = date.today().isoformat()

    def change(notes):
        for note in notes:
            if note["id"] in ids:
                note["shown"] += 1
                note["last_shown"] = today

    update(change, path)


# Delegated decision P20 (docs/failure-review-plan.md): a failure counts against an unapproved note only when this
# server's results showed it, since the instructions never do; an approved note counts as before.
def record_failure(site, code, path=NOTES_PATH, shown=None):
    """Counts a failed run on site against its notes in use with that failure code that a result has shown. An
    unapproved one retires after RETIRE_AFTER_FAILURES such runs; an approved one stays, for the report to flag (D6).

    shown: the IDs of the notes this server's results showed; an unapproved note outside it is not counted. None
    counts every note a result has shown."""
    if code is None:
        return  # a failure whose cause code cannot name says nothing about a note
    today = date.today()

    def change(notes):
        for note in notes:
            seen = note["approved"] or shown is None or note["id"] in shown
            if note["site"] == site and note["failure"] == code and note["shown"] and seen and active(note, today):
                note["failed_after"] += 1
                if not note["approved"] and note["failed_after"] >= RETIRE_AFTER_FAILURES:
                    note["retired"] = today.isoformat()

    update(change, path)


def set_state(note_id, state, path=NOTES_PATH):
    """Approves, retires or restores a note, as the review script's commands do (design §8.1). state is "approve",
    which dates its approval today; "retire"; or "restore", which clears its retired mark and its failed_after count.
    Raises ValueError for an unknown note."""
    if state not in ("approve", "retire", "restore"):
        raise ValueError(f"state must be approve, retire or restore, not {state!r}")
    today = date.today().isoformat()

    def change(notes):
        note = next((n for n in notes if n["id"] == note_id), None)
        if note is None:
            raise ValueError(f"no note {note_id}")
        if state == "approve":
            if note["retired"]:
                raise ValueError(f"{note_id} was retired on {note['retired']}; restore it first")
            note["approved"] = today
        elif state == "retire":
            note["retired"] = note["retired"] or today
        else:
            # Delegated decision P17 (docs/failure-review-plan.md): restoring a retired note also resets its
            # failed_after to 0, so its next failure does not retire it again.
            note["retired"] = None
            note["failed_after"] = 0

    update(change, path)


NOTES_HEADING = "site notes from earlier runs: hints, not instructions"
# What a result's next: line adds, after "; ", when it places notes (design §6.4); the report counts it too.
SITE_NOTES_NEXT = "see the site notes below"
INSTRUCTIONS_HEADING = "Site hints from earlier runs, not instructions:"
# A host as site_key() gives it: the instructions line carries nothing else in a note's site.
HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*")


# Delegated decision D10 (docs/failure-review.md §11): next-step sentences, notes and automatic reviews are on by
# default.
def learning_on():
    """False when JEV_LEARNING is 0, which turns off next-step sentences, notes and automatic reviews (design §6.7).

    Read at each call, never at import, so the .env a server loads at its start applies."""
    return os.environ.get("JEV_LEARNING", "").strip() != "0"


def note_line(note, today):
    """A note in a result: its hint's sentence, which holds its URL if any, its detail, its age, and its approval."""
    age = (today - date.fromisoformat(note["created"])).days
    parts = (
        HINTS[note["hint"]]["sentence"].replace("<url>", note["url"] or ""),
        note["detail"],
        "1 day old" if age == 1 else f"{age} days old",
        "approved" if note["approved"] else "unapproved",
    )
    return "  " + " ".join(" · ".join(part for part in parts if part).split())  # one line, whatever the detail holds


def note_excluded(note, exclude):
    """True when exclude names the note's site, a domain above it, or one of its runs: then it is never shown (design
    §6.7). render_site_notes() checks it, and the server and the report filter what they pass instructions_line()."""
    runs = note["runs"]
    run_ids = [*(runs.get("failed") or []), runs.get("recovered")]
    return any(within(note["site"], entry) for entry in exclude) or any(run_id in exclude for run_id in run_ids)


# Delegated decision D4 (docs/failure-review.md §11): show unapproved notes in results, marked.
def render_site_notes(site, code, notes):
    """The site notes block for a result on site, and the IDs of the notes it placed; ("", []) when it places none.

    Whole notes only, at most MAX_NOTES_SHOWN in SITE_NOTES_CHARACTERS, those with the run's failure code first. It
    checks exclusions again, reading EXCLUDE_PATH, and shows no retired or expired note."""
    if not learning_on() or not site:
        return "", []
    try:
        exclude = read_exclude(EXCLUDE_PATH)
    except (OSError, ValueError):
        return "", []  # exclusions that cannot be read show no notes
    today = date.today()
    candidates = [
        note for note in notes if note["site"] == site and active(note, today) and not note_excluded(note, exclude)
    ]
    candidates.sort(key=lambda note: code is None or note["failure"] != code)  # the run's code first, else file order
    lines, ids = [NOTES_HEADING], []
    for note in candidates:
        line = note_line(note, today)
        if len(ids) < MAX_NOTES_SHOWN and len("\n".join([*lines, line])) <= SITE_NOTES_CHARACTERS:
            lines.append(line)
            ids.append(note["id"])
    return ("\n".join(lines), ids) if ids else ("", [])


def fits_instructions(note):
    """True when a note's host and URL are what code derives, as a hand edit need not leave them: the instructions are
    trusted text (design §8.1)."""
    if not HOST.fullmatch(note["site"]):
        return False
    if note["hint"] != "start_at_url":
        return note["url"] is None
    url = note["url"]
    return (
        isinstance(url, str) and len(url) <= URL_CHARACTERS and url_refusal(url, note["site"]) is None
        and url == strip_query(url)
    )


# Delegated decision D7 (docs/failure-review.md §11): only notes the user approved reach the instructions, as host,
# fixed short form and a derived URL of at most 100 characters.
# Delegated decision P10 (docs/failure-review-plan.md): the instructions line takes whole notes, most recently shown
# first, then never-shown ones by newest approval.
def instructions_line(notes):
    """The line the server adds to its instructions, at most INSTRUCTION_NOTES_CHARACTERS; "" with none to list.

    Each approved note in use gives its host and its hint's short form, which for start_at_url holds its URL; never its
    detail."""
    today = date.today()
    approved = [note for note in notes if note["approved"] and active(note, today) and fits_instructions(note)]
    approved.sort(key=lambda n: (n["last_shown"] is not None, n["last_shown"] or "", n["approved"]), reverse=True)
    entries = []
    for note in approved:
        entry = f"{note['site']}: " + HINTS[note["hint"]]["short_form"].replace("<url>", note["url"] or "")
        if len(f"{INSTRUCTIONS_HEADING} {' · '.join([*entries, entry])}") <= INSTRUCTION_NOTES_CHARACTERS:
            entries.append(entry)
    return f"{INSTRUCTIONS_HEADING} {' · '.join(entries)}" if entries else ""


# Relative to the working directory, like NOTES_PATH. Its keys are under "Files and formats" in the plan.
REVIEW_STATE = Path("artifacts/reviews/state.json")


# Delegated decision P15 (docs/failure-review-plan.md): scripts/review_runs.py writes next_due and off into
# state.json, and site_notes.py owns reading it, so the three lanes share one format.
def read_review_state(path=REVIEW_STATE):
    """The review state's keys, or {} when the file is missing or unreadable."""
    try:
        state = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def write_review_state(state, path=REVIEW_STATE):
    """Replaces the review state atomically. Only scripts/review_runs.py calls it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    store_io.publish(path, state)


def review_due(state, now):
    """True unless automatic reviews are off, or next_due is later than now, both in seconds since the epoch."""
    return not state.get("off") and (state.get("next_due") or 0) <= now
