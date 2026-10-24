"""`dl` command line entry point."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml

from dltools.lines import discover, fetch_eol
from dltools.render import load_catalog, render
from dltools.state import diff, load_state, save_state
from dltools.wolfi import ARCHES, fetch_index, parse_apkindex


def _write_if_changed(path: Path, text: str) -> None:
    if not path.exists() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def cmd_sync(args) -> int:
    catalog = load_catalog(args.catalog)
    today = date.fromisoformat(args.today) if args.today else date.today()
    indexes = {arch: parse_apkindex(fetch_index(arch)) for arch in ARCHES}
    current = load_state(args.state)
    lines, warnings = discover(indexes, fetch_eol(), today, current)
    events = diff(current, lines)
    save_state(args.state, lines)

    locks = Path(args.locks)
    wanted: set[Path] = set()
    for line in lines:
        line_dir = locks / line.image / line.name
        wanted.add(line_dir)
        for variant in catalog["images"][line.image]["variants"]:
            cfg = render(catalog, line, variant)
            _write_if_changed(
                line_dir / f"{variant}.apko.yaml", yaml.safe_dump(cfg, sort_keys=False)
            )
    if locks.exists():
        for line_dir in locks.glob("*/*"):
            if line_dir.is_dir() and line_dir not in wanted:
                shutil.rmtree(line_dir)

    for event in events:
        print(json.dumps(event.to_dict()))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dl")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="resolve lines and pins, render apko configs")
    sync.add_argument("--state", default="state/lines.json")
    sync.add_argument("--locks", default="locks")
    sync.add_argument("--catalog", default="catalog.yaml")
    sync.add_argument("--today", help="YYYY-MM-DD (default: today)")
    sync.set_defaults(func=cmd_sync)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
