"""Command line: crawl pages, look up ranks, build the page, roll the registry forward."""

import argparse
from datetime import date
from pathlib import Path

from . import crawl, icore, registry, site

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="edu-venue-radar", description=__doc__)
    p.add_argument("--root", type=Path, default=ROOT, help="project folder with registry.yaml, data/ and docs/")
    p.add_argument("--today", type=date.fromisoformat, default=date.today(), help="pretend it is this day (ISO)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the current edition and call of every series")
    c = sub.add_parser("crawl", help="fetch the pages and record changes and candidate deadlines")
    c.add_argument("ids", nargs="*", help="only these series")
    sub.add_parser("icore", help="look up the ICORE ranks")
    sub.add_parser("build", help="write docs/index.html")
    sub.add_parser("update", help="crawl, then build (the weekly job)")
    r = sub.add_parser("roll", help="append the next edition of a series to registry.yaml")
    r.add_argument("id")
    args = p.parse_args(argv)

    reg_path = args.root / "registry.yaml"
    reg = registry.load(reg_path)
    crawl_dir = args.root / "data" / "crawl"
    icore_file = args.root / "data" / "icore.json"
    page = args.root / "docs" / "index.html"

    if args.cmd == "list":
        for s in reg["series"]:
            ed = registry.current_edition(s, args.today)
            dl = ed.next_deadline(args.today)
            flag = " (guessed)" if ed.synthesized else ""
            deadline = dl.isoformat() if dl else "-"
            print(f"{s['id']:<13} {ed.year}{flag:<10} {ed.status(args.today):<9} {deadline:<11} {ed.location or ''}")
    elif args.cmd == "crawl":
        for res in crawl.crawl(reg, crawl_dir, args.today, set(args.ids) or None):
            seen = ", ".join(c["when"] for c in res.get("candidates", []))
            changed = "changed " if res.get("changed_on") == res["checked"] else ""
            print(f"{res['id']:<13} {res.get('status')!s:<5} {changed}{seen}")
    elif args.cmd == "icore":
        ranks = icore.update(reg, icore_file, args.today)
        for sid, hit in ranks["ranks"].items():
            print(f"{sid:<13} {hit['rank']}")
    elif args.cmd == "build":
        print(site.build(reg, crawl_dir, icore_file, page, args.today))
    elif args.cmd == "update":
        crawl.crawl(reg, crawl_dir, args.today)
        print(site.build(reg, crawl_dir, icore_file, page, args.today))
    elif args.cmd == "roll":
        year = registry.roll(reg, args.id)
        registry.save(reg, reg_path)
        print(f"{args.id}: edition {year} added, check location, dates and deadline in registry.yaml")
    return 0
