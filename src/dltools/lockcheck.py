"""Validate that an apko lock file is released-only and covers every arch."""

from __future__ import annotations

from pathlib import Path

from dltools.wolfi import ARCHES, is_released

# Runtime images must not contain a shell or a package manager.
RUNTIME_FORBIDDEN = frozenset(
    {"busybox", "bash", "dash", "zsh", "ash", "apk-tools", "wolfi-base", "coreutils", "toybox"}
)

# Packages one image must never contain, whatever the variant. photoprism-base and
# stash-base use distroless-libvips (built with lcms2); Wolfi's libvips would replace or
# sit beside it.
IMAGE_FORBIDDEN = {
    "photoprism-base": frozenset({"libvips", "libvips-dev"}),
    "stash-base": frozenset({"libvips", "libvips-dev"}),
}


# Unreleased packages one image may contain because Wolfi has never had a released version of them.
# pin-released still pins them the moment a release appears. flaresolverr-base: Wolfi Chromium's
# dependencies (owner's decision, 2026-11-02).
IMAGE_UNRELEASED_ALLOWED = {
    "flaresolverr-base": {
        # libcups (which Chromium links) needs libavahi-client; avahi's last release is 0.8 (2020) and
        # Wolfi only ships 0.9 release candidates.
        "avahi-libs": "Wolfi ships only avahi 0.9 release candidates",
        # A direct Chromium dependency; Open Sans exists in Wolfi only as a git snapshot.
        "font-opensans": "Wolfi ships Open Sans only as a git snapshot",
    },
}


def image_allowed_unreleased(lock_path) -> frozenset[str]:
    """Unreleased packages allowed in the image of a `locks/<image>/<line>/<variant>.lock.json`."""
    return frozenset(IMAGE_UNRELEASED_ALLOWED.get(Path(lock_path).parent.parent.name, {}))


def image_forbidden(lock_path) -> frozenset[str]:
    """Forbidden packages for the image of a `locks/<image>/<line>/<variant>.lock.json`."""
    return IMAGE_FORBIDDEN.get(Path(lock_path).parent.parent.name, frozenset())


def check_lock(
    lock: dict,
    required_arches: set[str] = frozenset(ARCHES),
    forbidden: frozenset[str] = frozenset(),
    allowed_unreleased: frozenset[str] = frozenset(),
) -> list[str]:
    """Return human-readable violations; an empty list means the lock is acceptable."""
    packages = lock.get("contents", {}).get("packages", [])
    violations = [
        f"{p['architecture']}: {p['name']} {p['version']} is not a released version"
        for p in packages
        if not is_released(p["version"]) and p["name"] not in allowed_unreleased
    ]
    violations += [
        f"{p['architecture']}: {p['name']} is not allowed in this image"
        for p in packages
        if p["name"] in forbidden
    ]
    present = {p["architecture"] for p in packages}
    violations += [f"lock has no packages for {a}" for a in sorted(required_arches - present)]
    return violations
