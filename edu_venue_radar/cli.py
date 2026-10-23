"""Command line: crawl pages, look up ranks, build the page, roll the registry forward."""

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import crawl, icore, registry, site
from .schema import RegistryData

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Paths:
    registry: Path
    crawl_dir: Path
    icore_file: Path
    page: Path

    @classmethod
    def under(cls, root: Path) -> "Paths":
        return cls(root / "registry.yaml", root / "data" / "crawl", root / "data" / "icore.json", root / "docs" / "index.html")


def cmd_check(args: argparse.Namespace, reg: RegistryData, paths: Paths) -> int:
    problems = registry.validate(reg)
    for msg in problems:
        print(msg)
    print(f"{len(reg.get('series') or [])} series, {len(problems)} problems")
    return 1 if problems else 0


def cmd_list(args: argparse.Namespace, reg: RegistryData, paths: Paths) -> int:
    for s in reg["series"]:
        ed = registry.current_edition(s, args.today)
        dl = ed.next_deadline(args.today)
        flag = " (guessed)" if ed.synthesized else ""
        deadline = dl.isoformat() if dl else "-"
        print(f"{s['id']:<13} {ed.year}{flag:<10} {ed.status(args.today):<9} {deadline:<11} {ed.location or ''}")
    return 0


def cmd_crawl(args: argparse.Namespace, reg: RegistryData, paths: Paths) -> int:
    for res in crawl.crawl(reg, paths.crawl_dir, args.today, set(args.ids) or None):
        seen = ", ".join(c["when"] for c in res.get("candidates", []))
        changed = "changed " if res.get("changed_on") == res["checked"] else ""
        print(f"{res['id']:<13} {res.get('status')!s:<5} {changed}{seen}")
    return 0


def cmd_icore(args: argparse.Namespace, reg: RegistryData, paths: Paths) -> int:
    ranks = icore.update(reg, paths.icore_file, args.today)
    for sid, hit in ranks["ranks"].items():
        print(f"{sid:<13} {hit['rank']}")
    return 0


def cmd_build(args: argparse.Namespace, reg: RegistryData, paths: Paths) -> int:
    print(site.build(reg, paths.crawl_dir, paths.icore_file, paths.page, args.today))
    return 0


def cmd_update(args: argparse.Namespace, reg: RegistryData, paths: Paths) -> int:
    crawl.crawl(reg, paths.crawl_dir, args.today)
    return cmd_build(args, reg, paths)


def cmd_roll(args: argparse.Namespace, reg: RegistryData, paths: Paths) -> int:
    year = registry.roll(reg, args.id)
    registry.save(reg, paths.registry)
    print(f"{args.id}: edition {year} added, check location, dates and deadline in registry.yaml")
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace, RegistryData, Paths], int]] = {
    "check": cmd_check,
    "list": cmd_list,
    "crawl": cmd_crawl,
    "icore": cmd_icore,
    "build": cmd_build,
    "update": cmd_update,
    "roll": cmd_roll,
}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="edu-venue-radar", description=__doc__)
    p.add_argument("--root", type=Path, default=ROOT, help="project folder with registry.yaml, data/ and docs/")
    p.add_argument("--today", type=date.fromisoformat, default=date.today(), help="pretend it is this day (ISO)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show the current edition and call of every series")
    sub.add_parser("check", help="report typos and invalid values in registry.yaml (exit 1 if any)")
    c = sub.add_parser("crawl", help="fetch the pages and record changes and candidate deadlines")
    c.add_argument("ids", nargs="*", help="only these series")
    sub.add_parser("icore", help="look up the ICORE ranks")
    sub.add_parser("build", help="write docs/index.html")
    sub.add_parser("update", help="crawl, then build (the weekly job)")
    r = sub.add_parser("roll", help="append the next edition of a series to registry.yaml")
    r.add_argument("id")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    paths = Paths.under(args.root)
    return COMMANDS[args.cmd](args, registry.load(paths.registry), paths)
