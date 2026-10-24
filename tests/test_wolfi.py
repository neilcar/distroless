from pathlib import Path

import pytest

from dltools.wolfi import (
    is_released,
    newest_released,
    newest_released_all_arches,
    parse_apkindex,
    upstream_version,
    version_key,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def indexes():
    return {
        arch: parse_apkindex((FIXTURES / f"APKINDEX.{arch}").read_text())
        for arch in ("x86_64", "aarch64")
    }


@pytest.mark.parametrize("version", ["3.12.15-r6", "1.30.2-r0", "2026e-r0", "20260909-r3"])
def test_is_released_true(version):
    assert is_released(version)


@pytest.mark.parametrize(
    "version",
    [
        "3.13.16_git20261016-r2",
        "3.15.0_rc1-r0",
        "1.0_alpha2-r0",
        "2.0_beta1-r0",
        "2.0_pre1-r0",
    ],
)
def test_is_released_false(version):
    assert not is_released(version)


def test_parse_apkindex_reads_real_index(indexes):
    assert "3.13.15-r8" in indexes["x86_64"]["python-3.13"]
    assert "3.13.16_git20261016-r2" in indexes["x86_64"]["python-3.13"]


def test_newest_released_skips_snapshot(indexes):
    assert newest_released(indexes["x86_64"], "python-3.13") == "3.13.15-r8"
    assert newest_released(indexes["x86_64"], "python-3.15") == "3.15.0-r0"


def test_newest_released_prefers_higher_revision():
    index = {"python-3.12": ["3.12.15-r5", "3.12.15-r6", "3.12.14-r9"]}
    assert newest_released(index, "python-3.12") == "3.12.15-r6"


def test_newest_released_missing_package():
    assert newest_released({}, "python-3.99") is None


def test_version_ordering_is_apk_not_lexical():
    assert version_key("3.12.9-r0") < version_key("3.12.15-r0")
    assert version_key("1.30.10-r0") > version_key("1.30.2-r9")
    assert version_key("2026e-r0") > version_key("2026d-r3")


def test_newest_released_all_arches_requires_both(indexes):
    assert newest_released_all_arches(indexes, "only-on-x86") is None
    assert newest_released_all_arches(indexes, "python-3.12") == "3.12.15-r6"
    assert newest_released_all_arches(indexes, "nginx-stable") == "1.30.2-r0"


def test_newest_released_all_arches_picks_common_version():
    indexes = {
        "x86_64": {"p": ["1.2.0-r0", "1.3.0-r0"]},
        "aarch64": {"p": ["1.2.0-r0"]},
    }
    assert newest_released_all_arches(indexes, "p") == "1.2.0-r0"


def test_upstream_version():
    assert upstream_version("3.12.15-r6") == "3.12.15"
    assert upstream_version("1.30.2-r0") == "1.30.2"
    assert upstream_version("2026e") == "2026e"
