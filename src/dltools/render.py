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

    cfg: dict = {
        "contents": {
            "repositories": list(catalog["repositories"]) + image.get("extra_repositories", []),
            "keyring": list(catalog["keyring"]) + image.get("extra_keyring", []),
            "packages": packages,
        },
        "accounts": catalog["accounts"],
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
