"""Compare vendored pins with the newest stable upstream releases: GitHub releases for
tools, PyPI for wheels."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import PurePosixPath

REPOS = {
    "darktable": "darktable-org/darktable",
    "rawtherapee": "RawTherapee/RawTherapee",
    "yt-dlp": "yt-dlp/yt-dlp",
}
UNSTABLE = re.compile(r"rc|beta|alpha|dev|nightly", re.IGNORECASE)


def _version(tag: str) -> tuple[int, ...] | None:
    """`release-5.6.3` -> (5, 6, 3); `2026.10.21` -> (2026, 10, 21); None if not numeric."""
    m = re.fullmatch(r"(?:release-)?v?(\d+(?:\.\d+)*)", tag)
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def _stable(release: dict) -> bool:
    return not (release.get("draft") or release.get("prerelease")
                or UNSTABLE.search(release["tag_name"]))


def newer_releases(vendor: dict, releases: dict[str, list[dict]]) -> list[str]:
    """One message per vendored tool whose newest stable release is newer than its pin."""
    messages = []
    for tool in vendor["vendor"]:
        pinned = _version(tool["version"])
        candidates = [(v, r["tag_name"]) for r in releases.get(tool["name"], [])
                      if _stable(r) and (v := _version(r["tag_name"])) is not None]
        if pinned is None or not candidates:
            continue
        newest, tag = max(candidates)
        if newest > pinned:
            version = tag.removeprefix("release-")
            messages.append(f"{tool['name']}: {version} is available (pinned {tool['version']})")
    return messages


def fetch_releases(vendor: dict, token: str | None = None, timeout: float = 30) -> dict[str, list[dict]]:
    out = {}
    for tool in vendor["vendor"]:
        repo = REPOS.get(tool["name"])
        if repo is None:
            continue
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases?per_page=30",
            headers={"Accept": "application/vnd.github+json",
                     **({"Authorization": f"Bearer {token}"} if token else {})},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out[tool["name"]] = json.loads(resp.read())
    return out


def token() -> str | None:
    return os.environ.get("GH_TOKEN")


def pypi_project(entry: dict) -> str:
    """The PyPI project of a wheel entry, from its wheel file name (PEP 503-normalised):
    `stashapp_tools-0.2.59-py3-none-any.whl` -> `stashapp-tools`."""
    files = entry["files"]
    url = (files.get("any") or next(iter(files.values())))["url"]
    dist = PurePosixPath(url).name.split("-", 1)[0]
    return re.sub(r"[-_.]+", "-", dist).lower()


def _final_release(version: str) -> tuple[int, ...] | None:
    """(1, 4, 3) for a final release like `1.4.3`; None for pre/dev/post/local versions."""
    return tuple(int(p) for p in version.split(".")) if re.fullmatch(r"\d+(\.\d+)*", version) else None


def newer_wheels(vendor: dict, projects: dict[str, dict]) -> list[str]:
    """One message per vendored wheel whose newest final, non-yanked PyPI release is newer
    than its pin. `projects` maps entry name -> PyPI JSON (https://pypi.org/pypi/<p>/json)."""
    messages = []
    for entry in vendor["vendor"]:
        if entry.get("kind") != "wheel" or entry["name"] not in projects:
            continue
        pinned = _final_release(entry["version"])
        releases = projects[entry["name"]].get("releases", {})
        candidates = [(v, ver) for ver, files in releases.items()
                      if files and not all(f.get("yanked") for f in files)
                      and (v := _final_release(ver)) is not None]
        if pinned is None or not candidates:
            continue
        newest, ver = max(candidates)
        if newest > pinned:
            messages.append(f"{entry['name']}: {ver} is available on PyPI "
                            f"(pinned {entry['version']})")
    return messages


def fetch_pypi(vendor: dict, timeout: float = 30) -> dict[str, dict]:
    """PyPI JSON for each wheel entry, keyed by entry name."""
    out = {}
    for entry in vendor["vendor"]:
        if entry.get("kind") != "wheel":
            continue
        url = f"https://pypi.org/pypi/{pypi_project(entry)}/json"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            out[entry["name"]] = json.loads(resp.read())
    return out
