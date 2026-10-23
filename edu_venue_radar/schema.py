"""Shapes of the data on disk: registry.yaml as loaded, and the JSON files under data/.

These are the raw structures. registry.Edition and registry.Call are the derived,
checked view of one edition; everything that reads or writes files uses the types here.
"""

from datetime import date
from typing import NotRequired, Required, TypedDict

# ruamel.yaml turns ISO dates into `date`; hand-written strings stay `str` until to_date.
DateValue = date | str | None


class CallData(TypedDict, total=False):
    deadline: DateValue
    deadline_hint: DateValue
    note: str
    closed: bool


class EditionData(TypedDict, total=False):
    url: str
    url_is_fallback: bool
    call_url: str
    location: str
    start: DateValue
    end: DateValue
    when: str
    calls: dict[str, CallData | None]


class SeriesData(TypedDict, total=False):
    id: Required[str]
    name: Required[str]
    continent: Required[str]
    # Year keys are ints from YAML, strings when written by hand in tests or JSON.
    editions: Required[dict[int | str, EditionData | None]]
    full_name: str
    organizer: str
    kind: str
    icore: str | None
    topics: list[str]
    url_pattern: str
    deadlines_pattern: str
    keywords: list[str]
    layout: str
    # ISO 639-1 codes. presentation_languages only when talks may use others than the
    # submission; proceedings_languages empty when there are no proceedings.
    languages: list[str]
    presentation_languages: list[str]
    proceedings_languages: list[str]
    language_source: str


class RegistryData(TypedDict):
    series: list[SeriesData]


class CandidateRecord(TypedDict):
    when: str
    keyword: str
    context: str


class ProbeRecord(TypedDict):
    url: str
    status: int | None
    final_url: str
    exists: bool


class PageRecord(TypedDict):
    url: str
    status: int | None
    error: NotRequired[str]


class LanguageHint(TypedDict):
    kind: str  # statement or publisher
    phrase: str
    languages: list[str]


class CrawlRecord(TypedDict, total=False):
    """data/crawl/<id>.json"""

    id: Required[str]
    edition: Required[int]
    url: Required[str | None]
    checked: Required[str]
    status: int | None
    final_url: str | None
    deadlines_url: PageRecord
    call_url: PageRecord
    sha256_of: str
    page_hashes: dict[str, str]
    changed_on: str | None
    first_seen: str | None
    candidates: list[CandidateRecord]
    language_hints: list[LanguageHint]
    error: str
    warning: str
    probes: list[ProbeRecord]


class Rank(TypedDict, total=False):
    title: str
    acronym: Required[str]
    rank: Required[str]


class RankFile(TypedDict):
    """data/icore.json"""

    source: str
    checked: str
    ranks: dict[str, Rank]
