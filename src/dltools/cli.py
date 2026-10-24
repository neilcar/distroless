"""`dl` command line entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml

from dltools.gate import BLOCKING, evaluate, findings, load_ignore, summary_markdown
from dltools.lines import Line, discover, fetch_eol
from dltools.lockcheck import RUNTIME_FORBIDDEN, check_lock
from dltools.notify import upsert_issue
from dltools.ocilayout import append_layer
from dltools.pinning import apply_pins, released_overrides
from dltools.render import load_catalog, render, render_vendor
from dltools.rescan import decide
from dltools.state import diff, load_state, save_state
from dltools.tags import tags
from dltools.vendor import DEFAULT_LAUNCH_DIR, build_layer
from dltools.wolfi import ARCHES, fetch_index, parse_apkindex


def load_indexes(index_dir: str | None) -> dict:
    """APKINDEX per arch, read from `index_dir` (written by `dl fetch-index`) when given."""
    if index_dir:
        return {arch: parse_apkindex((Path(index_dir) / f"APKINDEX.{arch}").read_text())
                for arch in ARCHES}
    return {arch: parse_apkindex(fetch_index(arch)) for arch in ARCHES}


def cmd_fetch_index(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for arch in ARCHES:
        (out / f"APKINDEX.{arch}").write_text(fetch_index(arch))
    return 0


def _write_if_changed(path: Path, text: str) -> None:
    if not path.exists() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def cmd_sync(args) -> int:
    catalog = load_catalog(args.catalog)
    today = date.fromisoformat(args.today) if args.today else date.today()
    indexes = load_indexes(args.index_dir)
    current = load_state(args.state)
    lines, warnings = discover(
        indexes, fetch_eol(), today, current, catalog["images"]["nginx"].get("lines")
    )
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
        vendor = render_vendor(catalog, line)
        if vendor is not None:
            _write_if_changed(
                line_dir / "vendor.json", json.dumps(vendor, indent=2, sort_keys=True) + "\n"
            )
    if locks.exists():
        for line_dir in locks.glob("*/*"):
            if line_dir.is_dir() and line_dir not in wanted:
                shutil.rmtree(line_dir)

    for event in events:
        print(json.dumps(event.to_dict()))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.warnings:
        Path(args.warnings).write_text("".join(f"{w}\n" for w in warnings))
    return 0


def cmd_gate(args) -> int:
    candidate = json.loads(Path(args.candidate).read_text())
    published = json.loads(Path(args.published).read_text()) if args.published else None
    indexes = load_indexes(args.index_dir)
    prefixes, components = list(args.vendor_prefix), []
    if args.vendor:
        for v in json.loads(Path(args.vendor).read_text())["vendor"]:
            prefixes.append(v["prefix"])
            components.append(f"{v['name']} {v['version']}")
    result = evaluate(candidate, published, load_ignore(args.ignore), indexes,
                      vendor_prefixes=prefixes, vendor_components=components)
    print(summary_markdown(result, args.label))
    return 0 if result.passed else 1


def cmd_rescan_decide(args) -> int:
    report = json.loads(Path(args.report).read_text())
    prev_path = Path(args.previous)
    previous = set(prev_path.read_text().split()) if prev_path.exists() else set()
    ignore = load_ignore(args.ignore)
    indexes = load_indexes(args.index_dir)
    d = decide(report, ignore, previous, indexes)
    ids = sorted({f.id for f in findings(report, ignore) if f.severity in BLOCKING})
    print(json.dumps({"open_issue": d.open_issue, "rebuild": d.rebuild,
                      "summary": d.summary, "ids": ids}))
    return 0


def cmd_notify(args) -> int:
    upsert_issue(args.title, args.body)
    return 0


# Inputs that change what sync renders/locks: building now would use stale configs,
# so the build requests a sync instead (which re-locks, commits and builds).
RESYNC_INPUTS = ("catalog.yaml", "melange/", "packages/", "melange.rsa.pub")
# Inputs that only change how existing locks are judged: rebuild everything.
REBUILD_INPUTS = (".trivyignore",)


def cmd_matrix(args) -> int:
    locks = Path(args.locks)
    entries = sorted(
        (p.parts[-3], p.parts[-2], p.name.removesuffix(".apko.yaml"))
        for p in locks.glob("*/*/*.apko.yaml")
    )
    changed = [c.strip() for c in Path(args.changed).read_text().splitlines()]
    changed = [c for c in changed if c]
    if any(c.startswith(RESYNC_INPUTS) for c in changed):
        print(json.dumps({"include": [], "resync": True}))
        return 0
    if not changed or any(c.startswith(REBUILD_INPUTS) for c in changed):
        selected = entries
    else:
        wanted = set()
        for c in changed:
            parts = Path(c).parts
            if len(parts) == 4 and parts[0] == "locks":
                wanted.add((parts[1], parts[2], parts[3].split(".")[0]))
        # vendor.json is shared by every variant of its line.
        selected = [e for e in entries if e in wanted or (e[0], e[1], "vendor") in wanted]
    include = [{"image": i, "line": ln, "variant": v} for i, ln, v in selected]
    print(json.dumps({"include": include, "resync": False}))
    return 0


def cmd_lock_check(args) -> int:
    failed = False
    forbidden = RUNTIME_FORBIDDEN if args.runtime else frozenset()
    for path in args.locks:
        for violation in check_lock(json.loads(Path(path).read_text()), forbidden=forbidden):
            print(f"{path}: {violation}")
            failed = True
    return 1 if failed else 0


def cmd_tags(args) -> int:
    line = next(
        ln for ln in load_state(args.state) if ln.image == args.image and ln.name == args.line
    )
    raw = Path(args.lock).read_bytes()
    # The tag carries what the lock actually contains, not what state hoped for
    # (they differ when a re-lock for a new version was blocked).
    locked = {
        p["name"]: p["version"]
        for p in json.loads(raw).get("contents", {}).get("packages", [])
    }
    if line.package in locked:
        line = Line(line.image, line.name, line.package, locked[line.package])
    lock_hash = hashlib.sha256(raw).hexdigest()
    print("\n".join(tags(line, args.variant, lock_hash)))
    return 0


def cmd_pin_released(args) -> int:
    """0: lock is released-only; 3: config re-pinned, re-lock needed; 2: unresolvable."""
    lock = json.loads(Path(args.lock).read_text())
    indexes = load_indexes(args.index_dir)
    pins, missing = released_overrides(lock, indexes)
    if missing:
        print(f"no released version on every arch for: {', '.join(missing)}")
        return 2
    if not pins:
        return 0
    cfg_path = Path(args.config)
    cfg = apply_pins(yaml.safe_load(cfg_path.read_text()), pins)
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    print("pinned " + " ".join(f"{n}={v}" for n, v in sorted(pins.items())))
    return 3


def cmd_state_revert(args) -> int:
    """Put one line's state entry back to its previous value (or drop a new line)."""
    current = load_state(args.state)
    previous = {(ln.image, ln.name): ln for ln in load_state(args.previous)}
    key = (args.image, args.line)
    out = []
    for ln in current:
        if (ln.image, ln.name) != key:
            out.append(ln)
        elif key in previous:
            out.append(previous[key])
    save_state(args.state, out)
    return 0


