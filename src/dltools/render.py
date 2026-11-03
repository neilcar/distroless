"""Render a catalog image definition for one line and variant into an apko config."""

from __future__ import annotations

from pathlib import Path

import yaml

from dltools.lines import Line

SOURCE = "https://github.com/neilcar/distroless"


def load_catalog(path="catalog.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())


def _fill(value: str, line: Line) -> str:
    return value.format(line=line.name, package=line.package)


def render(catalog: dict, line: Line, variant: str) -> dict:
    image = catalog["images"][line.image]
    spec = image["variants"][variant]
    packages = list(catalog["base_packages"]) + [_fill(p, line) for p in spec["packages"]]
    # Pin the headline package to its exact version (it may also be a base package).
    pin = f"{line.package}={line.version}"
    packages = [pin if p == line.package else p for p in packages]
    if pin not in packages:
        packages.append(pin)

    accounts = dict(catalog["accounts"])
    # An image may add its own accounts beside the shared nonroot one.
    for kind in ("groups", "users"):
        extra = image.get("accounts", {}).get(kind, [])
        if extra:
            accounts[kind] = [dict(a) for a in accounts.get(kind, [])] + [dict(a) for a in extra]
    if "run_as" in image:
        accounts["run-as"] = image["run_as"]

    cfg: dict = {
        "contents": {
            "repositories": list(catalog["repositories"]) + image.get("extra_repositories", []),
            "keyring": list(catalog["keyring"]) + image.get("extra_keyring", []),
            "packages": packages,
        },
        "accounts": accounts,
        "archs": list(catalog["archs"]),
        "annotations": {
            "org.opencontainers.image.source": SOURCE,
            "org.opencontainers.image.title": f"{line.image}:{line.name}"
            + ("" if variant == "runtime" else f"-{variant}"),
        },
    }
    if "entrypoint" in spec:
        cfg["entrypoint"] = {"command": _fill(spec["entrypoint"], line)}
    if "cmd" in spec:
        cfg["cmd"] = spec["cmd"]
    if "environment" in image:
        cfg["environment"] = dict(image["environment"])
    if "paths" in image:
        cfg["paths"] = [dict(p) for p in image["paths"]]
    return cfg


def render_vendor(catalog: dict, line: Line) -> dict | None:
    """The image's vendored upstream files (pinned by sha256), or None if it has none. An image
    with `env_launcher: true` and nothing to vendor gets an empty list: its build still adds the
    launcher as the runtime's /usr/bin/env."""
    image = catalog["images"][line.image]
    vendor = image.get("vendor")
    if vendor:
        return {"vendor": vendor}
    return {"vendor": []} if image.get("env_launcher") else None
