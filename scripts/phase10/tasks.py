"""Phase 10 comparison tasks, chosen on the user's behalf: public sites, no login, nothing submitted or bought.

Each task has a kind (by how many fields need typed text), a start URL, a goal, and a deterministic check on the
final page read (the snapshot.js page dict: url, title, text, actions). Both arms are judged by the same check.
"""

import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.flights import URL as FLIGHTS_URL  # noqa: E402
from examples.flights import goal_for, verify  # noqa: E402

# Pinned to the executor arm's dates (run 2026-09-24), so the Chrome arm gets the same goals on any later day.
DEPARTURE = date(2026, 10, 22)
FLIGHTS_GOAL = goal_for(DEPARTURE)
VARIANT_DEPARTURE = date(2026, 10, 29)
VARIANT_DATE = f"{VARIANT_DEPARTURE:%B} {VARIANT_DEPARTURE.day}, {VARIANT_DEPARTURE.year}"


def host(page):
    return (urlparse(page["url"]).hostname or "").removeprefix("www.")


def path(page):
    return urlparse(page["url"]).path


def query(page, key):
    return " ".join(parse_qs(urlparse(page["url"]).query).get(key, [])).strip().lower()


def field(page, label_part):
    """Value of the first observed field whose label contains label_part (case-insensitive)."""
    for action in page["actions"]:
        if label_part.lower() in action["label"].lower() and action.get("value") is not None:
            return str(action["value"]).strip()
    return None


def checked(page, label_part):
    # The snapshot reports checked as the string "true", not a boolean.
    return any(
        label_part.lower() in a["label"].lower() and str(a.get("checked")).lower() == "true" for a in page["actions"]
    )


def flights_variant(page):
    """Like examples.flights.verify, for Geneva to Berlin on VARIANT_DEPARTURE."""
    day_label = f"{VARIANT_DEPARTURE:%a}, {VARIANT_DEPARTURE:%b} {VARIANT_DEPARTURE.day}"
    long_label = f"{VARIANT_DEPARTURE:%A}, {VARIANT_DEPARTURE:%B} {VARIANT_DEPARTURE.day}"
    flights = [a["label"] for a in page["actions"] if "Select flight" in a["label"]]
    return (
        host(page) == "google.com"
        and path(page) == "/travel/flights/search"
        and field(page, "ticket type") == "One way"
        and (field(page, "Where from?") or "").startswith("Geneva")
        and (field(page, "Where to?") or "").startswith("Berlin")
        and field(page, "Departure") == day_label
        and bool(flights)
        and all(long_label in f for f in flights)
    )


