import json
from datetime import date

from edu_venue_radar import crawl, site
from edu_venue_radar.registry import edition

REG = {
    "series": [
        {
            "id": "a",
            "name": "Alpha",
            "organizer": "ACM",
            "icore": "ALPHA",
            "continent": "Europe",
            "topics": ["sotl"],
            "keywords": ["workshop"],
            "url_pattern": "https://a.org/{year}/",
            "editions": {
                2027: {
                    "url": "https://a.org/2027/",
                    "start": "2027-04-06",
                    "end": "2027-04-09",
                    "calls": {"workshops": {"deadline": "2026-11-01"}, "papers": {"deadline": "2026-10-01"}},
                }
            },
        },
        {
            "id": "b",
            "name": "Beta",
            "continent": "Online",
            "topics": ["digital-education"],
            "editions": {2027: {"url": "https://b.org/", "start": "2027-02-01", "calls": {"papers": {"deadline": "2026-08-01"}}}},
        },
    ]
}


class FakeResponse:
    def __init__(self, status, text, url, headers=None):
        self.status_code, self.text, self.url = status, text, url
        self.headers = {"content-type": "text/html", **(headers or {})}
        self.encoding = "utf-8"

    def iter_content(self, size):
        data = self.text.encode()
        return (data[i : i + size] for i in range(0, len(data), size))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}

    def get(self, url, **_):
        status, text = self.pages.get(url, (404, ""))
        return FakeResponse(status, text, url)


def test_crawl_records_candidates_changes_and_probes(tmp_path):
    pages = {
        "https://a.org/2027/": (200, "<p>Workshop proposals due 7 December 2026</p><script>x</script>"),
        "https://a.org/2028/": (200, "<p>Save the date</p>"),
    }
    session = FakeSession(pages)
    first = crawl.crawl_series(session, REG["series"][0], date(2026, 10, 23), tmp_path)
    assert first["candidates"][0]["when"] == "2026-12-07"
    assert first["changed_on"] is None
    assert [p["exists"] for p in first["probes"]] == [True]

    pages["https://a.org/2027/"] = (200, "<p>Workshop proposals due 14 December 2026</p>")
    second = crawl.crawl_series(session, REG["series"][0], date(2026, 10, 30), tmp_path)
    assert second["changed_on"] == second["checked"]
    assert json.loads((tmp_path / "a.json").read_text())["candidates"][0]["when"] == "2026-12-14"


def test_rotating_teasers_without_dates_are_no_change(tmp_path):
    pages = {"https://a.org/2027/": (200, "<p>News: new podcast.</p><p>Workshop proposals due 7 December 2026.</p>")}
    session = FakeSession(pages)
    crawl.crawl_series(session, REG["series"][0], date(2026, 10, 23), tmp_path)
    pages["https://a.org/2027/"] = (200, "<p>News: keynote announced.</p><p>Workshop proposals due 7 December 2026.</p>")
    assert crawl.crawl_series(session, REG["series"][0], date(2026, 10, 23), tmp_path)["changed_on"] is None


def test_an_old_whole_page_hash_is_a_baseline_not_a_change(tmp_path):
    old = {"url": "https://a.org/2027/", "sha256": "0" * 64, "changed_on": "2026-09-01T05:00:00+00:00"}
    (tmp_path / "a.json").write_text(json.dumps(old))
    pages = {"https://a.org/2027/": (200, "<p>Workshop proposals due 7 December 2026.</p>")}
    session = FakeSession(pages)
    first = crawl.crawl_series(session, REG["series"][0], date(2026, 10, 23), tmp_path)
    assert first["changed_on"] == old["changed_on"]
    assert first["sha256_of"] == crawl.HASH_OF
    pages["https://a.org/2027/"] = (200, "<p>Workshop proposals due 14 December 2026.</p>")
    second = crawl.crawl_series(session, REG["series"][0], date(2026, 10, 30), tmp_path)
    assert second["changed_on"] == second["checked"]


