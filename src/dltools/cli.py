"""`dl` command line entry point."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml

from dltools.gate import BLOCKING, evaluate, findings, load_ignore, summary_markdown
from dltools.lines import discover, fetch_eol
from dltools.notify import upsert_issue
from dltools.render import load_catalog, render
from dltools.rescan import decide
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


def cmd_gate(args) -> int:
    candidate = json.loads(Path(args.candidate).read_text())
    published = json.loads(Path(args.published).read_text()) if args.published else None
    result = evaluate(candidate, published, load_ignore(args.ignore))
    print(summary_markdown(result, args.label))
    return 0 if result.passed else 1


def cmd_rescan_decide(args) -> int:
    report = json.loads(Path(args.report).read_text())
    prev_path = Path(args.previous)
    previous = set(prev_path.read_text().split()) if prev_path.exists() else set()
    ignore = load_ignore(args.ignore)
    d = decide(report, ignore, previous)
    ids = sorted({f.id for f in findings(report, ignore) if f.severity in BLOCKING})
    print(json.dumps({"open_issue": d.open_issue, "rebuild": d.rebuild,
                      "summary": d.summary, "ids": ids}))
    return 0


def cmd_notify(args) -> int:
    upsert_issue(args.title, args.body)
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

    gate = sub.add_parser("gate", help="apply the scan gate to Trivy JSON reports")
    gate.add_argument("--candidate", required=True)
    gate.add_argument("--published")
    gate.add_argument("--ignore", default=".trivyignore")
    gate.add_argument("--label", default="")
    gate.set_defaults(func=cmd_gate)

    rescan = sub.add_parser("rescan-decide", help="decide issue/rebuild for a re-scan report")
    rescan.add_argument("--report", required=True)
    rescan.add_argument("--ignore", default=".trivyignore")
    rescan.add_argument("--previous", required=True, help="file of previously seen IDs")
    rescan.set_defaults(func=cmd_rescan_decide)

    notify = sub.add_parser("notify", help="open or comment on an automation issue")
    notify.add_argument("--title", required=True)
    notify.add_argument("--body", required=True)
    notify.set_defaults(func=cmd_notify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
