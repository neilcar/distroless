"""Persisted line state and the events produced by comparing two states."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dltools.lines import Line
from dltools.wolfi import upstream_version

EventKind = Literal["line_added", "line_removed", "version_changed", "nginx_minor_changed"]


@dataclass(frozen=True)
class Event:
    kind: EventKind
    line: Line
    detail: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "line": self.line.to_dict(), "detail": self.detail}


def load_state(path) -> list[Line]:
    p = Path(path)
    if not p.exists():
        return []
    return [Line(**d) for d in json.loads(p.read_text())["lines"]]


def save_state(path, lines: list[Line]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"lines": [ln.to_dict() for ln in lines]}, indent=2) + "\n")


def _minor(version: str) -> str:
    return ".".join(upstream_version(version).split(".")[:2])


def diff(old: list[Line], new: list[Line]) -> list[Event]:
    key = lambda ln: (ln.image, ln.name)
    before = {key(ln): ln for ln in old}
    after = {key(ln): ln for ln in new}
    events: list[Event] = []
    for k, ln in after.items():
        prev = before.get(k)
        if prev is None:
            events.append(Event("line_added", ln, f"{ln.image}:{ln.name} {ln.version}"))
        elif prev.version != ln.version:
            events.append(
                Event("version_changed", ln, f"{ln.image}:{ln.name} {prev.version} -> {ln.version}")
            )
            if ln.image == "nginx" and _minor(prev.version) != _minor(ln.version):
                events.append(
                    Event(
                        "nginx_minor_changed",
                        ln,
                        f"nginx {ln.name} moved from {_minor(prev.version)} to "
                        f"{_minor(ln.version)}; images tagged {_minor(prev.version)} stop updating",
                    )
                )
    for k, ln in before.items():
        if k not in after:
            events.append(Event("line_removed", ln, f"{ln.image}:{ln.name} no longer supported"))
    return events
