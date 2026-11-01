import json
import re
from datetime import date
from pathlib import Path

import pytest

from dltools.lines import (
    LIBVIPS_MELANGE,
    Line,
    beets_base_lines,
    ci_tools_lines,
    debug_lines,
    discover,
    libvips_behind,
    melange_version,
    nginx_lines,
    photoprism_base_lines,
    python_lines,
    python_ssh_lines,
    sabnzbd_base_lines,
    servarr_base_lines,
    stash_base_lines,
    static_lines,
    tesseract_lines,
)
from dltools.wolfi import parse_apkindex

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 24)


@pytest.fixture(scope="module")
def indexes():
    return {
        arch: parse_apkindex((FIXTURES / f"APKINDEX.{arch}").read_text())
        for arch in ("x86_64", "aarch64")
    }


@pytest.fixture(scope="module")
def eol():
    return json.loads((FIXTURES / "python-eol.json").read_text())


def test_python_lines_expected_today(indexes, eol):
    lines = python_lines(eol, indexes, TODAY)
    assert [ln.name for ln in lines] == ["3.11", "3.12", "3.13", "3.14", "3.15"]
    by = {ln.name: ln for ln in lines}
    assert by["3.13"] == Line("python", "3.13", "python-3.13", "3.13.15-r8")
    assert by["3.15"].version == "3.15.0-r0"


def test_python_line_eol_excluded(indexes, eol):
    names = [ln.name for ln in python_lines(eol, indexes, date(2027, 11, 1))]
    assert "3.11" not in names  # 3.11 eol 2027-10-31


def test_python_unreleased_cycle_excluded(indexes, eol):
    names = [ln.name for ln in python_lines(eol, indexes, date(2026, 10, 8))]
    assert "3.15" not in names  # released 2026-10-09


def test_python_eol_false_means_supported():
    indexes = {a: {"python-3.20": ["3.20.0-r0"]} for a in ("x86_64", "aarch64")}
    eol = [{"cycle": "3.20", "releaseDate": "2030-10-01", "eol": False}]
    assert [ln.name for ln in python_lines(eol, indexes, date(2031, 1, 1))] == ["3.20"]


def test_line_needs_both_arches():
    indexes = {"x86_64": {"python-3.12": ["3.12.15-r6"]}, "aarch64": {}}
    eol = [{"cycle": "3.12", "releaseDate": "2023-10-02", "eol": "2028-10-31"}]
    assert python_lines(eol, indexes, TODAY) == []


def test_nginx_lines(indexes):
    assert nginx_lines(indexes) == [
        Line("nginx", "stable", "nginx-stable", "1.30.2-r0"),
        Line("nginx", "mainline", "nginx-mainline", "1.31.8-r1"),
    ]


def test_static_lines(indexes):
    (line,) = static_lines(indexes)
    assert (line.image, line.name, line.package) == ("static", "latest", "ca-certificates-bundle")


def test_discover_all_images(indexes, eol):
    lines, warnings = discover(indexes, eol, TODAY, current=[])
    assert warnings == []
    assert {(ln.image, ln.name) for ln in lines} >= {
        ("static", "latest"),
        ("python", "3.12"),
        ("nginx", "stable"),
        ("nginx", "mainline"),
    }


def test_eol_fetch_failure_keeps_current_lines(indexes, eol):
    current, _ = discover(indexes, eol, TODAY, current=[])
    lines, warnings = discover(indexes, None, TODAY, current=current)
    assert [ln.name for ln in lines if ln.image == "python"] == [
        "3.11", "3.12", "3.13", "3.14", "3.15",
    ]
    assert len(warnings) == 1 and "endoflife.date" in warnings[0]


def test_eol_failure_still_refreshes_versions(indexes):
    stale = [Line("python", "3.12", "python-3.12", "3.12.14-r0")]
    lines, _ = discover(indexes, None, TODAY, current=stale)
    assert [ln.version for ln in lines if ln.image == "python"] == ["3.12.15-r6"]


def test_changed_eol_schema_does_not_retire_lines(indexes):
    current, _ = discover(indexes, json.loads((FIXTURES / "python-eol.json").read_text()),
                          TODAY, current=[])
    junk = [{"cycle": c, "released": "x", "end": "y"} for c in ("3.11", "3.12")]  # renamed keys
    lines, warnings = discover(indexes, junk, TODAY, current=current)
    assert [ln.name for ln in lines if ln.image == "python"] == [
        "3.11", "3.12", "3.13", "3.14", "3.15"]
    assert warnings


