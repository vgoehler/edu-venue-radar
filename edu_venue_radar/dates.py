"""Find dates in free text, in the spellings conference pages use (English and German)."""

import re
from dataclasses import dataclass
from datetime import date

MONTHS = {
    "jan": 1,
    "january": 1,
    "januar": 1,
    "jänner": 1,
    "feb": 2,
    "february": 2,
    "februar": 2,
    "mar": 3,
    "march": 3,
    "märz": 3,
    "maerz": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "juni": 6,
    "jul": 7,
    "july": 7,
    "juli": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "okt": 10,
    "oktober": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    "dez": 12,
    "dezember": 12,
}
SEASONS = {"spring": 4, "frühjahr": 4, "summer": 7, "sommer": 7, "autumn": 9, "fall": 9, "herbst": 9, "winter": 12}

_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_PATTERNS = [
    # 2026-12-07
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), lambda m: (int(m[1]), int(m[2]), int(m[3]))),
    # 07.12.2026
    (re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b"), lambda m: (int(m[3]), int(m[2]), int(m[1]))),
    # 7 December 2026, 7th of Dec 2026, 7. Dezember 2026
    (
        re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+(?:of\s+)?({_MONTH})\.?,?\s+(\d{{4}})\b", re.IGNORECASE),
        lambda m: (int(m[3]), MONTHS[m[2].lower()], int(m[1])),
    ),
    # December 7, 2026 / Dec 07 2026
    (
        re.compile(rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE),
        lambda m: (int(m[3]), MONTHS[m[1].lower()], int(m[2])),
    ),
]


@dataclass(frozen=True)
class Found:
    when: date
    start: int
    end: int


def find_dates(text: str) -> list[Found]:
    """All dates in `text`, in order of appearance; impossible dates are skipped."""
    found: dict[int, Found] = {}
    for pattern, parts in _PATTERNS:
        for m in pattern.finditer(text):
            try:
                d = date(*parts(m))
            except ValueError:
                continue
            if m.start() not in found:
                found[m.start()] = Found(d, m.start(), m.end())
    return [found[k] for k in sorted(found)]


@dataclass(frozen=True)
class Candidate:
    when: date
    keyword: str
    context: str


_SENTENCE_END = re.compile(r"[.!?]\s+(?=[A-ZÄÖÜ])")


def _sentence_bounds(text: str, start: int, end: int, window: int) -> tuple[int, int]:
    """Window around [start, end), cut back to the sentence the date stands in."""
    lo, hi = max(0, start - window), min(len(text), end + window)
    for m in _SENTENCE_END.finditer(text, lo, start):
        lo = m.end()
    m = _SENTENCE_END.search(text, end, hi)
    if m:
        hi = m.start() + 1
    return lo, hi


def _nearest_keyword(lowered: str, keywords: list[str], start: int, end: int, lo: int, hi: int) -> tuple[int, str] | None:
    """Keyword closest to the date; one standing after the date counts double the distance."""
    best: tuple[int, str] | None = None
    for kw in keywords:
        k = kw.lower()
        before = lowered.rfind(k, lo, start)
        after = lowered.find(k, end, hi)
        distances = []
        if before != -1:
            distances.append(start - (before + len(k)))
        if after != -1:
            distances.append(2 * (after - end))
        if distances and (best is None or min(distances) < best[0]):
            best = (min(distances), kw)
    return best


# A date whose own label carries one of these is a follow-up or an event day, not a deadline.
# The nearest of these and POSITIVE_TERMS decides: "Abstract Notifications" loses,
# "Submission deadline (notification follows)" wins.
NEGATIVE_TERMS = [
    "notification",
    "notice of",
    "acceptance",
    "decision",
    "camera-ready",
    "camera ready",
    "final version",
    "regist",
    "early bird",
    "benachrichtigung",
    "zusage",
    "anmeldung",
]
# Words that name the event itself. They count only when no positive term stands in the label,
# because "Paper submission (main conference):" is still a deadline.
EVENT_TERMS = [
    "conference",
    "konferenz",
    "tagung",
    "held",
    "takes place",
    "take place",
    "will begin",
    "starts",
    "findet",
    "stattfinde",
]
POSITIVE_TERMS = ["deadline", "submission", "submit", "due", "call for", "einreichung", "einreichen", "frist", "abgabe"]


