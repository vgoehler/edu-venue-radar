import json
from datetime import date

import pytest

from edu_venue_radar import cli, icore, registry

REGISTRY = """series:
  - id: x
    name: X
    icore: XCONF
    continent: Europe
    topics: [sotl]
    languages: [de, en]
    language_source: stated
    url_pattern: https://x.org/{year}/
    editions:
      2027:
        url: https://x.org/2027/
        location: Leipzig
        start: 2027-09-01
        calls:
          workshops:
            deadline: 2027-02-01
"""


@pytest.fixture
def root(tmp_path):
    (tmp_path / "registry.yaml").write_text(REGISTRY)
    (tmp_path / "data" / "crawl").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    return tmp_path


def run(root, *args):
    return cli.main(["--root", str(root), "--today", "2026-10-23", *args])


def test_list_shows_the_current_edition(root, capsys):
    assert run(root, "list") == 0
    assert "x             2027" in capsys.readouterr().out


def test_build_writes_the_page_without_crawl_or_ranks(root):
    assert run(root, "build") == 0
    assert "X 2027" in (root / "docs" / "index.html").read_text()


def test_roll_appends_the_next_edition(root):
    assert run(root, "roll", "x") == 0
    assert "2028:" in (root / "registry.yaml").read_text()


def test_check_passes_a_clean_registry(root, capsys):
    assert run(root, "check") == 0
    assert "0 problems" in capsys.readouterr().out


def test_check_reports_typos(root, capsys):
    text = REGISTRY.replace("deadline: 2027", "deadine: 2027").replace("continent: Europe", "continent: Eurpoe")
    (root / "registry.yaml").write_text(text)
    assert run(root, "check") == 1
    out = capsys.readouterr().out
    assert "x 2027 workshops: unknown field deadine" in out
    assert "x: unknown continent 'Eurpoe'" in out


def test_validate_catches_bad_dates_layout_and_duplicates():
    data = {
        "series": [
            {"id": "a", "name": "A", "continent": "Online", "layout": "table", "editions": {2027: {"start": "2027-13-01"}}},
            {"id": "a", "name": "A", "continent": "Online", "editions": {}},
            {"name": "B", "continent": "Online", "editions": {}},
        ]
    }
    problems = registry.validate(data)
    assert "a: unknown layout 'table'" in problems
    assert "a 2027: start is not an ISO date: '2027-13-01'" in problems
    assert "a: duplicate id" in problems
    assert "#2: missing field id" in problems


ROW = "<tr><td>X Conference</td><td>{acr}</td><td>ICORE2026</td><td>{rank}</td><td>x</td></tr>"


class FakeResponse:
    def __init__(self, status, text):
        self.status_code, self.text = status, text
        self.headers, self.encoding = {"content-type": "text/html; charset=utf-8"}, "utf-8"

    def iter_content(self, size):
        yield self.text.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:  # noqa: PLR2004
            raise icore.requests.HTTPError(str(self.status_code))


class FakePortal:
    def __init__(self, rows="", status=200):
        self.rows, self.status, self.headers = rows, status, {}

    def get(self, _url, params=None, **_):
        if params is None:
            return FakeResponse(self.status, '<option value="CORE2023"><option value="ICORE2026">')
        return FakeResponse(self.status, f"<table>{self.rows}</table>")


