import json
from pathlib import Path

from dltools.lockcheck import check_lock

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
