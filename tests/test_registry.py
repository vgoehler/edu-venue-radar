from datetime import date
from pathlib import Path

import pytest

from edu_venue_radar import registry
from edu_venue_radar.registry import current_edition, expected_from_hint

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 23)


def series(**editions):
    return {"id": "x", "name": "X", "url_pattern": "https://x.org/{year}/", "editions": editions}


def test_expected_deadline_is_the_last_shift_before_the_conference():
    assert expected_from_hint(date(2023, 2, 5), date(2027, 9, 1)) == date(2027, 2, 5)
    assert expected_from_hint(date(2024, 12, 15), date(2027, 6, 8)) == date(2026, 12, 15)
    assert expected_from_hint(date(2026, 7, 12), date(2027, 11, 1)) == date(2027, 7, 12)


def test_one_open_call_keeps_the_edition():
    s = series(
        **{
            "2027": {
                "start": "2027-04-06",
                "calls": {"special-sessions": {"deadline": "2026-10-08"}, "workshops": {"deadline": "2026-12-07"}},
            }
        }
    )
    ed = current_edition(s, TODAY)
    assert (ed.year, ed.status(TODAY), ed.next_deadline(TODAY)) == (2027, "open", date(2026, 12, 7))
    assert [c.status(TODAY) for c in ed.calls] == ["closed", "open"]


def test_all_calls_closed_rolls_to_a_guessed_next_edition():
    s = series(
        **{
            "2027": {
                "start": "2027-02-09",
                "url": "https://x.org/2027/",
                "location": "St. Pölten",
                "calls": {"contributions": {"deadline": "2026-08-15"}},
            }
        }
    )
    ed = current_edition(s, TODAY)
    assert ed.synthesized and ed.year == 2028
    assert ed.calls[0].kind == "contributions"
    assert ed.calls[0].expected == date(2027, 8, 15)
    assert ed.url == "https://x.org/2027/" and ed.url_is_fallback
    assert ed.location == "not announced (2027: St. Pölten)"


def test_entered_next_edition_wins_over_a_guess():
    s = series(
        **{
            "2027": {"start": "2027-02-09", "calls": {"papers": {"deadline": "2026-08-15"}}},
            "2028": {"start": "2028-02-01", "location": "Graz", "url": "https://x.org/2028/"},
        }
    )
    ed = current_edition(s, TODAY)
    assert (ed.year, ed.synthesized, ed.location) == (2028, False, "Graz")


def test_expected_deadline_long_past_counts_as_closed():
    s = series(**{"2027": {"when": "March 2027", "calls": {"papers": {"deadline_hint": "2025-10-01"}}}})
    assert current_edition(s, TODAY).year == 2028


def test_closed_flag_without_date():
    s = series(**{"2027": {"when": "May 2027", "calls": {"congress": {"closed": True}}}})
    assert current_edition(s, TODAY).year == 2028


def test_edition_without_calls_stays_shown_as_unknown():
    s = series(**{"2027": {"when": "September 2027"}})
    ed = current_edition(s, TODAY)
    assert (ed.year, ed.status(TODAY), ed.next_deadline(TODAY)) == (2027, "unknown", None)


def test_roll_appends_the_next_edition(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        "# comment stays\nseries:\n  - id: x\n    name: X\n    editions:\n      2027:\n        url: https://x.org/2027/\n"
        "        location: Leipzig\n        start: 2027-09-01\n        calls:\n          workshops:\n"
        "            deadline: 2027-02-01\n"
    )
    data = registry.load(path)
    assert registry.roll(data, "x") == 2028
    registry.save(data, path)
    assert "# comment stays" in path.read_text()
    ed = registry.edition(registry.find(registry.load(path), "x"), 2028)
    assert ed.calls[0].hint == date(2027, 2, 1)
    assert ed.location == "not announced (2027: Leipzig)"


def test_roll_unknown_series():
    with pytest.raises(KeyError):
        registry.roll({"series": []}, "nope")


def test_shipped_registry_loads_and_every_series_has_a_current_edition():
    data = registry.load(ROOT / "registry.yaml")
    ids = [s["id"] for s in data["series"]]
    assert len(ids) == len(set(ids))
    for s in data["series"]:
        assert current_edition(s, TODAY).url, s["id"]


def test_evidence_of_an_edition():
    confirmed = series(**{"2027": {"start": "2027-04-06", "calls": {"papers": {"deadline": "2026-12-01"}}}})
    assert current_edition(confirmed, TODAY).evidence == "confirmed"
    partial = series(**{"2027": {"location": "Graz", "when": "March 2027", "calls": {"papers": {"deadline_hint": "2025-12-01"}}}})
    assert current_edition(partial, TODAY).evidence == "partial"
    guessed = series(**{"2027": {"start": "2027-02-09", "calls": {"papers": {"deadline": "2026-08-15"}}}})
    assert current_edition(guessed, TODAY).evidence == "guessed"
    placeholder = {"url": "https://x.org/2026/", "url_is_fallback": True, "location": "not announced (2026: Graz)"}
    rolled = series(**{"2027": {**placeholder, "when": "November 2027", "calls": {"papers": {"deadline_hint": "2026-08-16"}}}})
    assert current_edition(rolled, TODAY).evidence == "guessed"
