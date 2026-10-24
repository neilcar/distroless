"""Validate that an apko lock file is released-only and covers every arch."""

from __future__ import annotations

from dltools.wolfi import ARCHES, is_released

# Runtime images must not contain a shell or a package manager.
RUNTIME_FORBIDDEN = frozenset(
    {"busybox", "bash", "dash", "zsh", "ash", "apk-tools", "wolfi-base", "coreutils", "toybox"}
)


def check_lock(
    lock: dict,
    required_arches: set[str] = frozenset(ARCHES),
    forbidden: frozenset[str] = frozenset(),
) -> list[str]:
    """Return human-readable violations; an empty list means the lock is acceptable."""
    packages = lock.get("contents", {}).get("packages", [])
    violations = [
        f"{p['architecture']}: {p['name']} {p['version']} is not a released version"
        for p in packages
        if not is_released(p["version"])
    ]
    violations += [
        f"{p['architecture']}: {p['name']} is not allowed in this image"
        for p in packages
        if p["name"] in forbidden
    ]
    present = {p["architecture"] for p in packages}
    violations += [f"lock has no packages for {a}" for a in sorted(required_arches - present)]
    return violations
