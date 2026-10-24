"""Decide what a daily re-scan of a published image should do."""

from __future__ import annotations

from dataclasses import dataclass

from dltools.gate import BLOCKING, findings


@dataclass(frozen=True)
class RescanDecision:
    open_issue: bool
    rebuild: bool
    summary: str


def decide(report: dict, ignore: set[str], previous_ids: set[str]) -> RescanDecision:
    """New Critical/High findings open an issue; any fixable one triggers a rebuild."""
    serious = [f for f in findings(report, ignore) if f.severity in BLOCKING]
    new = [f for f in serious if f.id not in previous_ids]
    fixable = [f for f in serious if f.fixed_version]
    lines = [
        f"- {f.severity} {f.id} in {f.package}"
        + (f" (fixed in {f.fixed_version})" if f.fixed_version else " (no fix yet)")
        for f in sorted(new or fixable, key=lambda f: (f.severity, f.id))
    ]
    return RescanDecision(bool(new), bool(fixable), "\n".join(lines))