def test_crawl_drops_dates_from_the_conference_on(tmp_path):
    text = "<p>Workshop proposals due 7 December 2026. Workshops run on 7 April 2027.</p>"
    session = FakeSession({"https://a.org/2027/": (200, text)})
    found = crawl.crawl_series(session, REG["series"][0], date(2026, 10, 23), tmp_path)["candidates"]
    assert [c["when"] for c in found] == ["2026-12-07"]


def test_conference_start_falls_back_to_the_named_month_only():
    s = {"id": "x", "editions": {2027: {"when": "November 2027"}}}
    assert crawl.conference_start(edition(s, 2027)) == date(2027, 11, 1)
    s["editions"][2027] = {"when": "2027"}
    assert crawl.conference_start(edition(s, 2027)) is None
    s["editions"][2027] = {"start": "2027-04-06", "when": "November 2027"}
    assert crawl.conference_start(edition(s, 2027)) == date(2027, 4, 6)


def test_crawl_keeps_old_findings_when_the_page_is_down(tmp_path):
    good = FakeSession({"https://b.org/": (200, "<p>nothing</p>")})
    crawl.crawl_series(good, REG["series"][1], date(2026, 6, 1), tmp_path)
    down = crawl.crawl_series(FakeSession({}), REG["series"][1], date(2026, 6, 2), tmp_path)
    assert down["error"] == "HTTP 404"
    assert "sha256" in down


def test_crawl_appends_the_separate_deadlines_page(tmp_path):
    series = {**REG["series"][0], "deadlines_pattern": "https://a.org/{year}/dates", "url_pattern": None}
    pages = {
        "https://a.org/2027/": (200, "<p>Welcome</p>"),
        "https://a.org/2027/dates": (200, "<p>Workshop proposals due 7 December 2026</p>"),
    }
    res = crawl.crawl_series(FakeSession(pages), series, date(2026, 10, 23), tmp_path)
    assert res["deadlines_url"] == {"url": "https://a.org/2027/dates", "status": 200}
    assert [c["when"] for c in res["candidates"]] == ["2026-12-07"]


def test_crawl_skips_an_empty_deadlines_page(tmp_path):
    series = {**REG["series"][0], "deadlines_pattern": "https://a.org/{year}/dates", "url_pattern": None}
    pages = {"https://a.org/2027/": (200, "<p>Workshop proposals due 7 December 2026</p>")}
    res = crawl.crawl_series(FakeSession(pages), series, date(2026, 10, 23), tmp_path)
    assert res["deadlines_url"] == {"url": "https://a.org/2027/dates", "status": 404}
    assert [c["when"] for c in res["candidates"]] == ["2026-12-07"]


def test_crawl_of_an_edition_without_url(tmp_path):
    series = {**REG["series"][1], "editions": {2027: {"when": "May 2027", "calls": {"papers": {"deadline": "2027-01-10"}}}}}
    res = crawl.crawl_series(FakeSession({}), series, date(2026, 10, 23), tmp_path)
    assert (res["url"], res["error"]) == (None, "no URL")


def test_crawl_reads_the_call_page_and_stands_in_for_a_missing_edition_page(tmp_path):
    series = {**REG["series"][1], "keywords": ["paper"]}
    series["editions"] = {2027: {"url": "https://b.org/", "call_url": "https://cfp.b.org/2027", "start": "2027-02-01"}}
    pages = {"https://cfp.b.org/2027": (200, "<p>Papers must be submitted in English by 10 December 2026.</p>")}
    res = crawl.crawl_series(FakeSession(pages), series, date(2026, 10, 23), tmp_path)
    assert res["status"] == 404 and "error" not in res
    assert res["call_url"] == {"url": "https://cfp.b.org/2027", "status": 200}
    assert [c["when"] for c in res["candidates"]] == ["2026-12-10"]
    assert res["language_hints"][0]["languages"] == ["en"]


