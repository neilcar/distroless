"""Which lines each image is built for, and the pinned headline version of each."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import yaml

from dltools.wolfi import newest_released_all_arches, upstream_version, version_key

EOL_URL = "https://endoflife.date/api/python.json"
NGINX_LINES = {"stable": "nginx-stable", "mainline": "nginx-mainline"}
# photoprism-base is versioned by the local libvips build (Wolfi's has no lcms2).
PHOTOPRISM_BASE_PACKAGE = "distroless-libvips"
LIBVIPS_MELANGE = "melange/distroless-libvips.yaml"  # relative to the repository root
WOLFI_LIBVIPS = "libvips"
# stash-base is versioned by its Python (plugins and scrapers run on it).
STASH_BASE_PACKAGE = "python-3.12"
# tesseract is versioned by Wolfi's tesseract (the OCR engine is what callers depend on).
TESSERACT_PACKAGE = "tesseract"
# sabnzbd-base is versioned by its Python (SABnzbd is a Python program).
SABNZBD_BASE_PACKAGE = "python-3.14"
# servarr-base is versioned by the ICU its .NET apps load (Lidarr, Radarr, Prowlarr, Sonarr, Whisparr).
SERVARR_BASE_PACKAGE = "libicu79"
# beets-base is versioned by its Python (beets and its plugins are Python).
BEETS_BASE_PACKAGE = "python-3.12"
# debug (the break-glass toolbox for kubectl debug) is versioned by its shell.
DEBUG_PACKAGE = "bash"
# python-ssh (stdlib scripts that shell out to ssh) is versioned by its Python.
PYTHON_SSH_PACKAGE = "python-3.12"
# ci-tools (busybox and curl for CI smoke tests) is versioned by curl.
CI_TOOLS_PACKAGE = "curl"
# valkey (Redis-compatible; Wolfi has no Redis) is versioned by its server.
VALKEY_PACKAGE = "valkey-9.0"
# rust follows Wolfi's newest rust-1.NN with a released version on both arches.
RUST_PACKAGE = re.compile(r"rust-1\.(\d+)")
# cc (glibc and libgcc, for dynamically linked Rust/C binaries) is versioned by libgcc: Wolfi's
# current glibc is a versioned package (glibc-2.44) that libgcc's libc.so.6 dependency resolves.
CC_PACKAGE = "libgcc"
# flaresolverr-base is versioned by its Chromium (what Cloudflare's checks see).
FLARESOLVERR_BASE_PACKAGE = "chromium"
# jdownloader-base is versioned by its Java runtime (JDownloader is a Java program).
JDOWNLOADER_BASE_PACKAGE = "openjdk-21-jre"


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


def nginx_lines(indexes, names=None) -> list[Line]:
    wanted = NGINX_LINES if names is None else {n: NGINX_LINES[n] for n in names}
    return [
        Line("nginx", name, pkg, v)
        for name, pkg in wanted.items()
        if (v := newest_released_all_arches(indexes, pkg))
    ]


def static_lines(indexes) -> list[Line]:
    v = newest_released_all_arches(indexes, "ca-certificates-bundle")
    return [Line("static", "latest", "ca-certificates-bundle", v)] if v else []


def photoprism_base_lines(libvips_version: str | None) -> list[Line]:
    """The single `latest` line, versioned by distroless-libvips (ships libvips.so.42).

    That package is built locally (melange/), so its version comes from its melange
    config, not from the Wolfi index."""
    v = libvips_version
    return [Line("photoprism-base", "latest", PHOTOPRISM_BASE_PACKAGE, v)] if v else []


def stash_base_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by Python 3.12's newest released version."""
    v = newest_released_all_arches(indexes, STASH_BASE_PACKAGE)
    return [Line("stash-base", "latest", STASH_BASE_PACKAGE, v)] if v else []


def tesseract_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by tesseract's newest released version."""
    v = newest_released_all_arches(indexes, TESSERACT_PACKAGE)
    return [Line("tesseract", "latest", TESSERACT_PACKAGE, v)] if v else []


def sabnzbd_base_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by Python 3.14's newest released version."""
    v = newest_released_all_arches(indexes, SABNZBD_BASE_PACKAGE)
    return [Line("sabnzbd-base", "latest", SABNZBD_BASE_PACKAGE, v)] if v else []


def servarr_base_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by ICU 79's newest released version."""
    v = newest_released_all_arches(indexes, SERVARR_BASE_PACKAGE)
    return [Line("servarr-base", "latest", SERVARR_BASE_PACKAGE, v)] if v else []


def beets_base_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by Python 3.12's newest released version."""
    v = newest_released_all_arches(indexes, BEETS_BASE_PACKAGE)
    return [Line("beets-base", "latest", BEETS_BASE_PACKAGE, v)] if v else []


def debug_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by bash's newest released version."""
    v = newest_released_all_arches(indexes, DEBUG_PACKAGE)
    return [Line("debug", "latest", DEBUG_PACKAGE, v)] if v else []


def python_ssh_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by Python 3.12's newest released version."""
    v = newest_released_all_arches(indexes, PYTHON_SSH_PACKAGE)
    return [Line("python-ssh", "latest", PYTHON_SSH_PACKAGE, v)] if v else []


def ci_tools_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by curl's newest released version."""
    v = newest_released_all_arches(indexes, CI_TOOLS_PACKAGE)
    return [Line("ci-tools", "latest", CI_TOOLS_PACKAGE, v)] if v else []


def valkey_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by Valkey 9.0's newest released version."""
    v = newest_released_all_arches(indexes, VALKEY_PACKAGE)
    return [Line("valkey", "latest", VALKEY_PACKAGE, v)] if v else []