def reg(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text(REGISTRY)
    return registry.load(path)


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(icore, "PAUSE", 0)


def test_parse_rows_skips_short_rows_and_unescapes():
    page = "<tr><th>Title</th></tr>" + ROW.format(acr="A&amp;B", rank="A")
    assert icore.parse_rows(page) == [["X Conference", "A&B", "ICORE2026", "A", "x"]]


def test_update_writes_ranks(tmp_path):
    out = tmp_path / "icore.json"
    ranks = icore.update(reg(tmp_path), out, date(2026, 10, 23), FakePortal(ROW.format(acr="XCONF", rank="B")))
    assert ranks["source"] == "ICORE2026"
    assert json.loads(out.read_text())["ranks"]["x"]["rank"] == "B"


def test_update_keeps_the_old_file_when_nothing_is_found(tmp_path):
    out = tmp_path / "icore.json"
    out.write_text("old")
    with pytest.raises(RuntimeError):
        icore.update(reg(tmp_path), out, date(2026, 10, 23), FakePortal(""))
    assert out.read_text() == "old"


def test_update_fails_on_an_error_page(tmp_path):
    out = tmp_path / "icore.json"
    with pytest.raises(icore.requests.HTTPError):
        icore.update(reg(tmp_path), out, date(2026, 10, 23), FakePortal(status=503))
    assert not out.exists()


def test_validate_catches_placeholders_empty_editions_and_types():
    data = {
        "series": [
            {"id": "a", "name": "A", "continent": "Online", "url_pattern": "https://a.org/{yaer}/", "editions": {}},
            {
                "id": "b",
                "name": "B",
                "continent": "Online",
                "topics": "ai",
                "editions": {2027: {"calls": {"papers": {"closed": "yes"}}}},
            },
        ]
    }
    problems = registry.validate(data)
    assert "a: url_pattern has a placeholder other than {year} and {yy}: 'https://a.org/{yaer}/'" in problems
    assert "a: no editions" in problems
    assert "b: topics must be a list of words, not 'ai'" in problems
    assert "b 2027 papers: closed must be true or false, not 'yes'" in problems
    same = {
        "id": "c",
        "name": "C",
        "continent": "Online",
        "editions": {2027: {"url": "https://c.org", "call_url": "https://c.org"}},
    }
    assert "c 2027: call_url is the same as url, leave it out" in registry.validate({"series": [same]})


def test_validate_reports_a_registry_without_series():
    assert registry.validate({"series": []}) == ["registry has no series"]


def test_load_refuses_a_file_without_a_mapping(tmp_path):
    path = tmp_path / "registry.yaml"
    path.write_text("")
    with pytest.raises(ValueError, match="mapping"):
        registry.load(path)


def test_roll_keeps_the_usual_field_order(root):
    run(root, "roll", "x")
    data = registry.load(root / "registry.yaml")
    assert list(data["series"][0]["editions"][2028])[:2] == ["url", "url_is_fallback"]


def test_crawl_icore_and_update_commands(root, monkeypatch, capsys):
    record = {"id": "x", "edition": 2027, "url": None, "checked": "2026-10-23T05:00:00+00:00", "status": 200}
    monkeypatch.setattr(cli.crawl, "crawl", lambda *a, **k: [record])
    monkeypatch.setattr(
        cli.icore, "update", lambda *a, **k: {"source": "ICORE2026", "checked": "", "ranks": {"x": {"acronym": "X", "rank": "A"}}}
    )
    assert run(root, "crawl", "x") == 0
    assert run(root, "icore") == 0
    assert run(root, "update") == 0
    out = capsys.readouterr().out
    assert "x             200" in out
    assert "x             A" in out
    assert out.strip().endswith("index.html")


def test_validate_allows_only_web_urls():
    bad = {
        "id": "j",
        "name": "J",
        "continent": "Online",
        "url_pattern": "javascript:alert({year})",
        "editions": {2027: {"url": "https://j.org", "call_url": "javascript:alert(1)"}},
    }
    problems = registry.validate({"series": [bad]})
    assert "j: url_pattern must start with https:// or http://, not 'javascript:alert({year})'" in problems
    assert "j 2027: call_url must start with https:// or http://, not 'javascript:alert(1)'" in problems


def test_validate_reports_unknown_call_kinds():
    data = {"series": [{"id": "k", "name": "K", "continent": "Online", "editions": {2027: {"calls": {"workshps": {}}}}}]}
    problems = registry.validate(data)
    assert any(p.startswith("k 2027: unknown call kind 'workshps', known are abstracts, artifacts") for p in problems)
