"""Trivy scan gate: block fixable Critical/High findings and regressions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from dltools.wolfi import newest_released_all_arches, version_key

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
BLOCKING = ("CRITICAL", "HIGH")


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    package: str
    fixed_version: str
    installed: str = ""
    kind: str = "os-pkgs"  # Trivy result Class
    pkg_type: str = ""  # Trivy result Type, e.g. "wolfi", "python-pkg"


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]
    candidate_counts: dict[str, int]
    published_counts: dict[str, int] | None
    notes: list[str] = field(default_factory=list)


def load_ignore(path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    ids = set()
    for line in p.read_text().splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            ids.add(entry)
    return ids


def findings(report: dict, ignore: set[str]) -> list[Finding]:
    """Unique findings in a Trivy JSON report, minus ignored IDs."""
    seen: dict[tuple[str, str], Finding] = {}
    for result in report.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            if v["VulnerabilityID"] in ignore:
                continue
            f = Finding(
                v["VulnerabilityID"],
                v.get("Severity", "UNKNOWN").upper(),
                v.get("PkgName", ""),
                v.get("FixedVersion") or "",
                v.get("InstalledVersion") or "",
                result.get("Class") or "os-pkgs",
                result.get("Type") or "",
            )
            seen.setdefault((f.id, f.package), f)
    return list(seen.values())


def fix_status(finding: Finding, indexes) -> str:
    """One of: fixable, no-fix, no-release, not-wolfi, unparseable.

    `fixable` means a released Wolfi version (on every arch) is at or above the
    advisory's fix for the installed version's branch. Without indexes, any listed
    fixed version counts as fixable."""
    if not finding.fixed_version:
        return "no-fix"
    if indexes is None:
        return "fixable"
    if finding.kind != "os-pkgs":
        return "not-wolfi"
    fixes = []
    for raw in (v.strip() for v in finding.fixed_version.split(",")):
        try:
            fixes.append(version_key(raw))
        except ValueError:
            continue
    if not fixes:
        return "unparseable"
    try:
        installed = version_key(finding.installed) if finding.installed else None
    except ValueError:
        installed = None
    # Only fixes above the installed version are on its branch; a fix for an older
    # branch (e.g. 3.11.20 when 3.12.15 is installed) says nothing about this one.
    relevant = [f for f in fixes if installed is None or f > installed] or fixes
    if not any(finding.package in idx for idx in indexes.values()):
        return "not-wolfi"
    newest = newest_released_all_arches(indexes, finding.package)
    if newest is None:
        return "no-release"
    return "fixable" if version_key(newest) >= min(relevant) else "no-release"


def fix_available(finding: Finding, indexes) -> bool:
    return fix_status(finding, indexes) == "fixable"


_NOTE = {
    "no-fix": "no fix published",
    "no-release": "no released fix in Wolfi",
    "unparseable": "unparseable fixed version, not blocking",
}


def _note(f: Finding, status: str) -> str:
    reason = (
        f"not a Wolfi package ({f.pkg_type or f.kind})" if status == "not-wolfi" else _NOTE[status]
    )
    advisory = f" (advisory: {f.fixed_version})" if f.fixed_version else ""
    return f"{f.severity} {f.id} in {f.package}: {reason}{advisory}"


def counts(items: list[Finding]) -> dict[str, int]:
    c = dict.fromkeys(SEVERITIES, 0)
    for f in items:
        c[f.severity if f.severity in c else "UNKNOWN"] += 1
    return c


def evaluate(
    candidate: dict, published: dict | None, ignore: set[str], indexes=None
) -> GateResult:
    cand = findings(candidate, ignore)
    serious = [f for f in cand if f.severity in BLOCKING]
    statuses = [(f, fix_status(f, indexes)) for f in serious]
    reasons = [
        f"{f.severity} {f.id} in {f.package} has a fix ({f.fixed_version})"
        for f, st in statuses
        if st == "fixable"
    ]
    notes = [_note(f, st) for f, st in statuses if st != "fixable"]
    cand_counts = counts(cand)
    pub_counts = None
    if published is not None:
        pub_counts = counts(findings(published, ignore))
        reasons += [
            f"{sev}: {cand_counts[sev]} findings vs {pub_counts[sev]} in the published image"
            for sev in SEVERITIES
            if cand_counts[sev] > pub_counts[sev]
        ]
    return GateResult(not reasons, reasons, cand_counts, pub_counts, notes)


def summary_markdown(result: GateResult, label: str) -> str:
    rows = [f"### Scan gate: {label} — {'PASS' if result.passed else 'FAIL'}", "",
            "| Severity | Candidate | Published |", "|---|---|---|"]
    for sev in SEVERITIES:
        pub = "—" if result.published_counts is None else result.published_counts[sev]
        rows.append(f"| {sev} | {result.candidate_counts[sev]} | {pub} |")
    rows += [""] + [f"- {r}" for r in result.reasons] + [f"- note: {n}" for n in result.notes]
    return "\n".join(rows) + "\n"