def test_line_retired_only_when_eol_says_so(indexes, eol):
    current, _ = discover(indexes, eol, TODAY, current=[])
    lines, _ = discover(indexes, eol, date(2027, 11, 1), current=current)
    names = [ln.name for ln in lines if ln.image == "python"]
    assert "3.11" not in names and "3.12" in names  # 3.11 eol 2027-10-31


def test_cycle_missing_from_eol_data_is_kept(indexes, eol):
    current, _ = discover(indexes, eol, TODAY, current=[])
    truncated = [c for c in eol if c["cycle"] != "3.13"]
    lines, warnings = discover(indexes, truncated, TODAY, current=current)
    assert "3.13" in [ln.name for ln in lines if ln.image == "python"]
    assert any("3.13" in w for w in warnings)


def test_package_missing_from_index_keeps_current_line(indexes, eol):
    current, _ = discover(indexes, eol, TODAY, current=[])
    broken = {"x86_64": indexes["x86_64"],
              "aarch64": {k: v for k, v in indexes["aarch64"].items() if k != "nginx-stable"}}
    lines, warnings = discover(broken, eol, TODAY, current=current)
    stable = [ln for ln in lines if ln.image == "nginx" and ln.name == "stable"]
    assert stable and stable[0].version == "1.30.2-r0"
    assert any("nginx-stable" in w for w in warnings)


def test_nginx_lines_respects_configured_names(indexes):
    assert [ln.name for ln in nginx_lines(indexes, ["mainline"])] == ["mainline"]


def test_unconfigured_nginx_line_is_retired(indexes, eol):
    current, _ = discover(indexes, eol, TODAY, current=[])
    lines, _ = discover(indexes, eol, TODAY, current=current, nginx_names=["mainline"])
    assert [ln.name for ln in lines if ln.image == "nginx"] == ["mainline"]


ROOT = Path(__file__).parent.parent


def test_photoprism_base_line_is_the_local_libvips():
    assert photoprism_base_lines("8.18.7-r0") == [
        Line("photoprism-base", "latest", "distroless-libvips", "8.18.7-r0")
    ]
    assert photoprism_base_lines(None) == []


def test_discover_versions_photoprism_base_by_local_libvips(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[], photoprism_libvips="8.18.7-r0")
    pb = [ln for ln in lines if ln.image == "photoprism-base"]
    assert pb == [Line("photoprism-base", "latest", "distroless-libvips", "8.18.7-r0")]


def test_melange_version(tmp_path):
    cfg = tmp_path / "pkg.yaml"
    cfg.write_text('package:\n  name: x\n  version: "8.18.7"\n  epoch: 2\n')
    assert melange_version(cfg) == "8.18.7-r2"
    assert melange_version(tmp_path / "missing.yaml") is None


def test_repo_libvips_package_version_format():
    # Format only: the version is bumped by hand to follow Wolfi.
    assert re.fullmatch(r"\d+\.\d+\.\d+-r\d+", melange_version(ROOT / LIBVIPS_MELANGE))


def test_libvips_behind_compares_upstream_versions_only(indexes):
    # Fixture Wolfi: libvips 8.18.7-r0 released (8.18.8_rc1 is not a release).
    assert libvips_behind(indexes, "8.18.7-r0") is None
    assert libvips_behind(indexes, "8.18.7-r5") is None  # Wolfi epoch bumps don't count
    assert libvips_behind(indexes, "8.18.6-r0") == "8.18.7"
    assert libvips_behind(indexes, "8.18.8-r0") is None  # ahead of Wolfi: not behind
    assert libvips_behind(indexes, "8.18.10-r0") is None  # compared as versions, not strings
    newer = {a: {**idx, "libvips": idx["libvips"] + ["8.19.0-r1"]} for a, idx in indexes.items()}
    assert libvips_behind(newer, "8.18.7-r0") == "8.19.0"


def test_libvips_behind_needs_every_arch(indexes):
    one = {"x86_64": {**indexes["x86_64"], "libvips": ["8.19.0-r0"]}, "aarch64": indexes["aarch64"]}
    assert libvips_behind(one, "8.18.7-r0") is None
    assert libvips_behind({"x86_64": {}, "aarch64": {}}, "8.18.7-r0") is None


