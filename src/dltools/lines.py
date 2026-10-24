"""Which lines each image is built for, and the pinned headline version of each."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date

from dltools.wolfi import newest_released_all_arches, version_key

EOL_URL = "https://endoflife.date/api/python.json"
NGINX_LINES = {"stable": "nginx-stable", "mainline": "nginx-mainline"}


@dataclass(frozen=True)
class Line:
    image: str
    name: str
    package: str
    version: str

    def to_dict(self) -> dict:
        return asdict(self)


def _supported(cycle: dict, today: date) -> bool:
    try:
        released = date.fromisoformat(cycle["releaseDate"])
    except (KeyError, TypeError, ValueError):
        return False
    eol = cycle.get("eol")
    if eol is True:
        return False
    if eol in (False, None):
        return released <= today
    return released <= today < date.fromisoformat(eol)


def python_lines(eol: list[dict], indexes, today: date) -> list[Line]:
    lines = []
    for cycle in eol:
        if not _supported(cycle, today):
            continue
        name = cycle["cycle"]
        version = newest_released_all_arches(indexes, f"python-{name}")
        if version:
            lines.append(Line("python", name, f"python-{name}", version))
    return sorted(lines, key=lambda ln: version_key(ln.name))


def nginx_lines(indexes) -> list[Line]:
    return [
        Line("nginx", name, pkg, v)
        for name, pkg in NGINX_LINES.items()
        if (v := newest_released_all_arches(indexes, pkg))
    ]


def static_lines(indexes) -> list[Line]:
    v = newest_released_all_arches(indexes, "ca-certificates-bundle")
    return [Line("static", "latest", "ca-certificates-bundle", v)] if v else []


def fetch_eol(url: str = EOL_URL, timeout: int = 30) -> list[dict] | None:
    """Python release cycles from endoflife.date, or None on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except Exception:  # network, HTTP, or JSON errors all mean "no data"
        return None
    if not isinstance(data, list) or not data or not all("cycle" in c for c in data):
        return None
    return data


def discover(indexes, eol: list[dict] | None, today: date, current: list[Line]):
    """Return (lines, warnings). With no EOL data, keep the current Python lines."""
    warnings: list[str] = []
    if eol is None:
        warnings.append(
            "endoflife.date data unavailable; keeping the current Python lines unchanged"
        )
        py = []
        for ln in current:
            if ln.image != "python":
                continue
            v = newest_released_all_arches(indexes, ln.package) or ln.version
            py.append(Line(ln.image, ln.name, ln.package, v))
    else:
        py = python_lines(eol, indexes, today)
    return static_lines(indexes) + py + nginx_lines(indexes), warnings
