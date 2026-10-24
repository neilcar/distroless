"""Image tags for a line/variant."""

from __future__ import annotations

from dltools.lines import Line
from dltools.wolfi import upstream_version


def tags(line: Line, variant: str, lock_hash: str) -> list[str]:
    short = lock_hash[:8]
    if line.image == "static":
        return [line.name, short]
    upstream = upstream_version(line.version)
    out = [line.name]
    if line.image == "nginx":
        out.append(".".join(upstream.split(".")[:2]))
    out += [upstream, f"{upstream}-{short}"]
    return out if variant == "runtime" else [f"{t}-{variant}" for t in out]
