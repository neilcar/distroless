from dltools.pinning import apply_pins, released_overrides


def lock(*pkgs):
    return {"contents": {"packages": [
        {"name": n, "version": v, "architecture": a}
        for a in ("x86_64", "aarch64") for n, v in pkgs
    ]}}


INDEXES = {a: {
    "zlib": ["1.3.1-r9", "1.3.2.1_rc20260921-r0"],
    "libexpat1": ["2.7.4_git20261001-r0"],
    "python-3.12": ["3.12.15-r6"],
} for a in ("x86_64", "aarch64")}


def test_released_overrides_pins_newest_release():
    pins, missing = released_overrides(
        lock(("python-3.12", "3.12.15-r6"), ("zlib", "1.3.2.1_rc20260921-r0")), INDEXES
    )
    assert pins == {"zlib": "1.3.1-r9"} and missing == []


def test_released_overrides_reports_package_without_any_release():
    pins, missing = released_overrides(lock(("libexpat1", "2.7.4_git20261001-r0")), INDEXES)
    assert pins == {} and missing == ["libexpat1"]


def test_released_overrides_clean_lock():
    assert released_overrides(lock(("python-3.12", "3.12.15-r6")), INDEXES) == ({}, [])


def test_apply_pins_adds_and_replaces():
    cfg = {"contents": {"packages": ["wolfi-baselayout", "python-3.12=3.12.15-r6", "zlib=1.0-r0"]}}
    out = apply_pins(cfg, {"zlib": "1.3.1-r9", "libffi": "3.5-r0"})
    assert out["contents"]["packages"] == [
        "wolfi-baselayout", "python-3.12=3.12.15-r6", "zlib=1.3.1-r9", "libffi=3.5-r0",
    ]
    assert cfg["contents"]["packages"][2] == "zlib=1.0-r0"  # input not mutated
