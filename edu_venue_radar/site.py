"""Render the registry, crawl results and ICORE ranks into one static page for GitHub Pages."""

import json
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path

from .registry import CONTINENTS, STATUS_ORDER, Call, Edition, current_edition
from .schema import CrawlRecord, Rank, RankFile, RegistryData, SeriesData
from .worldmap import world_map

SOON_DAYS = 45
EVIDENCE = {
    "confirmed": "confirmed for this edition",
    "partial": "edition entered, deadlines from last year",
    "guessed": "guessed from last year",
}


def fmt(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def conference_text(ed: Edition) -> str:
    if ed.start and ed.end and ed.start != ed.end:
        if ed.start.month == ed.end.month:
            return f"{ed.start.day:02d}.–{fmt(ed.end)}"
        return f"{ed.start.strftime('%d.%m.')}–{fmt(ed.end)}"
    if ed.start:
        return fmt(ed.start)
    return ed.when or ""


def call_line(call: Call, today: date) -> str:
    """One call: kind, deadline (confirmed, typical, unknown or closed), note."""
    note = f'<div class="note">{escape(call.note)}</div>' if call.note else ""
    kind = f'<span class="kind">{escape(call.kind.replace("-", " "))}</span>'
    status = call.status(today)
    if call.deadline and status == "open":
        days = (call.deadline - today).days
        cls = "soon" if days <= SOON_DAYS else "open"
        when = f'<strong>{fmt(call.deadline)}</strong> <span class="days" data-deadline="{call.deadline.isoformat()}">in {days} days</span>'
    elif status == "expected":
        cls = "expected"
        last = f' <span class="muted">(last: {fmt(call.hint)})</span>' if call.hint else ""
        when = f"typically {fmt(call.expected)}{last}"
    elif status == "closed":
        cls = "closed"
        when = f"closed {fmt(call.deadline)}".strip()
    else:
        cls, when = "unknown", "date unknown"
    return f'<div class="cl st-{cls}">{kind} {when}{note}</div>'


def calls_cell(ed: Edition, today: date) -> str:
    if not ed.calls:
        return '<span class="muted">no call known yet</span>'
    calls = sorted(ed.calls, key=lambda c: (STATUS_ORDER.index(c.status(today)), c.effective_deadline() or date.max))
    return "".join(call_line(c, today) for c in calls)


def languages_cell(series: SeriesData) -> str:
    """Submission languages as chips, then talks and proceedings where they differ."""
    inferred = series.get("language_source") != "stated"
    cls = "lang inferred" if inferred else "lang"
    tip = ' title="inferred from the call text, programme or publisher, not stated in the call"' if inferred else ""
    langs = series.get("languages", [])
    parts = ["".join(f'<span class="{cls}"{tip}>{escape(c)}</span>' for c in langs)]
    talks = series.get("presentation_languages")
    if talks and talks != langs:
        parts.append(f'<div class="note">talks: {escape(" ".join(talks))}</div>')
    proceedings = series.get("proceedings_languages")
    if proceedings == []:
        parts.append('<div class="note">no proceedings</div>')
    elif proceedings and proceedings != langs:
        parts.append(f'<div class="note">proceedings: {escape(" ".join(proceedings))}</div>')
    return "".join(parts)


def language_flags(crawl: CrawlRecord, series: SeriesData) -> list[str]:
    """Language hints from the page that the registry does not cover yet."""
    known = set(series.get("languages", [])) | set(series.get("presentation_languages", []))
    proceedings = set(series.get("proceedings_languages", known))
    flags = []
    for hint in crawl.get("language_hints", []):
        expected = proceedings if hint["kind"] == "publisher" else known
        if hint["languages"] and not set(hint["languages"]) <= expected:
            flags.append(
                f'<span class="warn" title="{escape(hint["phrase"])}">language? '
                f"{escape(' '.join(hint['languages']))} ({escape(hint['kind'])})</span>"
            )
    return flags


def crawl_cell(crawl: CrawlRecord | None, ed: Edition, series: SeriesData) -> str:
    if not crawl:
        return '<span class="muted">not crawled yet</span>'
    parts = []
    confirmed = {c.deadline.isoformat() for c in ed.calls if c.deadline}
    checked = crawl.get("checked", "")[:10]
    if crawl.get("error"):
        parts.append(f'<span class="warn">unreachable ({escape(str(crawl["error"]))})</span>')
    if changed_on := crawl.get("changed_on"):
        parts.append(f'<span class="flag">page changed {fmt(date.fromisoformat(changed_on[:10]))}</span>')
    for c in crawl.get("candidates", [])[:3]:
        parts.append(
            f'<span class="cand{" ok" if c["when"] in confirmed else ""}" '
            f'title="{escape(c["context"])}">{fmt(date.fromisoformat(c["when"]))} '
            f'<span class="muted">near “{escape(c["keyword"])}”</span></span>'
        )
    parts += language_flags(crawl, series)
    for p in crawl.get("probes", []):
        if p.get("exists"):
            parts.append(f'<a class="flag" href="{escape(p["url"])}">page up: {escape(p["url"].split("//", 1)[-1])}</a>')
    if checked:
        parts.append(f'<span class="muted">checked {fmt(date.fromisoformat(checked))}</span>')
    return "<br>".join(parts)


def row(series: SeriesData, ed: Edition, crawl: CrawlRecord | None, rank: Rank | None, today: date) -> tuple[date, str]:
    sort_date = ed.next_deadline(today)
    topics = " ".join(series.get("topics", []))
    chips = "".join(f'<span class="chip">{escape(t)}</span>' for t in series.get("topics", []))
    kind = f'<div class="note">{escape(series["kind"])}</div>' if series.get("kind") else ""
    if rank:
        rank_html = escape(rank.get("rank", ""))
    elif series.get("icore"):
        rank_html = '<span class="muted">not looked up</span>'
    else:
        rank_html = '<span class="muted">not listed</span>'
    link_label = "previous edition" if ed.url_is_fallback else "website"
    link = f'<a href="{escape(ed.url)}">{link_label}</a>' if ed.url else ""
    if ed.call_url:
        link += f'<br><a href="{escape(ed.call_url)}">call</a>'
    guessed = '<div class="note">not yet in the registry, guessed from the last edition</div>' if ed.synthesized else ""
    html = f"""
      <tr class="ev-{ed.evidence}" data-topics="{escape(topics)}" data-langs="{escape(" ".join(series.get("languages", [])))}">
        <td><span class="sr">{EVIDENCE[ed.evidence]}: </span><strong>{escape(series["name"])} {ed.year}</strong><div class="note">{escape(series.get("full_name", ""))}</div>{chips}{guessed}</td>
        <td>{escape(series.get("organizer", ""))}{kind}</td>
        <td class="rank">{rank_html}</td>
        <td>{escape(ed.location or "")}</td>
        <td class="nowrap">{languages_cell(series)}</td>
        <td class="nowrap">{escape(conference_text(ed))}</td>
        <td class="call">{calls_cell(ed, today)}</td>
        <td class="crawl">{crawl_cell(crawl, ed, series)}</td>
        <td>{link}</td>
      </tr>"""
    return (sort_date or date.max), html


def build(registry: RegistryData, crawl_dir: Path, icore_file: Path, out: Path, today: date) -> Path:
    icore_meta: RankFile | None = json.loads(icore_file.read_text()) if icore_file.exists() else None
    ranks = icore_meta["ranks"] if icore_meta else {}
    groups: dict[int, dict[str, list[tuple[date, str]]]] = defaultdict(lambda: defaultdict(list))
    topics: set[str] = set()
    languages: set[str] = set()
    counts: dict[str, int] = defaultdict(int)
    for series in registry["series"]:
        ed = current_edition(series, today)
        crawl_file = crawl_dir / f"{series['id']}.json"
        crawl: CrawlRecord | None = json.loads(crawl_file.read_text()) if crawl_file.exists() else None
        if crawl and crawl.get("edition") != ed.year:
            crawl = None
        groups[ed.year][series.get("continent", "Online")].append(row(series, ed, crawl, ranks.get(series["id"]), today))
        topics.update(series.get("topics", []))
        languages.update(series.get("languages", []))
        counts[series.get("continent", "Online")] += 1

    sections = []
    for year in sorted(groups):
        blocks = []
        for continent in sorted(groups[year], key=lambda c: CONTINENTS.index(c) if c in CONTINENTS else 99):
            rows = "".join(h for _, h in sorted(groups[year][continent], key=lambda r: r[0]))
            blocks.append(f"""
    <div class="cblock" data-continent="{escape(continent)}">
    <h3>{escape(continent)}</h3>
    <div class="scroll"><table>
      <thead><tr><th>Venue</th><th>Organizer</th><th>ICORE</th><th>Location</th><th>Languages</th><th>Conference</th>
      <th>Calls</th><th>Crawler</th><th>Link</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div>
    </div>""")
        sections.append(f"<section><h2>Conferences in {year}</h2>{''.join(blocks)}</section>")

    filters = "".join(f'<label><input type="checkbox" value="{escape(t)}" checked> {escape(t)}</label>' for t in sorted(topics))
    language_filters = "".join(
        f'<label><input type="checkbox" value="{escape(c)}" checked> {escape(c)}</label>' for c in sorted(languages)
    )
    source = escape(icore_meta["source"] if icore_meta else "ICORE")
    page = TEMPLATE.format(
        today=fmt(today),
        sections="".join(sections),
        filters=filters,
        worldmap=world_map(counts),
        online=counts.get("Online", 0),
        language_filters=language_filters,
        ev_confirmed=EVIDENCE["confirmed"],
        ev_partial=EVIDENCE["partial"],
        ev_guessed=EVIDENCE["guessed"],
        icore_source=source,
        soon=SOON_DAYS,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Digital Education Venue Radar</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%232f5d8a'/%3E%3C/svg%3E">
<style>
:root {{
  --bg: #fbfaf7; --fg: #1f2328; --muted: #6a6f76; --line: #e3e0d8; --head: #f1eee6;
  --accent: #2f5d8a; --soon: #b3261e; --soon-bg: #fdecea; --open: #1e6b3a; --flag: #8a5a00; --flag-bg: #fff4d6;
  --chip: #e8eef5; --land: #c9d6e3; --land-hover: #a9bfd6; --land-on: #2f6aa3;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #16181b; --fg: #e6e6e3; --muted: #9aa0a6; --line: #2c3036; --head: #1f2227;
    --accent: #8ab4e0; --soon: #f28b82; --soon-bg: #3a1f1d; --open: #81c995; --flag: #f3c76b; --flag-bg: #3a3020;
    --chip: #253041; --land: #34404f; --land-hover: #46576b; --land-on: #4f8fd0;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #16181b; --fg: #e6e6e3; --muted: #9aa0a6; --line: #2c3036; --head: #1f2227;
  --accent: #8ab4e0; --soon: #f28b82; --soon-bg: #3a1f1d; --open: #81c995; --flag: #f3c76b; --flag-bg: #3a3020;
  --chip: #253041; --land: #34404f; --land-hover: #46576b; --land-on: #4f8fd0;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 24px 16px 48px; background: var(--bg); color: var(--fg);
  font: 15px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 1400px; margin: 0 auto; }}
h1 {{ margin: 0 0 4px; font-size: 1.6rem; }}
h2 {{ margin: 36px 0 4px; font-size: 1.3rem; border-bottom: 2px solid var(--line); padding-bottom: 4px; }}
h3 {{ margin: 20px 0 8px; font-size: 1.05rem; color: var(--muted); }}
a {{ color: var(--accent); }}
.lead {{ color: var(--muted); max-width: 70ch; }}
.filters {{ display: flex; flex-wrap: wrap; gap: 6px 14px; margin: 16px 0; font-size: .9rem; }}
.scroll {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 6px; }}
table {{ border-collapse: collapse; width: 100%; min-width: 1100px; }}
th, td {{ text-align: left; vertical-align: top; padding: 8px 10px; border-bottom: 1px solid var(--line); }}
th {{ background: var(--head); font-size: .85rem; font-weight: 600; }}
tr:last-child td {{ border-bottom: 0; }}
/* Bar before each row: how much of the edition is confirmed. Solid, dotted and striped, so it does not rely on colour. */
.ev-confirmed {{ --ev: var(--open); --ev-bg: var(--open); }}
.ev-partial {{ --ev: var(--flag); --ev-bg: repeating-linear-gradient(180deg, var(--flag) 0 4px, transparent 4px 7px); }}
.ev-guessed {{ --ev: var(--muted); --ev-bg: repeating-linear-gradient(135deg, var(--muted) 0 2px, transparent 2px 5px); }}
tbody tr td:first-child {{ position: relative; padding-left: 16px; }}
tbody tr td:first-child::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px; background: var(--ev-bg); }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 4px 0 16px; font-size: .88rem; color: var(--muted); }}
.legend strong {{ color: var(--fg); }}
.legend .ev {{ display: inline-block; width: 6px; height: 1.1em; vertical-align: -3px; margin-right: 6px; background: var(--ev-bg); }}
.sr {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }}
.note {{ color: var(--muted); font-size: .82rem; margin-top: 2px; }}
.muted {{ color: var(--muted); }}
.mapbox {{ display: flex; flex-wrap: wrap; align-items: center; gap: 12px 24px; margin: 18px 0 6px; }}
.worldmap {{ width: 100%; max-width: 520px; height: auto; }}
.region path {{ fill: var(--land); stroke: var(--bg); stroke-width: .4; transition: fill .15s; }}
.region {{ cursor: pointer; outline: none; }}
.region text {{ font-size: 9px; font-weight: 600; fill: var(--fg); text-anchor: middle; dominant-baseline: middle; pointer-events: none; }}
.region:hover path, .region:focus-visible path {{ fill: var(--land-hover); }}
.region.empty {{ cursor: default; }}
.region.empty path {{ fill: var(--line); }}
.worldmap.picking .region path {{ fill: var(--line); }}
.worldmap .region[aria-pressed="true"] path {{ fill: var(--land-on); }}
.worldmap .region[aria-pressed="true"] text {{ fill: #fff; }}
.mapside {{ display: flex; flex-direction: column; align-items: flex-start; gap: 8px; max-width: 220px; }}
.mapside button {{ font: inherit; font-size: .88rem; padding: 3px 10px; border: 1px solid var(--line); border-radius: 6px;
  background: var(--head); color: var(--fg); cursor: pointer; }}
.mapside button[aria-pressed="true"] {{ background: var(--land-on); border-color: var(--land-on); color: #fff; }}
.lang {{ display: inline-block; border: 1px solid var(--line); border-radius: 4px; padding: 0 5px; margin: 0 4px 2px 0; font-size: .78rem; font-weight: 600; }}
.lang.inferred {{ font-weight: 400; border-style: dashed; cursor: help; }}
.chip {{ display: inline-block; background: var(--chip); border-radius: 10px; padding: 0 7px; margin: 4px 4px 0 0; font-size: .75rem; }}
.nowrap {{ white-space: nowrap; }}
.rank {{ font-weight: 600; }}
.days {{ font-size: .82rem; }}
.cl {{ padding: 2px 4px; margin: 0 -4px 4px; border-radius: 4px; }}
.kind {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .03em; color: var(--muted); margin-right: 4px; }}
.cl.st-soon {{ background: var(--soon-bg); }}
.cl.st-soon strong, .cl.st-soon .days {{ color: var(--soon); }}
.cl.st-open strong {{ color: var(--open); }}
.cl.st-closed {{ color: var(--muted); }}
td.call {{ min-width: 240px; }}
.crawl {{ font-size: .82rem; min-width: 190px; }}
.flag {{ background: var(--flag-bg); color: var(--flag); border-radius: 4px; padding: 0 4px; }}
.warn {{ color: var(--soon); }}
.cand {{ cursor: help; border-bottom: 1px dotted var(--muted); }}
.cand.ok::after {{ content: " ✓"; color: var(--open); }}
footer {{ margin-top: 40px; color: var(--muted); font-size: .85rem; max-width: 80ch; }}
</style>
</head>
<body>
<main>
<h1>Digital Education Venue Radar</h1>
<p class="lead">Conferences on digital education, AI in education, computing education and the Scholarship of
Teaching and Learning, with their calls, deadlines, organizers and rankings. Built {today}, crawled weekly.
Deadlines due within {soon} days are marked red. Each series shows its next edition that still has an open call.</p>
<div class="mapbox">{worldmap}
<div class="mapside"><button type="button" class="region-btn" data-continent="Online" aria-pressed="false">Online ({online})</button>
<button type="button" id="all-continents">All continents</button>
<p class="note">Click a continent to show only its venues; click more to add them.</p></div></div>
<div class="filters" id="filters"><strong>Topics:</strong> {filters}</div>
<div class="filters" id="langs"><strong>Submission in:</strong> {language_filters}</div>
<div class="legend"><strong>Data:</strong>
<span><i class="ev ev-confirmed"></i>{ev_confirmed}</span>
<span><i class="ev ev-partial"></i>{ev_partial}</span>
<span><i class="ev ev-guessed"></i>{ev_guessed}</span></div>
{sections}
<footer>
<p><strong>Calls</strong> lists each call of the edition (workshops, papers, special sessions, ...). A bold date is confirmed
on the official page. “Typically” is the previous cycle's deadline moved to this cycle.</p>
<p><strong>Languages</strong> are the languages a contribution may be submitted in, with talks and proceedings
listed where they differ. A solid box means the call states it; a dashed one is inferred from the call text,
programme or proceedings publisher. The filter keeps venues that accept at least one of the ticked languages.</p>
<p><strong>ICORE</strong> ({icore_source}) rates the main paper track, A* &gt; A &gt; B &gt; C. A workshop at an A conference
is not an A publication. Education and German-language venues are not part of ICORE, so “not listed” says nothing about quality there.</p>
<p><strong>Crawler</strong> shows what the weekly crawl saw: whether the page changed, future dates near the call keywords
(hover for context; ✓ means it matches the confirmed deadline), whether the next edition's page is online, and “language?” when the page names a language or proceedings
publisher the registry does not list (hover for the phrase). It never changes the confirmed data, that is edited in
<code>registry.yaml</code>.</p>
</footer>
</main>
<script>
const checked = sel => new Set([...document.querySelectorAll(sel + ' input')].filter(b => b.checked).map(b => b.value));
// Continents picked on the map; empty means all.
const picked = new Set();
const toggles = document.querySelectorAll('.region, .region-btn');
function apply() {{
  const topics = checked('#filters'), langs = checked('#langs');
  document.querySelectorAll('tbody tr').forEach(tr => {{
    const t = tr.dataset.topics.split(' '), l = tr.dataset.langs.split(' ');
    tr.hidden = !t.some(x => topics.has(x)) || !l.some(x => langs.has(x));
  }});
  document.querySelectorAll('.cblock').forEach(b => {{
    const shown = picked.size === 0 || picked.has(b.dataset.continent);
    b.hidden = !shown || !b.querySelector('tbody tr:not([hidden])');
  }});
  document.querySelectorAll('main section').forEach(s => {{ s.hidden = !s.querySelector('.cblock:not([hidden])'); }});
  toggles.forEach(el => el.setAttribute('aria-pressed', picked.has(el.dataset.continent)));
  document.querySelector('.worldmap').classList.toggle('picking', picked.size > 0);
}}
function toggle(name) {{ picked.has(name) ? picked.delete(name) : picked.add(name); apply(); }}
toggles.forEach(el => {{
  if (el.classList.contains('empty')) return;
  el.addEventListener('click', () => toggle(el.dataset.continent));
  el.addEventListener('keydown', e => {{
    if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); toggle(el.dataset.continent); }}
  }});
}});
document.getElementById('all-continents').addEventListener('click', () => {{ picked.clear(); apply(); }});
document.querySelectorAll('.filters input').forEach(b => b.addEventListener('change', apply));
// The page is rebuilt weekly; count the days from the reader's today, not the build day.
const today = new Date(); today.setHours(0, 0, 0, 0);
document.querySelectorAll('.days[data-deadline]').forEach(el => {{
  const d = new Date(el.dataset.deadline + 'T00:00:00');
  const days = Math.round((d - today) / 86400000);
  const line = el.closest('.cl');
  if (days < 0) {{ el.textContent = 'passed'; line.className = 'cl st-closed'; }}
  else {{
    el.textContent = days === 0 ? 'today' : `in ${{days}} days`;
    line.className = days <= {soon} ? 'cl st-soon' : 'cl st-open';
  }}
}});
</script>
</body>
</html>
"""