def test_stash_base_line(indexes):
    # One `latest` line headed by Python 3.12 at its newest version on both arches.
    assert stash_base_lines(indexes) == [Line("stash-base", "latest", "python-3.12", "3.12.15-r6")]
    assert stash_base_lines({"x86_64": {}, "aarch64": {}}) == []
    snap = {a: {"python-3.12": ["3.12.15-r6", "3.12.16_rc1-r0"]} for a in ("x86_64", "aarch64")}
    assert stash_base_lines(snap)[0].version == "3.12.15-r6"  # pre-releases are skipped


def test_discover_includes_stash_base(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[])
    assert [ln for ln in lines if ln.image == "stash-base"] == [
        Line("stash-base", "latest", "python-3.12", "3.12.15-r6")]


def test_tesseract_line(indexes):
    # One `latest` line headed by tesseract's newest released version on both arches.
    assert tesseract_lines(indexes) == [Line("tesseract", "latest", "tesseract", "5.5.2-r8")]
    assert tesseract_lines({"x86_64": {}, "aarch64": {}}) == []


def test_discover_includes_tesseract_before_sabnzbd_base(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[])
    assert lines[-7] == Line("tesseract", "latest", "tesseract", "5.5.2-r8")


def test_sabnzbd_base_line(indexes):
    # One `latest` line headed by Python 3.14's newest released version on both arches.
    assert sabnzbd_base_lines(indexes) == [Line("sabnzbd-base", "latest", "python-3.14", "3.14.7-r8")]
    assert sabnzbd_base_lines({"x86_64": {}, "aarch64": {}}) == []


def test_discover_includes_sabnzbd_base_before_servarr_base(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[])
    assert lines[-6] == Line("sabnzbd-base", "latest", "python-3.14", "3.14.7-r8")


def test_servarr_base_line(indexes):
    # One `latest` line headed by ICU 79's newest released version on both arches (the .NET apps load libicu).
    assert servarr_base_lines(indexes) == [Line("servarr-base", "latest", "libicu79", "79.1-r1")]
    assert servarr_base_lines({"x86_64": {}, "aarch64": {}}) == []


def test_discover_includes_servarr_base_before_beets_base(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[])
    assert lines[-5] == Line("servarr-base", "latest", "libicu79", "79.1-r1")


def test_beets_base_line(indexes):
    # One `latest` line headed by Python 3.12 at its newest version on both arches (beets runs on 3.12).
    assert beets_base_lines(indexes) == [Line("beets-base", "latest", "python-3.12", "3.12.15-r6")]
    assert beets_base_lines({"x86_64": {}, "aarch64": {}}) == []


def test_discover_includes_beets_base_before_debug(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[])
    assert lines[-4] == Line("beets-base", "latest", "python-3.12", "3.12.15-r6")


def test_debug_line(indexes):
    # One `latest` line headed by bash's newest released version on both arches (the debug toolbox's shell).
    assert debug_lines(indexes) == [Line("debug", "latest", "bash", "5.3-r14")]
    assert debug_lines({"x86_64": {}, "aarch64": {}}) == []


def test_discover_includes_debug_before_python_ssh(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[])
    assert lines[-3] == Line("debug", "latest", "bash", "5.3-r14")


def test_python_ssh_line(indexes):
    # One `latest` line headed by Python 3.12's newest released version on both arches.
    assert python_ssh_lines(indexes) == [Line("python-ssh", "latest", "python-3.12", "3.12.15-r6")]
    assert python_ssh_lines({"x86_64": {}, "aarch64": {}}) == []


def test_discover_includes_python_ssh_before_ci_tools(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[])
    assert lines[-2] == Line("python-ssh", "latest", "python-3.12", "3.12.15-r6")


def test_ci_tools_line(indexes):
    # One `latest` line headed by curl's newest released version on both arches.
    assert ci_tools_lines(indexes) == [Line("ci-tools", "latest", "curl", "8.17.0-r1")]
    assert ci_tools_lines({"x86_64": {}, "aarch64": {}}) == []


def test_discover_includes_ci_tools_last(indexes, eol):
    lines, _ = discover(indexes, eol, TODAY, current=[])
    assert lines[-1] == Line("ci-tools", "latest", "curl", "8.17.0-r1")
