import json
from pathlib import Path

from dltools.lockcheck import check_lock, image_allowed_unreleased

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_lockcheck_clean_lock_ok():
    assert check_lock(load("lock-clean.json")) == []


def test_lockcheck_rejects_transitive_snapshot():
    violations = check_lock(load("lock-snapshot.json"))
    # one per arch, both naming the offending dependency and its version
    assert len(violations) == 2
    assert all("libexpat1" in v and "2.7.4_git20261001-r0" in v for v in violations)


def test_lockcheck_requires_both_arches():
    violations = check_lock(load("lock-x86-only.json"))
    assert violations == ["lock has no packages for aarch64"]


def test_lockcheck_empty_lock_is_a_violation():
    assert check_lock({"contents": {"packages": []}}) == [
        "lock has no packages for aarch64",
        "lock has no packages for x86_64",
    ]


def test_lockcheck_forbidden_packages():
    lock = {"contents": {"packages": [
        {"name": n, "version": "1.0-r0", "architecture": a}
        for a in ("x86_64", "aarch64") for n in ("busybox", "python-3.12")]}}
    from dltools.lockcheck import RUNTIME_FORBIDDEN
    v = check_lock(lock, forbidden=RUNTIME_FORBIDDEN)
    assert len(v) == 2 and all("busybox" in x and "not allowed" in x for x in v)


def _runtime_lock(*names):
    return {"contents": {"packages": [
        {"name": n, "version": "1.0-r0", "architecture": a}
        for a in ("x86_64", "aarch64") for n in names]}}


def test_lockcheck_runtime_accepts_no_shell_stub_without_bash():
    from dltools.lockcheck import RUNTIME_FORBIDDEN
    lock = _runtime_lock("libsrt", "distroless-no-shell", "ffmpeg")
    assert check_lock(lock, forbidden=RUNTIME_FORBIDDEN) == []


def test_lockcheck_runtime_still_rejects_real_bash():
    from dltools.lockcheck import RUNTIME_FORBIDDEN
    lock = _runtime_lock("libsrt", "distroless-no-shell", "bash")
    v = check_lock(lock, forbidden=RUNTIME_FORBIDDEN)
    assert len(v) == 2 and all("bash" in x for x in v)


def test_image_forbidden_photoprism_base():
    from dltools.lockcheck import image_forbidden
    assert image_forbidden("locks/photoprism-base/latest/dev.lock.json") == {"libvips", "libvips-dev"}
    assert image_forbidden("locks/python/3.12/runtime.lock.json") == frozenset()


def test_image_forbidden_stash_base():
    from dltools.lockcheck import image_forbidden
    assert image_forbidden("locks/stash-base/latest/runtime.lock.json") == {"libvips", "libvips-dev"}


def test_lockcheck_allows_named_unreleased_packages_only():
    lock = {"contents": {"packages": [
        {"name": n, "version": v, "architecture": a}
        for a in ("x86_64", "aarch64")
        for n, v in (("avahi-libs", "0.9_rc5-r3"), ("zlib", "1.3.2.1_rc20260921-r1"))
    ]}}
    violations = check_lock(lock, allowed_unreleased=frozenset({"avahi-libs"}))
    assert len(violations) == 2 and all("zlib" in v for v in violations)


def test_image_allowed_unreleased_flaresolverr_base():
    # Chromium's dependencies with no released version in Wolfi at all, and only for this image.
    assert image_allowed_unreleased("locks/flaresolverr-base/latest/runtime.lock.json") == frozenset(
        {"avahi-libs", "font-opensans"}
    )
    assert image_allowed_unreleased("locks/beets-base/latest/runtime.lock.json") == frozenset()
