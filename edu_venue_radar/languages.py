"""Hints on the languages a venue accepts, read from its call page.

Only explicit statements count ("papers must be submitted in English", "Beiträge auf
Deutsch oder Englisch") and the publisher of the proceedings. The language a page is
written in, or its html lang attribute, says too little: ITK has an English call for a
mostly Finnish programme. Like the deadline candidates, these hints never change the
registry; the site shows them next to the confirmed languages.
"""

import re

from .schema import LanguageHint

LANGUAGE_NAMES = {
    "english": "en",
    "englisch": "en",
    "englischer": "en",
    "german": "de",
    "deutsch": "de",
    "deutscher": "de",
    "finnish": "fi",
    "finnisch": "fi",
    "swedish": "sv",
    "schwedisch": "sv",
    "spanish": "es",
    "spanisch": "es",
    "portuguese": "pt",
    "portugiesisch": "pt",
    "french": "fr",
    "französisch": "fr",
    "dutch": "nl",
    "niederländisch": "nl",
}
# One language name as a whole word: "Deutsch" yes, "Deutschland" no.
_NAME = r"\b(?:" + "|".join(sorted(LANGUAGE_NAMES, key=len, reverse=True)) + r")\b"
# "Spanish, or Portuguese", "Deutsch oder Englisch", "German and English". Each separator can
# be read only one way and the list is capped, so a long hostile run of names cannot make the
# patterns backtrack exponentially.
_SEP = r"(?:\s*[,/]\s*|\s+)(?:(?:or|and|oder|und)\s+)?"
_NAMES = rf"{_NAME}(?:{_SEP}{_NAME}){{0,6}}"

STATEMENTS = [
    # papers must be submitted in English; delivered in English, Spanish, or Portuguese
    re.compile(rf"\b(?:submitted|written|presented|delivered|accepted)\s+(?:only\s+|either\s+)?in\s+({_NAMES})", re.I),
    # Authors should submit a paper in English
    re.compile(rf"\bsubmit\w*\s+(?:a\s+|your\s+)?(?:paper|contribution|proposal|abstract)s?\s+in\s+({_NAMES})", re.I),
    # official language of the conference is English; conference languages: German and English
    re.compile(rf"\b(?:official\s+)?languages?(?:\s+of\s+the\s+conference)?(?:\s+(?:is|are)|\s*:)\s*({_NAMES})", re.I),
    # Beiträge auf Deutsch oder Englisch; in deutscher oder englischer Sprache
    re.compile(rf"\bBeiträge\b[^.]{{0,60}}?\b(?:auf|in)\s+({_NAMES})", re.I),
    re.compile(rf"\bin\s+({_NAMES})\s+Sprache", re.I),
    re.compile(rf"\b(?:Tagungs|Konferenz)sprachen?\s*(?:ist|sind|:)\s*({_NAMES})", re.I),
]

# Proceedings series and what they publish in.
PUBLISHERS = {
    "ACM Digital Library": ["en"],
    "ACM ICPS": ["en"],
    "IEEE Xplore": ["en"],
    "Springer LNCS": ["en"],
    "Lecture Notes in Computer Science": ["en"],
    "SCITEPRESS": ["en"],
    "Lecture Notes in Informatics": ["de", "en"],
    "GI-Edition": ["de", "en"],
    "Waxmann": ["de"],
}


def codes(names: str) -> list[str]:
    """ISO 639-1 codes of the language names in `names`, in order, each once."""
    found = [LANGUAGE_NAMES[w.lower()] for w in re.findall(_NAME, names, re.I)]
    return list(dict.fromkeys(found))


def language_hints(text: str) -> list[LanguageHint]:
    """Explicit language statements and named proceedings publishers on a page, each once.

    Statements that overlap an earlier match ("Beiträge können in deutscher oder englischer
    Sprache" hits two patterns) count once.
    """
    hints: list[LanguageHint] = []
    spans: list[tuple[int, int]] = []
    seen: set[str] = set()
    for pattern in STATEMENTS:
        for m in pattern.finditer(text):
            phrase = " ".join(m.group(0).split())
            if phrase in seen or any(m.start() < hi and lo < m.end() for lo, hi in spans):
                continue
            seen.add(phrase)
            spans.append(m.span())
            hints.append({"kind": "statement", "phrase": phrase, "languages": codes(m.group(1))})
    lowered = text.lower()
    hints += [
        {"kind": "publisher", "phrase": name, "languages": langs} for name, langs in PUBLISHERS.items() if name.lower() in lowered
    ]
    return hints