TASKS = [
    # navigation: no typed text
    dict(
        id="nav-python-macos",
        kind="navigation",
        url="https://www.python.org/",
        goal="Open the python.org downloads page for macOS. Stop there.",
        check=lambda p: host(p) == "python.org" and path(p).rstrip("/") == "/downloads/macos",
    ),
    dict(
        id="nav-wikipedia-turing-machine",
        kind="navigation",
        url="https://en.wikipedia.org/wiki/Alan_Turing",
        goal="From this Wikipedia article, follow the link to the article about the Turing machine. Stop there.",
        check=lambda p: host(p) == "en.wikipedia.org" and path(p) == "/wiki/Turing_machine",
    ),
    dict(
        id="nav-hackernews-past",
        kind="navigation",
        url="https://news.ycombinator.com/",
        goal="Open the Hacker News 'past' page, which lists earlier front pages. Stop there.",
        check=lambda p: host(p) == "news.ycombinator.com" and path(p) == "/front",
    ),
    dict(
        id="nav-github-cpython-issues",
        kind="navigation",
        url="https://github.com/python/cpython",
        goal="Open this repository's Issues tab. Stop there.",
        check=lambda p: host(p) == "github.com" and path(p).rstrip("/") == "/python/cpython/issues",
    ),
    dict(
        id="nav-pypi-requests-history",
        kind="navigation",
        url="https://pypi.org/project/requests/",
        goal="Open this project's release history. Stop there.",
        check=lambda p: (
            host(p) == "pypi.org"
            and path(p).rstrip("/") == "/project/requests"
            and urlparse(p["url"]).fragment == "history"
        ),
    ),
    # search: one typed field
    dict(
        id="search-wikipedia-lovelace",
        kind="search",
        url="https://en.wikipedia.org/wiki/Main_Page",
        goal="Search Wikipedia for Ada Lovelace and open her article. Stop there.",
        check=lambda p: host(p) == "en.wikipedia.org" and path(p) == "/wiki/Ada_Lovelace",
    ),
    dict(
        id="search-pypi-httpx",
        kind="search",
        url="https://pypi.org/",
        goal="Search PyPI for httpx and open the httpx project page. Stop there.",
        check=lambda p: host(p) == "pypi.org" and path(p).rstrip("/") == "/project/httpx",
    ),
    dict(
        id="search-wiktionary-serendipity",
        kind="search",
        url="https://en.wiktionary.org/wiki/Wiktionary:Main_Page",
        goal="Look up the word serendipity and open its entry. Stop there.",
        check=lambda p: host(p) == "en.wiktionary.org" and path(p) == "/wiki/serendipity",
    ),
    dict(
        id="search-duckduckgo-rust",
        kind="search",
        url="https://duckduckgo.com/",
        goal="Search for Rust programming language and stop when the results page is showing.",
        # The URL, not result text: a final read can precede rendering, which would penalize the earlier reader.
        check=lambda p: (
            host(p) == "duckduckgo.com"
            and query(p, "q") == "rust programming language"
            and "bots use duckduckgo" not in p["text"].lower()
        ),
    ),
    dict(
        id="search-python-docs-taskgroup",
        kind="search",
        url="https://docs.python.org/3/",
        goal="Search the Python documentation for TaskGroup and stop on the search results page.",
        check=lambda p: (
            host(p) == "docs.python.org" and path(p).endswith("/search.html") and query(p, "q") == "taskgroup"
        ),
    ),
    # forms: two or more typed fields
    dict(
        id="forms-flights-example",
        kind="forms",
        url=FLIGHTS_URL,
        goal=FLIGHTS_GOAL,
        check=lambda p: verify(p, DEPARTURE)["passed"],
    ),
    dict(
        id="forms-flights-geneva-berlin",
        kind="forms",
        url=FLIGHTS_URL,
        goal=f"Find one-way flights from Geneva to Berlin on {VARIANT_DATE}, for one adult in economy. "
        "Stop when matching flight options are visible. Do not select or book a flight.",
        check=flights_variant,
    ),
    dict(
        id="forms-bmi-metric",
        kind="forms",
        url="https://www.calculator.net/bmi-calculator.html",
        goal="Using metric units, calculate the BMI of a 30-year-old male who is 175 cm tall and weighs 70 kg. "
        "Stop when the result is shown.",
        check=lambda p: (
            host(p) == "calculator.net"
            and query(p, "ctype") == "metric"
            and query(p, "cage") == "30"
            and query(p, "csex") == "m"
            and query(p, "cheightmeter") == "175"
            and query(p, "ckg") == "70"
        ),
    ),
    dict(
        id="forms-date-duration",
        kind="forms",
        url="https://www.timeanddate.com/date/duration.html",
        goal="Calculate the number of days from January 1, 2026 to March 15, 2026. Stop when the result is shown.",
        check=lambda p: (
            host(p) == "timeanddate.com"
            # Numbers, not strings: a day typed as "01" is still January 1.
            and [int(query(p, k) or 0) for k in ("d1", "m1", "y1", "d2", "m2", "y2")] == [1, 1, 2026, 15, 3, 2026]
        ),
    ),
    dict(
        id="forms-httpbin-pizza",
        kind="forms",
        url="https://httpbin.org/forms/post",
        goal="Fill in the pizza order form: customer name Ada Lovelace, telephone 555-0100, e-mail "
        "ada@example.com, size Medium, topping Bacon. Do not submit the order.",
        check=lambda p: (
            host(p) == "httpbin.org"
            and path(p) == "/forms/post"
            and field(p, "Customer name") == "Ada Lovelace"
            and field(p, "Telephone") == "555-0100"
            and field(p, "E-mail") == "ada@example.com"
            and checked(p, "Medium")
            and checked(p, "Bacon")
            and not any(checked(p, topping) for topping in ("Extra Cheese", "Onion", "Mushroom"))
        ),
    ),
    # Round 2 (plan decision 9): 5 more goals per kind, chosen by an independent agent before any of them ran.
    # navigation: no typed text
    # Criteria: static project site; one "Download" link on the start page; no login, wall, or locale redirect.
    # Check: host sqlite.org, path /download.html.
    dict(
        id="nav-sqlite-download",
        kind="navigation",
        url="https://www.sqlite.org/index.html",
        goal="Open the SQLite download page. Stop there.",
        check=lambda p: host(p) == "sqlite.org" and path(p) == "/download.html",
    ),
    # Criteria: static webcomic site; header "Archive" link (/archive redirects to /archive/); no wall.
    # Check: host xkcd.com, path /archive (trailing slash optional).
    dict(
        id="nav-xkcd-archive",
        kind="navigation",
        url="https://xkcd.com/",
        goal="Open the xkcd archive, which lists every comic. Stop there.",
        check=lambda p: host(p) == "xkcd.com" and path(p).rstrip("/") == "/archive",
    ),
    # Criteria: static generated API docs; the std index links vec/struct.Vec.html; no wall or locale.
    # Check: host doc.rust-lang.org, path ends /std/vec/struct.Vec.html (a /stable/ or version prefix also passes).
    dict(
        id="nav-rust-std-vec",
        kind="navigation",
        url="https://doc.rust-lang.org/std/",
        goal="Open the documentation page for the Vec struct. Stop there.",
        check=lambda p: host(p) == "doc.rust-lang.org" and path(p).endswith("/std/vec/struct.Vec.html"),
    ),
    # Criteria: public model page, no login; "Files and versions" tab links /tree/main; client-routed site.
    # Check: host huggingface.co, path /openai/whisper-large-v3/tree/main.
    dict(
        id="nav-huggingface-whisper-files",
        kind="navigation",
        url="https://huggingface.co/openai/whisper-large-v3",
        goal="Open this model's Files and versions tab. Stop there.",
        check=lambda p: host(p) == "huggingface.co" and path(p).rstrip("/") == "/openai/whisper-large-v3/tree/main",
    ),
    # Criteria: static NASA page; "Archive" (and "Discover the cosmos!") link archivepix.html; no wall.
    # Check: host apod.nasa.gov, path /apod/archivepix.html.
    dict(
        id="nav-apod-archive",
        kind="navigation",
        url="https://apod.nasa.gov/apod/astropix.html",
        goal="Open the Astronomy Picture of the Day archive, which lists past pictures. Stop there.",
        check=lambda p: host(p) == "apod.nasa.gov" and path(p) == "/apod/archivepix.html",
    ),
    # search: one typed field
    # Criteria: one query box; its list ends with a site-search entry to /en-US/search?q= (the page returns 200).
    # Check: host developer.mozilla.org, path ends /search (any locale), q == flexbox.
    dict(
        id="search-mdn-flexbox",
        kind="search",
        url="https://developer.mozilla.org/en-US/",
        goal="Search MDN for flexbox and stop on the search results page.",
        check=lambda p: (
            host(p) == "developer.mozilla.org" and path(p).endswith("/search") and query(p, "q") == "flexbox"
        ),
    ),
    # Criteria: one GET box (form action /, input term); many results, so no single-hit redirect; no wall.
    # Check: host pubmed.ncbi.nlm.nih.gov, path /, term == crispr base editing.
    dict(
        id="search-pubmed-crispr",
        kind="search",
        url="https://pubmed.ncbi.nlm.nih.gov/",
        goal="Search PubMed for CRISPR base editing and stop on the search results page.",
        check=lambda p: (
            host(p) == "pubmed.ncbi.nlm.nih.gov" and path(p) == "/" and query(p, "term") == "crispr base editing"
        ),
    ),
    # Criteria: one GET box (form action search/searcher.py, input query); static server-rendered results.
    # Check: host plato.stanford.edu, path /search/searcher.py, query == free will.
    dict(
        id="search-sep-free-will",
        kind="search",
        url="https://plato.stanford.edu/",
        goal="Search the Stanford Encyclopedia of Philosophy for free will and stop on the search results page.",
        check=lambda p: (
            host(p) == "plato.stanford.edu" and path(p) == "/search/searcher.py" and query(p, "query") == "free will"
        ),
    ),
    # Criteria: one header box; SvelteKit form (action /search, input q) routes to /search?q=; no wall.
    # Check: host crates.io, path /search, q == tokio.
    dict(
        id="search-crates-tokio",
        kind="search",
        url="https://crates.io/",
        goal="Search crates.io for tokio and stop on the search results page.",
        check=lambda p: host(p) == "crates.io" and path(p) == "/search" and query(p, "q") == "tokio",
    ),
    # Criteria: one "Quick search" GET box (action /ebooks/search/, input query); static results; no wall.
    # Check: host gutenberg.org, path /ebooks/search (trailing slash optional), query == moby dick.
    dict(
        id="search-gutenberg-moby-dick",
        kind="search",
        url="https://www.gutenberg.org/",
        goal="Search Project Gutenberg for Moby Dick and stop on the search results page.",
        check=lambda p: (
            host(p) == "gutenberg.org" and path(p).rstrip("/") == "/ebooks/search" and query(p, "query") == "moby dick"
        ),
    ),
    # forms: two or more typed fields
    # Criteria: 3 typed fields (term, from date, to date); read-only GET search, no side effects; no wall.
    # Check: host arxiv.org, path /search/advanced, terms-0-term diffusion, terms-0-field title (the default),
    # date-filter_by date_range (set when a date box is focused), date-from_date 2023-01-01, date-to_date 2023-06-30.
    dict(
        id="forms-arxiv-diffusion-dates",
        kind="forms",
        url="https://arxiv.org/search/advanced",
        goal="Using the advanced search, find papers with diffusion in the title submitted from 2023-01-01 "
        "to 2023-06-30. Stop when the results are shown.",
        check=lambda p: (
            host(p) == "arxiv.org"
            and path(p).rstrip("/") == "/search/advanced"
            and query(p, "terms-0-term") == "diffusion"
            and query(p, "terms-0-field") == "title"
            and query(p, "date-filter_by") == "date_range"
            and query(p, "date-from_date") == "2023-01-01"
            and query(p, "date-to_date") == "2023-06-30"
        ),
    ),
    # Criteria: 3 typed fields on the Structured tab; read-only geocoding lookup; submit pushState-s the params.
    # Check: host nominatim.openstreetmap.org, path /ui/search.html, street/city/country as given.
    dict(
        id="forms-nominatim-downing-street",
        kind="forms",
        url="https://nominatim.openstreetmap.org/ui/search.html",
        goal="Using the structured search, look up street 10 Downing Street, city London, country United Kingdom. "
        "Stop when the results are shown.",
        check=lambda p: (
            host(p) == "nominatim.openstreetmap.org"
            and path(p) == "/ui/search.html"
            and query(p, "street") == "10 downing street"
            and query(p, "city") == "london"
            and query(p, "country") == "united kingdom"
        ),
    ),
    # Criteria: 2 typed fields (Condition/disease -> cond, Other terms -> term); read-only search; no login or wall.
    # Check: host clinicaltrials.gov, path /search, cond == asthma, term == inhaler.
    dict(
        id="forms-clinicaltrials-asthma",
        kind="forms",
        url="https://clinicaltrials.gov/",
        goal="Search for studies with condition/disease asthma and other terms inhaler. "
        "Stop when the search results are shown.",
        check=lambda p: (
            host(p) == "clinicaltrials.gov"
            and path(p) == "/search"
            and query(p, "cond") == "asthma"
            and query(p, "term") == "inhaler"
        ),
    ),
    # Criteria: 2 typed fields (name, author) plus the Author criterion; read-only GET search; no login or wall.
    # Check: host datatracker.ietf.org, path /doc/search, name http, by author, author fielding (the author box is
    # disabled until its criterion is chosen, so author appears in the URL only with by=author).
    dict(
        id="forms-datatracker-http-fielding",
        kind="forms",
        url="https://datatracker.ietf.org/doc/search",
        goal="Search for IETF documents with http in the name or title and Fielding as the author. "
        "Stop when the search results are shown.",
        check=lambda p: (
            host(p) == "datatracker.ietf.org"
            and path(p).rstrip("/") == "/doc/search"
            and query(p, "name") == "http"
            and query(p, "by") == "author"
            and query(p, "author") == "fielding"
        ),
    ),
    # Criteria: 2 typed fields (Page 1, Page 2); read-only GET diff, nothing saved; no login, wall, or consent.
    # Check: host en.wikivoyage.org, path /wiki/Special:ComparePages, page1 keelung, page2 hsinchu.
    dict(
        id="forms-wikivoyage-compare",
        kind="forms",
        url="https://en.wikivoyage.org/wiki/Special:ComparePages",
        goal="Compare the Wikivoyage articles Keelung as page 1 and Hsinchu as page 2. "
        "Stop when the comparison is shown.",
        check=lambda p: (
            host(p) == "en.wikivoyage.org"
            and unquote(path(p)) == "/wiki/Special:ComparePages"
            and query(p, "page1") == "keelung"
            and query(p, "page2") == "hsinchu"
        ),
    ),
    # 10.1 seed: the repo's two other existing tasks, passed verbatim (the Flights example is forms-flights-example)
    dict(
        id="seed-wikipedia-godel",
        kind="seed",
        url="https://en.wikipedia.org/wiki/Main_Page",
        goal="Find and open the Wikipedia article about Gödel’s incompleteness theorems.",
        check=lambda p: host(p) == "en.wikipedia.org" and unquote(path(p)) == "/wiki/Gödel's_incompleteness_theorems",
    ),
    dict(
        id="seed-hotel-fixture",
        kind="seed",
        url="http://127.0.0.1:8766/fixture.html?scenario=travel",
        goal="Use the destination search and filters to find Design stays in Lisbon with Free cancellation, "
        "then open Casa Flora.",
        check=lambda p: (
            p["url"].endswith("#casa-flora")
            and "Your filters: Design · Free cancellation enabled · Destination Lisbon" in p["text"]
        ),
    ),
]

if __name__ == "__main__":
    for task in TASKS:
        print(task["kind"], task["id"], task["url"])
    print(len(TASKS), "tasks;", {k: sum(t["kind"] == k for t in TASKS) for k in ("navigation", "search", "forms")})
    Path(__file__).with_name("tasks.txt").write_text("\n".join(f"{t['id']}\t{t['goal']}" for t in TASKS))
