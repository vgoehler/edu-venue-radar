"""The registry of conference series and the logic that picks the edition worth showing.

The YAML file is the source of truth for confirmed facts. Everything here is derived:
which edition is current, what its deadline probably is, and what the next edition
looks like before anyone has entered it.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TypeGuard, cast

from ruamel.yaml import YAML

from .dates import month_of
from .schema import CallData, DateValue, EditionData, RegistryData, SeriesData

# How long after an expected (not confirmed) deadline we still treat a call as open.
GRACE_DAYS = 14

CONTINENTS = ["Europe", "North America", "South America", "Australia and Asia-Pacific", "Africa", "Online"]
LAYOUTS = {"prose", "date-first"}
# The fields documented in the header of registry.yaml; anything else is a typo.
SERIES_KEYS = {
    "id",
    "name",
    "full_name",
    "organizer",
    "kind",
    "icore",
    "continent",
    "topics",
    "url_pattern",
    "deadlines_pattern",
    "keywords",
    "layout",
    "editions",
    "languages",
    "presentation_languages",
    "proceedings_languages",
    "language_source",
}
SERIES_REQUIRED = {"id", "name", "continent", "editions", "languages", "language_source"}
LANGUAGE_FIELDS = {"languages", "presentation_languages", "proceedings_languages"}
LANGUAGE_SOURCES = {"stated", "inferred"}
EDITION_KEYS = {"url", "url_is_fallback", "call_url", "location", "start", "end", "when", "calls"}
CALL_KEYS = {"deadline", "deadline_hint", "note", "closed"}
LIST_FIELDS = {"topics", "keywords"} | LANGUAGE_FIELDS
BOOL_FIELDS = {"url_is_fallback", "closed"}
TEXT_FIELDS = {
    "id",
    "name",
    "full_name",
    "organizer",
    "kind",
    "icore",
    "continent",
    "url_pattern",
    "deadlines_pattern",
    "layout",
    "url",
    "call_url",
    "location",
    "when",
    "note",
    "language_source",
}


def _yaml() -> YAML:
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load(path: Path) -> RegistryData:
    with path.open(encoding="utf-8") as fh:
        data = _yaml().load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a mapping with a series list")
    return cast(RegistryData, data)


def save(data: RegistryData, path: Path) -> None:
    with path.open("w", encoding="utf-8") as fh:
        _yaml().dump(data, fh)


def to_date(value: DateValue) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _shift_year(d: date, year: int) -> date:
    try:
        return d.replace(year=year)
    except ValueError:  # 29 February
        return d.replace(year=year, day=28)


@dataclass
class Call:
    """One call of an edition: workshops, papers, special sessions, ..."""

    kind: str
    deadline: date | None = None
    hint: date | None = None
    note: str | None = None
    closed: bool = False
    expected: date | None = None

    def effective_deadline(self) -> date | None:
        return self.deadline or self.expected

    def status(self, today: date) -> str:
        """open, expected, unknown or closed."""
        if self.deadline:
            return "open" if self.deadline >= today else "closed"
        if self.closed:
            return "closed"
        if self.expected:
            return "closed" if (today - self.expected).days > GRACE_DAYS else "expected"
        return "unknown"


STATUS_ORDER = ["open", "expected", "unknown", "closed"]


@dataclass
class Edition:
    series_id: str
    year: int
    url: str | None
    url_is_fallback: bool
    location: str | None
    start: date | None
    end: date | None
    when: str | None
    calls: list[Call] = field(default_factory=list)
    synthesized: bool = False
    call_url: str | None = None

    @property
    def approx_start(self) -> date:
        """Conference date, or a stand-in from the free text, for ordering and estimates."""
        if self.start:
            return self.start
        month = month_of(self.when or "") or 7
        return date(self.year, month, 1)

    @property
    def evidence(self) -> str:
        """How much of the edition is confirmed.

        confirmed: at least one deadline confirmed for this edition;
        partial: something of this edition is known (its dates, place or own page), deadlines only from last year;
        guessed: nothing of this edition is known yet, everything comes from the previous one.
        """
        if any(c.deadline for c in self.calls) and not self.synthesized:
            return "confirmed"
        own_page = bool(self.url) and not self.url_is_fallback
        place = bool(self.location) and not (self.location or "").startswith("not announced")
        if not self.synthesized and (self.start or own_page or place):
            return "partial"
        return "guessed"

    def live_calls(self, today: date) -> list[Call]:
        return [c for c in self.calls if c.status(today) != "closed"]

    def next_deadline(self, today: date) -> date | None:
        """Soonest deadline among the calls that are not over."""
        dates = [d for c in self.live_calls(today) if (d := c.effective_deadline())]
        return min(dates) if dates else None

    def status(self, today: date) -> str:
        """The most open status among the calls; an edition without calls is unknown."""
        if not self.calls:
            return "unknown"
        return min((c.status(today) for c in self.calls), key=STATUS_ORDER.index)


def expected_from_hint(hint: date, conference: date) -> date:
    """The previous cycle's deadline moved to the latest year that still lies before the conference."""
    guess = _shift_year(hint, conference.year)
    while guess >= conference:
        guess = _shift_year(guess, guess.year - 1)
    return guess


