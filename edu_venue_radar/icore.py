"""Look up each series in the ICORE (formerly CORE) conference ranking portal."""

import html
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

PORTAL = "https://portal.core.edu.au/conf-ranks/"
PAUSE = 1.0
# title, acronym, source, rank, ...
MIN_CELLS = 4


def latest_source(session: requests.Session) -> str:
    """Newest ranking edition offered by the portal, e.g. ICORE2026."""
    page = session.get(PORTAL, timeout=30).text
    sources = re.findall(r'value="((?:I?CORE)(\d{4}))"', page)
    return max(sources, key=lambda s: int(s[1]))[0]


def parse_rows(page: str) -> list[list[str]]:
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= MIN_CELLS:
            rows.append(cells)
    return rows


def lookup(session: requests.Session, acronym: str, source: str) -> dict | None:
    params = {"search": acronym, "by": "acronym", "source": source, "sort": "atitle", "page": 1}
    page = session.get(PORTAL, params=params, timeout=30).text
    for title, acr, _source, rank, *_ in parse_rows(page):
        if acr.lower() == acronym.lower():
            return {"title": title, "acronym": acr, "rank": rank}
    return None


def update(registry: dict, out: Path, today: date) -> dict:
    session = requests.Session()
    source = latest_source(session)
    ranks: dict = {"source": source, "checked": today.isoformat(), "ranks": {}}
    for series in registry["series"]:
        acronym = series.get("icore")
        if not acronym:
            continue
        hit = lookup(session, acronym, source)
        ranks["ranks"][series["id"]] = hit or {"acronym": acronym, "rank": "not found"}
        time.sleep(PAUSE)
    out.write_text(json.dumps(ranks, indent=2, ensure_ascii=False) + "\n")
    return ranks
