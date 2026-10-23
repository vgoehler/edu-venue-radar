"""Fetch each series' page, notice changes, and pick out dates that look like deadlines.

The crawler never edits the registry. It writes one JSON file per series under
data/crawl/, and the site shows what it saw next to the confirmed facts, so a person
decides what goes into registry.yaml.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, cast

import requests
from bs4 import BeautifulSoup

from .dates import date_lines, deadline_candidates, month_of
from .languages import language_hints
from .registry import Edition, current_edition, url_for
from .schema import CandidateRecord, CrawlRecord, PageRecord, ProbeRecord, RegistryData, SeriesData

USER_AGENT = "edu-venue-radar/0.1 (+https://github.com/vgoehler/edu-venue-radar; conference deadline watcher)"
TIMEOUT = 30
PAUSE = 1.0
MAX_CANDIDATES = 5
HTTP_OK = 200
# What `sha256` was taken over; a stored hash of another kind is a baseline, not a change.
HASH_OF = "date-lines"
# Kept from the previous run when the page cannot be read this time.
CarriedKey = Literal["sha256", "sha256_of", "changed_on", "first_seen", "candidates", "language_hints"]
CARRIED_OVER: tuple[CarriedKey, ...] = ("sha256", "sha256_of", "changed_on", "first_seen", "candidates", "language_hints")


@dataclass
class Fetched:
    """One request: `text` is set when the page is usable, `error` when the request failed."""

    url: str
    status: int | None = None
    final_url: str | None = None
    text: str | None = None
    error: str | None = None


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def fetch(session: requests.Session, url: str) -> Fetched:
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        return Fetched(url, final_url=url, error=exc.__class__.__name__)
    page = Fetched(url, r.status_code, r.url)
    if r.status_code == HTTP_OK and "html" in r.headers.get("content-type", "html"):
        page.text = page_text(r.text)
    return page


def probe(session: requests.Session, url: str) -> ProbeRecord:
    """Does an edition page exist yet? A redirect to somewhere else counts as no."""
    page = fetch(session, url)
    final = page.final_url or url
    exists = page.status == HTTP_OK and page.text is not None and final.rstrip("/") == url.rstrip("/")
    return {"url": url, "status": page.status, "final_url": final, "exists": exists}


def page_digest(text: str) -> str:
    """Hash of the date-bearing sentences only, so rotating teasers without dates do not count as a change."""
    return hashlib.sha256("\n".join(date_lines(text)).encode()).hexdigest()


def conference_start(ed: Edition) -> date | None:
    """The edition's start, or the first of the month its free text names; None when neither is known."""
    if ed.start:
        return ed.start
    return ed.approx_start if month_of(ed.when or "") else None


def _edition_text(session: requests.Session, series: SeriesData, ed: Edition) -> tuple[Fetched, PageRecord | None]:
    """The edition page and, for series that keep their dates on a separate page, that page's record.

    The separate page's text is appended to the edition page's text.
    """
    if not ed.url:
        return Fetched("", error="no URL"), None
    page = fetch(session, ed.url)
    pattern = series.get("deadlines_pattern")
    if not pattern or page.text is None:
        return page, None
    extra = fetch(session, url_for(pattern, ed.year))
    if extra.text:
        page.text = f"{page.text} {extra.text}"
    return page, {"url": extra.url, "status": extra.status}


def _record_change(result: CrawlRecord, previous: CrawlRecord, digest: str) -> None:
    """sha256, changed_on and first_seen against the last run; a new URL starts over."""
    same_page = previous.get("url") == result["url"]
    comparable = previous.get("sha256_of") == HASH_OF
    changed = same_page and comparable and previous.get("sha256") not in (None, digest)
    now = result["checked"]
    result["sha256"], result["sha256_of"] = digest, HASH_OF
    result["changed_on"] = now if changed else (previous.get("changed_on") if same_page else None)
    result["first_seen"] = (previous.get("first_seen") if same_page else None) or now


def _candidates(text: str, series: SeriesData, ed: Edition, today: date) -> list[CandidateRecord]:
    keywords = list(series.get("keywords") or ["deadline", "submission"])
    layout = series.get("layout", "prose")
    found = deadline_candidates(text, keywords, today, layout=layout, before=conference_start(ed))[:MAX_CANDIDATES]
    return [{"when": c.when.isoformat(), "keyword": c.keyword, "context": c.context} for c in found]


def _probes(session: requests.Session, pattern: str, ed: Edition) -> list[ProbeRecord]:
    """This year's and next year's page from the URL pattern, unless that is the page already crawled."""
    urls = [url_for(pattern, y) for y in (ed.year, ed.year + 1)]
    return [probe(session, u) for u in urls if u != ed.url]


def crawl_series(session: requests.Session, series: SeriesData, today: date, state_dir: Path) -> CrawlRecord:
    ed = current_edition(series, today)
    state_file = state_dir / f"{series['id']}.json"
    previous = cast(CrawlRecord, json.loads(state_file.read_text()) if state_file.exists() else {})
    now = datetime.now(UTC).isoformat(timespec="seconds")

    result: CrawlRecord = {"id": series["id"], "edition": ed.year, "url": ed.url, "checked": now}
    page, deadlines_page = _edition_text(session, series, ed)
    if deadlines_page:
        result["deadlines_url"] = deadlines_page
    result["status"], result["final_url"] = page.status, page.final_url

    if page.text is not None:
        _record_change(result, previous, page_digest(page.text))
        result["candidates"] = _candidates(page.text, series, ed, today)
        result["language_hints"] = language_hints(page.text)
    else:
        result["error"] = page.error or f"HTTP {page.status}"
        if previous.get("url") == ed.url:
            for key in CARRIED_OVER:
                if key in previous:
                    result[key] = previous[key]

    pattern = series.get("url_pattern")
    if pattern:
        result["probes"] = _probes(session, pattern, ed)

    state_file.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def crawl(registry: RegistryData, state_dir: Path, today: date, only: set[str] | None = None) -> list[CrawlRecord]:
    state_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    results = []
    for series in registry["series"]:
        if only and series["id"] not in only:
            continue
        results.append(crawl_series(session, series, today, state_dir))
        time.sleep(PAUSE)
    return results
