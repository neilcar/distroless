import json
from datetime import date
from pathlib import Path

import pytest

from dltools.lines import Line, discover, nginx_lines, python_lines, static_lines
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
