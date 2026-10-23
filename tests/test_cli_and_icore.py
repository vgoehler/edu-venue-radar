import json
from datetime import date

import pytest

from edu_venue_radar import cli, icore, registry

REGISTRY = """series:
  - id: x
    name: X
    icore: XCONF
    continent: Europe
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
