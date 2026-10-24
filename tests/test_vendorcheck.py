from dltools.vendorcheck import newer_releases


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