def edition(series: SeriesData, year: int) -> Edition:
    editions = series["editions"]
    raw: EditionData = (editions[year] if year in editions else editions[str(year)]) or {}
    ed = Edition(
        series_id=series["id"],
        year=int(year),
        url=raw.get("url"),
        url_is_fallback=bool(raw.get("url_is_fallback", False)),
        location=raw.get("location"),
        start=to_date(raw.get("start")),
        end=to_date(raw.get("end")),
        when=raw.get("when"),
        call_url=raw.get("call_url"),
    )
    for kind, raw_call in (raw.get("calls") or {}).items():
        c: CallData = raw_call or {}
        call = Call(
            kind=kind,
            deadline=to_date(c.get("deadline")),
            hint=to_date(c.get("deadline_hint")),
            note=c.get("note"),
            closed=bool(c.get("closed", False)),
        )
        if not call.deadline and call.hint:
            call.expected = expected_from_hint(call.hint, ed.approx_start)
        ed.calls.append(call)
    return ed


def next_edition(prev: Edition) -> Edition:
    """The edition after `prev`, guessed from it until someone enters the real one."""
    year = prev.year + 1
    month = prev.approx_start.strftime("%B")
    prev_place = prev.location or "unknown"
    location = prev_place if prev_place.startswith("not announced") else f"not announced ({prev.year}: {prev_place})"
    # The previous edition's page is what exists today; the crawler probes url_pattern
    # for the new year and reports when that page goes online.
    ed = Edition(
        series_id=prev.series_id,
        year=year,
        url=prev.url,
        url_is_fallback=True,
        location=location,
        start=None,
        end=None,
        when=f"{month} {year}",
        synthesized=True,
    )
    for c in prev.calls:
        hint = c.deadline or c.hint or c.expected
        call = Call(kind=c.kind, hint=hint)
        if hint:
            call.expected = expected_from_hint(hint, ed.approx_start)
        ed.calls.append(call)
    return ed


def current_edition(series: SeriesData, today: date) -> Edition:
    """The first edition with a call that is not over, synthesizing later ones as needed."""
    years = sorted(int(y) for y in series["editions"])
    ed = edition(series, years[0])
    for y in years[1:]:
        if ed.status(today) != "closed":
            return ed
        ed = edition(series, y)
    while ed.status(today) == "closed":
        ed = next_edition(ed)
    return ed


def roll(data: RegistryData, series_id: str) -> int:
    """Append the next edition after the last entered one to the registry. Returns its year."""
    series = find(data, series_id)
    last = max(int(y) for y in series["editions"])
    nxt = next_edition(edition(series, last))
    entry: EditionData = {}
    if nxt.url:
        entry["url"] = nxt.url
    entry["url_is_fallback"] = True
    if nxt.location:
        entry["location"] = nxt.location
    if nxt.when:
        entry["when"] = nxt.when
    calls: dict[str, CallData | None] = {c.kind: ({"deadline_hint": c.hint} if c.hint else {}) for c in nxt.calls}
    if calls:
        entry["calls"] = calls
    series["editions"][nxt.year] = entry
    return nxt.year


def _check_dates(where: str, raw: EditionData | CallData, keys: tuple[str, ...]) -> list[str]:
    problems = []
    for key in keys:
        try:
            to_date(cast(DateValue, raw.get(key)))
        except ValueError:
            problems.append(f"{where}: {key} is not an ISO date: {raw.get(key)!r}")
    return problems


def url_for(pattern: str, year: int) -> str:
    """Fill a url_pattern or deadlines_pattern for one year."""
    return pattern.format(year=year, yy=f"{year % 100:02d}")


