"""Pin dependencies that resolved to unreleased versions back to their newest release."""

from __future__ import annotations

import copy

from dltools.wolfi import is_released, newest_released_all_arches


def released_overrides(lock: dict, indexes) -> tuple[dict[str, str], list[str]]:
    """Return (pins, missing): a released pin for every unreleased package in the lock,
    and the names that have no released version on every arch."""
    unreleased = sorted({
        p["name"] for p in lock.get("contents", {}).get("packages", [])
        if not is_released(p["version"])
    })
    pins, missing = {}, []
    for name in unreleased:
        version = newest_released_all_arches(indexes, name)
        if version:
            pins[name] = version
        else:
            missing.append(name)
    return pins, missing


def apply_pins(config: dict, pins: dict[str, str]) -> dict:
    """Return a copy of an apko config with `name=version` pins added or replaced."""
    out = copy.deepcopy(config)
    packages = out["contents"]["packages"]
    seen = set()
    for i, entry in enumerate(packages):
        name = entry.split("=", 1)[0]
        if name in pins:
            packages[i] = f"{name}={pins[name]}"
            seen.add(name)
    packages.extend(f"{n}={v}" for n, v in pins.items() if n not in seen)
    return out
