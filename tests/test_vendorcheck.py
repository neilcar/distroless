import io
import json

import pytest

from dltools import vendorcheck
from dltools.vendorcheck import fetch_pypi, newer_releases, newer_wheels, pypi_project


def vendor(**pins):
    return {"vendor": [{"name": n, "version": v} for n, v in pins.items()]}


def rel(tag, **kw):
    return {"tag_name": tag, "draft": False, "prerelease": False, **kw}


def test_newer_stable_release_reported():
    msgs = newer_releases(
        vendor(darktable="5.6.2"),
        {"darktable": [rel("release-5.8.0rc1"), rel("release-5.6.3"), rel("release-5.6.2")]},
    )
    assert len(msgs) == 1 and "5.6.3" in msgs[0] and "darktable" in msgs[0]
    assert "5.8.0" not in msgs[0]


def test_prerelease_and_draft_ignored():
    releases = {"rawtherapee": [
        rel("5.14", prerelease=True), rel("5.15", draft=True), rel("5.16-beta1"),
        rel("5.17-nightly"), rel("5.13"),
    ]}
    assert newer_releases(vendor(rawtherapee="5.13"), releases) == []


def test_same_version_no_message():
    assert newer_releases(vendor(darktable="5.6.2"), {"darktable": [rel("release-5.6.2")]}) == []


def test_yt_dlp_date_versions_compare():
    v = vendor(**{"yt-dlp": "2026.10.21"})
    assert newer_releases(v, {"yt-dlp": [rel("2026.10.21")]}) == []
    msgs = newer_releases(v, {"yt-dlp": [rel("2026.10.21"), rel("2026.11.02")]})
    assert len(msgs) == 1 and "2026.11.02" in msgs[0]


def test_older_release_not_reported_and_missing_releases_skipped():
    assert newer_releases(vendor(darktable="5.6.2", rawtherapee="5.13"),
                          {"darktable": [rel("release-5.4.0")]}) == []


def wheel(name, version, filename):
    return {"name": name, "version": version, "kind": "wheel",
            "prefix": "/usr/lib/python3.12/site-packages",
            "files": {"any": {"url": f"https://files.pythonhosted.org/packages/ab/{filename}",
                              "sha256": "0" * 64}}}


def pypi(*versions, yanked=()):
    return {"releases": {v: [{"filename": f"x-{v}.whl", "yanked": v in yanked}] for v in versions}}


STASHAPI = wheel("stashapi", "0.2.59", "stashapp_tools-0.2.59-py3-none-any.whl")


def test_pypi_project_comes_from_the_wheel_name():
    assert pypi_project(STASHAPI) == "stashapp-tools"
    assert pypi_project(wheel("c", "1", "cloudscraper-1.2.71-py2.py3-none-any.whl")) == "cloudscraper"
    assert pypi_project(wheel("m", "1", "MechanicalSoup-1.4.0-py3-none-any.whl")) == "mechanicalsoup"


def test_newer_wheel_reported():
    msgs = newer_wheels({"vendor": [STASHAPI]}, {"stashapi": pypi("0.2.58", "0.2.59", "0.2.60")})
    assert msgs == ["stashapi: 0.2.60 is available on PyPI (pinned 0.2.59)"]


def test_wheel_prereleases_yanked_and_older_ignored():
    data = pypi("0.2.59", "0.3.0rc1", "0.3.0.dev2", "0.2.61", "0.2.60.post1", "0.2.58",
                yanked=("0.2.61",))
    data["releases"]["0.2.62"] = []  # no files: never really released
    assert newer_wheels({"vendor": [STASHAPI]}, {"stashapi": data}) == []


def test_wheel_versions_compare_numerically():
    msgs = newer_wheels({"vendor": [wheel("apscheduler", "3.9.1", "apscheduler-3.9.1-py3-none-any.whl")]},
                        {"apscheduler": pypi("3.9.1", "3.10.0")})
    assert msgs and "3.10.0" in msgs[0]


def test_non_wheel_entries_ignored_by_pypi_check():
    assert newer_wheels(vendor(darktable="5.6.2"), {"darktable": pypi("9.9")}) == []


def test_fetch_pypi_queries_each_wheel_project(monkeypatch):
    seen = []

    def fake_urlopen(url, timeout=None):
        seen.append(url)
        return io.BytesIO(json.dumps(pypi("0.2.60")).encode())

    monkeypatch.setattr(vendorcheck.urllib.request, "urlopen", fake_urlopen)
    tools = {"vendor": [STASHAPI, {"name": "darktable", "version": "5.6.2", "kind": "appimage"}]}
    out = fetch_pypi(tools)
    assert seen == ["https://pypi.org/pypi/stashapp-tools/json"]
    assert newer_wheels(tools, out) == ["stashapi: 0.2.60 is available on PyPI (pinned 0.2.59)"]


def test_fetch_pypi_network_error_propagates(monkeypatch):
    import urllib.error

    def boom(url, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(vendorcheck.urllib.request, "urlopen", boom)
    with pytest.raises(OSError):
        fetch_pypi({"vendor": [STASHAPI]})
