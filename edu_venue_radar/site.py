"""Render the registry, crawl results and ICORE ranks into one static page for GitHub Pages."""

import json
from collections import defaultdict
from datetime import date
from html import escape
from pathlib import Path

from .registry import CONTINENTS, Call, Edition, current_edition

SOON_DAYS = 45


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
    order = {"open": 0, "expected": 1, "unknown": 2, "closed": 3}
    calls = sorted(ed.calls, key=lambda c: (order[c.status(today)], c.effective_deadline() or date.max))
    return "".join(call_line(c, today) for c in calls)


def crawl_cell(crawl: dict | None, ed: Edition) -> str:
    if not crawl:
        return '<span class="muted">not crawled yet</span>'
    parts = []
    confirmed = {c.deadline.isoformat() for c in ed.calls if c.deadline}
    checked = crawl.get("checked", "")[:10]
    if crawl.get("error"):
        parts.append(f'<span class="warn">unreachable ({escape(str(crawl["error"]))})</span>')
    if crawl.get("changed_on"):
        parts.append(f'<span class="flag">page changed {fmt(date.fromisoformat(crawl["changed_on"][:10]))}</span>')
    for c in crawl.get("candidates", [])[:3]:
        parts.append(
            f'<span class="cand{" ok" if c["when"] in confirmed else ""}" '
            f'title="{escape(c["context"])}">{fmt(date.fromisoformat(c["when"]))} '
            f'<span class="muted">near “{escape(c["keyword"])}”</span></span>'
        )
    for p in crawl.get("probes", []):
        if p.get("exists"):
            parts.append(f'<a class="flag" href="{escape(p["url"])}">page up: {escape(p["url"].split("//", 1)[-1])}</a>')
    if checked:
        parts.append(f'<span class="muted">checked {fmt(date.fromisoformat(checked))}</span>')
    return "<br>".join(parts)


def row(series: dict, ed: Edition, crawl: dict | None, rank: dict | None, today: date) -> tuple[date, str]:
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
    guessed = '<div class="note">not yet in the registry, guessed from the last edition</div>' if ed.synthesized else ""
    html = f"""
      <tr data-topics="{escape(topics)}">
        <td><strong>{escape(series["name"])} {ed.year}</strong><div class="note">{escape(series.get("full_name", ""))}</div>{chips}{guessed}</td>
        <td>{escape(series.get("organizer", ""))}{kind}</td>
        <td class="rank">{rank_html}</td>
        <td>{escape(ed.location or "")}</td>
        <td class="nowrap">{escape(conference_text(ed))}</td>
        <td class="call">{calls_cell(ed, today)}</td>
        <td class="crawl">{crawl_cell(crawl, ed)}</td>
        <td>{link}</td>
      </tr>"""
    return (sort_date or date.max), html


def build(registry: dict, crawl_dir: Path, icore_file: Path, out: Path, today: date) -> Path:
    ranks = json.loads(icore_file.read_text())["ranks"] if icore_file.exists() else {}
    icore_meta = json.loads(icore_file.read_text()) if icore_file.exists() else {}
    groups: dict[int, dict[str, list[tuple[date, str]]]] = defaultdict(lambda: defaultdict(list))
    topics: set[str] = set()
    for series in registry["series"]:
        ed = current_edition(series, today)
        crawl_file = crawl_dir / f"{series['id']}.json"
        crawl = json.loads(crawl_file.read_text()) if crawl_file.exists() else None
        if crawl and crawl.get("edition") != ed.year:
            crawl = None
        groups[ed.year][series.get("continent", "Online")].append(row(series, ed, crawl, ranks.get(series["id"]), today))
        topics.update(series.get("topics", []))

    sections = []
    for year in sorted(groups):
        blocks = []
        for continent in sorted(groups[year], key=lambda c: CONTINENTS.index(c) if c in CONTINENTS else 99):
            rows = "".join(h for _, h in sorted(groups[year][continent], key=lambda r: r[0]))
            blocks.append(f"""
    <h3>{escape(continent)}</h3>
    <div class="scroll"><table>
      <thead><tr><th>Venue</th><th>Organizer</th><th>ICORE</th><th>Location</th><th>Conference</th>
      <th>Calls</th><th>Crawler</th><th>Link</th></tr></thead>
      <tbody>{rows}</tbody>
    </table></div>""")
        sections.append(f"<section><h2>Conferences in {year}</h2>{''.join(blocks)}</section>")

    filters = "".join(f'<label><input type="checkbox" value="{escape(t)}" checked> {escape(t)}</label>' for t in sorted(topics))
    source = escape(icore_meta.get("source", "ICORE"))
    page = TEMPLATE.format(
        today=fmt(today),
        sections="".join(sections),
        filters=filters,
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
  --chip: #e8eef5;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #16181b; --fg: #e6e6e3; --muted: #9aa0a6; --line: #2c3036; --head: #1f2227;
    --accent: #8ab4e0; --soon: #f28b82; --soon-bg: #3a1f1d; --open: #81c995; --flag: #f3c76b; --flag-bg: #3a3020;
    --chip: #253041;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #16181b; --fg: #e6e6e3; --muted: #9aa0a6; --line: #2c3036; --head: #1f2227;
  --accent: #8ab4e0; --soon: #f28b82; --soon-bg: #3a1f1d; --open: #81c995; --flag: #f3c76b; --flag-bg: #3a3020;
  --chip: #253041;
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
.note {{ color: var(--muted); font-size: .82rem; margin-top: 2px; }}
.muted {{ color: var(--muted); }}
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
<div class="filters" id="filters"><strong>Topics:</strong> {filters}</div>
{sections}
<footer>
<p><strong>Calls</strong> lists each call of the edition (workshops, papers, special sessions, ...). A bold date is confirmed
on the official page. “Typically” is the previous cycle's deadline moved to this cycle.</p>
<p><strong>ICORE</strong> ({icore_source}) rates the main paper track, A* &gt; A &gt; B &gt; C. A workshop at an A conference
is not an A publication. Education and German-language venues are not part of ICORE, so “not listed” says nothing about quality there.</p>
<p><strong>Crawler</strong> shows what the weekly crawl saw: whether the page changed, future dates near the call keywords
(hover for context; ✓ means it matches the confirmed deadline), and whether the next edition's page is online. It never changes the confirmed data, that is edited in
<code>registry.yaml</code>.</p>
</footer>
</main>
<script>
const boxes = document.querySelectorAll('#filters input');
function apply() {{
  const on = new Set([...boxes].filter(b => b.checked).map(b => b.value));
  document.querySelectorAll('tbody tr').forEach(tr => {{
    const t = tr.dataset.topics.split(' ');
    tr.hidden = !t.some(x => on.has(x));
  }});
}}
boxes.forEach(b => b.addEventListener('change', apply));
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
