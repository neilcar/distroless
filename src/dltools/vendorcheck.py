"""Compare vendored tool pins with the newest stable upstream GitHub releases."""

from __future__ import annotations

import json
import os
import re
import urllib.request

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
