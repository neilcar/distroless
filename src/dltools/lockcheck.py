"""Validate that an apko lock file is released-only and covers every arch."""

from __future__ import annotations

from dltools.wolfi import ARCHES, is_released


def check_lock(lock: dict, required_arches: set[str] = frozenset(ARCHES)) -> list[str]:
    """Return human-readable violations; an empty list means the lock is acceptable."""
    packages = lock.get("contents", {}).get("packages", [])
    violations = [
        f"{p['architecture']}: {p['name']} {p['version']} is not a released version"
        for p in packages
        if not is_released(p["version"])
    ]
    present = {p["architecture"] for p in packages}
    violations += [f"lock has no packages for {a}" for a in sorted(required_arches - present)]
    return violations
