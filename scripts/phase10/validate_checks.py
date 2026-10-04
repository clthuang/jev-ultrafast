"""Validate each task's check without model calls: its known end page must pass, its start page must fail.

Usage: uv run python scripts/phase10/validate_checks.py [TASK_ID ...]   (default: every task)
"""

import sys
import time

from tasks import TASKS

from jev_ultrafast.browser import Browser

END_PAGES = {
    "nav-python-macos": "https://www.python.org/downloads/macos/",
    "nav-wikipedia-turing-machine": "https://en.wikipedia.org/wiki/Turing_machine",
    "nav-hackernews-past": "https://news.ycombinator.com/front",
    "nav-github-cpython-issues": "https://github.com/python/cpython/issues",
    "nav-pypi-requests-history": "https://pypi.org/project/requests/#history",
    "search-wikipedia-lovelace": "https://en.wikipedia.org/wiki/Ada_Lovelace",
    "search-pypi-httpx": "https://pypi.org/project/httpx/",
    "search-wiktionary-serendipity": "https://en.wiktionary.org/wiki/serendipity",
    "search-duckduckgo-rust": "https://duckduckgo.com/?q=Rust+programming+language",
    "search-python-docs-taskgroup": "https://docs.python.org/3/search.html?q=TaskGroup",
    "forms-bmi-metric": "https://www.calculator.net/bmi-calculator.html?ctype=metric&cage=30&csex=m"
    "&cheightmeter=175&ckg=70&printit=0",
    "forms-date-duration": "https://www.timeanddate.com/date/durationresult.html?d1=1&m1=1&y1=2026&d2=15&m2=3&y2=2026",
    "nav-sqlite-download": "https://www.sqlite.org/download.html",
    "nav-xkcd-archive": "https://xkcd.com/archive/",
    "nav-rust-std-vec": "https://doc.rust-lang.org/std/vec/struct.Vec.html",
    "nav-huggingface-whisper-files": "https://huggingface.co/openai/whisper-large-v3/tree/main",
    "nav-apod-archive": "https://apod.nasa.gov/apod/archivepix.html",
    "search-mdn-flexbox": "https://developer.mozilla.org/en-US/search?q=flexbox",
    "search-pubmed-crispr": "https://pubmed.ncbi.nlm.nih.gov/?term=CRISPR+base+editing",
    "search-sep-free-will": "https://plato.stanford.edu/search/searcher.py?query=free+will",
    "search-crates-tokio": "https://crates.io/search?q=tokio",
    "search-gutenberg-moby-dick": "https://www.gutenberg.org/ebooks/search/?query=Moby+Dick",
    "forms-arxiv-diffusion-dates": "https://arxiv.org/search/advanced?advanced=&terms-0-operator=AND"
    "&terms-0-term=diffusion&terms-0-field=title&classification-physics_archives=all"
    "&classification-include_cross_list=include&date-year=&date-filter_by=date_range&date-from_date=2023-01-01"
    "&date-to_date=2023-06-30&date-date_type=submitted_date&abstracts=show&size=50&order=-announced_date_first",
    "forms-nominatim-downing-street": "https://nominatim.openstreetmap.org/ui/search.html"
    "?street=10+Downing+Street&city=London&country=United+Kingdom",
    "forms-clinicaltrials-asthma": "https://clinicaltrials.gov/search?cond=Asthma&term=inhaler",
    "forms-datatracker-http-fielding": "https://datatracker.ietf.org/doc/search?name=http&sort=&rfcs=on"
    "&activedrafts=on&by=author&author=Fielding",
    "forms-wikivoyage-compare": "https://en.wikivoyage.org/wiki/Special:ComparePages"
    "?page1=Keelung&rev1=&page2=Hsinchu&rev2=",
}


def read(url):
    browser = Browser(url)
    try:
        time.sleep(2)  # let client-side search results render
        return browser.observe(screenshot=False)
    finally:
        browser.close()


for task in TASKS:
    if sys.argv[1:] and task["id"] not in sys.argv[1:]:
        continue
    start_passes = task["check"](read(task["url"]))
    end_url = END_PAGES.get(task["id"])
    end_passes = task["check"](read(end_url)) if end_url else None
    verdict = "OK" if not start_passes and end_passes in (True, None) else "FIX"
    print(f"{verdict}  {task['id']}: start page passes={start_passes}, end page passes={end_passes}", flush=True)
