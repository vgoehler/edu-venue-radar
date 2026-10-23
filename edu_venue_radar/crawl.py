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
# Limits per page, so a huge or trickling response cannot stall the weekly run.
MAX_BYTES = 2_000_000
MAX_SECONDS = 60
CHUNK = 65_536
PAUSE = 1.0
MAX_CANDIDATES = 5
HTTP_OK = 200
# What `sha256` was taken over; a stored hash of another kind is a baseline, not a change.
HASH_OF = "date-lines-per-page"
# Kept from the previous run when the page cannot be read this time.
CarriedKey = Literal["sha256", "sha256_of", "hashed_pages", "changed_on", "first_seen", "candidates", "language_hints"]
CARRIED_OVER: tuple[CarriedKey, ...] = (
    "sha256",
    "sha256_of",
    "hashed_pages",
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


def _body(r: requests.Response) -> str | None:
    """The response text, or None when it is larger than MAX_BYTES or takes longer than MAX_SECONDS."""
    if int(r.headers.get("content-length") or 0) > MAX_BYTES:
        return None
    started, size, chunks = time.monotonic(), 0, []
    for chunk in r.iter_content(CHUNK):
        size += len(chunk)
        if size > MAX_BYTES or time.monotonic() - started > MAX_SECONDS:
            return None
        chunks.append(chunk)
    data = b"".join(chunks)
    # requests assumes ISO-8859-1 for text/html without a charset; most such pages are UTF-8.
    if "charset" in r.headers.get("content-type", "").lower() and r.encoding:
        return data.decode(r.encoding, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def fetch(session: requests.Session, url: str) -> Fetched:
    try:
        with session.get(url, timeout=TIMEOUT, allow_redirects=True, stream=True) as r:
            page = Fetched(url, r.status_code, r.url)
            if r.status_code != HTTP_OK or "html" not in r.headers.get("content-type", "html"):
                return page
            body = _body(r)
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
    exists = page.status == HTTP_OK and page.text is not None and final.rstrip("/") == url.rstrip("/")
    return {"url": url, "status": page.status, "final_url": final, "exists": exists}


def page_digest(texts: dict[str, str]) -> str:
    """Hash of the date-bearing sentences of each page, so rotating teasers without dates do not count as a change.

    Each page is hashed on its own and under its URL, so text moving between pages or a page
    being added does not look like the same page changing.
    """
    parts = [f"{url}\n" + "\n".join(date_lines(text)) for url, text in sorted(texts.items())]
    return hashlib.sha256("\n\n".join(parts).encode()).hexdigest()


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
        pages.extras[key] = {"url": extra.url, "status": extra.status}
        if extra.text:
            pages.texts[url] = extra.text
    return pages


def _record_change(result: CrawlRecord, previous: CrawlRecord, texts: dict[str, str]) -> None:
    """sha256, changed_on and first_seen against the last run.

    A new edition URL starts over. When the set of readable pages differs from the last run
    (a page was down, or a call page was added), the hash is a new baseline, not a change.
    """
    digest, hashed = page_digest(texts), sorted(texts)
    same_page = previous.get("url") == result["url"]
    comparable = previous.get("sha256_of") == HASH_OF and previous.get("hashed_pages") == hashed
    changed = same_page and comparable and previous.get("sha256") not in (None, digest)
    now = result["checked"]
    result["sha256"], result["sha256_of"], result["hashed_pages"] = digest, HASH_OF, hashed
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
        results.append(crawl_series(session, series, today, state_dir))
        time.sleep(PAUSE)
    return results
