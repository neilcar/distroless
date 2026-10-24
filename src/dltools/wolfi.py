"""Wolfi APKINDEX parsing and release-only version selection."""

from __future__ import annotations

import io
import re
import tarfile
import urllib.request

WOLFI_REPO = "https://packages.wolfi.dev/os"
ARCHES = ("x86_64", "aarch64")

# apk suffix ordering: pre-release suffixes sort below a plain release,
# VCS snapshots and patch levels sort above it.
_SUFFIX_RANK = {
    "alpha": 0,
    "beta": 1,
    "pre": 2,
    "rc": 3,
    "": 4,  # plain release
    "cvs": 5,
    "svn": 6,
    "git": 7,
    "hg": 8,
    "p": 9,
}
# Everything except a plain release and a post-release patch level (`_p`).
_UNRELEASED = {"alpha", "beta", "pre", "rc", "cvs", "svn", "git", "hg"}

_VERSION_RE = re.compile(
    r"^(?P<nums>\d+(?:\.\d+)*)(?P<letter>[a-z]?)(?P<suffixes>(?:_[a-z]+\d*)*)(?:-r(?P<rev>\d+))?$"
)
_SUFFIX_RE = re.compile(r"_([a-z]+)(\d*)")


def parse_apkindex(text: str) -> dict[str, list[str]]:
    """Map package name to every version listed in an APKINDEX."""
    index: dict[str, list[str]] = {}
    name = None
    for line in text.splitlines():
        if line.startswith("P:"):
            name = line[2:]
        elif line.startswith("V:") and name is not None:
            index.setdefault(name, []).append(line[2:])
        elif not line.strip():
            name = None
    return index


def _parse(version: str):
    m = _VERSION_RE.match(version)
    if not m:
        raise ValueError(f"unparseable apk version: {version!r}")
    return m


def version_key(version: str) -> tuple:
    """Sort key following apk version ordering."""
    m = _parse(version)
    nums = tuple(int(n) for n in m["nums"].split("."))
    suffixes = tuple(
        (_SUFFIX_RANK[name], int(num or 0)) for name, num in _SUFFIX_RE.findall(m["suffixes"])
    ) or ((_SUFFIX_RANK[""], 0),)
    return (nums, m["letter"], suffixes, int(m["rev"] or 0))


def is_released(version: str) -> bool:
    """True unless the version carries a pre-release or VCS-snapshot suffix."""
    m = _parse(version)
    return not any(name in _UNRELEASED for name, _ in _SUFFIX_RE.findall(m["suffixes"]))


def newest_released(index: dict[str, list[str]], package: str) -> str | None:
    released = [v for v in index.get(package, []) if is_released(v)]
    return max(released, key=version_key, default=None)


def newest_released_all_arches(
    indexes: dict[str, dict[str, list[str]]], package: str
) -> str | None:
    """Newest released version of `package` present in every arch index."""
    common: set[str] | None = None
    for index in indexes.values():
        versions = {v for v in index.get(package, []) if is_released(v)}
        common = versions if common is None else common & versions
    return max(common or (), key=version_key, default=None)


def upstream_version(version: str) -> str:
    return re.sub(r"-r\d+$", "", version)


def fetch_index(arch: str, repo: str = WOLFI_REPO, timeout: int = 60) -> str:
    """Download and return the APKINDEX text for `arch`."""
    with urllib.request.urlopen(f"{repo}/{arch}/APKINDEX.tar.gz", timeout=timeout) as resp:
        data = resp.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        member = tar.extractfile("APKINDEX")
        if member is None:
            raise RuntimeError(f"APKINDEX missing in {arch} index")
        return member.read().decode()