def cmd_vendor_layer(args) -> int:
    vendor = json.loads(Path(args.vendor).read_text())
    manifest = build_layer(vendor, args.arch, Path(args.cache), Path(args.out),
                           Path(args.launcher), Path(args.launch_dir), env=not args.no_env)
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


def cmd_append_layer(args) -> int:
    append_layer(Path(args.layout), args.arch, Path(args.layer), args.history)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dl")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="resolve lines and pins, render apko configs")
    sync.add_argument("--state", default="state/lines.json")
    sync.add_argument("--locks", default="locks")
    sync.add_argument("--catalog", default="catalog.yaml")
    sync.add_argument("--today", help="YYYY-MM-DD (default: today)")
    sync.add_argument("--index-dir", help="read APKINDEX.<arch> from here (dl fetch-index)")
    sync.add_argument("--warnings", help="also write warnings to this file")
    sync.set_defaults(func=cmd_sync)

    gate = sub.add_parser("gate", help="apply the scan gate to Trivy JSON reports")
    gate.add_argument("--candidate", required=True)
    gate.add_argument("--published")
    gate.add_argument("--ignore", default=".trivyignore")
    gate.add_argument("--label", default="")
    gate.add_argument("--index-dir")
    gate.add_argument("--vendor-prefix", action="append", default=[],
                      help="path of vendored upstream files; findings under it are listed, not gated")
    gate.add_argument("--vendor", help="vendor.json: its prefixes are vendored (as --vendor-prefix)")
    gate.set_defaults(func=cmd_gate)

    rescan = sub.add_parser("rescan-decide", help="decide issue/rebuild for a re-scan report")
    rescan.add_argument("--report", required=True)
    rescan.add_argument("--ignore", default=".trivyignore")
    rescan.add_argument("--previous", required=True, help="file of previously seen IDs")
    rescan.add_argument("--index-dir")
    rescan.set_defaults(func=cmd_rescan_decide)

    notify = sub.add_parser("notify", help="open or comment on an automation issue")
    notify.add_argument("--title", required=True)
    notify.add_argument("--body", required=True)
    notify.set_defaults(func=cmd_notify)

    matrix = sub.add_parser("matrix", help="GitHub Actions build matrix for changed files")
    matrix.add_argument("--locks", default="locks")
    matrix.add_argument("--changed", required=True, help="file listing changed paths")
    matrix.set_defaults(func=cmd_matrix)

    lockcheck = sub.add_parser("lock-check", help="fail on unreleased or single-arch locks")
    lockcheck.add_argument("--runtime", action="store_true",
                           help="also reject shells and package managers")
    lockcheck.add_argument("locks", nargs="+")
    lockcheck.set_defaults(func=cmd_lock_check)

    tag = sub.add_parser("tags", help="print the tags for one image/line/variant")
    tag.add_argument("--state", default="state/lines.json")
    tag.add_argument("--image", required=True)
    tag.add_argument("--line", required=True)
    tag.add_argument("--variant", required=True)
    tag.add_argument("--lock", required=True)
    tag.set_defaults(func=cmd_tags)

    pin = sub.add_parser("pin-released", help="pin unreleased lock entries to their newest release")
    pin.add_argument("--config", required=True)
    pin.add_argument("--lock", required=True)
    pin.add_argument("--index-dir")
    pin.set_defaults(func=cmd_pin_released)

    fetch = sub.add_parser("fetch-index", help="download APKINDEX for every arch once")
    fetch.add_argument("--out", required=True)
    fetch.set_defaults(func=cmd_fetch_index)

    revert = sub.add_parser("state-revert", help="restore one line's previous state entry")
    revert.add_argument("--state", default="state/lines.json")
    revert.add_argument("--previous", required=True)
    revert.add_argument("--image", required=True)
    revert.add_argument("--line", required=True)
    revert.set_defaults(func=cmd_state_revert)

    vlayer = sub.add_parser("vendor-layer", help="build the layer of vendored upstream files")
    vlayer.add_argument("--vendor", required=True, help="locks/<image>/<line>/vendor.json")
    vlayer.add_argument("--arch", required=True, choices=ARCHES)
    vlayer.add_argument("--launcher", required=True, help="launcher binary for this arch")
    vlayer.add_argument("--cache", required=True, help="download cache directory")
    vlayer.add_argument("--out", required=True, help="layer .tar.gz to write")
    vlayer.add_argument("--manifest", required=True, help="JSON list of what went in")
    vlayer.add_argument("--launch-dir", default=str(DEFAULT_LAUNCH_DIR),
                        help="directory holding <name>/launch.json (default: repo vendor/)")
    vlayer.add_argument("--no-env", action="store_true",
                        help="don't install the launcher as /usr/bin/env (variants with busybox)")
    vlayer.set_defaults(func=cmd_vendor_layer)

    alayer = sub.add_parser("append-layer", help="add a layer to one arch of an OCI layout")
    alayer.add_argument("--layout", required=True)
    alayer.add_argument("--arch", required=True, choices=ARCHES)
    alayer.add_argument("--layer", required=True)
    alayer.add_argument("--history", default="vendor layer")
    alayer.set_defaults(func=cmd_append_layer)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
