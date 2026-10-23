"""Fetch each series' page, notice changes, and pick out dates that look like deadlines.

The crawler never edits the registry. It writes one JSON file per series under
data/crawl/, and the site shows what it saw next to the confirmed facts, so a person
decides what goes into registry.yaml.
"""

import hashlib
import json
import time
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from .dates import date_lines, deadline_candidates, month_of
from .registry import Edition, current_edition

USER_AGENT = "edu-venue-radar/0.1 (+https://github.com/vgoehler/edu-venue-radar; conference deadline watcher)"
TIMEOUT = 30
PAUSE = 1.0
MAX_CANDIDATES = 5
HTTP_OK = 200
# What `sha256` was taken over; a stored hash of another kind is a baseline, not a change.
HASH_OF = "date-lines"


def page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def fetch(session: requests.Session, url: str) -> tuple[int | None, str, str | None]:
    """Status code, final URL, and the page text (None when the page is not usable)."""
    try:
        r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        return None, url, f"error: {exc.__class__.__name__}"
    if r.status_code != HTTP_OK or "html" not in r.headers.get("content-type", "html"):
        return r.status_code, r.url, None
    return r.status_code, r.url, page_text(r.text)


def probe(session: requests.Session, url: str) -> dict:
    """Does an edition page exist yet? A redirect to somewhere else counts as no."""
    status, final, text = fetch(session, url)
    exists = status == HTTP_OK and text is not None and final.rstrip("/") == url.rstrip("/")
    return {"url": url, "status": status, "final_url": final, "exists": exists}


def page_digest(text: str) -> str:
    """Hash of the date-bearing sentences only, so rotating teasers without dates do not count as a change."""
    return hashlib.sha256("\n".join(date_lines(text)).encode()).hexdigest()


def conference_start(ed: Edition) -> date | None:
    """The edition's start, or the first of the month its free text names; None when neither is known."""
    if ed.start:
        return ed.start
    return ed.approx_start if month_of(ed.when or "") else None


def crawl_series(session: requests.Session, series: dict, today: date, state_dir: Path) -> dict:
    ed = current_edition(series, today)
    state_file = state_dir / f"{series['id']}.json"
    previous = json.loads(state_file.read_text()) if state_file.exists() else {}
    now = datetime.now(UTC).isoformat(timespec="seconds")

    result: dict = {"id": series["id"], "edition": ed.year, "url": ed.url, "checked": now}
    status, final, text = fetch(session, ed.url) if ed.url else (None, None, None)
    result.update(status=status, final_url=final)

    # Some series keep their dates on a separate page; its text joins the main page's.
    dl_pattern = series.get("deadlines_pattern")
    if dl_pattern and text is not None and not text.startswith("error:"):
        dl_url = dl_pattern.format(year=ed.year, yy=f"{ed.year % 100:02d}")
        dl_status, _, dl_text = fetch(session, dl_url)
        result["deadlines_url"] = {"url": dl_url, "status": dl_status}
        if dl_text and not dl_text.startswith("error:"):
            text = f"{text} {dl_text}"

    if text is not None and not str(text).startswith("error:"):
        digest = page_digest(text)
        same_page = previous.get("url") == ed.url
        comparable = previous.get("sha256_of") == HASH_OF
        changed = same_page and comparable and previous.get("sha256") not in (None, digest)
        result["sha256"], result["sha256_of"] = digest, HASH_OF
        result["changed_on"] = now if changed else (previous.get("changed_on") if same_page else None)
        result["first_seen"] = previous.get("first_seen") if same_page and previous.get("first_seen") else now
        keywords = list(series.get("keywords") or ["deadline", "submission"])
        layout = series.get("layout", "prose")
        found = deadline_candidates(text, keywords, today, layout=layout, before=conference_start(ed))[:MAX_CANDIDATES]
        result["candidates"] = [{**asdict(c), "when": c.when.isoformat()} for c in found]
    else:
        result["error"] = text if isinstance(text, str) else f"HTTP {status}"
        for key in ("sha256", "sha256_of", "changed_on", "first_seen", "candidates"):
            if key in previous and previous.get("url") == ed.url:
                result[key] = previous[key]

    pattern = series.get("url_pattern")
    if pattern:
        result["probes"] = [
            probe(session, pattern.format(year=y, yy=f"{y % 100:02d}"))
            for y in (ed.year, ed.year + 1)
            if pattern.format(year=y, yy=f"{y % 100:02d}") != ed.url
        ]

    state_file.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


def crawl(registry: dict, state_dir: Path, today: date, only: set[str] | None = None) -> list[dict]:
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
