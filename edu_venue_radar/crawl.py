"""Fetch each series' page, notice changes, and pick out dates that look like deadlines.

The crawler never edits the registry. It writes one JSON file per series under
data/crawl/, and the site shows what it saw next to the confirmed facts, so a person
decides what goes into registry.yaml.
"""

import codecs
import hashlib
import json
import sys
import threading
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
# Limits per page, so a huge or trickling response cannot stall the weekly run. MAX_SECONDS is
# enforced by a watchdog that closes the connection, so it holds even while a read blocks.
MAX_BYTES = 2_000_000
MAX_SECONDS = 60
CHUNK = 65_536
PAUSE = 1.0
MAX_CANDIDATES = 5
HTTP_OK = 200
# What the page hashes were taken over; a stored hash of another kind is a baseline, not a change.
HASH_OF = "date-lines-by-page"
# Kept from the previous run when the page cannot be read this time.
CarriedKey = Literal["sha256_of", "page_hashes", "changed_on", "first_seen", "candidates", "language_hints"]
CARRIED_OVER: tuple[CarriedKey, ...] = (
    "sha256_of",
    "page_hashes",
    "changed_on",
    "first_seen",
    "candidates",
    "language_hints",
)


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


def _decode(data: bytes, headers: dict[str, str] | requests.structures.CaseInsensitiveDict[str], encoding: str | None) -> str:
    """Decode with the declared charset if Python knows it, else UTF-8, else cp1252.

    requests assumes ISO-8859-1 for text/html without a charset, but most such pages are UTF-8;
    browsers accept charset names Python does not know (x-user-defined), so those fall back too.
    """
    if "charset" in headers.get("content-type", "").lower() and encoding:
        try:
            return data.decode(codecs.lookup(encoding).name, errors="replace")
        except LookupError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def read_body(r: requests.Response) -> str | None:
    """The response text, or None when it is larger than MAX_BYTES or takes longer than MAX_SECONDS."""
    announced = r.headers.get("content-length", "").strip()
    if announced.isdigit() and int(announced) > MAX_BYTES:
        return None
    expired = threading.Event()

    def stop() -> None:
        expired.set()
        r.close()

    watchdog = threading.Timer(MAX_SECONDS, stop)
    watchdog.start()
    size, chunks = 0, []
    try:
        for chunk in r.iter_content(CHUNK):
            size += len(chunk)
            if size > MAX_BYTES or expired.is_set():
                return None
            chunks.append(chunk)
    except Exception:
        # Closing the connection from the watchdog breaks the blocked read in one of several ways.
        if expired.is_set():
            return None
        raise
    finally:
        watchdog.cancel()
    return _decode(b"".join(chunks), r.headers, r.encoding)


def fetch(session: requests.Session, url: str) -> Fetched:
    try:
        with session.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True) as r:
            page = Fetched(url, r.status_code, r.url)
            if r.status_code != HTTP_OK or "html" not in r.headers.get("content-type", "html"):
                return page
            body = read_body(r)
    except requests.RequestException as exc:
        return Fetched(url, final_url=url, error=exc.__class__.__name__)
    if body is None:
        page.error = "page too large or too slow"
    else:
        page.text = page_text(body)
    return page


def probe(session: requests.Session, url: str) -> ProbeRecord:
    """Does an edition page exist yet? A redirect to somewhere else counts as no."""
    page = fetch(session, url)
    final = page.final_url or url
    exists = page.status == HTTP_OK and final.rstrip("/") == url.rstrip("/")
    return {"url": url, "status": page.status, "final_url": final, "exists": exists}


def page_digest(text: str) -> str:
    """Hash of the date-bearing sentences only, so rotating teasers without dates do not count as a change."""
    return hashlib.sha256("\n".join(date_lines(text)).encode()).hexdigest()


def conference_start(ed: Edition) -> date | None:
    """The edition's start, or the first of the month its free text names; None when neither is known."""
    if ed.start:
        return ed.start
    return ed.approx_start if month_of(ed.when or "") else None


ExtraPage = Literal["deadlines_url", "call_url"]


@dataclass
class EditionPages:
    """What one crawl read for an edition: the edition page, its extra pages, and the text of every usable page."""

    main: Fetched
    extras: dict[ExtraPage, PageRecord]
    texts: dict[str, str]

    @property
    def text(self) -> str | None:
        return " ".join(self.texts.values()) if self.texts else None


def _read_edition(session: requests.Session, series: SeriesData, ed: Edition) -> EditionPages:
    """The edition page plus its extra pages: the separate dates page of series that keep their
    dates apart, and the edition's call page. Without a usable edition page the call page stands in.
    """
    main = fetch(session, ed.url) if ed.url else Fetched("", error="no URL")
    pages = EditionPages(main, {}, {main.url: main.text} if main.text is not None else {})
    extras: list[tuple[ExtraPage, str]] = []
    pattern = series.get("deadlines_pattern")
    if pattern and main.text is not None:
        extras.append(("deadlines_url", url_for(pattern, ed.year)))
    if ed.call_url and ed.call_url != ed.url:
        extras.append(("call_url", ed.call_url))
    for key, url in extras:
        extra = fetch(session, url)
        record: PageRecord = {"url": extra.url, "status": extra.status}
        if extra.text is None:
            record["error"] = extra.error or f"HTTP {extra.status}"
        else:
            pages.texts[url] = extra.text
        pages.extras[key] = record
    return pages


def _record_change(result: CrawlRecord, previous: CrawlRecord, texts: dict[str, str]) -> None:
    """page_hashes, changed_on and first_seen against the last run.

    Each page has its own hash, and only pages read in both runs are compared: a page that was
    down or is new is a baseline, and a flickering call page still shows its real changes.
    A new edition URL starts over.
    """
    hashes = {url: page_digest(text) for url, text in sorted(texts.items())}
    same_page = previous.get("url") == result["url"]
    before = previous.get("page_hashes", {}) if previous.get("sha256_of") == HASH_OF else {}
    changed = same_page and any(url in before and before[url] != h for url, h in hashes.items())
    now = result["checked"]
    # Keep the last hash of a page that is down this time, so it is compared when it is back.
    result["page_hashes"] = {**before, **hashes} if same_page else hashes
    result["sha256_of"] = HASH_OF
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
    pages = _read_edition(session, series, ed)
    for extra_key, record in pages.extras.items():
        result[extra_key] = record
    main = pages.main
    result["status"], result["final_url"] = main.status, main.final_url
    main_problem = main.error or f"HTTP {main.status}"

    if (text := pages.text) is not None:
        if main.text is None:
            result["warning"] = f"edition page unreadable ({main_problem}), read the call page instead"
        _record_change(result, previous, pages.texts)
        result["candidates"] = _candidates(text, series, ed, today)
        result["language_hints"] = language_hints(text)
    else:
        result["error"] = main_problem
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
        try:
            results.append(crawl_series(session, series, today, state_dir))
        except Exception as exc:  # one broken site must not stop the weekly run
            print(f"{series['id']}: crawl failed: {exc!r}", file=sys.stderr)
        time.sleep(PAUSE)
    return results
