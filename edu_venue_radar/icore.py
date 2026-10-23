"""Look up each series in the ICORE (formerly CORE) conference ranking portal."""

import html
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

from .crawl import TIMEOUT, USER_AGENT
from .schema import Rank, RankFile, RegistryData

PORTAL = "https://portal.core.edu.au/conf-ranks/"
PAUSE = 1.0
# title, acronym, source, rank, ...
MIN_CELLS = 4


def _get(session: requests.Session, params: dict[str, str | int] | None = None) -> str:
    r = session.get(PORTAL, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def latest_source(session: requests.Session) -> str:
    """Newest ranking edition offered by the portal, e.g. ICORE2026."""
    sources: list[tuple[str, str]] = re.findall(r'value="((?:I?CORE)(\d{4}))"', _get(session))
    if not sources:
        raise RuntimeError("ICORE portal lists no ranking edition")
    return max(sources, key=lambda s: int(s[1]))[0]


def parse_rows(page: str) -> list[list[str]]:
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= MIN_CELLS:
            rows.append(cells)
    return rows


def lookup(session: requests.Session, acronym: str, source: str) -> Rank | None:
    params: dict[str, str | int] = {"search": acronym, "by": "acronym", "source": source, "sort": "atitle", "page": 1}
    for title, acr, _source, rank, *_ in parse_rows(_get(session, params)):
        if acr.lower() == acronym.lower():
            return {"title": title, "acronym": acr, "rank": rank}
    return None


def update(registry: RegistryData, out: Path, today: date, session: requests.Session | None = None) -> RankFile:
    """Look up every series and write `out`; keeps the old file when the portal answers with nothing."""
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
    source = latest_source(session)
    ranks: RankFile = {"source": source, "checked": today.isoformat(), "ranks": {}}
    for series in registry["series"]:
        acronym = series.get("icore")
        if not acronym:
            continue
        hit = lookup(session, acronym, source)
        ranks["ranks"][series["id"]] = hit or {"acronym": acronym, "rank": "not found"}
        time.sleep(PAUSE)
    looked_up = ranks["ranks"].values()
    if looked_up and all(hit["rank"] == "not found" for hit in looked_up):
        # An error or rate-limit page parses as "no hit" for everyone; that is not a real result.
        raise RuntimeError("ICORE portal found none of the series, keeping the last ranks")
    out.write_text(json.dumps(ranks, indent=2, ensure_ascii=False) + "\n")
    return ranks
