import time

from edu_venue_radar import registry, site
from edu_venue_radar.languages import codes, language_hints


def langs(text):
    return [(h["kind"], h["languages"]) for h in language_hints(text)]


def test_english_statements():
    assert langs("Authors should submit a paper in English.") == [("statement", ["en"])]
    text = (
        "proposals must be submitted in English. However, accepted sessions may be delivered in English, Spanish, or Portuguese"
    )
    assert langs(text) == [("statement", ["en"]), ("statement", ["en", "es", "pt"])]
    assert langs("The official language of the conference is English.") == [("statement", ["en"])]


def test_german_statements_count_once():
    assert langs("Beiträge auf Deutsch oder Englisch sind willkommen.") == [("statement", ["de", "en"])]
    assert langs("Beiträge können in deutscher oder englischer Sprache eingereicht werden.") == [("statement", ["de", "en"])]
    assert langs("Die Tagungssprache ist Deutsch.") == [("statement", ["de"])]


def test_no_hint_from_place_names_or_unrelated_words():
    assert langs("Beiträge aus Deutschland und der Schweiz") == []
    assert langs("Talks can be presented in person or online.") == []


def test_publishers():
    assert langs("Proceedings appear in the ACM Digital Library.") == [("publisher", ["en"])]
    assert langs("Tagungsband in der Reihe Lecture Notes in Informatics") == [("publisher", ["de", "en"])]


def test_codes_keep_order_and_drop_repeats():
    assert codes("English, German and English") == ["en", "de"]


SERIES = {"id": "x", "name": "X", "continent": "Europe", "editions": {2027: {}}}


def test_validate_language_fields():
    bad = {**SERIES, "languages": ["EN", "german"], "language_source": "guessed"}
    problems = registry.validate({"series": [bad]})
    assert "x: languages takes ISO 639-1 codes like en or de, not ['EN', 'german']" in problems
    assert "x: language_source must be stated or inferred, not 'guessed'" in problems
    assert registry.validate({"series": [SERIES]}) == ["x: missing field language_source", "x: missing field languages"]


def test_languages_cell():
    stated = {
        **SERIES,
        "languages": ["en"],
        "presentation_languages": ["en", "es"],
        "proceedings_languages": [],
        "language_source": "stated",
    }
    cell = site.languages_cell(stated)
    assert '<span class="lang">en</span>' in cell
    assert "talks: en es" in cell and "no proceedings" in cell
    inferred = {**SERIES, "languages": ["fi", "en"], "proceedings_languages": ["fi"], "language_source": "inferred"}
    cell = site.languages_cell(inferred)
    assert 'class="lang inferred"' in cell and "proceedings: fi" in cell


def test_language_flags_only_for_what_the_registry_lacks():
    series = {**SERIES, "languages": ["en"], "proceedings_languages": ["en"], "language_source": "inferred"}
    crawl = {
        "id": "x",
        "edition": 2027,
        "url": None,
        "checked": "",
        "language_hints": [
            {"kind": "statement", "phrase": "submitted in English", "languages": ["en"]},
            {"kind": "statement", "phrase": "Beiträge auf Deutsch", "languages": ["de"]},
            {"kind": "publisher", "phrase": "Waxmann", "languages": ["de"]},
        ],
    }
    flags = site.language_flags(crawl, series)
    assert len(flags) == 2
    assert "language? de (statement)" in flags[0] and "language? de (publisher)" in flags[1]


def test_long_hostile_name_lists_do_not_backtrack():
    # Before the fix this took hours: every split of the spaces between the names was tried.
    started = time.monotonic()
    assert langs("in English" + " or English" * 200 + " x") == []
    assert time.monotonic() - started < 1


def test_label_with_colon():
    assert langs("Language: English") == [("statement", ["en"])]
    assert langs("Conference language: German and English") == [("statement", ["de", "en"])]
    assert langs("The language is clear") == []