def test_fetch_refuses_pages_over_the_size_limit(monkeypatch):
    monkeypatch.setattr(crawl, "MAX_BYTES", 100)
    page = crawl.fetch(FakeSession({"https://x.org/": (200, "<p>" + "x" * 200 + "</p>")}), "https://x.org/")
    assert (page.text, page.error) == (None, "page too large or too slow")

    class Announced(FakeSession):
        def get(self, url, **_):
            return FakeResponse(200, "<p>small</p>", url, {"content-length": "5000000"})

    assert crawl.fetch(Announced({}), "https://x.org/").error == "page too large or too slow"


class BrokenSession(FakeSession):
    def get(self, url, **_):
        raise crawl.requests.ConnectionError(url)


def test_crawl_records_a_network_error_by_name(tmp_path):
    res = crawl.crawl_series(BrokenSession({}), REG["series"][1], date(2026, 10, 23), tmp_path)
    assert (res["status"], res["error"]) == (None, "ConnectionError")
    assert "candidates" not in res


def test_build_groups_by_year_and_marks_soon(tmp_path):
    crawl_dir = tmp_path / "crawl"
    crawl_dir.mkdir()
    (crawl_dir / "a.json").write_text(
        json.dumps(
            {
                "edition": 2027,
                "checked": "2026-10-23T05:00:00+00:00",
                "changed_on": "2026-10-23T05:00:00+00:00",
                "candidates": [{"when": "2026-12-07", "keyword": "workshop", "context": "Workshop proposals due"}],
                "probes": [{"url": "https://a.org/2028/", "exists": True}],
            }
        )
    )
    icore = tmp_path / "icore.json"
    icore.write_text(json.dumps({"source": "ICORE2026", "ranks": {"a": {"rank": "B"}}}))
    out = site.build(REG, crawl_dir, icore, tmp_path / "docs" / "index.html", date(2026, 10, 23))
    html = out.read_text()
    assert "Conferences in 2027" in html and "Conferences in 2028" in html
    assert 'class="cl st-soon"' in html
    assert 'class="cl st-closed"' in html
    assert "page changed 23.10.2026" in html
    assert "page up: a.org/2028/" in html
    assert "ICORE2026" in html
    assert "guessed from the last edition" in html  # Beta rolled to 2028
    assert '<tr class="ev-confirmed"' in html and '<tr class="ev-guessed"' in html
    assert "confirmed for this edition: </span><strong>Alpha 2027" in html


def test_conference_text():
    s = {"id": "a", "editions": {2027: {"start": "2027-04-06", "end": "2027-04-09"}}}
    assert site.conference_text(edition(s, 2027)) == "06.–09.04.2027"
    s["editions"][2027] = {"start": "2027-06-30", "end": "2027-07-02"}
    assert site.conference_text(edition(s, 2027)) == "30.06.–02.07.2027"


def test_sort_keys_per_call_category():
    ed = edition(REG["series"][0], 2027)  # workshops 2026-11-01, papers 2026-10-01
    keys = site.sort_keys(ed, date(2026, 9, 1))
    assert keys["conf"] == "2027-04-06" and keys["dl-all"] == "2026-10-01"
    assert keys["dl-papers"] == "2026-10-01" and keys["dl-workshops"] == "2026-11-01"
    assert "dl-posters" not in keys
    # After the papers deadline only the workshop call is live.
    assert "dl-papers" not in site.sort_keys(ed, date(2026, 10, 15))


def test_open_calls_count_for_every_category():
    assert site.categories("contributions") == list(site.CALL_CATEGORIES)
    assert site.categories("workshops-special-sessions") == ["workshops", "special"]
    assert site.categories("artifacts") == []


def test_row_drops_links_that_are_not_web_urls():
    series = {**REG["series"][1], "editions": {2027: {"url": "javascript:alert(1)", "call_url": "data:text/html,x"}}}
    _, html = site.row(series, edition(series, 2027), None, None, date(2026, 10, 23))
    assert "javascript:" not in html and "data:text" not in html