def rust_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by the newest rust-1.NN released on every arch."""
    minors = {
        int(m.group(1)): name
        for index in indexes.values()
        for name in index
        if (m := RUST_PACKAGE.fullmatch(name))
    }
    for minor in sorted(minors, reverse=True):
        if v := newest_released_all_arches(indexes, minors[minor]):
            return [Line("rust", "latest", minors[minor], v)]
    return []


def cc_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by libgcc's newest released version."""
    v = newest_released_all_arches(indexes, CC_PACKAGE)
    return [Line("cc", "latest", CC_PACKAGE, v)] if v else []


def flaresolverr_base_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by Chromium's newest released version."""
    v = newest_released_all_arches(indexes, FLARESOLVERR_BASE_PACKAGE)
    return [Line("flaresolverr-base", "latest", FLARESOLVERR_BASE_PACKAGE, v)] if v else []


def jdownloader_base_lines(indexes) -> list[Line]:
    """The single `latest` line, headed by OpenJDK 21's JRE at its newest released version."""
    v = newest_released_all_arches(indexes, JDOWNLOADER_BASE_PACKAGE)
    return [Line("jdownloader-base", "latest", JDOWNLOADER_BASE_PACKAGE, v)] if v else []


def melange_version(path) -> str | None:
    """`<version>-r<epoch>` of a melange config, or None if the file is missing."""
    p = Path(path)
    if not p.exists():
        return None
    pkg = yaml.safe_load(p.read_text())["package"]
    return f"{pkg['version']}-r{pkg.get('epoch', 0)}"


def libvips_behind(indexes, local_version: str) -> str | None:
    """Wolfi's newest released libvips upstream version (on every arch) when it is newer
    than distroless-libvips's; None otherwise. Epochs (-rN) are ignored: only the
    upstream version has to follow Wolfi."""
    wolfi = newest_released_all_arches(indexes, WOLFI_LIBVIPS)
    if wolfi is None:
        return None
    wolfi_upstream = upstream_version(wolfi)
    if version_key(wolfi_upstream) > version_key(upstream_version(local_version)):
        return wolfi_upstream
    return None


def fetch_eol(url: str = EOL_URL, timeout: int = 30) -> list[dict] | None:
    """Python release cycles from endoflife.date, or None on any failure."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
    except (OSError, ValueError):  # URLError/HTTPError are OSErrors; bad JSON is ValueError
        return None
    if not isinstance(data, list) or not data or not all("cycle" in c for c in data):
        return None
    return data


def _eol_passed(cycle: dict | None, today: date) -> bool:
    """True only when the data positively says the cycle is end-of-life."""
    if cycle is None:
        return False
    eol = cycle.get("eol")
    if eol is True:
        return True
    if isinstance(eol, str):
        try:
            return date.fromisoformat(eol) <= today
        except ValueError:
            return False
    return False


def _order(line: Line) -> tuple:
    rank = {"static": 0, "python": 1, "nginx": 2, "photoprism-base": 3, "stash-base": 4, "tesseract": 5,
            "sabnzbd-base": 6, "servarr-base": 7, "beets-base": 8, "debug": 9, "python-ssh": 10, "ci-tools": 11, "valkey": 12,
            "rust": 13, "cc": 14, "flaresolverr-base": 15, "jdownloader-base": 16}.get(line.image, 17)
    sub = version_key(line.name) if line.image == "python" else list(NGINX_LINES).index(
        line.name
    ) if line.name in NGINX_LINES else 0
    return (rank, sub)


def discover(
    indexes, eol: list[dict] | None, today: date, current: list[Line], nginx_names=None,
    photoprism_libvips: str | None = None,
):
    """Return (lines, warnings). `photoprism_libvips` is distroless-libvips's version.

    A current line is only retired when the data positively says so (a Python cycle
    listed with a past EOL date). Missing EOL data, a cycle absent from it, or a
    package missing from an arch's index keeps the line with a warning.
    """
    warnings: list[str] = []
    if eol is None:
        warnings.append(
            "endoflife.date data unavailable; keeping the current Python lines unchanged"
        )
        py: list[Line] = []
    else:
        py = python_lines(eol, indexes, today)
    lines = (
        static_lines(indexes) + py + nginx_lines(indexes, nginx_names)
        + photoprism_base_lines(photoprism_libvips) + stash_base_lines(indexes)
        + tesseract_lines(indexes) + sabnzbd_base_lines(indexes) + servarr_base_lines(indexes)
        + beets_base_lines(indexes) + debug_lines(indexes) + python_ssh_lines(indexes)
        + ci_tools_lines(indexes) + valkey_lines(indexes) + rust_lines(indexes) + cc_lines(indexes)
        + flaresolverr_base_lines(indexes) + jdownloader_base_lines(indexes)
    )
    present = {(ln.image, ln.name) for ln in lines}
    cycles = {c.get("cycle"): c for c in eol or []}

    for ln in current:
        if (ln.image, ln.name) in present:
            continue
        if ln.image == "python" and eol is not None and _eol_passed(cycles.get(ln.name), today):
            continue  # genuinely end-of-life: retire
        if ln.image == "nginx" and nginx_names is not None and ln.name not in nginx_names:
            continue  # removed from the catalog on purpose: retire
        version = newest_released_all_arches(indexes, ln.package)
        if version is None:
            warnings.append(
                f"{ln.package} has no released version on every arch in the Wolfi index; "
                f"keeping {ln.image}:{ln.name} at {ln.version}"
            )
            version = ln.version
        elif ln.image == "python" and eol is not None:
            warnings.append(
                f"python {ln.name} is not confirmed supported by endoflife.date data; keeping it"
            )
        lines.append(Line(ln.image, ln.name, ln.package, version))
    return sorted(lines, key=_order), warnings