def _check_types(where: str, raw: SeriesData | EditionData | CallData) -> list[str]:
    problems = []
    for key, value in raw.items():
        if key in LIST_FIELDS and not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
            problems.append(f"{where}: {key} must be a list of words, not {value!r}")
        elif key in BOOL_FIELDS and not isinstance(value, bool):
            problems.append(f"{where}: {key} must be true or false, not {value!r}")
        elif key in TEXT_FIELDS and value is not None and not isinstance(value, str):
            problems.append(f"{where}: {key} must be text, not {value!r}")
    return problems


def is_web_url(value: object) -> TypeGuard[str]:
    """Only http(s) links reach the page; javascript: or data: URLs never do."""
    return isinstance(value, str) and value.lower().startswith(("https://", "http://"))


def _check_urls(where: str, raw: SeriesData | EditionData, keys: tuple[str, ...]) -> list[str]:
    return [
        f"{where}: {key} must start with https:// or http://, not {raw.get(key)!r}"
        for key in keys
        if raw.get(key) is not None and not is_web_url(raw.get(key))
    ]


def _check_edition(where: str, ed: EditionData) -> list[str]:
    problems = [f"{where}: unknown field {k}" for k in sorted(set(ed) - EDITION_KEYS)]
    problems += _check_types(where, ed) + _check_dates(where, ed, ("start", "end"))
    problems += _check_urls(where, ed, ("url", "call_url"))
    if ed.get("call_url") and ed.get("call_url") == ed.get("url"):
        problems.append(f"{where}: call_url is the same as url, leave it out")
    for kind, raw_call in (ed.get("calls") or {}).items():
        call: CallData = raw_call or {}
        problems += [f"{where} {kind}: unknown field {k}" for k in sorted(set(call) - CALL_KEYS)]
        problems += _check_types(f"{where} {kind}", call)
        problems += _check_dates(f"{where} {kind}", call, ("deadline", "deadline_hint"))
    return problems


def _check_languages(sid: str, s: SeriesData) -> list[str]:
    problems = []
    if "language_source" in s and s["language_source"] not in LANGUAGE_SOURCES:
        problems.append(f"{sid}: language_source must be stated or inferred, not {s['language_source']!r}")
    for key in sorted(LANGUAGE_FIELDS & set(s)):
        value: object = s.get(key)
        bad = [c for c in value if not re.fullmatch("[a-z]{2}", str(c))] if isinstance(value, list) else []
        if bad:
            problems.append(f"{sid}: {key} takes ISO 639-1 codes like en or de, not {bad!r}")
    if s.get("languages") == []:
        problems.append(f"{sid}: languages is empty")
    return problems


def _check_series(sid: str, s: SeriesData) -> list[str]:
    problems = [f"{sid}: missing field {k}" for k in sorted(SERIES_REQUIRED - set(s))]
    problems += [f"{sid}: unknown field {k}" for k in sorted(set(s) - SERIES_KEYS)]
    problems += _check_types(sid, s)
    problems += _check_urls(sid, s, ("url_pattern", "deadlines_pattern"))
    if "continent" in s and s["continent"] not in CONTINENTS:
        problems.append(f"{sid}: unknown continent {s['continent']!r}")
    if s.get("layout", "prose") not in LAYOUTS:
        problems.append(f"{sid}: unknown layout {s['layout']!r}")
    problems += _check_languages(sid, s)
    for key in ("url_pattern", "deadlines_pattern"):
        pattern = s.get(key)
        if isinstance(pattern, str):
            try:
                url_for(pattern, 2000)
            except (KeyError, IndexError, ValueError):
                problems.append(f"{sid}: {key} has a placeholder other than {{year}} and {{yy}}: {pattern!r}")
    if "editions" in s and not s["editions"]:
        problems.append(f"{sid}: no editions")
    for year, raw_edition in (s.get("editions") or {}).items():
        problems += _check_edition(f"{sid} {year}", raw_edition or {})
    return problems


def validate(data: RegistryData) -> list[str]:
    """Typos and impossible values in the registry, one message each; empty when it is clean."""
    series = data.get("series") or []
    if not series:
        return ["registry has no series"]
    problems: list[str] = []
    seen: set[str] = set()
    for i, s in enumerate(series):
        sid = s.get("id", f"#{i}")
        if sid in seen:
            problems.append(f"{sid}: duplicate id")
        seen.add(sid)
        problems += _check_series(sid, s)
    return problems


def find(data: RegistryData, series_id: str) -> SeriesData:
    for s in data["series"]:
        if s["id"] == series_id:
            return s
    raise KeyError(series_id)