def _label_after(text: str, dates: list[Found], i: int, window: int) -> tuple[int, int]:
    """The text between a date and the next one: the label in a "date, label" table."""
    end = dates[i].end
    nxt = dates[i + 1].start if i + 1 < len(dates) else len(text)
    return end, min(nxt, end + window)


def _own_label(text: str, dates: list[Found], i: int, lo: int, hi: int) -> tuple[int, int]:
    """The part of the sentence [lo, hi) that labels date i, cut off at the neighbouring dates.

    A colon before the date ("Submission: 17 November 2026") or a sentence that ends after it
    puts the label before the date. When another date follows instead, the text reads like a
    "date, label, date, label" list and the label is what comes after.
    """
    f = dates[i]
    before_lo = max([lo] + [d.end for d in dates[:i] if d.end <= f.start])
    after_hi = min([hi] + [d.start for d in dates[i + 1 :] if d.start >= f.end])
    if ":" in text[before_lo : f.start] or after_hi == hi:
        return before_lo, f.start
    return f.end, after_hi


def _rejected(label: str, before: bool) -> bool:
    """Does the label name a follow-up date or the event rather than a deadline?"""

    def distance(term: str) -> int | None:
        pos = label.rfind(term) if before else label.find(term)
        if pos == -1:
            return None
        return len(label) - (pos + len(term)) if before else pos

    def nearest(terms: list[str]) -> int | None:
        found = [d for t in terms if (d := distance(t)) is not None]
        return min(found) if found else None

    positive, negative = nearest(POSITIVE_TERMS), nearest(NEGATIVE_TERMS)
    if negative is not None and (positive is None or negative < positive):
        return True
    return positive is None and nearest(EVENT_TERMS) is not None


def deadline_candidates(
    text: str, keywords: list[str], today: date, window: int = 160, layout: str = "prose", before: date | None = None
) -> list[Candidate]:
    """Future dates whose label carries one of the keywords.

    In `prose` layout the label is the sentence around the date, and the date is tied to
    its nearest keyword. In `date-first` layout (tables like "03.03.2027 Workshop submission
    24.03.2027 Notification") the label is the text up to the next date, and the best-ranked
    keyword in it wins. Keywords earlier in the list rank higher, so the series' own format
    comes first. Each date is reported once.

    Dates whose own label names a notification, registration, camera-ready version or the
    event itself are dropped, and so are dates on or after `before` (the conference start).
    """
    lowered = text.lower()
    best: dict[date, tuple[int, Candidate]] = {}
    dates = find_dates(text)
    for i, f in enumerate(dates):
        if f.when < today or f.when.year > today.year + 2 or (before and f.when >= before):
            continue
        if layout == "date-first":
            lo, hi = _label_after(text, dates, i, window)
            label = lowered[lo:hi]
            hit = next(((0, kw) for kw in keywords if kw.lower() in label), None)
            own = (lo, hi)
            lo = f.start
        else:
            lo, hi = _sentence_bounds(text, f.start, f.end, window)
            hit = _nearest_keyword(lowered, keywords, f.start, f.end, lo, hi)
            own = _own_label(text, dates, i, lo, hi)
        if hit is None or _rejected(lowered[own[0] : own[1]], before=own[1] == f.start):
            continue
        rank = keywords.index(hit[1])
        if f.when not in best or rank < best[f.when][0]:
            best[f.when] = (rank, Candidate(f.when, hit[1], " ".join(text[lo:hi].split())))
    return [c for _, c in sorted(best.values(), key=lambda rc: (rc[0], rc[1].when))]


def date_lines(text: str) -> list[str]:
    """The sorted, distinct sentences that carry a date: the part of a page worth watching."""
    lines = {" ".join(text[lo:hi].split()) for f in find_dates(text) for lo, hi in [_sentence_bounds(text, f.start, f.end, 80)]}
    return sorted(lines)


def month_of(text: str) -> int | None:
    """Month named in a free-text date like "early November 2027" or "autumn 2027"."""
    for word in re.findall(r"[a-zäöü]+", text.lower()):
        if word in MONTHS:
            return MONTHS[word]
        if word in SEASONS:
            return SEASONS[word]
    return None
